import logging
import os
import json
from typing import Dict, Any, Set
from datetime import datetime

from config.config import Config
from data_managers.market_state import MarketState

# The logger setup is a complete implementation based on your Pre-Genesis file.
def setup_compression_logger(config: Config) -> logging.Logger:
    log_path = config.compression_detector_log_path
    log_dir = os.path.dirname(log_path) if os.path.dirname(log_path) else '.'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logger = logging.getLogger('CompressionDetectorLogger')
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.FileHandler(log_path, mode='w')
        formatter = logging.Formatter('%(asctime)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger

class CompressionDetector:
    """
    Evaluates candles for minimal range/movement to identify zones where
    breakout energy may be depleted (market grind).
    """
    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_compression_logger(config)
        self.lookback_period = self.config.compression_lookback_period
        self.range_ratio = self.config.compression_range_ratio

    async def generate_report(self, market_state: MarketState) -> Dict[str, Any]:
        """
        Analyzes candle range to detect compression and generates a weighted
        report with a score, metrics, and flag.
        """
        report = {
            "filter_name": "CompressionDetector",
            "score": 0.0,
            "metrics": {},
            "flag": "❌ Block"
        }

        klines = market_state.klines
        live_candle = market_state.live_reconstructed_candle

        if len(klines) < self.lookback_period:
            report["metrics"]["reason"] = f"Not enough historical klines ({len(klines)}/{self.lookback_period})."
            return report

        if not live_candle:
            report["metrics"]["reason"] = "Live candle data not available."
            return report

        # --- Compression Analysis Logic ---
        lookback_klines = list(klines)[-self.lookback_period:]
        ranges = [float(k[2]) - float(k[3]) for k in lookback_klines]
        avg_range = sum(ranges) / len(ranges) if ranges else 0

        current_range = float(live_candle[2]) - float(live_candle[3])

        if avg_range <= 0:
            report["metrics"]["reason"] = "Invalid historical data (zero or negative average range)."
            report["score"] = 1.0 # Pass if history is invalid, cannot determine compression
            report["flag"] = "✅ Hard Pass"
            return report

        # --- Scoring Logic ---
        # The score is a measure of how NOT compressed the candle is.
        # A high score means high volatility / not compressed.
        # A low score means low volatility / compressed.
        compression_ratio = current_range / avg_range
        
        # We normalize the score. If ratio is at the threshold (e.g., 0.8), score is 0.5.
        # If ratio is 0, score is 0. If ratio is > 1.2 * threshold, score is 1.0.
        score = min(compression_ratio / (self.range_ratio * 1.2), 1.0)

        report["score"] = round(score, 4)
        report["metrics"] = {
            "average_range": round(avg_range, 4),
            "current_range": round(current_range, 4),
            "compression_ratio": round(compression_ratio, 2),
            "config_threshold_ratio": self.range_ratio
        }
        
        # --- Flagging Logic ---
        if score >= 0.75:
            report["flag"] = "✅ Hard Pass" # Clean, non-compressed state
        elif score >= 0.50:
            report["flag"] = "⚠️ Soft Flag" # Some compression, warrants review
        else:
            report["flag"] = "❌ Block" # Heavy compression/grind detected

        return report
