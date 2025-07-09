import logging
import asyncio
from typing import Dict, Any, List

from config.config import Config
from data_managers.market_state import MarketState
from memory_tracker import PassiveMemoryLogger  # NEW IMPORT

# The complete, agreed-upon set of filters
from filters.cts_filter import CtsFilter
from filters.spoof_filter import SpoofFilter
from filters.compression_detector import CompressionDetector
from filters.breakout_zone_origin_filter import BreakoutZoneOriginFilter
from filters.retest_entry_logic import RetestEntryLogic
from filters.low_volume_guard import LowVolumeGuard
from filters.sentiment_divergence_filter import SentimentDivergenceFilter
from filters.time_of_day_filter import TimeOfDayFilter
from filters.order_book_reversal_zone_detector import OrderBookReversalZoneDetector

logger = logging.getLogger(__name__)

class ValidatorStack:
    def __init__(self, config: Config):
        self.config = config
        self.filters: List[Any] = []

        self.filters.append(CtsFilter(self.config))
        self.filters.append(SpoofFilter(self.config))
        self.filters.append(CompressionDetector(self.config))
        self.filters.append(BreakoutZoneOriginFilter(self.config))
        self.filters.append(RetestEntryLogic(self.config))
        self.filters.append(LowVolumeGuard(self.config))
        self.filters.append(SentimentDivergenceFilter(self.config))
        self.filters.append(OrderBookReversalZoneDetector(self.config))

        if self.config.use_time_of_day_filter:
            self.filters.append(TimeOfDayFilter(self.config))
            logger.info("TimeOfDayFilter has been enabled via config.")

        logger.info(f"ValidatorStack (Report Compiler) initialized with {len(self.filters)} filters.")

    async def generate_report(self, market_state: MarketState) -> Dict[str, Any]:
        logger.info("--- Generating Pre-Analysis Report from Validator Stack ---")

        tasks = [f.generate_report(market_state) for f in self.filters]
        filter_results = await asyncio.gather(*tasks, return_exceptions=True)

        pre_analysis_report = {
            "filters": {}
        }

        for result in filter_results:
            if isinstance(result, Exception):
                logger.error(f"A filter failed during report generation: {result}", exc_info=result)
                continue

            if result and isinstance(result, dict):
                filter_name = result.pop("filter_name", "unknown_filter")
                pre_analysis_report["filters"][filter_name] = result

                # 🔻 NEW: Log result to passive memory
                try:
                    PassiveMemoryLogger.log(filter_name, result)
                except Exception as e:
                    logger.warning(f"PassiveMemoryLogger failed for {filter_name}: {e}")

        logger.info("-- Pre-Analysis Report Generated. --")
        return pre_analysis_report

    async def process_backfill_candle(self, candle: list):
        """
        Feeds a historical candle to each filter so it can build state.
        """
        for f in self.filters:
            if hasattr(f, 'ingest_candle'):
                try:
                    f.ingest_candle(candle, is_backfill=True)
                except Exception as e:
                    logger.warning(f"Filter {f.__class__.__name__} failed on backfill: {e}")