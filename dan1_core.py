# dan1_core.py (Trading Reality Core)
import asyncio
import json
import logging
import os
import time
import aiohttp
from websocket import create_connection, WebSocketConnectionClosedException
from orderbook_reader import OrderBookReader
from volume_analyzer import VolumeAnalyzer
from signal_push import push_signal

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CoreEngine:
    def __init__(self):
        self.symbol = "ETHUSDT"  # Hardcoded ETHUSDT
        self.order_book_reader = OrderBookReader(self.symbol)
        self.volume_analyzer = VolumeAnalyzer(self.symbol)
        self.candles = []  # Store recent 1m candles
        self.bot_endpoint = os.environ.get("BOT_ENDPOINT")
        self.http_auth_token = os.environ.get("HTTP_AUTH_TOKEN")
        self.retries = int(os.environ.get("RETRIES", 3))
        self.retry_delay = int(os.environ.get("RETRY_DELAY", 5))
        self.base_url = "https://api.bybit.com"
        self.ws_url = "wss://stream.bybit.com/v5/public/spot"

    async def fetch_kline_rest(self):
        """Fetch initial 1m candles via REST."""
        url = f"{self.base_url}/v5/market/kline?symbol={self.symbol}&interval=1&limit=60"
        for attempt in range(self.retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            self.candles = data["result"]["list"]
                            logger.debug(f"REST kline updated: {self.symbol}")
                            return self.candles
                        logger.error(f"REST kline fetch failed: {response.status}")
            except Exception as e:
                logger.error(f"REST kline fetch error: {e}")
            await asyncio.sleep(self.retry_delay)
        return None

    async def stream_kline_ws(self):
        """Stream 1m candles via WebSocket."""
        while True:
            try:
                ws = create_connection(self.ws_url)
                ws.send(json.dumps({
                    "op": "subscribe",
                    "args": [f"kline.1m.{self.symbol}"]
                }))
                logger.info(f"WebSocket subscribed to kline.1m.{self.symbol}")
                while True:
                    data = json.loads(ws.recv())
                    if "topic" in data and "data" in data:
                        self.candles.append(data["data"])
                        if len(self.candles) > 60:  # Keep last 60 candles
                            self.candles.pop(0)
                        logger.debug(f"Kline received: {data['data']}")
            except (WebSocketConnectionClosedException, Exception) as e:
                logger.error(f"WebSocket error: {e}")
                await asyncio.sleep(self.retry_delay)

    async def generate_signal(self):
        """Generate Rolling5 signal."""
        order_book = self.order_book_reader.get_order_book()
        volume_metrics = self.volume_analyzer.get_volume_metrics()
        latest_candle = self.candles[-1] if self.candles else {}
        # Simplified Rolling5 signal logic (customize as needed)
        signal = {
            "signal_id": int(time.time()),
            "type": "buy" if volume_metrics["pressure_imbalance"] > 0 else "sell",
            "price": float(order_book["bids"][0][0]) if order_book["bids"] else float(latest_candle.get("close", 0)),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "direction": "up" if volume_metrics["pressure_imbalance"] > 0 else "down",
            "exit_price": float(order_book["bids"][0][0]) * 1.01 if order_book["bids"] else float(latest_candle.get("close", 0)) * 1.01,
            "roi": 1.0,
            "detonation": "none",
            "predictions": {
                "price_direction": "up" if volume_metrics["pressure_imbalance"] > 0 else "down",
                "c1": {"action": "buy", "price": float(order_book["bids"][0][0]), "volume": 1000},
                "c2": {"action": "hold", "price": float(order_book["bids"][0][0]) * 1.005, "volume": 500},
                "c3": {"action": "sell", "price": float(order_book["bids"][0][0]) * 1.01, "volume": 300},
                "c4": {"action": "hold", "price": float(order_book["bids"][0][0]) * 1.008, "volume": 200},
                "c5": {"action": "buy", "price": float(order_book["bids"][0][0]) * 1.007, "volume": 100},
                "midpoint": float(order_book["bids"][0][0]) * 1.005,
                "roi_so_far": 0.5,
                "expected_move": "up" if volume_metrics["pressure_imbalance"] > 0 else "down"
            }
        }
        await push_signal(signal, self.bot_endpoint, self.http_auth_token)
        logger.info(f"Generated signal: {signal['signal_id']}")
        return signal

    async def run(self):
        """Run core engine."""
        # Initial REST fetch
        await self.fetch_kline_rest()
        # Start WebSocket streams
        ws_tasks = [
            asyncio.create_task(self.order_book_reader.stream_order_book_ws()),
            asyncio.create_task(self.volume_analyzer.stream_trades_ws()),
            asyncio.create_task(self.stream_kline_ws())
        ]
        # Periodic REST fetches and signal generation
        while True:
            await self.order_book_reader.fetch_order_book_rest()
            await self.volume_analyzer.fetch_open_interest_rest()
            signal = await self.generate_signal()
            await asyncio.sleep(60)  # Generate signal every 60s
        await asyncio.gather(*ws_tasks)

async def main():
    """Main entry point."""
    engine = CoreEngine()
    await engine.run()

if __name__ == "__main__":
    asyncio.run(main())