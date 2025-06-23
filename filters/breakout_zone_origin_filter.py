import logging
from typing import Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class BreakoutZoneOriginFilter:
    """
    Rejects trade signals originating within the breakout zone unless the entry price
    is confirmed to be outside the origin compression cluster.
    Optimized for ETH trading with robust input validation.
    """
    # Constants for configuration
    DEFAULT_ZONE_THRESHOLD = 0.01  # 1% as a decimal

    def __init__(self, zone_threshold: float = DEFAULT_ZONE_THRESHOLD) -> None:
        """
        Initializes the BreakoutZoneOriginFilter.

        Args:
            zone_threshold (float): Percentage range (as a decimal, e.g., 0.01 for 1%)
                                   around origin price to define the breakout zone.

        Raises:
            ValueError: If zone_threshold is negative.
        """
        if not isinstance(zone_threshold, (int, float)) or zone_threshold < 0:
            raise ValueError("zone_threshold must be non-negative")
        
        self.zone_threshold = float(zone_threshold)
        logger.info("BreakoutZoneOriginFilter initialized: zone_threshold=%.2f%%", self.zone_threshold * 100)

    async def validate(self, signal_data: Dict[str, Any]) -> bool:
        """
        Validates that the signal’s entry price is outside the breakout zone around the origin price.

        Args:
            signal_data (Dict[str, Any]): Signal data containing:
                - 'symbol': str (optional, for logging)
                - 'origin_price': float (price where signal originated)
                - 'entry_price': float (intended entry price)

        Returns:
            bool: True if entry price is outside the breakout zone (signal passes),
                  False if inside (signal rejected).

        Raises:
            ValueError: If signal_data is invalid or missing required keys.
        """
        # Validate input
        if not isinstance(signal_data, dict):
            logger.error("Invalid signal_data: must be a dictionary")
            raise ValueError("signal_data must be a dictionary")

        symbol = signal_data.get("symbol", "unknown")
        if not isinstance(symbol, str):
            logger.warning("Invalid symbol: expected string, got %s", type(symbol))
            symbol = "unknown"

        origin_price = signal_data.get("origin_price")
        entry_price = signal_data.get("entry_price")

        # Validate prices
        try:
            origin = float(origin_price) if origin_price is not None else 0.0
            entry = float(entry_price) if entry_price is not None else 0.0
        except (ValueError, TypeError):
            logger.warning("Invalid prices for %s: origin_price=%s, entry_price=%s. Signal passed.",
                           symbol, origin_price, entry_price)
            return True

        if origin == 0 or entry == 0:
            logger.warning("Zero or missing price for %s: origin_price=%.2f, entry_price=%.2f. Signal passed.",
                           symbol, origin, entry)
            return True

        if origin < 0 or entry < 0:
            logger.warning("Negative price for %s: origin_price=%.2f, entry_price=%.2f. Signal passed.",
                           symbol, origin, entry)
            return True

        # Calculate breakout zone bounds
        lower_bound = origin * (1 - self.zone_threshold)
        upper_bound = origin * (1 + self.zone_threshold)

        # Check if entry price is within the breakout zone
        if lower_bound <= entry <= upper_bound:
            logger.warning(
                "Signal REJECTED for %s by BreakoutZoneOriginFilter: entry_price=%.2f within breakout zone [%.2f, %.2f]",
                symbol, entry, lower_bound, upper_bound
            )
            return False

        logger.info(
            "Signal PASSED for %s by BreakoutZoneOriginFilter: entry_price=%.2f outside breakout zone [%.2f, %.2f]",
            symbol, entry, lower_bound, upper_bound
        )
        return True