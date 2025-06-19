# chart_reader.py
# No longer needs to import 'requests'

# We will import our new ApiClient class
from api_client import ApiClient

class ChartReader:
    # It now takes the api_client as its main dependency
    def __init__(self, api_client: ApiClient, pair="ETHUSDT", interval="1m"):
        self.api_client = api_client
        self.pair = pair
        self.interval = interval
        print("ChartReader: Initialized and using ApiClient.")

    def fetch_latest_candle(self, limit=1):
        """
        Fetches the latest candle data using the centralized ApiClient.
        """
        try:
            # Instead of requests.get, we use our client's method
            data = self.api_client.get_klines(
                symbol=self.pair,
                interval=self.interval,
                limit=limit
            )
            # The ApiClient already handles errors and JSON conversion
            return data[-1] if data and "error" not in data else None
        except Exception as e:
            print(f"[ChartReader] Failed to fetch candles: {e}")
            return None

    def parse_candle(self, candle_data: list):
        """Parses a single kline from the API response."""
        if not candle_data or len(candle_data) < 6:
            return None
        return {
            "open_time": candle_data[0],
            "open": float(candle_data[1]),
            "high": float(candle_data[2]),
            "low": float(candle_data[3]),
            "close": float(candle_data[4]),
            "volume": float(candle_data[5])
        }

    def get_latest(self):
        """Fetches and parses the single latest candle."""
        raw_candle = self.fetch_latest_candle()
        return self.parse_candle(raw_candle)

