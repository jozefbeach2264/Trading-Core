import logging
import asyncio
from collections import deque
import time
from typing import Dict, Any, Optional, List
from config.config import Config
from data_managers.orderbook_l2 import L2Book, SequenceGap
from data_managers.orderbook_parser import OrderBookParser, WallTracker

logger = logging.getLogger(__name__)

SPOOF_WINDOW_S = 1.0   # publish the worst thinning seen within the last second of book ticks


class MarketState:
    def __init__(self, symbol: str, config: Config):
        self.symbol = symbol
        self.config = config
        self.last_update_time: float = time.time()
        self.order_book_parser = OrderBookParser()
        self.l2_book = L2Book()
        self.wall_tracker = WallTracker(config.wall_size_multiple, config.wall_skip_levels,
                                        config.wall_min_age_s, config.wall_max_distance_pct)
        self.wall_events: List[Dict[str, Any]] = []              # endings from the most recent book update
        self.recent_wall_events: deque = deque(maxlen=200)       # rolling history for TrapX
        self.initial_data_ready = asyncio.Event()

        # --- Caching Flag ---
        self._is_ob_metrics_dirty: bool = True

        # --- CORRECTED: Core attributes are now correctly initialized within __init__ ---
        self.mark_price: Optional[float] = None
        self.klines: deque = deque(maxlen=config.kline_deque_maxlen)
        self.book_ticker: Dict[str, Any] = {}
        self.recent_trades: deque = deque(maxlen=1000)
        self.depth_20: Dict[str, Any] = {"bids": [], "asks": []}
        self.live_reconstructed_candle: Optional[List[Any]] = None
        self.open_interest: float = 0.0
        self.positions: Dict[str, Dict] = {}
        self.account_balance: Optional[float] = None
        self.oi_history: deque = deque(maxlen=600)  # store recent OI snapshots (ts, oi)
        
        # --- Live Calculated & Cached Metrics ---
        self.running_cvd: float = 0.0
        self.order_book_pressure: Dict[str, float] = {}
        self.order_book_walls: Dict[str, Any] = {}
        self.spoof_metrics: Dict[str, float] = {}
        
        self.previous_depth_20: Dict[str, Any] = {"bids": [], "asks": []}
        self.filter_audit_report: Dict[str, Any] = {}
        # Direction of the signal currently being validated (LONG/SHORT); set by AIStrategy before the
        # post-signal filters run so a filter can judge context AGAINST the trade, cleared afterwards.
        self.pending_signal_direction: Optional[str] = None

        # OKX SWAP sizes (trade sz, candle vol) are in CONTRACTS; ctVal converts to the base asset (ETH).
        # Every consumer (volume guard, CVD, HUD, AI packet) assumes base-asset units.
        self.contract_value: float = 1.0
        # Per-tick thinning readings; the published spoof_thin_rate is the max over SPOOF_WINDOW_S so the
        # 0.2 s engine cycle cannot miss a pull that lasted one 100 ms book tick.
        self._spoof_ticks: deque = deque(maxlen=64)

        logger.debug(f"MarketState for symbol {self.symbol} initialized.")

    def set_contract_value(self, contract_value: float) -> None:
        if contract_value and contract_value > 0:
            self.contract_value = float(contract_value)

    def reset_l2_book(self) -> None:
        self.l2_book.reset()

    async def apply_l2_message(self, action: str, data: dict) -> bool:
        """Merge one `books` message into the local L2 book and publish its top N levels as depth_20.
        Returns False when the sequence chain broke (caller must resubscribe)."""
        try:
            self.l2_book.apply(action, data)
        except SequenceGap as e:
            logger.warning("L2 book sequence gap (%s); book invalidated", e)
            self.l2_book.reset()
            return False
        except Exception as e:  # noqa: BLE001 - a malformed level must not kill the feed
            logger.error("L2 book update failed: %r", e, exc_info=True)
            return True
        top = self.l2_book.top(self.config.orderbook_depth_levels)
        self.previous_depth_20 = self.depth_20
        self.depth_20 = top
        self._is_ob_metrics_dirty = True
        self.last_update_time = time.time()
        return True

    async def update_from_ws_books(self, data: dict):
        """
        Lean update method. Only updates raw data and marks the cache as dirty.
        """
        try:
            self.previous_depth_20 = self.depth_20.copy()
            bids_data = data.get('bids', [])
            asks_data = data.get('asks', [])
            # Accept variable tuple lengths from different book feeds
            def _parse_side(side):
                parsed = []
                for entry in side:
                    if len(entry) >= 2:
                        price, qty = entry[0], entry[1]
                        parsed.append((float(price), float(qty)))
                return parsed
            # OKX sends bids best-first (descending) and asks best-first (ascending) — verified 2026-09-15.
            # Keep that order: index 0 is top-of-book on both sides (the parser's wall threshold and the
            # console HUD depend on it). The old .reverse() made asks[0] the DEEPEST level.
            self.depth_20['bids'] = _parse_side(bids_data)
            self.depth_20['asks'] = _parse_side(asks_data)
            
            # Mark the cache as dirty; calculations will be done on-demand.
            self._is_ob_metrics_dirty = True
            self.last_update_time = time.time()
        except Exception as e:
            logger.error("Error processing raw 'books' data", extra={"error": str(e)}, exc_info=True)

    async def ensure_order_book_metrics_are_current(self):
        """
        If the cache is dirty, this method runs all expensive calculations once.
        Otherwise, it does nothing.
        """
        if self._is_ob_metrics_dirty:
            logger.debug("Order book metrics are dirty. Recalculating...")
            self.order_book_pressure = self.order_book_parser.calculate_pressure_vectors(self.depth_20)
            now = time.time()
            if self.config.wall_mode == "size_persistence":
                previous_walls = self.order_book_walls
                bids, asks = self.depth_20.get("bids") or [], self.depth_20.get("asks") or []
                mid = (bids[0][0] + asks[0][0]) / 2.0 if bids and asks else None
                # The wall tracker needs the FULL book: 50 levels on a $0.01 tick spans only $0.50, and price
                # walks out of that in seconds, so a resting wall looked like it vanished every few ticks.
                self.order_book_walls = self.wall_tracker.update(self.l2_book.top(self.config.wall_book_levels), now, mid=mid)
                # Wall endings are the TrapX signal: a pulled wall is a trap being sprung.
                self.wall_events = list(self.order_book_walls.get("events") or [])
                self.recent_wall_events.extend(self.wall_events)
                # Thinning = what happened to the walls we KNEW about, at their price, in the current book.
                tick = self.order_book_parser.thinning_of_walls(previous_walls, self.depth_20)
            else:
                self.order_book_walls = self.order_book_parser.find_wall_clusters(self.depth_20, self.config.orderbook_reversal_wall_multiplier)
                tick = self.order_book_parser.analyze_thinning_and_spoofing(
                    self.previous_depth_20, self.depth_20,
                    self.config.spoof_distance_percent, self.config.spoof_large_order_multiplier)
            self._spoof_ticks.append((now, tick))
            window = [t for ts, t in self._spoof_ticks if now - ts <= SPOOF_WINDOW_S]
            worst = max(window, key=lambda t: t.get("spoof_thin_rate", 0.0), default=tick)
            self.spoof_metrics = {
                **worst,
                "tick_thin_rate": tick.get("spoof_thin_rate", 0.0),
                "snapshot_ts": self.last_update_time,
            }
            self._is_ob_metrics_dirty = False # Mark the cache as clean

    async def update_from_ws_agg_trade(self, data: dict):
        try:
            trade_time = int(data['ts'])
            trade_qty = float(data['sz']) * self.contract_value   # contracts → base asset
            trade_side = data['side']
            trade = {'time': trade_time, 'price': float(data['px']), 'qty': trade_qty, 'side': trade_side}

            # If the deque is full and about to pop an old trade, subtract its value from CVD first.
            if len(self.recent_trades) == self.recent_trades.maxlen:
                oldest_trade = self.recent_trades[0]
                if oldest_trade['side'] == 'buy':
                    self.running_cvd -= oldest_trade['qty']
                elif oldest_trade['side'] == 'sell':
                    self.running_cvd += oldest_trade['qty']

            self.recent_trades.append(trade)
            
            # Update the running CVD with the new trade
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
        # OKX /market/history-candles returns NEWEST first (verified 2026-09-15), which is exactly this
        # deque's convention (index 0 = newest; websocket candles are appendleft'ed). The previous
        # reversed() stored the block oldest-first, so every lookback window mixed the newest live
        # candles with the OLDEST history until 500 websocket candles had pushed it out.
        self.klines.clear()
        for k in klines_data:
            try:
                if str(k[8]) != "1":
                    continue  # the in-progress minute is reconstructed live from trades, not stored as closed
                self.klines.append([int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]),
                                    float(k[5]) * self.contract_value,   # vol: contracts → base asset
                                    float(k[6]), float(k[7]), str(k[8])])
            except (ValueError, TypeError, IndexError) as e:
                logger.error("Error parsing historical kline", extra={"kline": k, "error": str(e)})

    async def update_open_interest(self, oi_data: Dict[str, Any]):
        if oi_data and 'oi' in oi_data:
            try:
                oi_value = float(oi_data['oi'])
                ts = int(oi_data.get('ts', time.time() * 1000))
            except (ValueError, TypeError):
                oi_value = self.open_interest
                ts = int(time.time() * 1000)
            self.open_interest = oi_value
            self.oi_history.append({"ts": ts, "oi": oi_value})
        else:
            logger.warning("Invalid open interest data received", extra={"data": oi_data})

    async def update_filter_audit_report(self, filter_name: str, report: Dict[str, Any]):
        self.filter_audit_report[filter_name] = report

    def get_latest_data_snapshot(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol, "mark_price": self.mark_price, "klines": list(self.klines),
            "live_reconstructed_candle": self.live_reconstructed_candle, "depth_20": self.depth_20,
            "book_ticker": self.book_ticker, "recent_trades": list(self.recent_trades),
            "open_interest": self.open_interest, "order_book_pressure": self.order_book_pressure,
            "order_book_walls": self.order_book_walls, "spoof_metrics": self.spoof_metrics,
            "running_cvd": self.running_cvd, "filter_audit_report": self.filter_audit_report
        }
