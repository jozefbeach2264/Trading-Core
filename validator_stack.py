import logging
import asyncio
from typing import Dict, Any, List
from config.config import Config
from data_managers.market_state import MarketState
from memory_tracker import MemoryTracker

# Import all filter classes
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
        self.memory_tracker = MemoryTracker(config)
        
        # Filters are grouped according to the new protocol
        self.primary_gate_filters = [
            CtsFilter(config),
            TimeOfDayFilter(config)
        ]
        
        self.post_signal_filters = [
            RetestEntryLogic(config),
            OrderBookReversalZoneDetector(config),
            SpoofFilter(config),
            LowVolumeGuard(config),
            CompressionDetector(config),
            BreakoutZoneOriginFilter(config),
            SentimentDivergenceFilter(config)
        ]
        logger.debug(f"ValidatorStack initialized with {len(self.primary_gate_filters)} primary gates and {len(self.post_signal_filters)} post-signal validators.")

    async def _run_filter_group(self, market_state: MarketState, filters: List[Any], group_name: str) -> Dict[str, Any]:
        """Generic function to run a group of filters and report results."""
        tasks = [f.generate_report(market_state) for f in filters]
        filter_results = await asyncio.gather(*tasks, return_exceptions=True)

        report = {"filters": {}, "hard_blocks": 0}
        
        logger.info(f"--- Validator {group_name} Report ---")
        for result in filter_results:
            if isinstance(result, Exception):
                logger.error(f"A {group_name} filter failed", extra={"error": str(result)}, exc_info=True)
                continue

            filter_name = result.get("filter_name", "UnknownFilter")
            flag = result.get("flag", "N/A")
            score = result.get("score", 0.0)
            logger.info(f"{filter_name:<35} | Flag: {flag:<18} | Score: {score:.4f}")
            
            report["filters"][filter_name] = result
            await market_state.update_filter_audit_report(filter_name, result)
            await self.memory_tracker.update_memory(filter_report=result)

            if "❌ Block" in flag:
                report["hard_blocks"] += 1
        
        return report

    async def run_pre_filters(self, market_state: MarketState) -> Dict[str, Any]:
        """Runs the initial, primary gate filters."""
        return await self._run_filter_group(market_state, self.primary_gate_filters, "Primary Gate")

    async def run_post_signal_validators(self, market_state: MarketState) -> Dict[str, Any]:
        """Runs the secondary stack of filters after a signal is generated."""
        return await self._run_filter_group(market_state, self.post_signal_filters, "Post-Signal")
