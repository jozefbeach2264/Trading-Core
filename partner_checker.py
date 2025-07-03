import asyncio
import logging
import httpx
from typing import List, Tuple

from core import config

logger = logging.getLogger(__name__)

class PartnerChecker:
    """
    Performs continuous health checks (heartbeat) on all partner services.
    """
    def __init__(self, interval_seconds: int = 10):
        self.interval = interval_seconds
        self.partners: List[Tuple[str, str]] = []
        
        # Standardize on the /status endpoint for all health checks
        if config.neurosync_url:
            self.partners.append(("NeuroSync", f"{config.neurosync_url}/status"))
        if config.rolling5_url:
            self.partners.append(("Rolling5", f"{config.rolling5_url}/status"))
        
        self._client = httpx.AsyncClient(timeout=5.0)
        self.running = False
        self.task: Optional[asyncio.Task] = None
        logger.info(f"PartnerChecker initialized with a {self.interval}s interval.")

    async def _check_one(self, name: str, url: str):
        """Checks a single partner and logs the result."""
        try:
            response = await self._client.get(url)
            response.raise_for_status()
            data = response.json()
            if data.get("status") == "ok":
                # This log can be changed to logging.DEBUG to reduce noise later
                logger.info(f"Partner Health Check | {name}: OK")
            else:
                logger.warning(f"Partner Health Check | {name} Failed: Status was not 'ok'. Response: {data}")
        except httpx.RequestError as e:
            logger.warning(f"Partner Health Check | {name} Failed: ConnectionError to {e.request.url}.")
        except httpx.HTTPStatusError as e:
            logger.warning(f"Partner Health Check | {name} Failed: Received status {e.response.status_code}.")
        except Exception as e:
            logger.error(f"Partner Health Check | {name} Failed with unexpected error: {e}")

    async def _heartbeat_loop(self):
        """The main loop that runs checks at the specified interval."""
        while self.running:
            if self.partners:
                tasks = [self._check_one(name, url) for name, url in self.partners]
                await asyncio.gather(*tasks)
            await asyncio.sleep(self.interval)

    def start(self):
        """Starts the heartbeat loop in a background task."""
        if not self.running:
            self.running = True
            self.task = asyncio.create_task(self._heartbeat_loop())
            logger.info("PartnerChecker heartbeat started.")
    
    async def stop(self):
        """Stops the heartbeat loop gracefully."""
        if self.running:
            self.running = False
            if self.task:
                self.task.cancel()
                try:
                    await self.task
                except asyncio.CancelledError:
                    pass
            await self._client.aclose()
            logger.info("PartnerChecker heartbeat stopped.")

