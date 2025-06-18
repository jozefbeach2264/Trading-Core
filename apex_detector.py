class ApexDetector:
    def __init__(self, sensitivity=3):
        self.sensitivity = sensitivity

    def is_apex(self, candles):
        if len(candles) < self.sensitivity + 2:
            return False
        mid_idx = len(candles) // 2
        mid = candles[mid_idx]["high"]
        return all(mid > c["high"] for i, c in enumerate(candles) if i != mid_idx)