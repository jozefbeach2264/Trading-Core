import logging
import json
from typing import Dict, Any
from config.config import Config
from log_utils import file_logger
from data_managers.market_state import MarketState

def setup_low_volume_logger(config: Config) -> logging.Logger:
    return file_logger("LowVolumeGuardLogger", config.low_volume_guard_log_path)

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

        mark_price = market_state.mark_price or 0.0
        volume_notional = current_volume * mark_price if mark_price > 0 else None

        # Prefer notional (quote currency) threshold when mark price is available
        if volume_notional is not None:
            report["metrics"]["candle_volume_notional"] = round(volume_notional, 4)
            report["metrics"]["min_notional_threshold"] = self.config.low_volume_min_notional
            threshold_met = volume_notional >= self.config.low_volume_min_notional
            threshold_reason = "VOLUME_OK" if threshold_met else "LOW_NOTIONAL_THRESHOLD_NOT_MET"
        else:
            # Fallback to base asset volume threshold
            report["metrics"]["candle_volume"] = current_volume
            report["metrics"]["min_threshold"] = self.min_volume_threshold
            threshold_met = current_volume >= self.min_volume_threshold
            threshold_reason = "VOLUME_OK" if threshold_met else "LOW_VOLUME_THRESHOLD_NOT_MET"

        if not threshold_met:
            report["score"] = 0.0; report["flag"] = "❌ Block"
            report["metrics"]["reason"] = threshold_reason
        else:
            report["metrics"]["reason"] = threshold_reason

        self.logger.debug(f"LowVolumeGuard report generated: {json.dumps(report)}")
        return report
