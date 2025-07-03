import logging
from collections import deque
import time
from typing import Dict, Any, Optional, List

from config.config import Config
from data_managers.orderbook_parser import parse_orderbook

logger = logging.getLogger(__name__)

class MarketState:
    def __init__(self, symbol: str, config: Config):
        self.symbol = symbol
        self.config = config
        self.last_update_time: float = time.time()
        
        # --- Core Data Structures ---
        self.mark_price: Optional[float] = None
        self.klines: deque = deque(maxlen=self.config.kline_deque_maxlen)
        self.book_ticker: Dict[str, Any] = {}
        self.recent_trades: deque = deque(maxlen=1000)
        self.depth_20: Dict[str, Any] = {"bids": [], "asks": []}
        self.open_interest: float = 0.0
        self.oi_history: deque = deque(maxlen=300)
        self.positions: Dict[str, Dict] = {}
        self.account_balance: Optional[float] = None

        logger.info(f"MarketState for symbol {self.symbol} initialized.")
        
    async def update_account(self, account_data: dict):
        positions_data = account_data.get('P', [])
        for position in positions_data:
            symbol = position.get('s')
            if symbol:
                self.positions[symbol] = {
                    'amount': float(position.get('pa', 0.0)),
                    'entry_price': float(position.get('ep', 0.0)),
                    'unrealized_pnl': float(position.get('up', 0.0))
                }
        
        balances_data = account_data.get('B', [])
        for balance in balances_data:
            if balance.get('a') == 'USDT':
                self.account_balance = float(balance.get('wb', 0.0))
                break
        self.last_update_time = time.time()

    async def update_order(self, order_data: dict):
        pass

    # --- WebSocket Stream Updaters ---
    async def update_from_ws_depth(self, data: dict):
        try:
            self.depth_20['bids'] = [[float(p), float(q)] for p, q in data.get('b', [])]
            self.depth_20['asks'] = [[float(p), float(q)] for p, q in data.get('a', [])]
            self.last_update_time = time.time()
        except (ValueError, TypeError) as e:
            logger.warning(f"Error parsing depth data: {e}")

    async def update_from_ws_agg_trade(self, data: dict):
        try:
            trade = {
                'time': int(data.get('T')), 'price': float(data.get('p')),
                'qty': float(data.get('q')), 'isBuyerMaker': data.get('m', False)
            }
            self.recent_trades.append(trade)
            self.last_update_time = time.time()
        except (ValueError, TypeError) as e:
            logger.warning(f"Error parsing aggTrade data: {e}")

    async def update_from_ws_kline(self, data: dict):
        try:
            kline_data = data.get('k', {})
            formatted_kline = [
                int(kline_data.get('t')), float(kline_data.get('o')), float(kline_data.get('h')),
                float(kline_data.get('l')), float(kline_data.get('c')), float(kline_data.get('v')),
                int(kline_data.get('T')), float(kline_data.get('q')), int(kline_data.get('n')),
                float(kline_data.get('V')), float(kline_data.get('Q')), kline_data.get('B')
            ]
            if self.klines and self.klines[-1][0] == formatted_kline[0]:
                self.klines[-1] = formatted_kline
            else:
                self.klines.append(formatted_kline)
            self.last_update_time = time.time()
        except (ValueError, TypeError) as e:
            logger.warning(f"Error parsing kline data: {e}")
        
    async def update_from_ws_book_ticker(self, data: dict):
        try:
            self.book_ticker = {
                'bidPrice': float(data.get('b')), 'bidQty': float(data.get('B')),
                'askPrice': float(data.get('a')), 'askQty': float(data.get('A'))
            }
            self.last_update_time = time.time()
        except (ValueError, TypeError) as e:
            logger.warning(f"Error parsing bookTicker data: {e}")
        
    async def update_from_ws_mark_price(self, data: dict):
        new_price = data.get('p')
        if new_price is not None:
            self.mark_price = float(new_price)
        self.last_update_time = time.time()

    # --- REST API Updaters ---
    async def update_klines(self, klines_data: List[Any]):
        if klines_data and isinstance(klines_data, list):
            self.klines.clear()
            for kline in klines_data:
                self.klines.append(kline)
            self.last_update_time = time.time()

    async def update_depth_20(self, depth_data: Dict[str, Any]):
        if depth_data:
            self.depth_20 = parse_orderbook(depth_data, level=20)
            self.last_update_time = time.time()

    async def update_premium_index(self, premium_data: Dict[str, Any]):
        if premium_data:
            self.mark_price = float(premium_data.get('markPrice', self.mark_price))
            self.last_update_time = time.time()

    async def update_book_ticker(self, ticker_data: Dict[str, Any]):
        if ticker_data:
            self.book_ticker = ticker_data
            if not self.mark_price or self.mark_price == 0.0:
                try:
                    bid = float(ticker_data.get("bidPrice", 0.0))
                    ask = float(ticker_data.get("askPrice", 0.0))
                    self.mark_price = (bid + ask) / 2
                except Exception:
                    pass
            self.last_update_time = time.time()

    async def update_recent_trades(self, trades_data: List[Any]):
        if trades_data and isinstance(trades_data, list):
            self.recent_trades.clear()
            for trade in trades_data:
                self.recent_trades.append(trade)
            self.last_update_time = time.time()

    async def update_open_interest(self, oi_data: Dict[str, Any]):
        if oi_data and 'openInterest' in oi_data:
            self.open_interest = float(oi_data['openInterest'])
            self.last_update_time = time.time()

    async def update_oi_history(self, oi_history_data: List[Any]):
        if oi_history_data and isinstance(oi_history_data, list):
            self.oi_history.clear()
            for item in oi_history_data:
                self.oi_history.append(item)
            self.last_update_time = time.time()

    # --- Data Access Methods ---
    def get_spread(self) -> Optional[float]:
        bid_price = self.book_ticker.get("bidPrice")
        ask_price = self.book_ticker.get("askPrice")
        if bid_price is not None and ask_price is not None:
            return ask_price - bid_price
        return None

    def get_latest_data_snapshot(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "mark_price": self.mark_price,
            "klines": list(self.klines),
            "depth_20": self.depth_20,
            "book_ticker": self.book_ticker,
            "recent_trades": list(self.recent_trades),
            "open_interest": self.open_interest,
            "oi_history": list(self.oi_history),
        }

    def get_best_bid(self) -> Optional[float]:
        bid_price = self.book_ticker.get("bidPrice")
        return float(bid_price) if bid_price is not None else None

    def get_best_ask(self) -> Optional[float]:
        ask_price = self.book_ticker.get("askPrice")
        return float(ask_price) if ask_price is not None else None
