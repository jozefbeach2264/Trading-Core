import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class CompressionTrapSensor:
    """
    Implements the proprietary logic for detecting compression trap scenarios.
    This logic was consolidated from the CtsFilter and the logic document.
    """
    def __init__(self):
        logger.info("CompressionTrapSensor initialized.")
        self.compression_threshold_pct = 0.1
        self.wick_multiplier = 3.0

    async def validate(self, signal_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyzes recent candle data for compression trap signatures.

        Args:
            signal_data (Dict[str, Any]): The market state data, must include 'klines'.

        Returns:
            Dict[str, Any]: A dictionary containing the analysis result.
        """
        # This implementation is identical to the one in CompressionDetector.
        # This file is provided to match the file list, but in the final build,
        # you would use one or the other and have the ValidatorStack import it.
        klines = signal_data.get('klines', [])
        result = {
            "filter_name": "CompressionTrapSensor",
            "status": "pass",
            "reason": "No compression trap signature detected."
        }

        if not klines or len(klines) < 2:
            result["reason"] = "Not enough kline data."
            return result

        last_candle = klines[-2]
        try:
            o, h, l, c = float(last_candle[1]), float(last_candle[2]), float(last_candle[3]), float(last_candle[4])
        except (ValueError, TypeError):
            result["reason"] = "Malformed kline data."
            return result

        candle_range = h - l
        if candle_range == 0:
            result["reason"] = "Zero range candle."
            return result
        
        candle_body = abs(c - o)
        is_compressed = (candle_body / candle_range) <= self.compression_threshold_pct
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l

        has_large_impulse_wick = False
        if candle_body > 0:
            if (upper_wick / candle_body) >= self.wick_multiplier or (lower_wick / candle_body) >= self.wick_multiplier:
                has_large_impulse_wick = True

        if is_compressed and has_large_impulse_wick:
            result.update({
                "status": "fail",
                "reason": "Compression trap signature detected."
            })
        
        return result
