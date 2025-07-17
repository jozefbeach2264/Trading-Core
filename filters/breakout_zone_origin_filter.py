import logging
import os
import json
from typing import Dict, Any, Set
from datetime import datetime

from config.config import Config
from data_managers.market_state import MarketState

def setup_breakout_logger(config: Config) -> logging.Logger:
    log_path = config.breakout_filter_log_path
    log_dir = os.path.dirname(log_path) if os.path.dirname(log_path) else '.'
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger('BreakoutZoneOriginFilterLogger')
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.FileHandler(log_path, mode='a')
        formatter = logging.Formatter('%(asctime)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger

class BreakoutZoneOriginFilter:
    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_breakout_logger(self.config)
        self.zone_lookback = self.config.breakout_zone_lookback
        self.volatility_ratio = self.config.breakout_zone_volatility_ratio
        self.logger.debug("BreakoutZoneOriginFilter initialized: lookback=%d, volatility_ratio=%.2f",
                         self.zone_lookback, self.volatility_ratio)

    async def generate_report(self, market_state: MarketState) -> Dict[str, Any]:
        report = {
            "filter_name": "BreakoutZoneOriginFilter",
            "score": 0.0,
            "metrics": {},
            "flag": "❌ Block"
        }

        klines = market_state.klines
        live_candle = market_state.live_reconstructed_candle
        mark_price = market_state.mark_price or 0.0

        required_klines = self.zone_lookback + 3
        if len(klines) < required_klines:
            report["metrics"]["reason"] = f"Not enough historical klines ({len(klines)}/{required_klines})."
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

        breakout_range = float(live_candle[2]) - float(live_candle[3])
        # Adjust breakout_range with mark_price
        if mark_price > 0:
            breakout_range = max(breakout_range, abs(mark_price - float(live_candle[2])), abs(mark_price - float(live_candle[3])))

        pre_breakout_klines = list(klines)[:3]
        pre_breakout_ranges = [float(k[2]) - float(k[3]) for k in pre_breakout_klines]
        avg_pre_breakout_range = sum(pre_breakout_ranges) / len(pre_breakout_ranges) if pre_breakout_ranges else 0
        
        if avg_pre_breakout_range <= 0:
            report["metrics"]["reason"] = "Invalid pre-breakout data (zero range)."
            report["score"] = 1.0
            report["flag"] = "✅ Hard Pass"
            self.logger.error(report["metrics"]["reason"])
            return report

        is_breakout_candle = breakout_range > (avg_pre_breakout_range * 2.0)
        if not is_breakout_candle:
            report["metrics"]["reason"] = "Current candle is not a breakout candle."
            report["score"] = 1.0
            report["flag"] = "✅ Hard Pass"
            self.logger.debug(report["metrics"]["reason"])
            return report

        origin_zone_klines = list(klines)[3 : 3 + self.zone_lookback]
        origin_zone_ranges = [float(k[2]) - float(k[3]) for k in origin_zone_klines]
        avg_origin_zone_range = sum(origin_zone_ranges) / len(origin_zone_ranges) if origin_zone_ranges else 0

        is_valid_origin = avg_origin_zone_range < (avg_pre_breakout_range * self.volatility_ratio)

        report["metrics"] = {
            "live_candle_range": round(breakout_range, 4),
            "pre_breakout_avg_range": round(avg_pre_breakout_range, 4),
            "origin_zone_avg_range": round(avg_origin_zone_range, 4),
            "is_breakout": is_breakout_candle,
            "is_valid_origin": is_valid_origin,
            "mark_price": round(mark_price, 4)
        }

        if is_valid_origin:
            score = 1.0 - (avg_origin_zone_range / (avg_pre_breakout_range * self.volatility_ratio))
            report["score"] = round(max(0, score), 4)
            report["flag"] = "✅ Confirmed"
        else:
            score = 1.0 - min((avg_origin_zone_range / avg_pre_breakout_range), 1.0)
            report["score"] = round(max(0, score), 4)
            report["flag"] = "⚠️ Soft Flag"

        self.logger.debug("BreakoutZoneOriginFilter report: score=%.4f, flag=%s, metrics=%s",
                         report["score"], report["flag"], report["metrics"])
        await market_state.update_filter_audit_report("BreakoutZoneOriginFilter", report)
        return report