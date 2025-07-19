import logging
import os
import json
from typing import Dict, Any
from config.config import Config
from data_managers.market_state import MarketState

def setup_low_volume_logger(config: Config) -> logging.Logger:
    log_path = config.low_volume_guard_log_path
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    
    logger = logging.getLogger('LowVolumeGuardLogger')
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.FileHandler(log_path, mode='a')
        formatter = logging.Formatter('%(asctime)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
    return logger

class LowVolumeGuard:
    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_low_volume_logger(self.config)
        self.min_volume_threshold = self.config.low_volume_min_threshold

    async def generate_report(self, market_state: MarketState) -> Dict[str, Any]:
        live_candle = market_state.live_reconstructed_candle
        
        report = {
            "filter_name": "LowVolumeGuard", "score": 1.0,
            "metrics": {}, "flag": "✅ Hard Pass"
        }

        if not live_candle:
            report["score"] = 0.0; report["flag"] = "❌ Block"
            report["metrics"]["reason"] = "LIVE_CANDLE_UNAVAILABLE"
            self.logger.warning(report["metrics"]["reason"])
            return report

        try:
            current_volume = float(live_candle[5])
        except (IndexError, TypeError):
            report["score"] = 0.0; report["flag"] = "❌ Block"
            report["metrics"]["reason"] = "MALFORMED_CANDLE_DATA"
            self.logger.error(report["metrics"]["reason"])
            return report
            
        report["metrics"]["candle_volume"] = current_volume
        report["metrics"]["min_threshold"] = self.min_volume_threshold

        if current_volume < self.min_volume_threshold:
            report["score"] = 0.0; report["flag"] = "❌ Block"
            report["metrics"]["reason"] = "LOW_VOLUME_THRESHOLD_NOT_MET"
        else:
            report["metrics"]["reason"] = "VOLUME_OK"

        self.logger.debug(f"LowVolumeGuard report generated: {json.dumps(report)}")
        return report
