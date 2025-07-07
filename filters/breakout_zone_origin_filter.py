import logging
import os
import json
from typing import Dict, Any, Set
from datetime import datetime

from config.config import Config
from data_managers.market_state import MarketState

def setup_breakout_logger(config: Config) -> logging.Logger:
    """Sets up a dedicated logger for the BreakoutZoneOriginFilter."""
    log_path = config.breakout_filter_log_path

    log_dir = os.path.dirname(log_path)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logger = logging.getLogger('BreakoutZoneOriginFilterLogger')
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.FileHandler(log_path)
        formatter = logging.Formatter('%(asctime)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger

class BreakoutZoneOriginFilter:
    """
    Validates a breakout by ensuring it originated from a low-volatility zone.
    """
    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_breakout_logger(self.config)

        # Dynamic logic parameters from config
        self.zone_lookback = self.config.breakout_zone_lookback
        self.volatility_ratio = self.config.breakout_zone_volatility_ratio

        self.allowed_hours = self._parse_trade_windows(config.trade_windows)

        self.logger.info(
            f"BreakoutZoneOriginFilter Initialized. Lookback: {self.zone_lookback}, "
            f"Volatility Ratio: {self.volatility_ratio}"
        )

    def _parse_trade_windows(self, window_str: str) -> Set[int]:
        """Parses the trade window string into a set of hours."""
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
        """Checks if the current UTC hour is within the allowed trading windows."""
        return datetime.utcnow().hour in self.allowed_hours

    async def generate_report(self, market_state: MarketState) -> Dict[str, Any]:
        """
        Analyzes kline data for valid breakout origins and generates a report.
        """
        report = {
            "filter_name": "BreakoutZoneOriginFilter",
            "breakout_origin_valid": False,
            "confidence_score": 0.0,
            "notes": "Not in trade window or not autonomous."
        }

        if not self.config.autonomous_mode_enabled or not self._is_within_trade_window():
            return report

        report["notes"] = "No valid breakout pattern detected."
        klines = list(market_state.klines)

        required_klines = self.zone_lookback + 3
        if len(klines) < required_klines:
            report["notes"] = f"Not enough kline data ({len(klines)}/{required_klines})."
            return report

        breakout_candle = klines[-1]
        breakout_range = float(breakout_candle[2]) - float(breakout_candle[3])

        pre_breakout_klines = klines[-4:-1]
        pre_breakout_ranges = [float(k[2]) - float(k[3]) for k in pre_breakout_klines]
        avg_pre_breakout_range = sum(pre_breakout_ranges) / len(pre_breakout_ranges) if pre_breakout_ranges else 0

        is_breakout = breakout_range > (avg_pre_breakout_range * 2.0) if avg_pre_breakout_range > 0 else False

        if not is_breakout:
            report["notes"] = "No recent high-volatility breakout candle identified."
            self.logger.info(f"REJECTED: No breakout. Range {breakout_range:.4f} vs Pre-breakout Avg {avg_pre_breakout_range:.4f}")
            return report

        origin_zone_klines = klines[-(required_klines):-4]
        origin_zone_ranges = [float(k[2]) - float(k[3]) for k in origin_zone_klines]
        avg_origin_zone_range = sum(origin_zone_ranges) / len(origin_zone_ranges) if origin_zone_ranges else 0

        is_valid_origin = avg_origin_zone_range < (avg_pre_breakout_range * self.volatility_ratio) if avg_pre_breakout_range > 0 else False

        if is_valid_origin:
            confidence = 1.0 - (avg_origin_zone_range / avg_pre_breakout_range) if avg_pre_breakout_range > 0 else 0

            report.update({
                "breakout_origin_valid": True,
                "confidence_score": round(confidence, 4),
                "notes": f"Valid breakout origin. Origin range {avg_origin_zone_range:.4f} < Pre-breakout avg {avg_pre_breakout_range:.4f}"
            })

            self.logger.info(
                f"DECISION: Valid origin. OriginRange={avg_origin_zone_range:.4f}, "
                f"PreBreakoutRange={avg_pre_breakout_range:.4f}, "
                f"BreakoutRange={breakout_range:.4f}, "
                f"VolatilityRatio={self.volatility_ratio}, "
                f"Confidence={round(confidence, 4)}"
            )
        else:
            report["notes"] = f"Invalid origin zone. Origin range {avg_origin_zone_range:.4f} > threshold."
            self.logger.info(
                f"REJECTED: Invalid origin. OriginRange={avg_origin_zone_range:.4f}, "
                f"PreBreakoutRange={avg_pre_breakout_range:.4f}, "
                f"VolatilityRatio={self.volatility_ratio}"
            )

        return report