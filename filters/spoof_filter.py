import logging
import os
import json
from typing import Dict, Any
from config.config import Config
from data_managers.market_state import MarketState

def setup_spoof_logger(config: Config) -> logging.Logger:
    log_path = config.spoof_filter_log_path
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    
    logger = logging.getLogger('SpoofFilterLogger')
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if logger.handlers:
        logger.handlers.clear()

    handler = logging.FileHandler(log_path, mode='a')
    formatter = logging.Formatter('%(asctime)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
        
    return logger

class SpoofFilter:
    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_spoof_logger(self.config)

    async def generate_report(self, market_state: MarketState) -> Dict[str, Any]:
        
        # --- NEW: Ensure the latest OB metrics are calculated before proceeding ---
        await market_state.ensure_order_book_metrics_are_current()

        report = {
            "filter_name": "SpoofFilter",
            "score": 1.0,
            "metrics": {},
            "flag": "✅ Hard Pass"
        }
        
        # Read the pre-calculated (cached) metrics from the market state
        spoof_metrics = market_state.spoof_metrics

        if not spoof_metrics:
            report["flag"] = "⚠️ Soft Flag"
            report["score"] = 0.5
            report["metrics"]["reason"] = "SPOOF_METRICS_UNAVAILABLE"
            self.logger.warning(report["metrics"]["reason"])
            return report

        spoof_thin_rate = spoof_metrics.get("spoof_thin_rate", 0.0)
        wall_delta_pct = spoof_metrics.get("wall_delta_pct", 0.0)
        
        report["metrics"] = {
            "spoof_thin_rate": round(spoof_thin_rate, 2),
            "wall_delta_pct": round(wall_delta_pct, 2)
        }

        if spoof_thin_rate > 10.0:
            report["score"] = 0.0
            report["flag"] = "❌ Block"
            report["metrics"]["reason"] = "SPOOFING_DETECTED"
        else:
            report["metrics"]["reason"] = "NO_SPOOFING_DETECTED"
            
        self.logger.debug(f"SpoofFilter report generated: {json.dumps(report)}")
        return report
