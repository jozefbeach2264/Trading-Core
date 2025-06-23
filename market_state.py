# TradingCore/market_state.py
import logging
from typing import List, Dict, Any

from orderbook_parser import parse_orderbook

logger = logging.getLogger(__name__)

class MarketState:
    """A class to hold and manage the real-time state of the market for a single symbol."""
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.depth_5: Dict[str, List] = {"bids": [], "asks": []}
        self.depth_20: Dict[str, List] = {"bids": [], "asks": []}
        self.book_ticker: Dict[str, Any] = {}
        self.klines: List[List[Any]] = []
        self.mark_price: float = 0.0
        self.open_interest: float = 0.0
        self.previous_open_interest: float = 0.0
        self.funding_rate: float = 0.0
        self.recent_trades: List[Dict[str, Any]] = []
        logger.info("MarketState for symbol %s initialized.", self.symbol)

    def update_open_interest(self, open_interest_data: dict):
        new_oi = float(open_interest_data.get('openInterest', 0.0))
        if new_oi > 0 and new_oi != self.open_interest:
            if self.previous_open_interest == 0:
                self.previous_open_interest = new_oi
            else:
                self.previous_open_interest = self.open_interest
            self.open_interest = new_oi

    def update_recent_trades(self, trades_data: List[Dict[str, Any]]):
        self.recent_trades = trades_data
        
    def update_depth_5(self, raw_data: Dict[str, Any]):
        self.depth_5['bids'], self.depth_5['asks'] = parse_orderbook(raw_data)
    def update_depth_20(self, raw_data: Dict[str, Any]):
        self.depth_20['bids'], self.depth_20['asks'] = parse_orderbook(raw_data)
    def update_book_ticker(self, ticker_data: Dict[str, Any]):
        self.book_ticker = ticker_data
    def update_klines(self, kline_data: List[List[Any]]):
        self.klines = kline_data
    def update_premium_index(self, premium_data: Dict[str, Any]):
        self.mark_price = float(premium_data.get('markPrice', 0.0))
        self.funding_rate = float(premium_data.get('lastFundingRate', 0.0))
        
    def get_signal_data(self) -> Dict[str, Any]:
        """
        Assembles a complete and safe data dictionary for the ValidatorStack.
        This ensures all keys are present, even on a cold start.
        """
        price_change_1m = 0.0
        if self.klines:
            try:
                kline_open = float(self.klines[-1][1])
                kline_close = float(self.klines[-1][4])
                if kline_open > 0:
                    price_change_1m = ((kline_close - kline_open) / kline_open) * 100
            except (IndexError, TypeError):
                price_change_1m = 0.0
        
        # This explicitly constructed dictionary is the key to the fix.
        # It guarantees every key exists, even if the value is a default.
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
            "recent_trades": self.recent_trades,
            "price_change_1m": price_change_1m,
            # For compatibility with your error log, we ensure 'order_book' exists
            # by mapping it to one of the depth levels.
            "order_book": self.depth_20
        }
