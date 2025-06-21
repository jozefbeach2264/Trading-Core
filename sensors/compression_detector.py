class CompressionDetector:
    def __init__(self, max_range=3.0):
        self.max_range = max_range

    def is_compressed(self, candles):
        if len(candles) < 3:
            return False
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        range_pct = (max(highs) - min(lows)) / min(lows) * 100
        return range_pct <= self.max_range