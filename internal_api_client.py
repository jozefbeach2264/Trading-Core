import logging
import httpx
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class InternalApiClient:
    """
    A dedicated client for internal, service-to-service communication.
    Used by TradingCore to communicate with NeuroSync and Rolling5.
    """
    def __init__(self, config: Any):
        self.config = config
        self.client = httpx.AsyncClient(timeout=10.0)
        logger.info("InternalApiClient initialized.")

    async def get_volume_data_from_neurosync(self) -> Optional[Dict[str, Any]]:
        """Fetches the latest volume aggregate data from NeuroSync."""
        url = self.config.neurosync_volume_data_url
        if not url: return None
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to fetch volume data from NeuroSync: {e}")
            return None

    async def send_alert_to_bot(self, message: str, alert_level: str = "INFO"):
        """Sends a critical alert message to the Rolling5 bot."""
        url = self.config.rolling5_alert_url
        if not url:
            logger.warning("ROLLING5_ALERT_URL not configured. Cannot send alert.")
            return

        payload = {"message": message, "level": alert_level}
        try:
            response = await self.client.post(url, json=payload)
            response.raise_for_status()
            logger.info(f"Successfully sent alert to Rolling5 bot: '{message}'")
        except Exception as e:
            logger.error(f"Failed to send alert to Rolling5 bot: {e}")

    async def close(self):
        """Gracefully closes the httpx client."""
        await self.client.aclose()
