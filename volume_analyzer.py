# volume_analyzer.py (Trading Reality Core)
import asyncio
import json
import logging
import aiohttp
from websocket import create_connection, WebSocketConnectionClosedException

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class VolumeAnalyzer:
    def __init__(self, symbol="ETHUSDT"):  # Hardcoded ETHUSDT
        self.symbol = symbol
        self.trades = []
        self.open_interest = 0
        self.base_url = "https://api.bybit.com"
        self.ws_url = "wss://stream.bybit.com/v5/public/spot"
        self.retries = int(os.environ.get("RETRIES", 3))
        self.retry_delay = int(os.environ.get("RETRY_DELAY", 5))

    async def fetch_open_interest_rest(self):
        """Fetch open interest via REST."""
        url = f"{self.base_url}/v5/market/open-interest?symbol={self.symbol}&interval=5m"
        for attempt in range(self.retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            self.open_interest = float(data["result"]["openInterest"])
                            logger.debug(f"Open interest updated: {self.open_interest}")
                            return self.open_interest
                        logger.error(f"REST fetch failed: {response.status}")
            except Exception as e:
                logger.error(f"REST fetch error: {e}")
            await asyncio.sleep(self.retry_delay)
        return None

    async def stream_trades_ws(self):
        """Stream trades via WebSocket."""
        while True:
            try:
                ws = create_connection(self.ws_url)
                ws.send(json.dumps({
                    "op": "subscribe",
                    "args": [f"trade.{self.symbol}"]
                }))
                logger.info(f"WebSocket subscribed to trade.{self.symbol}")
                while True:
                    data = json.loads(ws.recv())
                    if "topic" in data and "data" in data:
                        self.trades.append(data["data"])
                        if len(self.trades) > 100:  # Keep last 100 trades
                            self.trades.pop(0)
                        logger.debug(f"Trade received: {data['data']}")
            except (WebSocketConnectionClosedException, Exception) as e:
                logger.error(f"WebSocket error: {e}")
                await asyncio.sleep(self.retry_delay)

    def get_volume_metrics(self):
        """Calculate volume metrics."""
        volume = sum(float(trade["v"]) for trade in self.trades)
        speed = len(self.trades) / 60  # Trades per second (assuming 60s window)
        pressure = sum(float(trade["v"]) * (1 if trade["S"] == "Buy" else -1) for trade in self.trades)
        return {
            "volume": volume,
            "speed": speed,
            "pressure_imbalance": pressure,
            "open_interest": self.open_interest
        }