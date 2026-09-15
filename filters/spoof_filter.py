import logging
import os
import json
from typing import Dict, Any
from config.config import Config
from data_managers.market_state import MarketState
import collections

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
        self._recent_rates = collections.deque(maxlen=100)
        self._recent_blocks = collections.deque(maxlen=5)

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

        self._recent_rates.append(spoof_thin_rate)
        median_rate = 0.0
        if self._recent_rates:
            sorted_rates = sorted(self._recent_rates)
            mid = len(sorted_rates)//2
            median_rate = (sorted_rates[mid] if len(sorted_rates)%2==1 else (sorted_rates[mid-1]+sorted_rates[mid])/2)
        
        report["metrics"] = {
            "spoof_thin_rate": round(spoof_thin_rate, 2),
            "wall_delta_pct": round(wall_delta_pct, 2),
            "median_spoof_rate": round(median_rate, 2)
        }

        # Dynamic thresholds with hysteresis
        dynamic_block = max(10.0, median_rate * 2.0)
        dynamic_soft = max(5.0, median_rate * 1.2)

        # Smooth out bursty single-sample spikes: require sustained spike (track last few blocks)
        block = spoof_thin_rate > dynamic_block
        if block:
            self._recent_blocks.append(True)
        else:
            self._recent_blocks.append(False)
        sustained_block = sum(self._recent_blocks) >= 2  # at least 2 recent spikes

        if sustained_block:
            report["score"] = 0.0
            report["flag"] = "❌ Block"
            report["metrics"]["reason"] = "SPOOFING_DETECTED"
            report["metrics"]["dynamic_block_threshold"] = round(dynamic_block, 2)
        elif spoof_thin_rate > dynamic_soft:
            report["score"] = 0.5
            report["flag"] = "⚠️ Soft Flag"
            report["metrics"]["reason"] = "SPOOFING_SUSPECT"
            report["metrics"]["dynamic_block_threshold"] = round(dynamic_block, 2)
            report["metrics"]["dynamic_soft_threshold"] = round(dynamic_soft, 2)
        else:
            report["metrics"]["reason"] = "NO_SPOOFING_DETECTED"
            report["metrics"]["dynamic_block_threshold"] = round(dynamic_block, 2)
            report["metrics"]["dynamic_soft_threshold"] = round(dynamic_soft, 2)
            
        self.logger.debug(f"SpoofFilter report generated: {json.dumps(report)}")
        return report
