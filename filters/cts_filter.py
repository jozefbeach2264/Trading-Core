import logging
import os
import json
from typing import Dict, Any, Set
from datetime import datetime

from config.config import Config
from data_managers.market_state import MarketState

def setup_cts_logger(config: Config) -> logging.Logger:
    # This function is unchanged.
    log_path = config.cts_filter_log_path

    log_dir = os.path.dirname(log_path)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logger = logging.getLogger('CtsFilterLogger')
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.FileHandler(log_path)
        formatter = logging.Formatter('%(asctime)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger

class CtsFilter:
    def __init__(self, config: Config):
        # This function is unchanged.
        self.config = config
        self.logger = setup_cts_logger(self.config)
        self.lookback_period = self.config.cts_lookback_period
        self.narrow_range_ratio = self.config.cts_narrow_range_ratio
        self.rejection_multiplier = self.config.cts_wick_rejection_multiplier
        self.allowed_hours = self._parse_trade_windows(config.trade_windows)
        self.logger.info(
            f"CtsFilter Initialized. Lookback: {self.lookback_period}, "
            f"Narrow Range Ratio: {self.narrow_range_ratio}, "
            f"Wick Multiplier: {self.rejection_multiplier}"
        )

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
            self.logger.error(f"Invalid trade_windows format: '{window_str}'. Error: {e}")
        return allowed_hours

    def _is_within_trade_window(self) -> bool:
        # This function is unchanged.
        return datetime.utcnow().hour in self.allowed_hours

    async def generate_report(self, market_state: MarketState) -> Dict[str, Any]:
        report = {
            "filter_name": "CtsFilter",
            "trap_probability": 0.0,
            "trap_direction": "none",
            "notes": "Not in trade window or not autonomous."
        }

        if not self.config.autonomous_mode_enabled or not self._is_within_trade_window():
            return report

        report["notes"] = "No pattern detected."
        
        # ✅ NECESSARY UPDATE: Get both historical and live candle data.
        klines = market_state.klines
        live_candle = market_state.live_reconstructed_candle

        if len(klines) < self.lookback_period:
            report["notes"] = f"Not enough historical kline data ({len(klines)}/{self.lookback_period})."
            return report

        if not live_candle:
            report["notes"] = "Live candle data not yet available for CTS check."
            return report

        # This logic is unchanged as it correctly uses historical data.
        lookback_klines = list(klines)[-self.lookback_period:]
        ranges = [float(k[2]) - float(k[3]) for k in lookback_klines]
        average_range = sum(ranges) / len(ranges) if ranges else 0

        # ✅ NECESSARY UPDATE: The candle to be analyzed is now our live, reconstructed candle.
        last_candle = live_candle
        o, h, l, c = map(float, [last_candle[1], last_candle[2], last_candle[3], last_candle[4]])

        current_range = h - l
        current_body = abs(c - o)

        is_compressed = current_range < (average_range * self.narrow_range_ratio) if average_range > 0 else False

        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        dynamic_rejection_threshold = current_body * self.rejection_multiplier

        wick_signal = "none"
        if lower_wick > dynamic_rejection_threshold:
            wick_signal = "bull_trap"
        elif upper_wick > dynamic_rejection_threshold:
            wick_signal = "bear_trap"

        if is_compressed and wick_signal != "none":
            exceed_ratio = 0
            if wick_signal == "bull_trap" and dynamic_rejection_threshold > 0:
                exceed_ratio = lower_wick / dynamic_rejection_threshold
            elif wick_signal == "bear_trap" and dynamic_rejection_threshold > 0:
                exceed_ratio = upper_wick / dynamic_rejection_threshold

            probability = min(0.70 + (0.05 * (exceed_ratio - 1)), 0.95)

            report.update({
                "trap_probability": round(probability, 4),
                "trap_direction": wick_signal,
                "notes": f"Compression trap detected ({wick_signal}). Live range {current_range:.2f}."
            })
            
            # This logging is preserved and correct.
            log_payload = report.copy()
            log_payload["details"] = { "avg_range": round(average_range, 4), "current_range": round(current_range, 4), "dynamic_threshold": round(dynamic_rejection_threshold, 4), "lower_wick": round(lower_wick, 4), "upper_wick": round(upper_wick, 4)}
            self.logger.info(f"DECISION: {log_payload}")
        else:
            report["notes"] = "No compression trap pattern detected."

        return report
