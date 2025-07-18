import logging
import os
from typing import Dict, Any, Set, Tuple
from datetime import datetime

from config.config import Config
from data_managers.market_state import MarketState

def setup_retest_logger(config: Config) -> logging.Logger:
    log_path = config.retest_logic_log_path
    log_dir = os.path.dirname(log_path) if os.path.dirname(log_path) else '.'
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger('RetestEntryLogicLogger')
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.FileHandler(log_path, mode='a')
        formatter = logging.Formatter('%(asctime)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
    return logger

class RetestEntryLogic:
    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_retest_logger(self.config)
        self.lookback = self.config.retest_lookback
        self.proximity_percent = self.config.retest_proximity_percent
        self.logger.debug("RetestEntryLogic initialized: lookback=%d, proximity_percent=%.2f",
                         self.lookback, self.proximity_percent)

    async def generate_report(self, market_state: MarketState) -> Dict[str, Any]:
        report = {
            "filter_name": "RetestEntryLogic",
            "score": 1.0,
            "metrics": {"reason": "NO_RETEST_SCENARIO"},
            "flag": "✅ Hard Pass"
        }

        klines = market_state.klines
        live_candle = market_state.live_reconstructed_candle
        mark_price = market_state.mark_price or 0.0

        if len(klines) < self.lookback:
            report["metrics"]["reason"] = f"INSUFFICIENT_KLINE_DATA ({len(klines)}/{self.lookback})."
            report["flag"] = "⚠️ Soft Flag"
            report["score"] = 0.5
            self.logger.error(report["metrics"]["reason"])
            return report
            
        if not live_candle:
            report["metrics"]["reason"] = "LIVE_CANDLE_UNAVAILABLE"
            report["flag"] = "❌ Block"
            report["score"] = 0.0
            self.logger.error(report["metrics"]["reason"])
            return report

        if mark_price <= 0:
            report["metrics"]["reason"] = "INVALID_MARK_PRICE"
            report["flag"] = "❌ Block"
            report["score"] = 0.0
            self.logger.error(report["metrics"]["reason"])
            return report

        lookback_klines = list(klines)[-self.lookback:]
        highest_high = max(float(k[2]) for k in lookback_klines)
        lowest_low = min(float(k[3]) for k in lookback_klines)

        live_open, live_high, live_low, live_close = map(float, live_candle[1:5])
        live_high = max(live_high, mark_price)
        live_low = min(live_low, mark_price)

        proximity_to_high = highest_high * (self.proximity_percent / 100)
        proximity_to_low = lowest_low * (self.proximity_percent / 100)

        is_near_high = abs(live_high - highest_high) <= proximity_to_high
        is_near_low = abs(live_low - lowest_low) <= proximity_to_low
        
        retest_pct = 0.0
        
        if is_near_high:
            rejection_confirmed = live_close < live_high
            report["metrics"] = {
                "retest_type": "resistance",
                "historical_level": highest_high,
                "live_high": live_high,
                "rejection_confirmed": rejection_confirmed,
                "mark_price": round(mark_price, 4)
            }
            if rejection_confirmed:
                retest_pct = (live_high - live_close) / (live_high - live_low) if (live_high - live_low) > 0 else 0
                report["score"] = round(retest_pct, 4)
                report["metrics"]["retest_strength_pct"] = round(retest_pct * 100, 2)
                if retest_pct > 0.5:
                    report["flag"] = "✅ Validated"
                    report["metrics"]["reason"] = "VALIDATED_RESISTANCE_REJECTION"
                else:
                    report["flag"] = "⚠️ Soft Flag"
                    report["metrics"]["reason"] = "WEAK_RESISTANCE_REJECTION"
            else:
                report["score"] = 0.0
                report["flag"] = "fallback_strategy: Scalpel"
                report["metrics"]["reason"] = "RESISTANCE_BROKEN"
        
        elif is_near_low:
            bounce_confirmed = live_close > live_low
            report["metrics"] = {
                "retest_type": "support",
                "historical_level": lowest_low,
                "live_low": live_low,
                "bounce_confirmed": bounce_confirmed,
                "mark_price": round(mark_price, 4)
            }
            if bounce_confirmed:
                retest_pct = (live_close - live_low) / (live_high - live_low) if (live_high - live_low) > 0 else 0
                report["score"] = round(retest_pct, 4)
                report["metrics"]["retest_strength_pct"] = round(retest_pct * 100, 2)
                if retest_pct > 0.5:
                    report["flag"] = "✅ Validated"
                    report["metrics"]["reason"] = "VALIDATED_SUPPORT_BOUNCE"
                else:
                    report["flag"] = "⚠️ Soft Flag"
                    report["metrics"]["reason"] = "WEAK_SUPPORT_BOUNCE"
            else:
                report["score"] = 0.0
                report["flag"] = "fallback_strategy: Scalpel"
                report["metrics"]["reason"] = "SUPPORT_BROKEN"
        
        self.logger.debug("RetestEntryLogic report: score=%.4f, flag=%s, metrics=%s",
                         report["score"], report["flag"], report["metrics"])
        await market_state.update_filter_audit_report("RetestEntryLogic", report)
        return report

