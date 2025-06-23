# TradingCore/validator_stack.py
import logging
from typing import Dict, Any

# --- Import all filter classes from the 'filters' package ---
# Note: We are creating a placeholder for TimeOfDayFilter as it's the last one.
from filters.spoof_filter import SpoofFilter
from filters.cts_filter import CtsFilter
from filters.compression_detector import CompressionDetector
from filters.breakout_zone_origin_filter import BreakoutZoneOriginFilter
from filters.retest_entry_logic import RetestEntryLogic
from filters.low_volume_guard import LowVolumeGuard
from filters.sentiment_divergence_filter import SentimentDivergenceFilter

# --- Placeholder class for the final filter ---
class TimeOfDayFilter:
    """Placeholder filter."""
    def __init__(self):
        logging.info("TimeOfDayFilter initialized (placeholder).")
    async def validate(self, signal_data: Dict[str, Any]) -> bool:
        logging.debug("Signal PASSED TimeOfDayFilter (placeholder).")
        return True

logger = logging.getLogger(__name__)

class ValidatorStack:
    def __init__(self):
        """
        Initializes the ValidatorStack and loads all filter modules.
        This class acts as the single point of contact for all pre-trade validation.
        """
        # --- Instantiate all your filter classes ---
        self.filters = [
            SpoofFilter(),
            CtsFilter(),
            CompressionDetector(),
            BreakoutZoneOriginFilter(),
            RetestEntryLogic(),
            LowVolumeGuard(),
            SentimentDivergenceFilter(),
            TimeOfDayFilter(), # Using the placeholder for now
        ]
        logger.info("ValidatorStack initialized with %d filters.", len(self.filters))

    async def run_all(self, signal_data: Dict[str, Any]) -> bool:
        """
        Runs the signal sequentially through every filter in the stack.
        If any single filter returns False, the entire stack fails.
        """
        logger.info("--- Running signal through Validator Stack ---")
        for f in self.filters:
            is_valid = await f.validate(signal_data)
            if not is_valid:
                # The filter itself is responsible for logging the reason for rejection.
                logger.error("--- Signal FAILED validation at: %s ---", f.__class__.__name__)
                return False
        
        logger.info("--- Signal PASSED all %d filters in ValidatorStack. ---", len(self.filters))
        return True
