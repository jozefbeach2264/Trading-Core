# TradingCore/exchange_client.py
import logging
import httpx
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

class ExchangeClient:
    """
    A dedicated client for interacting with the Asterdex exchange API.
    It manages a persistent connection and standardizes data fetching.
    """
    def __init__(self):
        """
        Initializes the ExchangeClient with a base URL and an httpx AsyncClient.
        """
        self.base_url = "https://fapi.asterdex.com/fapi/v1"
        # Using a persistent client is more efficient as it reuses connections.
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=10.0)
        logger.info("ExchangeClient initialized for base URL: %s", self.base_url)

    async def _make_request(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        """A helper method to make and handle API requests."""
        try:
            response = await self.client.get(endpoint, params=params)
            response.raise_for_status()  # Raises an exception for 4xx or 5xx status codes
            return response.json()
        except httpx.RequestError as e:
            logger.error("HTTP RequestError for %s: %s", e.request.url, e)
        except httpx.HTTPStatusError as e:
            logger.error("HTTP StatusError for %s: %s - %s", e.request.url, e.response.status_code, e.response.text)
        return None

    async def get_depth(self, symbol: str, limit: int) -> Optional[Dict[str, Any]]:
        return await self._make_request("/depth", {"symbol": symbol, "limit": limit})

    async def get_klines(self, symbol: str, interval: str, limit: int) -> Optional[List[Any]]:
        return await self._make_request("/klines", {"symbol": symbol, "interval": interval, "limit": limit})

    async def get_book_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        return await self._make_request("/ticker/bookTicker", {"symbol": symbol})

    async def get_recent_trades(self, symbol: str, limit: int) -> Optional[List[Dict[str, Any]]]:
        return await self._make_request("/trades", {"symbol": symbol, "limit": limit})

    async def get_premium_index(self, symbol: str) -> Optional[Dict[str, Any]]:
        return await self._make_request("/premiumIndex", {"symbol": symbol})

    async def get_open_interest(self, symbol: str) -> Optional[Dict[str, Any]]:
        return await self._make_request("/openInterest", {"symbol": symbol})

    async def close(self):
        """Gracefully closes the httpx client session."""
        await self.client.aclose()
        logger.info("ExchangeClient session closed.")

