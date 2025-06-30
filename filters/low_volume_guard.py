import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class LowVolumeGuard:
    """
    Filters out trades during low-volume market conditions by checking against
    a dynamic threshold calculated from recent volume data.
    """
    def __init__(self):
        logger.info("LowVolumeGuard initialized.")
        self.lookback_period = 20  # Number of recent candles to average for baseline
        self.volume_multiplier = 0.75 # Current volume must be at least 75% of the recent average

    async def validate(self, signal_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validates that current volume is sufficient for a trade.

        Args:
            signal_data (Dict[str, Any]): The market state data, must include 'klines'.

        Returns:
            Dict[str, Any]: A dictionary containing the analysis result.
        """
        klines = signal_data.get('klines', [])
        if len(klines) < self.lookback_period:
            return {
                "filter_name": "LowVolumeGuard",
                "status": "fail",
                "reason": f"Not enough kline data to establish baseline (have {len(klines)}/{self.lookback_period})."
            }

        try:
            # Calculate average volume over the lookback period (excluding the current candle)
            recent_candles = klines[-self.lookback_period:-1]
            volumes = [float(c[5]) for c in recent_candles]
            average_volume = sum(volumes) / len(volumes) if volumes else 0
            
            # Get the volume of the most recently closed candle
            current_volume = float(klines[-2][5])

        except (ValueError, TypeError, IndexError) as e:
            logger.error(f"Error processing kline data in LowVolumeGuard: {e}")
            return {"filter_name": "LowVolumeGuard", "status": "fail", "reason": "Malformed kline data."}

        volume_threshold = average_volume * self.volume_multiplier

        if current_volume >= volume_threshold:
            return {
                "filter_name": "LowVolumeGuard",
                "status": "pass",
                "current_volume": current_volume,
                "volume_threshold": volume_threshold,
                "reason": "Volume is sufficient."
            }
        else:
            return {
                "filter_name": "LowVolumeGuard",
                "status": "fail",
                "current_volume": current_volume,
                "volume_threshold": volume_threshold,
                "reason": "Current volume is below the required threshold."
            }

