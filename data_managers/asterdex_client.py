import asyncio
import logging
import aiohttp
from typing import Callable, Optional, List

logger = logging.getLogger(__name__)

class AsterdexWsClient:
    _REST_BASE_URL = "https://fapi.asterdex.com"
    _WS_BASE_URL = "wss://fstream.asterdex.com/ws/"

    def __init__(self, api_key: str, on_message_callback: Callable, session: aiohttp.ClientSession):
        self.api_key = api_key
        self.on_message_callback = on_message_callback
        self.session = session
        self.listen_key: Optional[str] = None
        self._tasks: List[asyncio.Task] = []
        self.running = False

    async def _get_listen_key(self) -> Optional[str]:
        url = f"{self._REST_BASE_URL}/fapi/v1/listenKey"
        headers = {'X-MBX-APIKEY': self.api_key}
        try:
            async with self.session.post(url, headers=headers, timeout=10) as response:
                response.raise_for_status()
                data = await response.json()
                key = data.get('listenKey')
                if key:
                    logger.info("Successfully obtained new listen key.")
                    return key
        except Exception as e:
            logger.error("Error getting listen key: %s", e)
        return None

    async def _keep_listen_key_alive(self):
        url = f"{self._REST_BASE_URL}/fapi/v1/listenKey"
        headers = {'X-MBX-APIKEY': self.api_key}
        while self.running:
            try:
                await asyncio.sleep(30 * 60) # Sleep for 30 minutes
                if self.listen_key and not self.session.closed:
                        await self.session.put(url, headers=headers, timeout=10)
            except asyncio.CancelledError:
                # This is expected on shutdown, break the loop
                break
            except Exception as e:
                logger.warning("Failed to send listen key keep-alive: %s", e)


    async def _connection_loop(self):
        while self.running:
            self.listen_key = await self._get_listen_key()
            if not self.listen_key:
                await asyncio.sleep(20)
                continue
            
            ws_url = self._WS_BASE_URL + self.listen_key
            try:
                async with self.session.ws_connect(ws_url, heartbeat=30) as ws:
                    logger.info("User Data Stream WebSocket connected.")
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self.on_message_callback(msg.json())
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            break
            except asyncio.CancelledError:
                break # Expected on shutdown
            except Exception:
                # A_E: Removed detailed exception logging to reduce spam, just log reconnect
                pass
            
            if not self.running:
                break

            logger.info("WebSocket disconnected. Reconnecting in 10 seconds.")
            await asyncio.sleep(10)

    def start(self):
        if not self.running:
            self.running = True
            # Create tasks individually and store them
            self._tasks.append(asyncio.create_task(self._connection_loop()))
            self._tasks.append(asyncio.create_task(self._keep_listen_key_alive()))
            logger.info("AsterdexWsClient started with %d background tasks.", len(self._tasks))

    async def stop(self):
        if self.running:
            self.running = False
            # Cancel all running tasks for this client
            for task in self._tasks:
                if not task.done():
                    task.cancel()
            
            # Wait for all tasks to acknowledge cancellation
            if self._tasks:
                await asyncio.gather(*self._tasks, return_exceptions=True)
            
            self._tasks.clear()
            logger.info("AsterdexWsClient stopped.")
