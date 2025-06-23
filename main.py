# TradingCore/main.py (Definitive Version)
import asyncio
import logging
import sys
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import time

# --- Logging Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(name)s - %(message)s')
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# --- Import All Core and New Modules ---
from market_state import MarketState
from validator_stack import ValidatorStack
from strategy_router import StrategyRouter
from console_display import format_market_state_for_console
from exchange_client import ExchangeClient
from trade_lifecycle_manager import TradeLifecycleManager

# --- Global State ---
market_state = MarketState(symbol="ETHUSDT")
trading_services = {}

# --- API Models ---
class SignalTrigger(BaseModel):
    strategy: str
    user_id: int

# --- Data Fetching Loops (Using the ExchangeClient) ---
async def high_freq_loop(client: ExchangeClient):
    """300ms loop for depth."""
    while True:
        start_time = time.time()
        try:
            d5_data, d20_data = await asyncio.gather(
                client.get_depth(market_state.symbol, 5),
                client.get_depth(market_state.symbol, 20)
            )
            if d5_data: market_state.update_depth_5(d5_data)
            if d20_data: market_state.update_depth_20(d20_data)
        except Exception as e:
            logging.error(f"Error in high_freq_loop: {e}", exc_info=False)
        await asyncio.sleep(max(0, 0.3 - (time.time() - start_time)))

async def mid_freq_loop(client: ExchangeClient):
    """1s loop for tickers, trades, and klines."""
    while True:
        start_time = time.time()
        try:
            kline_data, ticker_data, trades_data = await asyncio.gather(
                client.get_klines(market_state.symbol, "1m", 10), # Fetch more klines for sensors
                client.get_book_ticker(market_state.symbol),
                client.get_recent_trades(market_state.symbol, 50)
            )
            if kline_data: market_state.update_klines(kline_data)
            if ticker_data: market_state.update_book_ticker(ticker_data)
            if trades_data: market_state.update_recent_trades(trades_data)
        except Exception as e:
            logging.error(f"Error in mid_freq_loop: {e}", exc_info=False)
        await asyncio.sleep(max(0, 1.0 - (time.time() - start_time)))

async def low_freq_loop(client: ExchangeClient):
    """3s loop for mark price and OI."""
    while True:
        start_time = time.time()
        try:
            premium_data, oi_data = await asyncio.gather(
                client.get_premium_index(market_state.symbol),
                client.get_open_interest(market_state.symbol)
            )
            if premium_data: market_state.update_premium_index(premium_data)
            if oi_data: market_state.update_open_interest(oi_data)
        except Exception as e:
            logging.error(f"Error in low_freq_loop: {e}", exc_info=False)
        await asyncio.sleep(max(0, 3.0 - (time.time() - start_time)))

async def console_log_loop():
    """1s loop for display."""
    while True:
        sys.stdout.write(format_market_state_for_console(market_state))
        sys.stdout.flush()
        await asyncio.sleep(1)

# --- FastAPI Lifespan: Manages Startup and Shutdown ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info("TradingCore starting up...")
    
    # Initialize the single client for the exchange API
    exchange_client = ExchangeClient()
    
    # Initialize all core services and modules
    trading_services["validator_stack"] = ValidatorStack()
    trading_services["strategy_router"] = StrategyRouter()
    trading_services["lifecycle_manager"] = TradeLifecycleManager(market_state)
    logging.info("Core modules initialized.")
    
    # Create and start all background tasks
    tasks = [
        asyncio.create_task(high_freq_loop(exchange_client)),
        asyncio.create_task(mid_freq_loop(exchange_client)),
        asyncio.create_task(low_freq_loop(exchange_client)),
        asyncio.create_task(console_log_loop())
    ]
    
    yield # Application is now running
    
    logging.info("Shutting down TradingCore...")
    for task in tasks:
        task.cancel()
    await exchange_client.close() # Gracefully close the client session
    logging.info("Shutdown complete.")

# --- FastAPI Application ---
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
    """
    This endpoint is the main entry point for the trading logic.
    It validates a signal and, if valid, hands it off to the TradeLifecycleManager.
    """
    logging.info("--- VALIDATE_SIGNAL ENDPOINT TRIGGERED ---")
    
    signal_data = market_state.get_signal_data()
    signal_data['strategy'] = trigger.strategy # Add strategy context
    
    validator = trading_services.get("validator_stack")
    if not validator:
        raise HTTPException(status_code=500, detail="ValidatorStack not initialized.")
    
    is_valid = await validator.run_all(signal_data)
    
    if is_valid:
        logging.info("SUCCESS: Signal for strategy '%s' passed initial validation.", trigger.strategy)
        lifecycle_manager = trading_services.get("lifecycle_manager")
        # Hand off control to the manager to start the "Predict–Enter–Roll–Exit" flow
        response = await lifecycle_manager.start_new_trade_cycle(signal_data)
        return response
    else:
        # If validation fails, raise an error. The bot will see this response.
        raise HTTPException(status_code=400, detail="Signal failed validation.")
