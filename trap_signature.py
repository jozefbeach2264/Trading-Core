class TrapSignature:
    def __init__(self):
        self.last_candle = None

    def detect(self, candle):
        if not candle:
            return False
        body = abs(candle["close"] - candle["open"])
        wick = candle["high"] - candle["low"]
        if wick > 2 * body and candle["volume"] > 10000:
            return True
        return False