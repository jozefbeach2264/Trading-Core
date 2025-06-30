import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class CompressionDetector:
    """
    Detects compression trap scenarios by identifying narrow-range candles
    followed by large impulse wicks, based on your proprietary logic.
    """
    def __init__(self):
        logger.info("CompressionDetector initialized.")
        self.compression_threshold_pct = 0.1 # Example: Body is 10% or less of total candle range
        self.wick_multiplier = 3.0 # Example: Wick is 3x or more of the body size

    async def validate(self, signal_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyzes recent candle data for compression trap signatures.

        Args:
            signal_data (Dict[str, Any]): The market state data, must include 'klines'.

        Returns:
            Dict[str, Any]: A dictionary containing the analysis result.
        """
        klines = signal_data.get('klines', [])
        if not klines or len(klines) < 2:
            return {"filter_name": "CompressionDetector", "status": "pass", "reason": "Not enough kline data."}

        # Analyzing the most recently closed candle
        last_candle = klines[-2] # -1 is the current, forming candle
        try:
            # o, h, l, c
            o, h, l, c = float(last_candle[1]), float(last_candle[2]), float(last_candle[3]), float(last_candle[4])
        except (ValueError, TypeError):
            return {"filter_name": "CompressionDetector", "status": "pass", "reason": "Malformed kline data."}

        candle_range = h - l
        candle_body = abs(c - o)

        if candle_range == 0:
            return {"filter_name": "CompressionDetector", "status": "pass", "reason": "Zero range candle."}

        is_compressed = (candle_body / candle_range) <= self.compression_threshold_pct
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l

        # Check for large impulse wick
        has_large_impulse_wick = False
        if candle_body > 0: # Avoid division by zero
            if (upper_wick / candle_body) >= self.wick_multiplier or \
               (lower_wick / candle_body) >= self.wick_multiplier:
                has_large_impulse_wick = True

        if is_compressed and has_large_impulse_wick:
            return {
                "filter_name": "CompressionDetector",
                "status": "fail",
                "is_compressed": True,
                "has_large_impulse_wick": True,
                "reason": "Compression trap signature detected on previous candle."
            }
        
        return {
            "filter_name": "CompressionDetector",
            "status": "pass",
            "is_compressed": is_compressed,
            "has_large_impulse_wick": has_large_impulse_wick,
            "reason": "No compression trap signature detected."
        }
