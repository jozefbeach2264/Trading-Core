import logging
from collections import deque
import time
from typing import Dict, Any, Optional, List

from config.config import Config

logger = logging.getLogger(__name__)

class MarketState:
    def __init__(self, symbol: str, config: Config):
        # This __init__ is correct and unchanged.
        self.symbol = symbol
        self.config = config
        self.last_update_time: float = time.time()
        
        self.mark_price: Optional[float] = None
        self.klines: deque = deque(maxlen=config.kline_deque_maxlen)
        self.book_ticker: Dict[str, Any] = {}
        self.recent_trades: deque = deque(maxlen=1000)
        self.depth_20: Dict[str, Any] = {"bids": [], "asks": []}
        self.depth_5: Dict[str, Any] = {"bids": [], "asks": []}
        self.open_interest: float = 0.0
        self.oi_history: deque = deque(maxlen=300)
        self.positions: Dict[str, Dict] = {}
        self.account_balance: Optional[float] = None
        self.live_reconstructed_candle: Optional[List[Any]] = None

        logger.info(f"MarketState for symbol {self.symbol} initialized.")
        
    async def update_live_reconstructed_candle(self, candle: List[Any]):
        self.live_reconstructed_candle = candle

    async def update_klines(self, klines_data: List[List[Any]]):
        """
        ✅ THE FIX: This method is now correctly parsing the response from the
        /history-candles endpoint. It iterates through each candle list in the
        'data' field and correctly formats it.
        """
        if not klines_data or not isinstance(klines_data, list):
            logger.warning("update_klines received empty or invalid data.")
            return
        
        self.klines.clear()
        # The data from the API is newest first, so we process it in reverse
        # to add the oldest candles to our deque first.
        for k in reversed(klines_data):
            try:
                # OKX history-candles format: [ts,o,h,l,c,vol,volCcy,volCcyQuote,confirm]
                formatted_kline = [
                    int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]),
                    float(k[5]), float(k[6]), float(k[7]), str(k[8])
                ]
                # appendleft adds to the front, ensuring newest is at index 0
                self.klines.appendleft(formatted_kline)
            except (ValueError, TypeError, IndexError) as e:
                logger.error(f"Error parsing historical kline: {k} - {e}")
        
        logger.info(f"Successfully loaded {len(self.klines)} historical klines.")
        self.last_update_time = time.time()

    # --- All other methods are preserved from the last fully functional version ---

    async def update_from_ws_books(self, data: dict):
        try:
            bids_data = data.get('bids', [])
            asks_data = data.get('asks', [])
            self.depth_20['bids'] = [(float(p), float(q)) for p, q, _, _ in bids_data]
            self.depth_20['asks'] = [(float(p), float(q)) for p, q, _, _ in asks_data]
            self.depth_20['asks'].reverse()
            self.last_update_time = time.time()
        except (ValueError, TypeError) as e:
            logger.error(f"Error parsing OKX 'books' data: {e}", exc_info=True)

    async def update_from_ws_books5(self, data: dict):
        try:
            bids_data = data.get('bids', [])
            asks_data = data.get('asks', [])
            self.depth_5['bids'] = [(float(p), float(q)) for p, q, _, _ in bids_data]
            self.depth_5['asks'] = [(float(p), float(q)) for p, q, _, _ in asks_data]
            self.depth_5['asks'].reverse()
            self.last_update_time = time.time()
        except (ValueError, TypeError) as e:
            logger.error(f"Error parsing OKX 'books5' data: {e}", exc_info=True)

    async def update_from_ws_agg_trade(self, data: dict):
        try:
            trade = {
                'time': int(data.get('ts')), 'price': float(data.get('px')),
                'qty': float(data.get('sz')), 'side': data.get('side')
            }
            self.recent_trades.append(trade)
            self.last_update_time = time.time()
        except (ValueError, TypeError) as e:
            logger.error(f"Error parsing OKX trade data: {e}", exc_info=True)

    async def update_from_ws_kline(self, kline_data: list):
        try:
            if self.klines and self.klines[0][0] == kline_data[0]:
                self.klines[0] = kline_data
            else:
                self.klines.appendleft(kline_data)
            self.last_update_time = time.time()
        except (ValueError, TypeError, IndexError) as e:
            logger.error(f"Error processing reconstructed kline data: {kline_data} - {e}")
        
    async def update_from_ws_book_ticker(self, data: dict):
        try:
            self.book_ticker = {
                'bidPrice': float(data.get('bidPx')), 'bidQty': float(data.get('bidSz')),
                'askPrice': float(data.get('askPx')), 'askQty': float(data.get('askSz')),
                'lastPrice': float(data.get('last'))
            }
            self.last_update_time = time.time()
        except (ValueError, TypeError) as e:
            logger.error(f"Error parsing OKX ticker data: {e}", exc_info=True)
        
    async def update_from_ws_mark_price(self, data: dict):
        try:
            new_price = data.get('markPx')
            if new_price:
                self.mark_price = float(new_price)
            self.last_update_time = time.time()
        except (ValueError, TypeError) as e:
            logger.error(f"Error parsing OKX markPrice data: {e}", exc_info=True)
    
    async def update_depth_20(self, depth_data: Dict[str, Any]):
        if depth_data and 'bids' in depth_data and 'asks' in depth_data:
            bids_data = depth_data.get('bids', [])
            asks_data = depth_data.get('asks', [])
            self.depth_20['bids'] = [(float(p), float(q)) for p, q, _, _ in bids_data]
            self.depth_20['asks'] = [(float(p), float(q)) for p, q, _, _ in asks_data]
            self.depth_20['asks'].reverse()
            self.last_update_time = time.time()
    
    async def update_open_interest(self, oi_data: Dict[str, Any]):
        if oi_data and 'oi' in oi_data:
            self.open_interest = float(oi_data['oi'])
            self.last_update_time = time.time()

    async def update_account(self, account_data: dict):
        pass
    async def update_order(self, order_data: dict):
        pass
    async def update_premium_index(self, premium_data: Dict[str, Any]):
        pass
    async def update_book_ticker(self, ticker_data: Dict[str, Any]):
        pass
    async def update_recent_trades(self, trades_data: List[Any]):
        pass
    async def update_oi_history(self, oi_history_data: List[Any]):
        pass
    def get_spread(self) -> Optional[float]:
        return None
    def get_latest_data_snapshot(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol, "mark_price": self.mark_price,
            "klines": list(self.klines), 
            "live_reconstructed_candle": self.live_reconstructed_candle,
            "depth_20": self.depth_20,
            "depth_5": self.depth_5, "book_ticker": self.book_ticker,
            "recent_trades": list(self.recent_trades), "open_interest": self.open_interest,
            "oi_history": list(self.oi_history),
        }
    def get_best_bid(self) -> Optional[float]:
        return None
    def get_best_ask(self) -> Optional[float]:
        return None
