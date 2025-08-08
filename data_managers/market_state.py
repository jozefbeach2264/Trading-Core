import logging
import asyncio
from collections import deque
import time
from typing import Dict, Any, Optional, List
from config.config import Config
from data_managers.orderbook_parser import OrderBookParser

logger = logging.getLogger(__name__)

class MarketState:
    def __init__(self, symbol: str, config: Config):
        self.symbol = symbol
        self.config = config
        self.last_update_time: float = time.time()
        self.order_book_parser = OrderBookParser()
        self.initial_data_ready = asyncio.Event()

        # --- Caching Flag ---
        self._is_ob_metrics_dirty: bool = True

        # --- Core attributes ---
        self.mark_price: Optional[float] = None
        self.klines: deque = deque(maxlen=config.kline_deque_maxlen)
        self.book_ticker: Dict[str, Any] = {}
        self.recent_trades: deque = deque(maxlen=1000)
        self.depth_20: Dict[str, Any] = {"bids": [], "asks": []}
        self.live_reconstructed_candle: Optional[List[Any]] = None
        self.open_interest: float = 0.0
        self.oi_history: deque = deque(maxlen=config.kline_deque_maxlen)
        self.positions: Dict[str, Dict] = {}
        self.account_balance: Optional[float] = None

        # --- Live Calculated & Cached Metrics ---
        self.running_cvd: float = 0.0
        self.order_book_pressure: Dict[str, float] = {}
        self.order_book_walls: Dict[str, Any] = {}
        self.spoof_metrics: Dict[str, float] = {}

        self.previous_depth_20: Dict[str, Any] = {"bids": [], "asks": []}
        self.filter_audit_report: Dict[str, Any] = {}
        self.system_stats: Dict[str, Any] = {}

        logger.debug(f"MarketState for symbol {self.symbol} initialized.")

    async def update_system_stats(self, stats: Dict[str, Any]):
        """Updates the system resource statistics."""
        self.system_stats = stats

    async def update_from_ws_books(self, data: dict):
        try:
            self.previous_depth_20 = self.depth_20.copy()
            bids_data = data.get('bids', [])
            asks_data = data.get('asks', [])
            self.depth_20['bids'] = [(float(p), float(q)) for p, q, _, _ in bids_data]
            self.depth_20['asks'] = [(float(p), float(q)) for p, q, _, _ in asks_data]
            self.depth_20['asks'].reverse()

            self._is_ob_metrics_dirty = True
            self.last_update_time = time.time()
        except Exception as e:
            logger.error("Error processing raw 'books' data", extra={"error": str(e)}, exc_info=True)

    async def ensure_order_book_metrics_are_current(self):
        if self._is_ob_metrics_dirty:
            logger.debug("Order book metrics are dirty. Recalculating...")
            self.order_book_pressure = self.order_book_parser.calculate_pressure_vectors(self.depth_20)
            self.order_book_walls = self.order_book_parser.find_wall_clusters(self.depth_20, self.config.orderbook_reversal_wall_multiplier)
            self.spoof_metrics = self.order_book_parser.analyze_thinning_and_spoofing(self.previous_depth_20, self.depth_20, self.config.spoof_distance_percent)
            self._is_ob_metrics_dirty = False

    async def update_from_ws_agg_trade(self, data: dict):
        try:
            trade_time = int(data['ts'])
            trade_qty = float(data['sz'])
            trade_side = data['side']

            # --- FINAL FIX: Use the 'side' field to determine the maker/taker ---
            trade = {
                'time': trade_time,
                'price': float(data['px']),
                'qty': trade_qty,
                'side': trade_side,
                'isBuyerMaker': data['side'] == 'sell'
            }

            if len(self.recent_trades) == self.recent_trades.maxlen:
                oldest_trade = self.recent_trades[0]
                if oldest_trade['side'] == 'buy':
                    self.running_cvd -= oldest_trade['qty']
                elif oldest_trade['side'] == 'sell':
                    self.running_cvd += oldest_trade['qty']

            self.recent_trades.append(trade)

            if trade_side == 'buy':
                self.running_cvd += trade_qty
            elif trade_side == 'sell':
                self.running_cvd -= trade_qty

            self.last_update_time = time.time()
        except Exception as e:
            logger.error("Error processing 'trades' data or CVD", extra={"error": str(e)}, exc_info=True)

    async def update_live_reconstructed_candle(self, candle: List[Any]):
        self.live_reconstructed_candle = candle

    async def update_from_ws_kline(self, kline_data: list):
        if self.klines and self.klines[0][0] == int(kline_data[0]):
            self.klines[0] = kline_data
        else:
            self.klines.appendleft(kline_data)

    async def update_from_ws_book_ticker(self, data: dict):
        try:
            self.book_ticker = {
                'bidPrice': float(data.get('bidPx')), 'bidQty': float(data.get('bidSz')),
                'askPrice': float(data.get('askPx')), 'askQty': float(data.get('askSz')),
                'lastPrice': float(data.get('last'))
            }
        except Exception as e:
            logger.error("Error updating book ticker", extra={"error": str(e)}, exc_info=True)

    async def update_from_ws_mark_price(self, data: dict):
        try:
            new_price = data.get('markPx')
            if new_price is not None and isinstance(new_price, (int, float, str)) and float(new_price) > 0:
                self.mark_price = float(new_price)
            else:
                logger.warning("Invalid markPx in data received", extra={"data": data})
        except (ValueError, TypeError) as e:
            logger.error("Error parsing markPx", extra={"error": str(e), "data": data})

    async def update_klines(self, klines_data: List[List[Any]]):
        if not klines_data:
            logger.warning("No klines data provided to update.")
            return
        self.klines.clear()
        for k in reversed(klines_data):
            try:
                self.klines.append([int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), float(k[6]), float(k[7]), str(k[8])])
            except (ValueError, TypeError) as e:
                logger.error("Error parsing historical kline", extra={"kline": k, "error": str(e)})

    async def update_open_interest(self, oi_data: Dict[str, Any]):
        if oi_data and 'oi' in oi_data:
            self.open_interest = float(oi_data['oi'])
            self.oi_history.append({'timestamp': int(oi_data.get('ts', time.time() * 1000)), 'openInterest': self.open_interest})
        else:
            logger.warning("Invalid open interest data received", extra={"data": oi_data})

    async def update_filter_audit_report(self, filter_name: str, report: Dict[str, Any]):
        self.filter_audit_report[filter_name] = report

    def get_latest_data_snapshot(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol, "mark_price": self.mark_price, "klines": list(self.klines),
            "live_reconstructed_candle": self.live_reconstructed_candle, "depth_20": self.depth_20,
            "book_ticker": self.book_ticker, "recent_trades": list(self.recent_trades),
            "open_interest": self.open_interest, "oi_history": list(self.oi_history),
            "order_book_pressure": self.order_book_pressure,
            "order_book_walls": self.order_book_walls, "spoof_metrics": self.spoof_metrics,
            "running_cvd": self.running_cvd, "filter_audit_report": self.filter_audit_report,
            "system_stats": self.system_stats
        }

    def is_ready(self, required_candles: int = 100) -> bool:
        return len(self.klines) >= required_candles