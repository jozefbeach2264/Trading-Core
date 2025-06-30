import logging
from typing import List, Dict, Any
from collections import deque
import time

from .orderbook_parser import parse_orderbook

logger = logging.getLogger(__name__)

class MarketState:
    """
    A class to hold and manage the real-time state of the market for a single symbol.
    This acts as the central, live data repository for all other modules.
    """
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.depth_5: Dict[str, list] = {"bids": [], "asks": []}
        self.depth_20: Dict[str, list] = {"bids": [], "asks": []}
        self.book_ticker: Dict[str, Any] = {}
        self.klines: List[list] = []
        self.mark_price: float = 0.0
        self.open_interest: float = 0.0
        self.previous_open_interest: float = 0.0
        self.funding_rate: float = 0.0
        # Use a deque for efficient appends and pops from both ends
        self.recent_trades: deque = deque(maxlen=1000)
        self.oi_history: deque = deque(maxlen=200)

        logger.info("MarketState for symbol %s initialized.", self.symbol)

    def update_open_interest(self, oi_data: dict):
        if not oi_data: return
        new_oi = float(oi_data.get('openInterest', 0.0))
        if new_oi > 0 and new_oi != self.open_interest:
            self.previous_open_interest = self.open_interest
            self.open_interest = new_oi
            self.oi_history.append({'time': int(oi_data.get('time', time.time() * 1000)), 'openInterest': self.open_interest})

    def update_recent_trades(self, trades_data: List[Dict]):
        if not trades_data: return
        # Sort incoming trades by time to ensure correct order before extending deque
        sorted_trades = sorted(trades_data, key=lambda x: int(x.get('time', 0)))
        self.recent_trades.extend(sorted_trades)

    def update_depth_5(self, raw_data: Dict):
        if raw_data: self.depth_5['bids'], self.depth_5['asks'] = parse_orderbook(raw_data)
        
    def update_depth_20(self, raw_data: Dict):
        if raw_data: self.depth_20['bids'], self.depth_20['asks'] = parse_orderbook(raw_data)
        
    def update_book_ticker(self, ticker_data: Dict):
        if ticker_data: self.book_ticker = ticker_data

    def update_klines(self, kline_data: List):
        if kline_data: self.klines = kline_data

    def update_premium_index(self, premium_data: Dict):
        if not premium_data: return
        self.mark_price = float(premium_data.get('markPrice', self.mark_price))
        self.funding_rate = float(premium_data.get('lastFundingRate', 0.0))

    def get_signal_data(self) -> Dict[str, Any]:
        """
        Assembles a complete and safe data dictionary for the ValidatorStack.
        This ensures all keys are present, even on a cold start.
        """
        price_change_1m = 0.0
        if self.klines:
            try:
                # kline format: [open_time, open, high, low, close, volume, ...]
                kline_open = float(self.klines[-1][1])
                kline_close = float(self.klines[-1][4])
                if kline_open > 0:
                    price_change_1m = ((kline_close - kline_open) / kline_open)
            except (IndexError, TypeError, ZeroDivisionError) as e:
                logger.warning(f"Could not calculate 1m price change: {e}")
                price_change_1m = 0.0
        
        # This explicitly constructed dictionary is the key to preventing errors.
        return {
            "symbol": self.symbol,
            "depth_5": self.depth_5,
            "depth_20": self.depth_20,
            "book_ticker": self.book_ticker,
            "klines": self.klines,
            "mark_price": self.mark_price,
            "open_interest": self.open_interest,
            "previous_open_interest": self.previous_open_interest,
            "funding_rate": self.funding_rate,
            "recent_trades": list(self.recent_trades),
            "price_change_1m": price_change_1m,
            # For compatibility with older filter versions that might use 'order_book' key
            "order_book": self.depth_20
        }
