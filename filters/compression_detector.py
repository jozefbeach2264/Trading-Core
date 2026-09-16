import logging
import json
from typing import Dict, Any
from config.config import Config
from filters.candle_age import candle_age_fraction, expected_partial_range, is_too_young
from log_utils import file_logger
from data_managers.market_state import MarketState
import statistics

def setup_compression_logger(config: Config) -> logging.Logger:
    return file_logger("CompressionDetectorLogger", config.compression_detector_log_path)

SCORE_SCALE_MULTIPLIER = 1.2
HARD_PASS_SCORE = 0.75
SOFT_FLAG_SCORE = 0.50
MIN_STATS_WINDOW = 5      # samples needed before percentile diagnostics are reported
ROLLING_WINDOW_MAX = 200


class CompressionDetector:
    @staticmethod
    def _window_stats(prior_ratios: list) -> Dict[str, Any]:
        """Median / p20 / p80 of the ratios seen BEFORE this cycle (diagnostics for tuning)."""
        if len(prior_ratios) < MIN_STATS_WINDOW:
            return {"median_ratio": None, "p20_ratio": None, "p80_ratio": None}
        quantiles = statistics.quantiles(prior_ratios, n=5)
        return {"median_ratio": round(statistics.median(prior_ratios), 4),
                "p20_ratio": round(quantiles[0], 4), "p80_ratio": round(quantiles[-1], 4)}

    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_compression_logger(config)
        self.lookback_period = self.config.compression_lookback_period
        self.range_ratio = self.config.compression_range_ratio
        # Simple rolling buffer for adaptive thresholds
        self._recent_ratios = []
        self._recent_max = ROLLING_WINDOW_MAX  # cap to avoid unbounded growth

    async def generate_report(self, market_state: MarketState) -> Dict[str, Any]:
        report = {"filter_name": "CompressionDetector", "score": 0.0, "metrics": {}, "flag": "❌ Block"}
        klines = list(market_state.klines)
        live_candle = market_state.live_reconstructed_candle
        
        if len(klines) < self.lookback_period:
            report["metrics"]["reason"] = f"INSUFFICIENT_KLINE_DATA ({len(klines)}/{self.lookback_period})."
            self.logger.warning(report["metrics"]["reason"])
            return report

        if not live_candle:
            report["metrics"]["reason"] = "LIVE_CANDLE_UNAVAILABLE"
            self.logger.warning(report["metrics"]["reason"])
            return report

        lookback_klines = klines[:self.lookback_period]
        ranges = [float(k[2]) - float(k[3]) for k in lookback_klines]
        avg_range = sum(ranges) / len(ranges) if ranges else 0
        current_range = float(live_candle[2]) - float(live_candle[3])

        if avg_range <= 0:
            report["metrics"]["reason"] = "INVALID_HISTORICAL_DATA"; report["score"] = 1.0; report["flag"] = "✅ Hard Pass"
            return report

        # Age-aware: a live candle 10 s into its minute is expected to show ≈√(10/60) of a full range.
        age_fraction = candle_age_fraction(live_candle)
        expected_range = expected_partial_range(avg_range, age_fraction)
        if is_too_young(age_fraction) or expected_range <= 0:
            report["score"] = 0.5
            report["flag"] = "⚠️ Soft Flag"
            report["metrics"] = {"reason": "CANDLE_TOO_YOUNG", "candle_age_s": round(age_fraction * 60.0, 1),
                                 "average_range": round(avg_range, 4)}
            return report
        compression_ratio = current_range / expected_range

        # Rolling stats are DIAGNOSTICS ONLY, computed from the PRIOR window (current sample excluded).
        # Review finding 5: deriving thresholds from a window that includes the current sample means the
        # bottom ~20% of samples hard-block by construction; a prior-window percentile still does.
        window_stats = self._window_stats(self._recent_ratios)
        self._recent_ratios.append(compression_ratio)
        if len(self._recent_ratios) > self._recent_max:
            self._recent_ratios.pop(0)

        # Thresholds anchored on the operator's COMPRESSION_RANGE_RATIO (pre-review semantics):
        # score = ratio / (range_ratio * 1.2); Hard Pass ≥ 0.75, Soft Flag ≥ 0.50, else Block.
        score_scale = self.range_ratio * SCORE_SCALE_MULTIPLIER
        hard_threshold = score_scale * HARD_PASS_SCORE
        soft_threshold = score_scale * SOFT_FLAG_SCORE
        score = min(compression_ratio / score_scale, 1.0) if score_scale > 0 else 0.0

        report["score"] = round(score, 4)
        report["metrics"] = {
            "average_range": round(avg_range, 4), "current_range": round(current_range, 4),
            "expected_range": round(expected_range, 4), "candle_age_s": round(age_fraction * 60.0, 1),
            "compression_ratio": round(compression_ratio, 2), "config_threshold_ratio": self.range_ratio,
            "soft_threshold": round(soft_threshold, 4),
            "hard_threshold": round(hard_threshold, 4),
            **window_stats,
        }

        if compression_ratio >= hard_threshold:
            report["flag"] = "✅ Hard Pass"; report["metrics"]["reason"] = "PRICE_ACTION_NORMAL"
        elif compression_ratio >= soft_threshold:
            report["flag"] = "⚠️ Soft Flag"; report["metrics"]["reason"] = "MILD_PRICE_COMPRESSION"
        else:
            report["flag"] = "❌ Block"; report["metrics"]["reason"] = "HEAVY_PRICE_COMPRESSION"

        self.logger.debug(f"CompressionDetector report generated: {json.dumps(report)}")
        return report
