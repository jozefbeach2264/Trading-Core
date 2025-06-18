import requests

class ChartReader:
    def __init__(self, base_url="https://fapi.asterdex.com", pair="ETHUSDT", interval="1m"):
        self.base_url = base_url
        self.pair = pair
        self.interval = interval

    def fetch_latest_candle(self, limit=1):
        url = f"{self.base_url}/fapi/v1/klines"
        params = {
            "symbol": self.pair,
            "interval": self.interval,
            "limit": limit
        }
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            return data[-1] if data else None
        except Exception as e:
            print(f"[ChartReader] Failed to fetch candles: {e}")
            return None

    def parse_candle(self, candle):
        if not candle or len(candle) < 6:
            return None
        return {
            "open_time": candle[0],
            "open": float(candle[1]),
            "high": float(candle[2]),
            "low": float(candle[3]),
            "close": float(candle[4]),
            "volume": float(candle[5])
        }

    def get_latest(self):
        raw = self.fetch_latest_candle()
        return self.parse_candle(raw)