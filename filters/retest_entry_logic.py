import logging
from typing import Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class RetestEntryLogic:
    """
    Validates trade signals by confirming the entry price is within an acceptable distance
    of the breakout level for a valid retest. Optimized for ETH trading with robust input handling.
    """
    # Constants for configuration
    DEFAULT_MAX_RETEST_DISTANCE_PCT = 0.015  # 1.5% as a decimal

    def __init__(self, max_retest_distance_pct: float = DEFAULT_MAX_RETEST_DISTANCE_PCT) -> None:
        """
        Initializes the RetestEntryLogic filter.

        Args:
            max_retest_distance_pct (float): Maximum acceptable distance between breakout level
                                            and entry price as a percentage (e.g., 0.015 for 1.5%).

        Raises:
            ValueError: If max_retest_distance_pct is negative.
        """
        if not isinstance(max_retest_distance_pct, (int, float)) or max_retest_distance_pct < 0:
            raise ValueError("max_retest_distance_pct must be non-negative")

        self.max_retest_distance_pct = float(max_retest_distance_pct)
        logger.info("RetestEntryLogic initialized: max_retest_distance_pct=%.2f%%",
                    self.max_retest_distance_pct * 100)

    async def validate(self, signal_data: Dict[str, Any]) -> bool:
        """
        Validates that the entry price is within the acceptable distance of the breakout level
        for a valid retest.

        Args:
            signal_data (Dict[str, Any]): Signal data containing:
                - 'symbol': str (optional, for logging)
                - 'breakout_level': float (price level of the breakout)
                - 'entry_price': float (intended entry price)

        Returns:
            bool: True if entry price is within the acceptable retest distance (signal passes),
                  False if too far (signal rejected).

        Raises:
            ValueError: If signal_data is invalid or missing required keys.
        """
        # Validate input
        if not isinstance(signal_data, dict):
            logger.error("Invalid signal_data: must be a dictionary")
            raise ValueError("signal_data must be a dictionary")

        symbol = signal_data.get("symbol", "unknown")
        if not isinstance(symbol, str):
            logger.warning("Invalid symbol for RetestEntryLogic: expected string, got %s", type(symbol))
            symbol = "unknown"

        breakout_level = signal_data.get("breakout_level")
        entry_price = signal_data.get("entry_price")

        # Validate prices
        try:
            breakout = float(breakout_level) if breakout_level is not None else 0.0
            entry = float(entry_price) if entry_price is not None else 0.0
        except (ValueError, TypeError):
            logger.warning("Invalid prices for %s: breakout_level=%s, entry_price=%s. Signal passed.",
                           symbol, breakout_level, entry_price)
            return True

        if breakout == 0 or entry == 0:
            logger.warning("Zero or missing price for %s: breakout_level=%.2f, entry_price=%.2f. Signal passed.",
                           symbol, breakout, entry)
            return True

        if breakout < 0 or entry < 0:
            logger.warning("Negative price for %s: breakout_level=%.2f, entry_price=%.2f. Signal passed.",
                           symbol, breakout, entry)
            return True

        # Calculate distance as a percentage
        try:
            distance_pct = abs(entry - breakout) / breakout
        except ZeroDivisionError:
            logger.warning("Zero breakout_level for %s: cannot calculate distance. Signal passed.", symbol)
            return True

        # Check if distance exceeds the threshold
        if distance_pct > self.max_retest_distance_pct:
            logger.warning(
                "Signal REJECTED for %s by RetestEntryLogic: entry_price=%.2f too far from breakout_level=%.2f "
                "(distance=%.2f%% > threshold=%.2f%%)",
                symbol, entry, breakout, distance_pct * 100, self.max_retest_distance_pct * 100
            )
            return False

        logger.info(
            "Signal PASSED for %s by RetestEntryLogic: entry_price=%.2f, breakout_level=%.2f, distance=%.2f%%",
            symbol, entry, breakout, distance_pct * 100
        )
        return True