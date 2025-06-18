class VolumeAnalyzer:
    def __init__(self, volume_threshold=15000):
        self.volume_threshold = volume_threshold

    def evaluate_volume(self, candle_volume):
        if candle_volume >= self.volume_threshold:
            return {
                "valid": True,
                "signal": "Volume sufficient",
                "volume": candle_volume
            }
        else:
            return {
                "valid": False,
                "signal": "Volume too low",
                "volume": candle_volume
            }

    def get_normalized_pressure(self, buy_volume, sell_volume):
        total = buy_volume + sell_volume
        if total == 0:
            return {
                "nprs": 0.0,
                "signal": "No volume"
            }

        bias = ((buy_volume - sell_volume) / total) * 100
        return {
            "nprs": round(bias, 2),
            "signal": "Bullish" if bias > 0 else "Bearish"
        }