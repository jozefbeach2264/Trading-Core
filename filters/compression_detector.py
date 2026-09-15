import logging
import os
import json
from typing import Dict, Any
from config.config import Config
from data_managers.market_state import MarketState
import statistics

def setup_compression_logger(config: Config) -> logging.Logger:
    log_path = config.compression_detector_log_path
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    
    logger = logging.getLogger('CompressionDetectorLogger')
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.FileHandler(log_path, mode='a')
        formatter = logging.Formatter('%(asctime)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
    return logger

class CompressionDetector:
    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_compression_logger(config)
        self.lookback_period = self.config.compression_lookback_period
        self.range_ratio = self.config.compression_range_ratio
        # Simple rolling buffer for adaptive thresholds
        self._recent_ratios = []
        self._recent_max = 200  # cap to avoid unbounded growth

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

        compression_ratio = current_range / avg_range
        # Update rolling stats (bounded)
        self._recent_ratios.append(compression_ratio)
        if len(self._recent_ratios) > self._recent_max:
            self._recent_ratios.pop(0)

        # Adaptive thresholds from rolling window
        median_ratio = statistics.median(self._recent_ratios) if self._recent_ratios else compression_ratio
        p20_ratio = statistics.quantiles(self._recent_ratios, n=5)[0] if len(self._recent_ratios) >= 5 else compression_ratio * 0.5
        p80_ratio = statistics.quantiles(self._recent_ratios, n=5)[-1] if len(self._recent_ratios) >= 5 else compression_ratio * 1.2

        # Hysteresis: require higher ratio to move from block to pass
        soft_threshold = max(self.range_ratio * 0.5, p20_ratio)
        hard_threshold = max(self.range_ratio, max(median_ratio, p80_ratio * 0.8))

        # Score normalized to hard threshold
        score = min(compression_ratio / hard_threshold, 1.0) if hard_threshold > 0 else 0.0
        
        report["score"] = round(score, 4)
        report["metrics"] = {
            "average_range": round(avg_range, 4), "current_range": round(current_range, 4),
            "compression_ratio": round(compression_ratio, 2), "config_threshold_ratio": self.range_ratio,
            "median_ratio": round(median_ratio, 4),
            "p20_ratio": round(p20_ratio, 4),
            "p80_ratio": round(p80_ratio, 4),
            "soft_threshold": round(soft_threshold, 4),
            "hard_threshold": round(hard_threshold, 4)
        }

        if compression_ratio >= hard_threshold:
            report["flag"] = "✅ Hard Pass"; report["metrics"]["reason"] = "PRICE_ACTION_NORMAL"
        elif compression_ratio >= soft_threshold:
            report["flag"] = "⚠️ Soft Flag"; report["metrics"]["reason"] = "MILD_PRICE_COMPRESSION"
        else:
            report["flag"] = "❌ Block"; report["metrics"]["reason"] = "HEAVY_PRICE_COMPRESSION"

        self.logger.debug(f"CompressionDetector report generated: {json.dumps(report)}")
        return report
