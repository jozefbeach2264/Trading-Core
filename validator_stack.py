import logging
import asyncio
from typing import Dict, Any, List

# --- Correctly import the final, agreed-upon set of filters ---
from config.config import Config
from filters.spoof_filter import SpoofFilter
from filters.compression_detector import CompressionDetector
from filters.breakout_zone_origin_filter import BreakoutZoneOriginFilter
from filters.retest_entry_logic import RetestEntryLogic
from filters.low_volume_guard import LowVolumeGuard
from filters.sentiment_divergence_filter import SentimentDivergenceFilter
from filters.time_of_day_filter import TimeOfDayFilter
from filters.OrderBookReversalZoneDetector import OrderBookReversalZoneDetector

logger = logging.getLogger(__name__)

class ValidatorStack:
    def __init__(self, config: Config):
        """
        Initializes the ValidatorStack and loads all filter modules.
        Its role is to compile a data-rich report for the AI.
        """
        self.config = config
        self.filters = []

        # --- Instantiate all filter classes ---
        # The list of filters is based on our final project cleanup.
        # As per your documents, the config is passed to filters that need it.
        self.filters.append(SpoofFilter())
        self.filters.append(CompressionDetector())
        self.filters.append(BreakoutZoneOriginFilter())
        self.filters.append(RetestEntryLogic())
        self.filters.append(LowVolumeGuard())
        self.filters.append(SentimentDivergenceFilter())
        self.filters.append(OrderBookReversalZoneDetector(self.config)) # This filter needs config
        
        # As per your boolean toggle requirement, this filter is loaded conditionally.
        if self.config.use_time_of_day_filter:
            self.filters.append(TimeOfDayFilter())
            logger.info("TimeOfDayFilter has been enabled via config.")
        
        logger.info("ValidatorStack (Report Compiler) initialized with %d filters.", len(self.filters))

    async def generate_report(self, market_state: Any) -> Dict[str, Any]:
        """
        Runs all enabled filters concurrently to generate their data reports.
        This method replaces the old 'run_all' and compiles data instead of
        returning a simple True/False.
        """
        logger.info("--- Generating Pre-Analysis Report from Validator Stack ---")
        
        # Run all filters concurrently to be efficient
        tasks = [f.generate_report(market_state) for f in self.filters]
        filter_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Compile the results into a single report dictionary
        pre_analysis_report = {
            "filters": {}
        }

        for result in filter_results:
            if isinstance(result, Exception):
                logger.error(f"A filter failed during report generation: {result}", exc_info=result)
                continue
            
            # Use pop to get the name and leave the rest of the data
            filter_name = result.pop("filter_name", "unknown_filter")
            pre_analysis_report["filters"][filter_name] = result
        
        logger.info("--- Pre-Analysis Report Generated. ---")
        return pre_analysis_report
