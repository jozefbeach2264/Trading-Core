import logging
import httpx
from typing import Dict, Any

from config.config import Config

logger = logging.getLogger(__name__)

class AIClient:
    """
    Handles sending requests to the external AI provider and returning the verdict.
    """
    def __init__(self, config: Config):
        self.config = config
        headers = {"Authorization": f"Bearer {self.config.ai_provider_api_key}"}
        
        # The httpx client is configured with the URL, headers, and timeout from the config file
        self.client = httpx.AsyncClient(
            base_url=self.config.ai_provider_url,
            headers=headers,
            timeout=self.config.ai_client_timeout
        )
        logger.info(f"AIClient initialized for URL: {self.config.ai_provider_url}")

    async def get_ai_verdict(self, report: Dict[str, Any]) -> Dict[str, Any]:
        """Sends the Pre-Analysis Report to the AI and returns its decision."""
        try:
            logger.info("Sending Pre-Analysis Report to AI provider...")
            # The endpoint name "/adjudicate" is assumed, but could be configured.
            response = await self.client.post("/adjudicate", json=report)
            response.raise_for_status() # Raises an exception for 4xx or 5xx status codes
            logger.info("Received verdict from AI provider.")
            return response.json()
            
        except httpx.TimeoutException:
            logger.error("Request to AI provider timed out.")
            return {"verdict": "NO GO", "reasoning": "AI provider request timed out."}
        except httpx.RequestError as e:
            logger.error(f"Could not connect to AI provider: {e}")
            return {"verdict": "NO GO", "reasoning": "AI provider connection error."}
        except Exception as e:
            logger.error(f"An unexpected error occurred with AI provider: {e}", exc_info=True)
            return {"verdict": "NO GO", "reasoning": "A general error occurred with the AI provider."}

    async def close(self):
        """Closes the HTTP client session."""
        await self.client.aclose()
        logger.info("AIClient session closed.")
