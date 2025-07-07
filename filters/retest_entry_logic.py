import logging
import os
import json
from typing import Dict, Any, Set
from datetime import datetime

from config.config import Config
from data_managers.market_state import MarketState

def setup_retest_logger(config: Config) -> logging.Logger:
    log_path = config.retest_logic_log_path
    log_dir = os.path.dirname(log_path)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logger = logging.getLogger('RetestEntryLogicLogger')
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.FileHandler(log_path)
        formatter = logging.Formatter('%(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
    return logger

class RetestEntryLogic:
    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_retest_logger(self.config)
        self.lookback = self.config.retest_lookback
        self.proximity_percent = self.config.retest_proximity_percent
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
            "filter_name": "RetestEntryLogic",
            "retest_detected": False,
            "retest_type": "none",
            "retest_level": 0.0,
            "notes": "Not in trade window or not autonomous."
        }

        if not self.config.autonomous_mode_enabled or not self._is_within_trade_window():
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "result": False,
                "denial_reason": "Not in trade window or autonomous mode off"
            }))
            return report

        klines = list(market_state.klines)
        mark_price = market_state.mark_price

        if len(klines) < self.lookback:
            report["notes"] = f"Not enough kline data ({len(klines)}/{self.lookback})."
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "result": False,
                "denial_reason": "Insufficient kline history",
                "klines_available": len(klines),
                "required": self.lookback
            }))
            return report
            
        if not mark_price:
            report["notes"] = "Mark price not available."
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "result": False,
                "denial_reason": "Mark price missing"
            }))
            return report

        lookback_klines = klines[-self.lookback:]
        highest_high = max(float(k[2]) for k in lookback_klines)
        lowest_low = min(float(k[3]) for k in lookback_klines)

        proximity_to_high = highest_high * (self.proximity_percent / 100)
        proximity_to_low = lowest_low * (self.proximity_percent / 100)

        if abs(mark_price - highest_high) <= proximity_to_high:
            report.update({
                "retest_detected": True,
                "retest_type": "resistance",
                "retest_level": highest_high,
                "notes": f"Price {mark_price} is retesting resistance level at {highest_high}."
            })
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "retest_type": "resistance",
                "retest_level": highest_high,
                "mark_price": mark_price,
                "proximity_threshold": proximity_to_high,
                "result": True
            }))
        elif abs(mark_price - lowest_low) <= proximity_to_low:
            report.update({
                "retest_detected": True,
                "retest_type": "support",
                "retest_level": lowest_low,
                "notes": f"Price {mark_price} is retesting support level at {lowest_low}."
            })
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "retest_type": "support",
                "retest_level": lowest_low,
                "mark_price": mark_price,
                "proximity_threshold": proximity_to_low,
                "result": True
            }))
        else:
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "result": False,
                "denial_reason": "No retest match found",
                "mark_price": mark_price,
                "highest_high": highest_high,
                "lowest_low": lowest_low,
                "proximity_high": proximity_to_high,
                "proximity_low": proximity_to_low
            }))

        return report