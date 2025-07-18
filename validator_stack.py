import logging
import asyncio
from typing import Dict, Any, List

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
        while not (market_state.depth_20.get("bids") and market_state.depth_20.get("asks") and market_state.mark_price):
            logger.debug("Waiting for MarketState data: depth_20=%s, mark_price=%s", market_state.depth_20, market_state.mark_price)
            await asyncio.sleep(0.05)

        logger.debug("MarketState ready: depth_20=%s, walls=%s, pressure=%s, mark_price=%s",
                     market_state.depth_20, market_state.order_book_walls, market_state.order_book_pressure, market_state.mark_price)

        tasks = [f.generate_report(market_state) for f in self.filters]
        filter_results = await asyncio.gather(*tasks, return_exceptions=True)

        aggregated_report = {
            "stack_result": "✅ All Clear",
            "hard_blocks": 0,
            "soft_flags": 0,
            "filters": {}
        }

        for result in filter_results:
            if isinstance(result, Exception):
                logger.error(f"Filter failed: %s", result, exc_info=True)
                continue
            
            filter_name = result.get("filter_name", "UnknownFilter")
            if filter_name == "OrderBookReversalZoneDetector":
                result["metrics"]["mark_price"] = market_state.mark_price or 0.0
            aggregated_report["filters"][filter_name] = result
            await market_state.update_filter_audit_report(filter_name, result)
            await self.memory_tracker.update_memory(filter_report=result)

            flag = result.get("flag", "")
            if "❌ Block" in flag:
                aggregated_report["hard_blocks"] += 1
            elif "⚠️ Soft Flag" in flag or "fallback_strategy" in flag:
                aggregated_report["soft_flags"] += 1
        
        if aggregated_report["hard_blocks"] > 0:
            aggregated_report["stack_result"] = "❌ Hard Block"
            logger.debug(f"ValidatorStack failed: {aggregated_report['hard_blocks']} hard block(s).")
        elif aggregated_report["soft_flags"] > 0:
            aggregated_report["stack_result"] = "⚠️ Soft Flag"
            logger.info(f"ValidatorStack passed with {aggregated_report['soft_flags']} soft flag(s).")
        else:
            logger.debug("ValidatorStack passed with all filters clear.")
            
        return aggregated_report