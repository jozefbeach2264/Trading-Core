import logging
import httpx
from typing import Dict, Any

from config.config import Config

logger = logging.getLogger(__name__)

class InternalApiClient:
    """
    Handles HTTP communication between TradingCore and other internal services like NeuroSync.
    """
    def __init__(self, config: Config):
        self.config = config
        self.client = httpx.AsyncClient(timeout=5.0)
        logger.info("InternalApiClient initialized.")

    async def get_volume_data_from_neurosync(self) -> Dict[str, Any]:
        """Fetches the latest aggregated volume data from the NeuroSync service."""
        try:
            response = await self.client.get(self.config.neurosync_volume_data_url)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            logger.error(f"Could not connect to NeuroSync to get volume data: {e}")
            return {}
        except Exception as e:
            logger.error(f"Error fetching/parsing volume data from NeuroSync: {e}")
            return {}

    async def close(self):
        """Closes the HTTP client session."""
        await self.client.aclose()
