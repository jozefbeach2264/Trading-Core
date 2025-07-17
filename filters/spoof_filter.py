import logging
from typing import Dict, Any

from config.config import Config
from data_managers.market_state import MarketState

logger = logging.getLogger(__name__)

class SpoofFilter:
    def __init__(self, config: Config):
        self.config = config

    async def generate_report(self, market_state: MarketState) -> Dict[str, Any]:
        report = {
            "filter_name": "SpoofFilter",
            "score": 1.0,
            "metrics": {},
            "flag": "✅ Hard Pass"
        }

        spoof_metrics = market_state.spoof_metrics
        if not spoof_metrics:
            report["flag"] = "⚠️ Soft Flag"
            report["score"] = 0.5
            report["metrics"]["reason"] = "Spoof metrics not yet available."
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
            report["metrics"]["reason"] = f"Spoofing detected: wall thinning rate {spoof_thin_rate:.2f}% > 10%"

        return report
