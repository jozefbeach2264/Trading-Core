import logging
import httpx
import os
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

class ExchangeClient:
    """
    A dedicated client for interacting with the exchange's authenticated (private) API.
    It manages a persistent connection, handles authentication, and standardizes data fetching.
    """
    def __init__(self):
        """
        Initializes the ExchangeClient with a base URL and an httpx AsyncClient.
        """
        self.base_url = "https://fapi.asterdex.com/fapi/v1" # Example API base URL
        self.api_key = os.getenv("ASTERDEX_API_KEY")
        self.api_secret = os.getenv("ASTERDEX_API_SECRET")

        if not self.api_key or not self.api_secret:
            raise ValueError("ASTERDEX_API_KEY and ASTERDEX_API_SECRET must be set in secrets.")

        # The client will automatically handle headers for all requests
        headers = {
            "X-MBX-APIKEY": self.api_key
            # In a real Binance-like API, you would also add a signature to params/headers
        }

        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=10.0, headers=headers)
        logger.info("Authenticated ExchangeClient initialized.")

    async def _make_request(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        """A helper method to make and handle authenticated API requests."""
        # Here you would add your signature generation logic if required by the exchange
        # For example: params['signature'] = self._generate_signature(params)
        try:
            response = await self.client.get(endpoint, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            logger.error(f"HTTP RequestError for {e.request.url}: {e}")
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP StatusError for {e.request.url}: {e.response.status_code} - {e.response.text}")
        return None

    # --- Methods for pulling data needed by TradingCore ---
    async def get_klines(self, symbol: str, interval: str, limit: int) -> Optional[List[Any]]:
        return await self._make_request("/klines", {"symbol": symbol, "interval": interval, "limit": limit})

    async def get_premium_index(self, symbol: str) -> Optional[Dict[str, Any]]:
        return await self._make_request("/premiumIndex", {"symbol": symbol})

    async def get_depth(self, symbol: str, limit: int) -> Optional[Dict[str, Any]]:
        return await self._make_request("/depth", {"symbol": symbol, "limit": limit})
        
    async def get_book_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        return await self._make_request("/ticker/bookTicker", {"symbol": symbol})

    async def get_open_interest(self, symbol: str) -> Optional[Dict[str, Any]]:
        return await self._make_request("/openInterest", {"symbol": symbol})

    async def close(self):
        """Gracefully closes the httpx client session."""
        await self.client.aclose()
        logger.info("Authenticated ExchangeClient session closed.")

