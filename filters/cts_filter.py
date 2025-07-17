import logging
import os
from typing import Dict, Any, Set
from datetime import datetime

from config.config import Config
from data_managers.market_state import MarketState

def setup_cts_logger(config: Config) -> logging.Logger:
    log_path = config.cts_filter_log_path
    log_dir = os.path.dirname(log_path) if os.path.dirname(log_path) else '.'
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger('CtsFilterLogger')
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    logger.handlers.clear()
    file_handler = logging.FileHandler(log_path, mode='a')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(console_handler)

    return logger

class CtsFilter:
    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_cts_logger(self.config)
        self.lookback_period = self.config.cts_lookback_period
        self.narrow_range_ratio = self.config.cts_narrow_range_ratio
        self.rejection_multiplier = self.config.cts_wick_rejection_multiplier
        self.logger.debug("CtsFilter initialized: lookback=%d, narrow_range_ratio=%.2f, rejection_multiplier=%.2f",
                         self.lookback_period, self.narrow_range_ratio, self.rejection_multiplier)

    async def generate_report(self, market_state: MarketState) -> Dict[str, Any]:
        report = {
            "filter_name": "CtsFilter",
            "score": 0.0,
            "metrics": {},
            "flag": "❌ Block"
        }

        klines = market_state.klines
        live_candle = market_state.live_reconstructed_candle
        mark_price = market_state.mark_price or 0.0

        self.logger.debug("Checking MarketState: klines_length=%d, live_candle=%s, mark_price=%s",
                         len(klines), live_candle, mark_price)

        if len(klines) < self.lookback_period:
            report["metrics"]["reason"] = f"Not enough historical klines ({len(klines)}/{self.lookback_period})."
            self.logger.error(report["metrics"]["reason"])
            return report

        if not live_candle:
            report["metrics"]["reason"] = "Live candle data not available."
            self.logger.error(report["metrics"]["reason"])
            return report

        if mark_price <= 0:
            report["metrics"]["reason"] = "Invalid mark price."
            self.logger.error(report["metrics"]["reason"])
            return report

        lookback_klines = list(klines)[-self.lookback_period:]
        ranges = [float(k[2]) - float(k[3]) for k in lookback_klines]
        average_range = sum(ranges) / len(ranges) if ranges else 0

        o, h, l, c = map(float, [live_candle[1], live_candle[2], live_candle[3], live_candle[4]])
        current_range = h - l
        # Adjust range with mark_price if candle is stale
        if mark_price > 0:
            current_range = max(current_range, abs(mark_price - max(o, c)), abs(mark_price - min(o, c)))
        current_body = abs(c - o)

        if average_range <= 0 or current_range <= 0:
            report["metrics"]["reason"] = "Invalid candle data (zero or negative range)."
            self.logger.error(report["metrics"]["reason"])
            return report

        is_compressed = current_range < (average_range * self.narrow_range_ratio)
        grind_ratio = current_range / average_range

        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        dynamic_rejection_threshold = current_body * self.rejection_multiplier

        wick_signal = "none"
        wick_strength = 0.0
        if lower_wick > dynamic_rejection_threshold and dynamic_rejection_threshold > 0:
            wick_signal = "bull_trap_rejection"
            wick_strength = lower_wick / dynamic_rejection_threshold
        elif upper_wick > dynamic_rejection_threshold and dynamic_rejection_threshold > 0:
            wick_signal = "bear_trap_rejection"
            wick_strength = upper_wick / dynamic_rejection_threshold

        report["metrics"] = {
            "average_range": round(average_range, 4),
            "current_range": round(current_range, 4),
            "grind_ratio": round(grind_ratio, 2),
            "is_compressed": is_compressed,
            "wick_signal": wick_signal,
            "wick_strength_ratio": round(wick_strength, 2),
            "mark_price": round(mark_price, 4)
        }
        
        score = 0.0
        if is_compressed and wick_signal != "none":
            score = 0.6
            score += min((wick_strength - 1) * 0.2, 0.4)
        elif not is_compressed:
            score = 1.0
        
        report["score"] = round(score, 4)
        report["flag"] = "✅ Hard Pass" if score >= 0.75 else "⚠️ Soft Flag" if score >= 0.50 else "❌ Block"

        self.logger.debug("CtsFilter report: score=%.4f, flag=%s, metrics=%s",
                         report["score"], report["flag"], report["metrics"])
        await market_state.update_filter_audit_report("CtsFilter", report)
        return report