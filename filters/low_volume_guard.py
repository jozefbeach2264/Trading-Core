import logging
import os
import json
from typing import Dict, Any, Set
from datetime import datetime

from config.config import Config
from data_managers.market_state import MarketState

def setup_low_volume_logger(config: Config) -> logging.Logger:
    log_path = config.low_volume_guard_log_path
    log_dir = os.path.dirname(log_path) if os.path.dirname(log_path) else '.'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logger = logging.getLogger('LowVolumeGuardLogger')
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.FileHandler(log_path, mode='w')
        formatter = logging.Formatter('%(asctime)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
    return logger

class LowVolumeGuard:
    """
    Acts as a binary hard gate, instantly blocking signals if the live candle
    volume is below the mandatory minimum threshold.
    """
    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_low_volume_logger(self.config)
        self.min_volume_threshold = self.config.low_volume_min_threshold

    async def generate_report(self, market_state: MarketState) -> Dict[str, Any]:
        """
        Checks the live candle's volume against a hardcoded minimum and returns
        a binary pass/block report.
        """
        live_candle = market_state.live_reconstructed_candle
        
        report = {
            "filter_name": "LowVolumeGuard",
            "score": 1.0,
            "metrics": {},
            "flag": "✅ Hard Pass"
        }

        if not live_candle:
            report["score"] = 0.0
            report["flag"] = "❌ Block"
            report["metrics"]["reason"] = "Live candle data not available for volume check."
            return report

        # OKX kline volume is at index 5
        try:
            current_volume = float(live_candle[5])
        except (IndexError, TypeError):
            report["score"] = 0.0
            report["flag"] = "❌ Block"
            report["metrics"]["reason"] = "Malformed live candle data."
            return report

        report["metrics"]["candle_volume"] = current_volume
        report["metrics"]["min_threshold"] = self.min_volume_threshold
        
        # --- GENESIS Hard Gate Logic ---
        if current_volume < self.min_volume_threshold:
            report["score"] = 0.0
            report["flag"] = "❌ Block"
            report["metrics"]["reason"] = f"Volume {current_volume:.2f} < hard threshold {self.min_volume_threshold}"
        
        return report
