import logging
import os
import json
from typing import Dict, Any, Set
from datetime import datetime

from config.config import Config
from data_managers.market_state import MarketState

def setup_orderbook_logger(config: Config) -> logging.Logger:
    log_path = config.orderbook_reversal_log_path
    log_dir = os.path.dirname(log_path)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logger = logging.getLogger('OrderBookReversalZoneDetectorLogger')
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.FileHandler(log_path)
        formatter = logging.Formatter('%(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
    return logger

class OrderBookReversalZoneDetector:
    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_orderbook_logger(self.config)
        self.depth_percent = self.config.orderbook_reversal_depth_percent
        self.wall_multiplier = self.config.orderbook_reversal_wall_multiplier
        self.allowed_hours = self._parse_trade_windows(config.trade_windows)

    def _parse_trade_windows(self, window_str: str) -> Set[int]:
        allowed_hours = set()
        try:
            parts = window_str.split(',')
            for part in parts:
                if '-' in part:
                    start, end = map(int, part.split('-'))
                    for hour in range(start, end + 1):
                        allowed_hours.add(hour)
                else:
                    allowed_hours.add(int(part))
        except ValueError as e:
            logging.getLogger(__name__).error(f"Invalid trade_windows format: '{window_str}'. Error: {e}")
        return allowed_hours

    def _is_within_trade_window(self) -> bool:
        return datetime.utcnow().hour in self.allowed_hours

    async def generate_report(self, market_state: MarketState) -> Dict[str, Any]:
        report = {
            "filter_name": "OrderBookReversalZoneDetector",
            "reversal_zone_detected": False,
            "zone_type": "none",
            "total_zone_volume": 0.0,
            "notes": "Not in trade window or not autonomous."
        }

        if not self.config.autonomous_mode_enabled or not self._is_within_trade_window():
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "result": False,
                "denial_reason": "Not in trade window or autonomous mode off"
            }))
            return report

        bids = market_state.depth_20.get("bids", [])
        asks = market_state.depth_20.get("asks", [])
        mark_price = market_state.mark_price

        if not bids or not asks or not mark_price:
            report["notes"] = "Not enough order book data to analyze."
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "result": False,
                "denial_reason": "Missing order book data"
            }))
            return report

        ask_zone_start = mark_price * (1 + (self.depth_percent / 100))
        bid_zone_start = mark_price * (1 - (self.depth_percent / 100))

        ask_wall_threshold = float(asks[0][1]) * self.wall_multiplier
        bid_wall_threshold = float(bids[0][1]) * self.wall_multiplier

        resistance_volume = sum(float(qty) for price, qty in asks if float(price) >= ask_zone_start)

        if resistance_volume > ask_wall_threshold:
            report.update({
                "reversal_zone_detected": True,
                "zone_type": "resistance",
                "total_zone_volume": resistance_volume,
                "notes": f"Large resistance wall detected ({resistance_volume:.2f}) above threshold ({ask_wall_threshold:.2f})."
            })
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "zone_type": "resistance",
                "zone_volume": round(resistance_volume, 2),
                "threshold_volume": round(ask_wall_threshold, 2),
                "result": True
            }))
            return report

        support_volume = sum(float(qty) for price, qty in bids if float(price) <= bid_zone_start)

        if support_volume > bid_wall_threshold:
            report.update({
                "reversal_zone_detected": True,
                "zone_type": "support",
                "total_zone_volume": support_volume,
                "notes": f"Large support wall detected ({support_volume:.2f}) above threshold ({bid_wall_threshold:.2f})."
            })
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "zone_type": "support",
                "zone_volume": round(support_volume, 2),
                "threshold_volume": round(bid_wall_threshold, 2),
                "result": True
            }))
            return report

        self.logger.info(json.dumps({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "result": False,
            "denial_reason": "No qualifying reversal wall found",
            "resistance_volume": round(resistance_volume, 2),
            "resistance_threshold": round(ask_wall_threshold, 2),
            "support_volume": round(support_volume, 2),
            "support_threshold": round(bid_wall_threshold, 2)
        }))
        return report