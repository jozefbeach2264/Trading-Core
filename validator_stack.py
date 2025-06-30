import logging
import asyncio
from typing import Dict, Any, List

# Import all filter classes
from .filters.spoof_filter import SpoofFilter
from .filters.cts_filter import CtsFilter
from .filters.compression_detector import CompressionDetector
from .filters.breakout_zone_origin_filter import BreakoutZoneOriginFilter
from .filters.retest_entry_logic import RetestEntryLogic
from .filters.low_volume_guard import LowVolumeGuard
from .filters.sentiment_divergence_filter import SentimentDivergenceFilter
from .filters.time_of_day_filter import TimeOfDayFilter

logger = logging.getLogger(__name__)

class ValidatorStack:
    """
    Reworked to act as a "report compiler" for the AI-Assisted Hybrid Model.
    It runs a signal through all filters and compiles their JSON outputs into
    a single Pre-Analysis Report.
    """
    def __init__(self):
        # Instantiate all filter classes
        self.filters = [
            SpoofFilter(),
            # CtsFilter(), # Consolidating into CompressionDetector
            CompressionDetector(),
            BreakoutZoneOriginFilter(),
            RetestEntryLogic(),
            LowVolumeGuard(),
            SentimentDivergenceFilter(),
            TimeOfDayFilter(),
        ]
        logger.info("ValidatorStack (Report Compiler) initialized with %d filters.", len(self.filters))

    async def generate_report(self, signal_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Runs the signal through every filter and compiles their results into a single report.

        Args:
            signal_data (Dict[str, Any]): The initial market state data.

        Returns:
            Dict[str, Any]: The consolidated Pre-Analysis Report.
        """
        logger.info("--- Generating Pre-Analysis Report from Validator Stack ---")
        
        # Run all filters concurrently
        tasks = [f.validate(signal_data) for f in self.filters]
        filter_results = await asyncio.gather(*tasks)

        # Compile the report
        pre_analysis_report = {
            "initial_signal": signal_data.get("trigger_type", "unknown"),
            "timestamp": signal_data.get("timestamp", 0),
            "filters": {}
        }

        for result in filter_results:
            filter_name = result.pop("filter_name", "unknown_filter")
            pre_analysis_report["filters"][filter_name] = result

        logger.info("--- Pre-Analysis Report Generated. ---")
        return pre_analysis_report
