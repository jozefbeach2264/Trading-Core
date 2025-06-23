# TradingCore/filters/cts_filter.py
import logging

# Configure logging
logger = logging.getLogger(__name__)

class CtsFilter:
    """
    Compression Trap Sensor (CTS) filter.
    This filter checks the compression score of a signal and rejects it
    if it exceeds a predefined risk threshold.
    """
    def __init__(self, compression_threshold: float = 0.75):
        """
        Initializes the CtsFilter.

        Args:
            compression_threshold (float): The score above which a signal is rejected.
        """
        self.compression_threshold = compression_threshold
        logger.info("CtsFilter initialized with threshold: %.2f", self.compression_threshold)

    async def validate(self, signal_data: dict) -> bool:
        """
        Validates the signal based on its compression score.

        Args:
            signal_data (dict): A dictionary containing signal data, including 'compression_score'.

        Returns:
            bool: True if the signal passes, False otherwise.
        """
        compression_score = signal_data.get("compression_score", 0)
        logger.debug("Validating CTS with compression score: %.2f", compression_score)

        if compression_score > self.compression_threshold:
            logger.warning("Signal REJECTED by CtsFilter due to high compression score: %.2f", compression_score)
            return False  # Block entry due to compression risk
        
        logger.info("Signal PASSED CtsFilter.")
        return True

