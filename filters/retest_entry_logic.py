import logging
import os
import json
from typing import Dict, Any, Set
from datetime import datetime

from config.config import Config
from data_managers.market_state import MarketState

def setup_retest_logger(config: Config) -> logging.Logger:
    # This function is unchanged.
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
        # This function is unchanged.
        self.config = config
        self.logger = setup_retest_logger(self.config)
        self.lookback = self.config.retest_lookback
        self.proximity_percent = self.config.retest_proximity_percent
        self.allowed_hours = self._parse_trade_windows(config.trade_windows)

    def _parse_trade_windows(self, window_str: str) -> Set[int]:
        # This function is unchanged.
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
        # This function is unchanged.
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
            return report

        # ✅ NECESSARY UPDATE: Get both historical and live candle data.
        klines = market_state.klines
        live_candle = market_state.live_reconstructed_candle

        # Check for historical data to establish levels
        if len(klines) < self.lookback:
            report["notes"] = f"Not enough kline history to establish levels ({len(klines)}/{self.lookback})."
            return report
            
        # Check for the live intra-candle data to perform the check
        if not live_candle:
            report["notes"] = "Live candle data not yet available for retest check."
            return report

        # This logic is unchanged: find the significant high/low from history.
        lookback_klines = list(klines)[-self.lookback:]
        highest_high = max(float(k[2]) for k in lookback_klines)
        lowest_low = min(float(k[3]) for k in lookback_klines)

        proximity_to_high = highest_high * (self.proximity_percent / 100)
        proximity_to_low = lowest_low * (self.proximity_percent / 100)

        # ✅ NECESSARY UPDATE: Use the live candle's high and low for the comparison.
        live_candle_high = float(live_candle[2])
        live_candle_low = float(live_candle[3])

        if abs(live_candle_high - highest_high) <= proximity_to_high:
            report.update({
                "retest_detected": True,
                "retest_type": "resistance",
                "retest_level": highest_high,
                "notes": f"Live price high {live_candle_high} is retesting resistance at {highest_high}."
            })
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "retest_type": "resistance",
                "retest_level": highest_high,
                "live_candle_high": live_candle_high,
                "result": True
            }))
        elif abs(live_candle_low - lowest_low) <= proximity_to_low:
            report.update({
                "retest_detected": True,
                "retest_type": "support",
                "retest_level": lowest_low,
                "notes": f"Live price low {live_candle_low} is retesting support at {lowest_low}."
            })
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "retest_type": "support",
                "retest_level": lowest_low,
                "live_candle_low": live_candle_low,
                "result": True
            }))
        else:
            # This is not an error, just a log that no retest was detected.
            report["notes"] = "No retest of significant levels detected."

        return report
