# orderbook_reader.py (Trading Reality Core)
import asyncio
import json
import logging
import aiohttp
from websocket import create_connection, WebSocketConnectionClosedException

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class OrderBookReader:
    def __init__(self, symbol="ETHUSDT"):  # Hardcoded ETHUSDT
        self.symbol = symbol
        self.order_book = {"bids": [], "asks": []}
        self.base_url = "https://api.bybit.com"
        self.ws_url = "wss://stream.bybit.com/v5/public/spot"
        self.retries = int(os.environ.get("RETRIES", 3))
        self.retry_delay = int(os.environ.get("RETRY_DELAY", 5))

    async def fetch_order_book_rest(self):
        """Fetch order book via REST."""
        url = f"{self.base_url}/v5/market/depth?symbol={self.symbol}&limit=50"
        for attempt in range(self.retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            self.order_book = {
                                "bids": data["result"]["b"],
                                "asks": data["result"]["a"]
                            }
                            logger.debug(f"REST order book updated: {self.symbol}")
                            return self.order_book
                        logger.error(f"REST fetch failed: {response.status}")
            except Exception as e:
                logger.error(f"REST fetch error: {e}")
            await asyncio.sleep(self.retry_delay)
        return None

    async def stream_order_book_ws(self):
        """Stream order book via WebSocket."""
        while True:
            try:
                ws = create_connection(self.ws_url)
                ws.send(json.dumps({
                    "op": "subscribe",
                    "args": [f"orderbook.100ms.{self.symbol}"]
                }))
                logger.info(f"WebSocket subscribed to orderbook.100ms.{self.symbol}")
                while True:
                    data = json.loads(ws.recv())
                    if "topic" in data and "data" in data:
                        self.order_book = {
                            "bids": data["data"]["b"],
                            "asks": data["data"]["a"]
                        }
                        logger.debug(f"WebSocket order book updated: {self.symbol}")
            except (WebSocketConnectionClosedException, Exception) as e:
                logger.error(f"WebSocket error: {e}")
                await asyncio.sleep(self.retry_delay)

    def get_order_book(self):
        """Return current order book."""
        return self.order_book