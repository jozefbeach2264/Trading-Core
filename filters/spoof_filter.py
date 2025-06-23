import asyncio
from time import time
from typing import Dict, List, Tuple, Optional
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SpoofFilter:
    """
    Analyzes market data for spoofing or absorption to validate trade signals.
    Used as a component in the ValidatorStack.
    """
    # Constants for configuration
    DEFAULT_VOLUME_THRESHOLD = 75
    DEFAULT_MIN_THINNING_PERCENT = 10
    DEFAULT_MAX_DURATION = 6
    DEFAULT_PRICE_WINDOW = 5

    def __init__(
        self,
        volume_threshold: float = DEFAULT_VOLUME_THRESHOLD,
        min_thinning_percent: float = DEFAULT_MIN_THINNING_PERCENT,
        max_duration: float = DEFAULT_MAX_DURATION,
        price_window: float = DEFAULT_PRICE_WINDOW
    ) -> None:
        """
        Initializes the SpoofFilter with spoof detection thresholds.

        Args:
            volume_threshold (float): Minimum volume to consider an order book wall.
            min_thinning_percent (float): Minimum percentage of volume reduction to flag spoofing.
            max_duration (float): Maximum time (seconds) for a wall to thin out to be considered spoofing.
            price_window (float): Price range around mark price to analyze walls.
        """
        # Validate initialization parameters
        if volume_threshold <= 0:
            raise ValueError("volume_threshold must be positive")
        if min_thinning_percent < 0:
            raise ValueError("min_thinning_percent must be non-negative")
        if max_duration <= 0:
            raise ValueError("max_duration must be positive")
        if price_window <= 0:
            raise ValueError("price_window must be positive")

        self.volume_threshold = volume_threshold
        self.min_thinning_percent = min_thinning_percent
        self.max_duration = max_duration
        self.price_window = price_window
        self.tracked_walls: Dict[Tuple[str, float], Dict[str, float]] = {}  # (side, price) -> {'volume': float, 'timestamp': float}
        logger.info("SpoofFilter initialized with volume_threshold=%.2f, min_thinning_percent=%.2f, max_duration=%.2f, price_window=%.2f",
                    volume_threshold, min_thinning_percent, max_duration, price_window)

    async def validate(self, signal_data: Dict) -> bool:
        """
        Validates a trade signal by scanning for spoofing activity in the order book.

        Args:
            signal_data (dict): {
                'symbol': str,
                'order_book': {'asks': [(price: float, volume: float)], 'bids': [(price: float, volume: float)]},
                'mark_price': float
            }

        Returns:
            bool: True if no spoofing detected, False if spoofing detected.

        Raises:
            ValueError: If signal_data is missing required keys or contains invalid data.
        """
        # Validate input
        if not isinstance(signal_data, dict):
            logger.error("Invalid signal_data: must be a dictionary")
            raise ValueError("signal_data must be a dictionary")
        if "symbol" not in signal_data or "order_book" not in signal_data or "mark_price" not in signal_data:
            logger.error("Invalid signal_data: missing required keys (symbol, order_book, mark_price)")
            raise ValueError("signal_data missing required keys")
        symbol = signal_data["symbol"]
        if not isinstance(symbol, str) or not symbol:
            logger.error("Invalid symbol: must be a non-empty string")
            raise ValueError("symbol must be a non-empty string")
        if not isinstance(signal_data["order_book"], dict):
            logger.error("Invalid order_book: must be a dictionary")
            raise ValueError("order_book must be a dictionary")
        if not isinstance(signal_data["mark_price"], (int, float)) or signal_data["mark_price"] < 0:
            logger.error("Invalid mark_price: must be a non-negative number")
            raise ValueError("mark_price must be a non-negative number")

        logger.info("Running SpoofFilter validation for symbol: %s", symbol)
        order_book = signal_data["order_book"]
        mark_price = float(signal_data["mark_price"])
        current_time = time()
        spoof_detected = False

        # Process asks and bids
        for side in ["asks", "bids"]:
            levels: List[Tuple[float, float]] = order_book.get(side, [])
            if not isinstance(levels, list):
                logger.warning("Invalid %s data for %s: expected list, got %s", side, symbol, type(levels))
                continue

            for price, volume in levels:
                # Validate price and volume
                if not isinstance(price, (int, float)) or not isinstance(volume, (int, float)):
                    logger.warning("Invalid price or volume for %s %s: price=%s, volume=%s", symbol, side, price, volume)
                    continue
                if price < 0 or volume < 0:
                    logger.warning("Negative price or volume for %s %s: price=%.2f, volume=%.2f", symbol, side, price, volume)
                    continue

                # Skip levels outside the price window
                if abs(price - mark_price) > self.price_window:
                    continue

                key = (side, price)
                tracked = self.tracked_walls.get(key)

                if volume >= self.volume_threshold:
                    if tracked:
                        time_alive = current_time - tracked["timestamp"]
                        prev_volume = tracked["volume"]
                        thinning_percent = ((prev_volume - volume) / prev_volume * 100) if prev_volume > 0 else 0
                        self.tracked_walls[key] = {"volume": volume, "timestamp": current_time}

                        if thinning_percent >= self.min_thinning_percent and time_alive <= self.max_duration:
                            logger.warning("Spoofing detected on %s wall at price=%.2f for %s: thinned %.2f%% in %.2f seconds",
                                           side, price, symbol, thinning_percent, time_alive)
                            spoof_detected = True
                    else:
                        self.tracked_walls[key] = {"volume": volume, "timestamp": current_time}
                elif tracked:
                    del self.tracked_walls[key]

        # Clean up stale walls (older than max_duration)
        self._cleanup_stale_walls(current_time)

        if spoof_detected:
            logger.warning("Spoofing detected for %s: signal rejected", symbol)
            return False
        logger.info("No significant spoofing detected for %s: signal passed", symbol)
        return True

    def _cleanup_stale_walls(self, current_time: float) -> None:
        """
        Removes tracked walls older than max_duration to prevent memory growth.

        Args:
            current_time (float): Current timestamp for comparison.
        """
        stale_keys = [
            key for key, data in self.tracked_walls.items()
            if current_time - data["timestamp"] > self.max_duration
        ]
        for key in stale_keys:
            del self.tracked_walls[key]
        if stale_keys:
            logger.debug("Cleaned up %d stale walls", len(stale_keys))