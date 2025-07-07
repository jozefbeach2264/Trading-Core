import asyncio
import json
import logging
from typing import Callable

import aiohttp
import websockets
from config.config import Config

logger = logging.getLogger(__name__)

class AsterdexWsClient:
    def __init__(self, api_key: str, on_message_callback: Callable, session: aiohttp.ClientSession):
        self._base_ws_url = "wss://fstream.asterdex.com/ws/"
        self._base_api_url = "https://fapi.asterdex.com"
        self._api_key = api_key
        self.on_message_callback = on_message_callback
        self._aiohttp_session = session
        self.ws = None
        self._running = False
        self._listen_key = None
        self._tasks = []

    async def _get_listen_key(self) -> str:
        url = f"{self._base_api_url}/fapi/v1/listenKey"
        headers = {'X-MBX-APIKEY': self._api_key}
        async with self._aiohttp_session.post(url, headers=headers) as response:
            response.raise_for_status()
            data = await response.json()
            return data['listenKey']

    async def _keep_listen_key_alive(self):
        url = f"{self._base_api_url}/fapi/v1/listenKey"
        headers = {'X-MBX-APIKEY': self._api_key}
        while self._running:
            await asyncio.sleep(30 * 60) # Keep alive every 30 minutes
            try:
                async with self._aiohttp_session.put(url, headers=headers) as response:
                    if response.status == 200:
                        logger.info("Listen key kept alive.")
                    else:
                        logger.warning("Failed to keep listen key alive, will get new one on next reconnect.")
            except Exception as e:
                logger.error(f"Error keeping listen key alive: {e}")

    async def _main_loop(self):
        while self._running:
            try:
                self._listen_key = await self._get_listen_key()
                logger.info("Successfully obtained new listen key.")
                url = self._base_ws_url + self._listen_key
                
                async with websockets.connect(url) as ws:
                    self.ws = ws
                    logger.info("User Data Stream WebSocket connected.")
                    try:
                        async for msg in self.ws:
                            # --- ADDED DIAGNOSTIC LOGGING ---
                            logger.info("Received message on Private User Data Stream.")
                            data = json.loads(msg)
                            await self.on_message_callback(data)
                    except websockets.exceptions.ConnectionClosed as e:
                        logger.warning(f"User Data Stream WS connection closed: {e}. Reconnecting...")
                    except Exception as e:
                        logger.error(f"Error in User Data Stream WS message loop: {e}", exc_info=True)

            except Exception as e:
                logger.error(f"Failed to connect to User Data Stream WS: {e}. Retrying in 10s.")

            if self._running:
                await asyncio.sleep(10)

    def start(self):
        if not self._running:
            self._running = True
            self._tasks.append(asyncio.create_task(self._main_loop()))
            self._tasks.append(asyncio.create_task(self._keep_listen_key_alive()))
            logger.info(f"AsterdexWsClient started with {len(self._tasks)} background tasks.")

    async def stop(self):
        if self._running:
            self._running = False
            if self.ws:
                await self.ws.close()
            for task in self._tasks:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            self._tasks = []
            logger.info("AsterdexWsClient stopped.")

