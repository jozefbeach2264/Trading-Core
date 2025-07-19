import logging
import asyncio
from typing import Dict, Any
from config.config import Config
from data_managers.market_state import MarketState
from memory_tracker import MemoryTracker
from filters.low_volume_guard import LowVolumeGuard
from filters.time_of_day_filter import TimeOfDayFilter
from filters.spoof_filter import SpoofFilter
from filters.cts_filter import CtsFilter
from filters.compression_detector import CompressionDetector
from filters.breakout_zone_origin_filter import BreakoutZoneOriginFilter
from filters.retest_entry_logic import RetestEntryLogic
from filters.sentiment_divergence_filter import SentimentDivergenceFilter
from filters.order_book_reversal_zone_detector import OrderBookReversalZoneDetector

# This logger will be used for the console summary
logger = logging.getLogger(__name__)

class ValidatorStack:
    def __init__(self, config: Config):
        self.config = config
        self.filters = [
            LowVolumeGuard(config),
            TimeOfDayFilter(config),
            SpoofFilter(config),
            CtsFilter(config),
            CompressionDetector(config),
            BreakoutZoneOriginFilter(config),
            RetestEntryLogic(config),
            SentimentDivergenceFilter(config),
            OrderBookReversalZoneDetector(config)
        ]
        self.memory_tracker = MemoryTracker(config)
        logger.debug(f"ValidatorStack initialized with {len(self.filters)} filters.")

    async def generate_report(self, market_state: MarketState) -> Dict[str, Any]:
        tasks = [f.generate_report(market_state) for f in self.filters]
        filter_results = await asyncio.gather(*tasks, return_exceptions=True)

        aggregated_report = {
            "stack_result": "✅ All Clear",
            "hard_blocks": 0,
            "soft_flags": 0,
            "filters": {}
        }
        
        # --- New Console Summary Logging ---
        logger.info("--- Validator Stack Report ---")

        for result in filter_results:
            if isinstance(result, Exception):
                logger.error("A filter failed with an exception", extra={"error": str(result)}, exc_info=True)
                continue

            filter_name = result.get("filter_name", "UnknownFilter")
            flag = result.get("flag", "N/A")
            score = result.get("score", 0.0)

            # Log the high-level summary to the console
            logger.info(f"{filter_name:<35} | Flag: {flag:<18} | Score: {score:.4f}")

            # Continue with aggregation and memory tracking
            aggregated_report["filters"][filter_name] = result
            await market_state.update_filter_audit_report(filter_name, result)
            await self.memory_tracker.update_memory(filter_report=result)
            
            if "❌ Block" in flag:
                aggregated_report["hard_blocks"] += 1
            elif "⚠️ Soft Flag" in flag or "fallback_strategy" in flag:
                aggregated_report["soft_flags"] += 1

        if aggregated_report["hard_blocks"] > 0:
            aggregated_report["stack_result"] = "❌ Hard Block"
        elif aggregated_report["soft_flags"] > 0:
            aggregated_report["stack_result"] = "⚠️ Soft Flag"
        
        logger.info(f"--- Stack Result: {aggregated_report['stack_result']} ---")
        
        return aggregated_report
