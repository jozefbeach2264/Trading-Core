# TradingCore/system_managers/partner_checker.py
import asyncio
import logging
import httpx
from typing import List, Tuple, Optional
from config.config import Config

logger = logging.getLogger(__name__)

class PartnerChecker:
    def __init__(self, config: Config, client: httpx.AsyncClient, interval_seconds: int = 10):
        self.interval = interval_seconds
        self.partners: List[Tuple[str, str]] = []
        if config.neurosync_url:
            self.partners.append(("NeuroSync", f"{config.neurosync_url}/status"))
        if config.rolling5_url:
            self.partners.append(("Rolling5", f"{config.rolling5_url}/status"))
        self._client = client # Uses the shared client
        self.running = False
        self.task: Optional[asyncio.Task] = None
        logger.info(f"PartnerChecker initialized with a {self.interval}s interval.")

    async def _check_one(self, name: str, url: str):
        try:
            response = await self._client.get(url, timeout=5.0)
            response.raise_for_status()
            data = response.json()
            if data.get("status") == "ok":
                logger.info(f"Partner Health | {name}: OK")
            else:
                logger.warning(f"Partner Health | {name}: FAILED (Status not 'ok')")
        except Exception:
            logger.warning(f"Partner Health | {name}: FAILED (Connection Error or Invalid Response)")

    async def _heartbeat_loop(self):
        while self.running:
            if self.partners:
                await asyncio.gather(*[self._check_one(name, url) for name, url in self.partners])
            await asyncio.sleep(self.interval)

    def start(self):
        if not self.running:
            self.running = True
            self.task = asyncio.create_task(self._heartbeat_loop())
            logger.info("PartnerChecker heartbeat started.")
    
    async def stop(self):
        if self.running:
            self.running = False
            if self.task: self.task.cancel()
            logger.info("PartnerChecker heartbeat stopped.")
