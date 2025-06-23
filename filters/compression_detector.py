import logging
from typing import Dict, List, Any, Union, Tuple

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CompressionDetector:
    """
    Detects low-volatility market compression and rejects trade signals during such periods.
    Used as a component in the ValidatorStack.
    """
    # Constants for configuration
    DEFAULT_CANDLE_COUNT = 3
    DEFAULT_RANGE_THRESHOLD = 0.02  # 2% as a decimal
    KLINE_HIGH_INDEX = 2
    KLINE_LOW_INDEX = 3
    KLINE_CLOSE_INDEX = 4

    def __init__(
        self,
        candle_count: int = DEFAULT_CANDLE_COUNT,
        range_threshold: float = DEFAULT_RANGE_THRESHOLD
    ) -> None:
        """
        Initializes the CompressionDetector with compression detection parameters.

        Args:
            candle_count (int): Number of recent candles to analyze for compression.
            range_threshold (float): Maximum price range (as a decimal, e.g., 0.02 for 2%)
                                    allowed before compression is flagged.

        Raises:
            ValueError: If candle_count is non-positive or range_threshold is negative.
        """
        if not isinstance(candle_count, int) or candle_count <= 0:
            raise ValueError("candle_count must be a positive integer")
        if not isinstance(range_threshold, (int, float)) or range_threshold < 0:
            raise ValueError("range_threshold must be non-negative")

        self.candle_count = candle_count
        self.range_threshold = range_threshold
        logger.info(
            "CompressionDetector initialized: candle_count=%d, range_threshold=%.2f%%",
            candle_count, range_threshold * 100
        )

    async def validate(self, signal_data: Dict[str, Any]) -> bool:
        """
        Validates a trade signal by checking for price compression in recent kline data.

        Args:
            signal_data (Dict[str, Any]): Signal data containing:
                - 'symbol': str (optional, for logging)
                - 'klines': List[List[float]] or List[Tuple[float, ...]], where each kline is:
                    [open_time, open, high, low, close, volume, ...]

        Returns:
            bool: True if no compression detected (signal passes), False if compression detected (signal rejected).

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

        klines: List[Union[List[float], Tuple[float, ...]]] = signal_data.get("klines", [])
        if not isinstance(klines, list):
            logger.error("Invalid klines for %s: must be a list, got %s", symbol, type(klines))
            raise ValueError("klines must be a list")

        # Check if enough kline data is available
        if len(klines) < self.candle_count:
            logger.warning(
                "Insufficient kline data for %s: got %d candles, need %d. Signal passed.",
                symbol, len(klines), self.candle_count
            )
            return True

        # Validate recent klines
        try:
            # Extract high, low, and last close efficiently
            highs = []
            lows = []
            last_close = None
            for kline in klines[-self.candle_count:]:
                if not isinstance(kline, (list, tuple)) or len(kline) <= self.KLINE_CLOSE_INDEX:
                    logger.warning("Invalid kline format for %s: %s", symbol, kline)
                    return True  # Skip invalid kline, pass signal
                try:
                    high = float(kline[self.KLINE_HIGH_INDEX])
                    low = float(kline[self.KLINE_LOW_INDEX])
                    close = float(kline[self.KLINE_CLOSE_INDEX])
                except (ValueError, TypeError):
                    logger.warning("Invalid kline values for %s: high=%s, low=%s, close=%s",
                                   symbol, kline[self.KLINE_HIGH_INDEX], kline[self.KLINE_LOW_INDEX],
                                   kline[self.KLINE_CLOSE_INDEX])
                    return True  # Skip invalid values, pass signal
                if high < 0 or low < 0 or close < 0:
                    logger.warning("Negative kline values for %s: high=%.2f, low=%.2f, close=%.2f",
                                   symbol, high, low, close)
                    return True  # Skip negative values, pass signal
                highs.append(high)
                lows.append(low)
                last_close = close

            # Calculate price range
            highest_high = max(highs)
            lowest_low = min(lows)
            if last_close == 0:
                logger.warning("Zero last_close_price for %s: cannot calculate range. Signal passed.", symbol)
                return True

            price_range = (highest_high - lowest_low) / last_close
            if price_range < self.range_threshold:
                logger.warning(
                    "Signal REJECTED for %s by CompressionDetector: price range=%.2f%% < threshold=%.2f%%",
                    symbol, price_range * 100, self.range_threshold * 100
                )
                return False

            logger.info("Signal PASSED CompressionDetector for %s: price range=%.2f%%", symbol, price_range * 100)
            return True

        except Exception as e:
            logger.error("Unexpected error processing klines for %s: %s", symbol, str(e))
            return True  # Fail-safe: pass signal on unexpected errors
