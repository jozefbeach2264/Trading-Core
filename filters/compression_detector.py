import logging
import os
import json
from typing import Dict, Any
from config.config import Config
from data_managers.market_state import MarketState

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
        score = min(compression_ratio / (self.range_ratio * 1.2), 1.0)
        
        report["score"] = round(score, 4)
        report["metrics"] = {
            "average_range": round(avg_range, 4), "current_range": round(current_range, 4),
            "compression_ratio": round(compression_ratio, 2), "config_threshold_ratio": self.range_ratio
        }

        if score >= 0.75:
            report["flag"] = "✅ Hard Pass"; report["metrics"]["reason"] = "PRICE_ACTION_NORMAL"
        elif score >= 0.50:
            report["flag"] = "⚠️ Soft Flag"; report["metrics"]["reason"] = "MILD_PRICE_COMPRESSION"
        else:
            report["flag"] = "❌ Block"; report["metrics"]["reason"] = "HEAVY_PRICE_COMPRESSION"
        
        self.logger.debug(f"CompressionDetector report generated: {json.dumps(report)}")
        return report
