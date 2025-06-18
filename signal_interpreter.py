class SignalInterpreter:
    def __init__(self, chart_reader, validator_stack):
        self.chart_reader = chart_reader
        self.validator = validator_stack

    def generate_signal(self):
        latest = self.chart_reader.get_latest()
        if not latest:
            print("[SignalInterpreter] No candle data available.")
            return None

        signal = {
            "strategy": "scalpel",
            "entry": latest["close"],
            "volume": latest["volume"],
            "speed": (latest["high"] - latest["low"]),
            "open": latest["open"],
            "close": latest["close"],
            "high": latest["high"],
            "low": latest["low"]
        }
        return signal