# TradingCore/data_managers/market_data_ws_client.py
import asyncio
import logging
import aiohttp
from typing import Callable, Coroutine

logger = logging.getLogger(__name__)

class MarketDataWsClient:
    _WS_BASE_URL = "wss://fstream.asterdex.com/stream?streams="

    def __init__(self, symbol: str, on_message_callback: Callable[[str, dict], Coroutine]):
        self.symbol = symbol.lower()
        self.on_message_callback = on_message_callback
        self.session: aiohttp.ClientSession = aiohttp.ClientSession()
        self._task: asyncio.Task = None
        self.running = False

    def _get_stream_url(self) -> str:
        # Subscribe to all the public streams needed for the console display
        streams = [
            f"{self.symbol}@depth20@100ms", # For Walls
            f"{self.symbol}@aggTrade",      # For Volume and Delta
            f"{self.symbol}@kline_1m",      # For Trend
            f"{self.symbol}@bookTicker",    # For Spread
            f"{self.symbol}@markPrice@1s",  # For Mark Price
        ]
        return self._WS_BASE_URL + "/".join(streams)

    async def _connection_loop(self):
        ws_url = self._get_stream_url()
        while self.running:
            try:
                async with self.session.ws_connect(ws_url, heartbeat=30) as ws:
                    logger.info("Public Market Data WebSocket connected.")
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = msg.json()
                            if 'stream' in data and 'data' in data:
                                stream_name = data['stream']
                                payload = data['data']
                                await self.on_message_callback(stream_name, payload)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            break
            except Exception as e:
                logger.error("Public Market Data WebSocket failed: %s.", e)
            
            if not self.running:
                break
                
            logger.info("Public Market Data WS disconnected. Reconnecting in 10s.")
            await asyncio.sleep(10)

    def start(self):
        if not self.running:
            self.running = True
            self._task = asyncio.create_task(self._connection_loop())
            logger.info("MarketDataWsClient started.")

    async def stop(self):
        if self.running:
            self.running = False
            if self._task:
                self._task.cancel()
            if self.session and not self.session.closed:
                await self.session.close()
            logger.info("MarketDataWsClient stopped.")
