# TradingCore/filters/low_volume_guard.py

class LowVolumeGuard:
    """
    Blocks trades if the recent market volume is below a certain threshold.
    """
    def __init__(self, min_volume_threshold: float = 15000.0):
        # [span_0](start_span)Your outline specifies rejecting entries if the last 3 candles < 15K[span_0](end_span)
        # We'll use the live volume for now as a starting point.
        self.min_volume = min_volume_threshold
        print("LowVolumeGuard Filter Initialized.")

    def check(self, market_state) -> bool:
        """
        Returns True if the volume is sufficient, False otherwise.
        """
        # This checks the volume of the most recent 1-minute candle
        if market_state.volume < self.min_volume:
            return False
            
        return True
