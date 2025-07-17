import logging
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
        self.time_offset: int = 0
        self.order_book_parser = OrderBookParser()
        
        # --- Core Data Attributes ---
        self.mark_price: Optional[float] = None
        self.klines: deque = deque(maxlen=config.kline_deque_maxlen)
        self.book_ticker: Dict[str, Any] = {}
        self.recent_trades: deque = deque(maxlen=1000)
        self.depth_20: Dict[str, Any] = {"bids": [], "asks": []}
        self.depth_5: Dict[str, Any] = {"bids": [], "asks": []}
        self.live_reconstructed_candle: Optional[List[Any]] = None
        self.open_interest: float = 0.0

        # --- Private Account Data ---
        self.positions: Dict[str, Dict] = {}
        self.account_balance: Optional[float] = None
        
        # --- Advanced Analysis Metrics (GENESIS) ---
        self.order_book_pressure: Dict[str, float] = {}
        self.momentum_deltas: Dict[str, float] = {"speed": 0.0, "acceleration": 0.0}
        self.last_trade_time: Optional[int] = None
        self.order_book_walls: Dict[str, Any] = {}
        self.spoof_metrics: Dict[str, float] = {}
        self.previous_depth_20: Dict[str, Any] = {"bids": [], "asks": []}
        self.filter_audit_report: Dict[str, Any] = {}
        
        logger.debug(f"MarketState for symbol {self.symbol} initialized.")

    async def update_live_reconstructed_candle(self, candle: List[Any]):
        self.live_reconstructed_candle = candle
        logger.debug("Updated live reconstructed candle: %s", candle)

    async def update_from_ws_books(self, data: dict):
        try:
            logger.debug("Processing order book data: %s", data)
            self.previous_depth_20 = self.depth_20.copy()
            bids_data = data.get('bids', [])
            asks_data = data.get('asks', [])
            self.depth_20['bids'] = [(float(p), float(q)) for p, q, _, _ in bids_data]
            self.depth_20['asks'] = [(float(p), float(q)) for p, q, _, _ in asks_data]
            self.depth_20['asks'].reverse()
            self.order_book_pressure = self.order_book_parser.calculate_pressure_vectors(self.depth_20)
            self.order_book_walls = self.order_book_parser.find_wall_clusters(self.depth_20, self.config.orderbook_reversal_wall_multiplier)
            self.spoof_metrics = self.order_book_parser.analyze_thinning_and_spoofing(self.previous_depth_20, self.depth_20, self.config.spoof_distance_percent)
            self.last_update_time = time.time()
            logger.debug("Order book updated: bids=%d, asks=%d", len(self.depth_20['bids']), len(self.depth_20['asks']))
        except Exception as e:
            logger.error(f"Error processing 'books' data: %s", e, exc_info=True)
            self.order_book_pressure = {"bid_pressure": 0.0, "ask_pressure": 0.0, "total_pressure": 0.0}
            self.order_book_walls = {"bid_walls": [], "ask_walls": []}
            self.spoof_metrics = {"spoof_thin_rate": 0.0, "wall_delta_pct": 0.0}

    async def update_from_ws_agg_trade(self, data: dict):
        try:
            trade_time = int(data['ts'])
            trade_qty = float(data['sz'])
            trade = {'time': trade_time, 'price': float(data['px']), 'qty': trade_qty, 'side': data['side']}
            self.recent_trades.append(trade)
            self.last_update_time = time.time()

            if self.last_trade_time:
                time_delta = (trade_time - self.last_trade_time) / 1000.0
                if time_delta > 0:
                    speed = trade_qty / time_delta
                    acceleration = (speed - self.momentum_deltas.get("speed", 0)) / time_delta
                    self.momentum_deltas["speed"] = speed
                    self.momentum_deltas["acceleration"] = acceleration
            self.last_trade_time = trade_time
        except Exception as e:
            logger.error(f"Error processing 'trades' data or momentum: %s", e, exc_info=True)
            
    async def update_from_ws_kline(self, kline_data: list):
        if self.klines and self.klines[0][0] == int(kline_data[0]):
            self.klines[0] = kline_data
        else:
            self.klines.appendleft(kline_data)
        logger.debug("Updated kline: %s", kline_data)

    async def update_from_ws_book_ticker(self, data: dict):
        try:
            self.book_ticker = {
                'bidPrice': float(data.get('bidPx')),
                'bidQty': float(data.get('bidSz')),
                'askPrice': float(data.get('askPx')),
                'askQty': float(data.get('askSz')),
                'lastPrice': float(data.get('last'))
            }
            logger.debug("Updated book ticker: %s", self.book_ticker)
        except Exception as e:
            logger.error(f"Error updating book ticker: %s", e, exc_info=True)

    async def update_from_ws_mark_price(self, data: dict):
        try:
            new_price = data.get('markPx')
            if new_price is not None and isinstance(new_price, (int, float, str)) and float(new_price) > 0:
                self.mark_price = float(new_price)
                logger.debug("Updated mark price: %s", self.mark_price)
            else:
                logger.error("Invalid markPx in data: %s", data)
        except (ValueError, TypeError) as e:
            logger.error(f"Error parsing markPx: %s, data: %s", e, data)

    async def update_klines(self, klines_data: List[List[Any]]):
        if not klines_data:
            logger.error("No klines data provided")
            return
        self.klines.clear()
        for k in reversed(klines_data):
            try:
                self.klines.append([int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), float(k[6]), float(k[7]), str(k[8])])
            except (ValueError, TypeError) as e:
                logger.error(f"Error parsing kline: %s, error: %s", k, e)
        logger.debug("Updated %d klines", len(self.klines))
    
    async def update_open_interest(self, oi_data: Dict[str, Any]):
        if oi_data and 'oi' in oi_data:
            self.open_interest = float(oi_data['oi'])
            logger.debug("Updated open interest: %s", self.open_interest)
        else:
            logger.error("Invalid open interest data: %s", oi_data)

    async def update_account(self, account_data: dict):
        try:
            for balance in account_data.get('details', []):
                if balance.get('ccy') == 'USDT':
                    self.account_balance = float(balance.get('availBal', 0.0))
                    logger.debug("Updated account balance: %s", self.account_balance)
                    break
        except Exception as e:
            logger.error(f"Error parsing account balance data: %s", e, exc_info=True)

    async def update_order(self, order_data: dict):
        try:
            symbol = order_data.get('instId')
            if symbol:
                self.positions[symbol] = {
                    'amount': float(order_data.get('pos', 0.0)),
                    'entry_price': float(order_data.get('avgPx', 0.0)),
                    'unrealized_pnl': float(order_data.get('upl', 0.0))
                }
                logger.debug("Updated position for %s: %s", symbol, self.positions[symbol])
        except Exception as e:
            logger.error(f"Error parsing position data: %s", e, exc_info=True)

    async def update_filter_audit_report(self, filter_name: str, report: Dict[str, Any]):
        self.filter_audit_report[filter_name] = report
        logger.debug("Updated filter audit report for %s: %s", filter_name, report)
        
    def get_latest_data_snapshot(self) -> Dict[str, Any]:
        snapshot = {
            "symbol": self.symbol,
            "mark_price": self.mark_price,
            "klines": list(self.klines),
            "live_reconstructed_candle": self.live_reconstructed_candle,
            "depth_20": self.depth_20,
            "book_ticker": self.book_ticker,
            "recent_trades": list(self.recent_trades),
            "open_interest": self.open_interest,
            "order_book_pressure": self.order_book_pressure,
            "order_book_walls": self.order_book_walls,
            "spoof_metrics": self.spoof_metrics,
            "momentum_deltas": self.momentum_deltas,
            "filter_audit_report": self.filter_audit_report
        }
        logger.debug("Generated data snapshot: %s", snapshot)
        return snapshot