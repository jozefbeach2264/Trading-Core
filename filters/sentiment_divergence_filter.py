import logging
from typing import Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SentimentDivergenceFilter:
    """
    Validates trade signals by checking for divergence between price action and market sentiment.
    Rejects signals where price movement conflicts with funding rate (e.g., rising price with negative
    funding rate), indicating a weak trend. Optimized for ETH trading with robust input handling.
    """

    def __init__(self) -> None:
        """
        Initializes the SentimentDivergenceFilter.

        No configurable parameters are required.
        """
        logger.info("SentimentDivergenceFilter initialized.")

    async def validate(self, signal_data: Dict[str, Any]) -> bool:
        """
        Validates a trade signal based on sentiment divergence between price action and funding rate.

        Args:
            signal_data (Dict[str, Any]): Signal data containing:
                - 'symbol': str (optional, for logging, e.g., 'ETHUSD')
                - 'funding_rate': float (market sentiment indicator, e.g., from perpetual futures)
                - 'price_change_1m': float (1-minute price change as a percentage, e.g., 0.5 for 0.5%)

        Returns:
            bool: True if no divergence detected (signal passes), False if divergence detected
                  (signal rejected).

        Raises:
            ValueError: If signal_data is invalid.
        """
        # Validate input
        if not isinstance(signal_data, dict):
            logger.error("Invalid signal_data: must be a dictionary")
            raise ValueError("signal_data must be a dictionary")

        symbol = signal_data.get("symbol", "unknown")
        if not isinstance(symbol, str):
            logger.warning("Invalid symbol: expected string, got %s", type(symbol))
            symbol = "unknown"

        logger.debug("Running SentimentDivergenceFilter validation for %s", symbol)

        funding_rate = signal_data.get("funding_rate")
        price_change_1m = signal_data.get("price_change_1m")

        # Validate funding rate and price change
        try:
            funding = float(funding_rate) if funding_rate is not None else None
            price_change = float(price_change_1m) if price_change_1m is not None else None
        except (ValueError, TypeError):
            logger.warning("Invalid data for %s: funding_rate=%s, price_change_1m=%s. Signal passed.",
                           symbol, funding_rate, price_change_1m)
            return True

        if funding is None or price_change is None:
            logger.warning("Missing data for %s: funding_rate=%s, price_change_1m=%s. Signal passed.",
                           symbol, funding_rate, price_change_1m)
            return True

        # Divergence Logic: Reject if price rises with negative funding or falls with positive funding
        divergence_detected = (
            (price_change > 0 and funding < 0) or
            (price_change < 0 and funding > 0)
        )

        if divergence_detected:
            logger.warning(
                "Signal REJECTED for %s by SentimentDivergenceFilter: "
                "funding_rate=%.6f, price_change_1m=%.2f%%",
                symbol, funding, price_change
            )
            return False

        logger.info("Signal PASSED for %s by SentimentDivergenceFilter: "
                    "funding_rate=%.6f, price_change_1m=%.2f%%",
                    symbol, funding, price_change)
        return True