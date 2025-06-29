# TradingCore/main.py
import asyncio
import logging
import sys
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from collections import deque
from typing import List, Dict
import time
import shutil

# --- Logging Configuration ---
logging.basicConfig(level=logging.WARNING, format='%(asctime)s - [%(levelname)s] - %(name)s - %(message)s')
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# --- Import Core Modules ---
from validator_stack import ValidatorStack
from strategy_router import StrategyRouter
from console_display import format_market_state_for_console
from exchange_client import ExchangeClient
from trade_lifecycle_manager import TradeLifecycleManager

# --- MarketState Class (inline, move to market_state.py if separate) ---
class MarketState:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.mark_price = 0.0
        self.book_ticker = {}
        self.klines = []
        self.recent_trades = deque(maxlen=1000)  # Cover ~1min
        self.depth_5 = {}
        self.depth_20 = {}
        self.open_interest = 0.0
        self.previous_open_interest = 0.0
        self.oi_history = deque(maxlen=200)  # ~10min of OI (3s updates)
        self.premium_index = {}

    def update_depth_5(self, depth_data: Dict):
        self.depth_5 = depth_data or {}

    def update_depth_20(self, depth_data: Dict):
        self.depth_20 = depth_data or {}

    def update_klines(self, kline_data: List):
        self.klines = kline_data or []

    def update_book_ticker(self, ticker_data: Dict):
        self.book_ticker = ticker_data or {}
        # Fallback: Use mid-price if markPrice not available elsewhere
        bid_price = float(ticker_data.get('bidPrice', 0.0))
        ask_price = float(ticker_data.get('askPrice', 0.0))
        if bid_price and ask_price:
            self.mark_price = (bid_price + ask_price) / 2
        if not self.mark_price:
            logging.warning(f"No valid price in book_ticker: {ticker_data}")

    def update_premium_index(self, premium_data: Dict):
        self.premium_index = premium_data or {}
        # Primary source for mark_price (Asterdex/Binance Futures format)
        if premium_data.get('markPrice'):
            self.mark_price = float(premium_data.get('markPrice', self.mark_price))
        elif not self.mark_price:
            logging.warning(f"No markPrice in premium_index: {premium_data}")

    def update_recent_trades(self, trades_data: List[Dict]):
        if not trades_data:
            return
        sorted_trades = sorted(trades_data, key=lambda x: int(x.get('time', 0)))
        self.recent_trades.extend(sorted_trades)

    def update_open_interest(self, oi_data: Dict):
        if not oi_data:
            return
        self.previous_open_interest = self.open_interest
        self.open_interest = float(oi_data.get('openInterest', 0.0))
        self.oi_history.append({
            'time': int(oi_data.get('time', time.time() * 1000)),
            'openInterest': self.open_interest
        })

    def get_signal_data(self) -> Dict:
        return {
            'symbol': self.symbol,
            'mark_price': self.mark_price,
            'book_ticker': self.book_ticker,
            'klines': self.klines,
            'recent_trades': list(self.recent_trades),
            'depth_5': self.depth_5,
            'depth_20': self.depth_20,
            'open_interest': self.open_interest,
            'premium_index': self.premium_index
        }

# --- Global State ---
market_state = MarketState(symbol="ETHUSDT")
trading_services = {}

# --- API Models ---
class SignalTrigger(BaseModel):
    strategy: str
    user_id: int

# --- Sensor Functions ---
async def high_freq_loop(client: ExchangeClient):
    while True:
        start_time = time.time()
        try:
            d5_data, d20_data = await asyncio.gather(
                client.get_depth(market_state.symbol, 5),
                client.get_depth(market_state.symbol, 20)
            )
            if d5_data:
                market_state.update_depth_5(d5_data)
            if d20_data:
                market_state.update_depth_20(d20_data)
        except Exception as e:
            logging.error(f"Error in high_freq_loop: {e}", exc_info=False)
        await asyncio.sleep(max(0, 0.3 - (time.time() - start_time)))

async def mid_freq_loop(client: ExchangeClient):
    while True:
        start_time = time.time()
        try:
            kline_data, ticker_data, trades_data = await asyncio.gather(
                client.get_klines(market_state.symbol, "1m", 10),
                client.get_book_ticker(market_state.symbol),
                client.get_recent_trades(market_state.symbol, 100)
            )
            if kline_data:
                market_state.update_klines(kline_data)
            if ticker_data:
                market_state.update_book_ticker(ticker_data)
            if trades_data:
                market_state.update_recent_trades(trades_data)
        except Exception as e:
            logging.error(f"Error in mid_freq_loop: {e}", exc_info=False)
        await asyncio.sleep(max(0, 1.0 - (time.time() - start_time)))

async def low_freq_loop(client: ExchangeClient):
    while True:
        start_time = time.time()
        try:
            premium_data, oi_data = await asyncio.gather(
                client.get_premium_index(market_state.symbol),
                client.get_open_interest(market_state.symbol)
            )
            if premium_data:
                market_state.update_premium_index(premium_data)
            if oi_data:
                market_state.update_open_interest(oi_data)
        except Exception as e:
            logging.error(f"Error in low_freq_loop: {e}", exc_info=False)
        await asyncio.sleep(max(0, 3.0 - (time.time() - start_time)))

async def console_log_loop():
    while True:
        try:
            sys.stdout.write(format_market_state_for_console(market_state))
            sys.stdout.flush()
        except Exception as e:
            logging.error(f"Error in console_log_loop: {e}", exc_info=False)
        await asyncio.sleep(1)

# --- FastAPI Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info("TradingCore starting up...")
    exchange_client = ExchangeClient()
    trading_services["validator_stack"] = ValidatorStack()
    trading_services["strategy_router"] = StrategyRouter()
    trading_services["lifecycle_manager"] = TradeLifecycleManager(market_state)
    tasks = [
        asyncio.create_task(high_freq_loop(exchange_client)),
        asyncio.create_task(mid_freq_loop(exchange_client)),
        asyncio.create_task(low_freq_loop(exchange_client)),
        asyncio.create_task(console_log_loop())
    ]
    yield
    logging.info("Shutting down TradingCore...")
    for task in tasks:
        task.cancel()
    try:
        await exchange_client.close()
    except Exception as e:
        logging.error(f"Error closing exchange client: {e}", exc_info=False)
    logging.info("Shutdown complete.")

app = FastAPI(lifespan=lifespan)

# --- API Endpoints ---
@app.get("/")
def root():
    return {"message": "TradingCore is active."}

@app.get("/status")
def health_check():
    return {"status": "ok", "service": "TradingCore"}

@app.post("/validate_signal")
async def validate_signal(trigger: SignalTrigger):
    try:
        signal_data = market_state.get_signal_data()
        signal_data['strategy'] = trigger.strategy
        validator = trading_services.get("validator_stack")
        if not validator:
            raise HTTPException(status_code=500, detail="ValidatorStack not initialized.")
        is_valid = await validator.run_all(signal_data)
        if is_valid:
            lifecycle_manager = trading_services.get("lifecycle_manager")
            response = await lifecycle_manager.start_new_trade_cycle(signal_data)
            return response
        else:
            raise HTTPException(status_code=400, detail="Signal failed validation.")
    except Exception as e:
        logging.error(f"Error in validate_signal: {e}", exc_info=False)
        raise HTTPException(status_code=500, detail="Internal server error.")