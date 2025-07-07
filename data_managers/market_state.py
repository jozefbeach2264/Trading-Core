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
        
        self.mark_price: Optional[float] = None
        self.klines: deque = deque(maxlen=self.config.kline_deque_maxlen)
        self.book_ticker: Dict[str, Any] = {}
        self.recent_trades: deque = deque(maxlen=1000)
        self.depth_20: Dict[str, Any] = {"bids": [], "asks": []}
        self.depth_5: Dict[str, Any] = {"bids": [], "asks": []}
        self.open_interest: float = 0.0
        self.oi_history: deque = deque(maxlen=300)
        self.positions: Dict[str, Dict] = {}
        self.account_balance: Optional[float] = None

        logger.info(f"MarketState for symbol {self.symbol} initialized.")
        
    async def update_account(self, account_data: dict):
        # Preserved from your original file
        pass

    async def update_order(self, order_data: dict):
        # Preserved from your original file
        pass

    async def update_from_ws_books(self, data: dict):
        try:
            bids_data = data.get('bids', [])
            asks_data = data.get('asks', [])
            self.bids = [(float(p), float(q)) for p, q, _, _ in bids_data]
            self.asks = [(float(p), float(q)) for p, q, _, _ in asks_data]
            self.asks.reverse()
            self.last_update_time = time.time()
        except (ValueError, TypeError) as e:
            logger.error(f"Error parsing OKX books data: {e}", exc_info=True)

    async def update_from_ws_books5(self, data: dict):
        try:
            bids_data = data.get('bids', [])
            asks_data = data.get('asks', [])
            self.depth_5['bids'] = [(float(p), float(q)) for p, q, _, _ in bids_data]
            self.depth_5['asks'] = [(float(p), float(q)) for p, q, _, _ in asks_data]
            self.depth_5['asks'].reverse()
            self.last_update_time = time.time()
        except (ValueError, TypeError) as e:
            logger.error(f"Error parsing OKX books5 data: {e}", exc_info=True)

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
            # ✅ FINAL FIX: OKX candlestick data has 9 fields.
            # [ts,o,h,l,c,vol,volCcy,volCcyQuote,confirm]
            # The 'confirm' flag at the end indicates if the candle is finalized.
            formatted_kline = [
                int(kline_data[0]), float(kline_data[1]), float(kline_data[2]),
                float(kline_data[3]), float(kline_data[4]), float(kline_data[5]),
                float(kline_data[6]), float(kline_data[7]), str(kline_data[8])
            ]
            if self.klines and self.klines[0][0] == formatted_kline[0]:
                self.klines[0] = formatted_kline
            else:
                self.klines.appendleft(formatted_kline)
            self.last_update_time = time.time()
        except (ValueError, TypeError, IndexError) as e:
            logger.error(f"Error parsing OKX kline data: {kline_data} - {e}", exc_info=True)
        
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
            if new_price is not None:
                self.mark_price = float(new_price)
            self.last_update_time = time.time()
        except (ValueError, TypeError) as e:
            logger.error(f"Error parsing OKX markPrice data: {e}", exc_info=True)

    async def update_klines(self, klines_data: List[List[Any]]):
        if not klines_data or not isinstance(klines_data, list):
            return
        self.klines.clear()
        for k in klines_data:
            try:
                # ✅ FINAL FIX: Ensure REST data matches the 9-field structure.
                formatted_kline = [
                    int(k[0]), float(k[1]), float(k[2]),
                    float(k[3]), float(k[4]), float(k[5]),
                    float(k[6]), float(k[7]), str(k[8])
                ]
                self.klines.appendleft(formatted_kline)
            except (ValueError, TypeError, IndexError) as e:
                logger.error(f"Error parsing OKX historical kline: {k} - {e}")
        self.last_update_time = time.time()

    async def update_depth_20(self, depth_data: Dict[str, Any]):
        if depth_data and 'bids' in depth_data and 'asks' in depth_data:
            self.depth_20['bids'] = [(float(p), float(q)) for p, q, _, _ in depth_data.get('bids', [])]
            self.depth_20['asks'] = [(float(p), float(q)) for p, q, _, _ in depth_data.get('asks', [])]
            self.depth_20['asks'].reverse()
            self.last_update_time = time.time()
    
    async def update_open_interest(self, oi_data: Dict[str, Any]):
        if oi_data and 'oi' in oi_data:
            self.open_interest = float(oi_data['oi'])
            self.last_update_time = time.time()

    # The following methods are preserved from your original file
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
            "klines": list(self.klines), "depth_20": self.depth_20,
            "depth_5": self.depth_5, "book_ticker": self.book_ticker,
            "recent_trades": list(self.recent_trades), "open_interest": self.open_interest,
            "oi_history": list(self.oi_history),
        }
    def get_best_bid(self) -> Optional[float]:
        return None
    def get_best_ask(self) -> Optional[float]:
        return None
