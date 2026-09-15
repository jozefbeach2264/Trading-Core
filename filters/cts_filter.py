import logging
import json
import time
from typing import Dict, Any
from config.config import Config
from log_utils import file_logger
from data_managers.market_state import MarketState

def setup_cts_logger(config: Config) -> logging.Logger:
    return file_logger("CtsFilterLogger", config.cts_filter_log_path)

WICK_BASE_SCORE = 0.6          # compressed candle with a confirmed wick rejection
WICK_STRENGTH_WEIGHT = 0.2     # per unit of wick strength above the rejection threshold
HARD_PASS_SCORE = 0.75
SOFT_FLAG_SCORE = 0.50
LOW_SCORE_STREAK_LIMIT = 5     # consecutive blocks before a short cooldown
COOLDOWN_SECONDS = 3.0


class CtsFilter:
    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_cts_logger(self.config)
        self.lookback_period = self.config.cts_lookback_period
        self.narrow_range_ratio = self.config.cts_narrow_range_ratio
        self.rejection_multiplier = self.config.cts_wick_rejection_multiplier
        self._low_score_streak = 0
        self._cooldown_until = 0.0
        self.logger.debug(
            "CtsFilter initialized: lookback=%d, narrow_range_ratio=%.2f, rejection_multiplier=%.2f",
            self.lookback_period, self.narrow_range_ratio, self.rejection_multiplier
        )

    async def generate_report(self, market_state: MarketState) -> Dict[str, Any]:
        report = {"filter_name": "CtsFilter", "score": 0.0, "metrics": {}, "flag": "❌ Block"}
        now = time.time()

        # Cooldown: if we have repeatedly low scores, pause re-evaluation briefly to reduce churn
        if now < self._cooldown_until:
            report["metrics"]["reason"] = "CTS_COOLDOWN_ACTIVE"
            report["score"] = 0.0
            report["flag"] = "❌ Block"
            await market_state.update_filter_audit_report("CtsFilter", report)
            return report
        # Reset cooldown sentinel if expired
        if self._cooldown_until and now >= self._cooldown_until:
            self._low_score_streak = 0
            self._cooldown_until = 0.0
        klines = list(market_state.klines)
        live_candle = market_state.live_reconstructed_candle
        mark_price = market_state.mark_price or 0.0
        
        self.logger.debug(
            f"Checking MarketState: klines_length={len(klines)}, live_candle={'Yes' if live_candle else 'No'}, mark_price={mark_price}"
        )
        
        if len(klines) < self.lookback_period:
            report["metrics"]["reason"] = f"INSUFFICIENT_KLINE_DATA ({len(klines)}/{self.lookback_period})."
            self.logger.warning(report["metrics"]["reason"])
            return report

        if not live_candle:
            report["metrics"]["reason"] = "LIVE_CANDLE_UNAVAILABLE"
            self.logger.warning(report["metrics"]["reason"])
            return report

        if mark_price <= 0:
            report["metrics"]["reason"] = "INVALID_MARK_PRICE"
            self.logger.warning(report["metrics"]["reason"])
            return report

        lookback_klines = klines[:self.lookback_period]
        ranges = [float(k[2]) - float(k[3]) for k in lookback_klines]
        average_range = sum(ranges) / len(ranges) if ranges else 0
        
        o, h, l, c = map(float, [live_candle[1], live_candle[2], live_candle[3], live_candle[4]])
        current_range = h - l
        
        if mark_price > 0:
            current_range = max(current_range, abs(mark_price - max(o, c)), abs(mark_price - min(o, c)))
            
        current_body = abs(c - o)
        
        if average_range <= 0 or current_range <= 0:
            report["metrics"]["reason"] = "INVALID_CANDLE_DATA"
            self.logger.warning(report["metrics"]["reason"])
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
            "average_range": round(average_range, 4), "current_range": round(current_range, 4),
            "grind_ratio": round(grind_ratio, 2), "is_compressed": is_compressed,
            "wick_signal": wick_signal, "wick_strength_ratio": round(wick_strength, 2),
            "mark_price": round(mark_price, 4)
        }

        # Scoring (restored 2026-09-15, review findings 4/7/8):
        #   not compressed                     → 1.0  (normal expansion)
        #   compressed + wick rejection        → 0.6 + wick strength bonus, capped at 1.0 (the trap pattern)
        #   compressed + no rejection evidence → 0.0  (dead chop: HARD BLOCK — this is the gate's whole job)
        # The reviewed diff floored the last case at 0.55, which made "❌ Block" unreachable.
        if not is_compressed:
            score = 1.0
            report["metrics"]["reason"] = "EXPANSION_NORMAL"
        elif wick_signal != "none":
            score = min(WICK_BASE_SCORE + (wick_strength - 1.0) * WICK_STRENGTH_WEIGHT, 1.0)
            report["metrics"]["reason"] = "COMPRESSION_WITH_WICK_REJECTION"
        else:
            score = 0.0
            report["metrics"]["reason"] = "COMPRESSION_NO_EXPANSION"

        report["score"] = round(score, 4)

        if score >= HARD_PASS_SCORE:
            report["flag"] = "✅ Hard Pass"
            self._low_score_streak = 0
        elif score >= SOFT_FLAG_SCORE:
            report["flag"] = "⚠️ Soft Flag"; report["metrics"]["reason"] = "WEAK_TRAP_SIGNAL"
            self._low_score_streak = 0
        else:
            report["flag"] = "❌ Block"; report["metrics"]["reason"] = "NO_TRAP_SIGNAL"
            self._low_score_streak += 1

        # Repeated blocks → short cooldown to avoid log/decision churn (now reachable again).
        if self._low_score_streak >= LOW_SCORE_STREAK_LIMIT and self._cooldown_until == 0.0:
            self._cooldown_until = now + COOLDOWN_SECONDS
            report["metrics"]["reason"] = "CTS_COOLDOWN_TRIGGERED"
            report["flag"] = "❌ Block"
            
        self.logger.debug(f"CtsFilter report generated: {json.dumps(report)}")
        await market_state.update_filter_audit_report("CtsFilter", report)
        return report
