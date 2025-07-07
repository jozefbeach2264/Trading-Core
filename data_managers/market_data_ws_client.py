import asyncio
import json
import logging
from typing import Callable

import websockets

logger = logging.getLogger(__name__)

class MarketDataWsClient:
    def __init__(self, symbol: str, on_message_callback: Callable):
        self._base_url = "wss://fstream.asterdex.com/stream"
        self.symbol = symbol.lower()
        self.on_message_callback = on_message_callback
        self.ws = None
        self._running = False
        self._main_task = None

    def _get_url(self) -> str:
        # Subscribe to multiple streams in one connection
        streams = [
            f"{self.symbol}@aggTrade",
            f"{self.symbol}@markPrice@1s",
            f"{self.symbol}@depth20@100ms",
            f"{self.symbol}@kline_1m",
            f"{self.symbol}@bookTicker"
        ]
        stream_path = "?streams=" + "/".join(streams)
        return self._base_url + stream_path

    async def _main_loop(self):
        url = self._get_url()
        while self._running:
            try:
                async with websockets.connect(url) as ws:
                    self.ws = ws
                    logger.info("Public Market Data WebSocket connected.")
                    try:
                        async for msg in self.ws:
                            # --- ADDED DIAGNOSTIC LOGGING ---
                            logger.info("Received message on Public Market Data Stream.")
                            data = json.loads(msg)
                            if 'stream' in data and 'data' in data:
                                await self.on_message_callback(data['stream'], data['data'])
                    except websockets.exceptions.ConnectionClosed as e:
                        logger.warning(f"Public Market Data WS connection closed: {e}. Reconnecting...")
                    except Exception as e:
                        logger.error(f"Error in Public Market Data WS message loop: {e}", exc_info=True)
            except Exception as e:
                logger.error(f"Failed to connect to Public Market Data WS: {e}. Retrying in 10s.")
            
            if self._running:
                await asyncio.sleep(10)

    def start(self):
        if not self._running:
            self._running = True
            self._main_task = asyncio.create_task(self._main_loop())
            logger.info("MarketDataWsClient started.")

    async def stop(self):
        if self._running:
            self._running = False
            if self.ws:
                await self.ws.close()
            if self._main_task:
                self._main_task.cancel()
                try:
                    await self._main_task
                except asyncio.CancelledError:
                    pass
            logger.info("MarketDataWsClient stopped.")
