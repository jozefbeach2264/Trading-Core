# TradingCore/api_client.py (Updated)
import time
import hmac
import hashlib
import httpx

class ApiClient:
    """Handles all authenticated communication with the Asterdex exchange."""
    BASE_URL = "https://fapi.asterdex.com"

    def __init__(self, config):
        self.api_key = config.api_key
        self.secret_key = config.secret_key
        self.uid = config.uid
        self.client = httpx.AsyncClient(base_url=self.BASE_URL)
        print("ApiClient Initialized.")

    def _get_signature(self, params_str: str) -> str:
        """Creates the required SHA256 signature for a request."""
        return hmac.new(
            self.secret_key.encode('utf-8'),
            params_str.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    async def _make_request(self, method: str, endpoint: str, params: dict = None):
        """A generic, signed request-making function."""
        if params is None:
            params = {}
        
        timestamp = str(int(time.time() * 1000))
        params.update({"timestamp": timestamp, "uid": self.uid})
        
        params_str = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
        signature = self._get_signature(params_str)
        
        headers = {
            "X-API-KEY": self.api_key,
            "X-SIGNATURE": signature,
            "X-TIMESTAMP": timestamp,
            "X-UID": self.uid
        }

        try:
            if method.upper() == "GET":
                response = await self.client.get(endpoint, params=params, headers=headers)
            else:
                # Add POST, etc. here if needed later
                raise NotImplementedError
            
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            print(f"ApiClient Error: {e.response.status_code} on {e.request.url} - {e.response.text}")
        except httpx.RequestError as e:
            print(f"ApiClient Request Error on {e.request.url}: {e}")
        return None

    # --- Methods for fetching specific data types ---

    async def get_klines(self, symbol: str = "ETHUSDT", interval: str = "1m", limit: int = 1):
        return await self._make_request("GET", "/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": str(limit)})

    async def get_ticker_price(self, symbol: str = "ETHUSDT"):
        return await self._make_request("GET", "/fapi/v1/ticker/price", {"symbol": symbol})

    async def get_premium_index(self, symbol: str = "ETHUSDT"):
        return await self._make_request("GET", "/fapi/v1/premiumIndex", {"symbol": symbol})
        
    async def get_funding_rate(self, symbol: str = "ETHUSDT"):
        # Note: Funding rate is often part of the premium index call.
        return await self.get_premium_index(symbol)

    async def get_open_interest(self, symbol: str = "ETHUSDT"):
         return await self._make_request("GET", "/fapi/v1/openInterest", {"symbol": symbol})

    async def get_order_book(self, symbol: str = "ETHUSDT", limit: int = 10):
        # limit=10 gets 10 layers up and 10 down
        return await self._make_request("GET", "/fapi/v1/depth", {"symbol": symbol, "limit": str(limit)})

    # Placeholder for data types not available via simple REST endpoints
    async def get_long_short_ratio(self, symbol: str = "ETHUSDT"):
        print("WARN: Long/Short Ratio data source not yet implemented.")
        return None 
    
    async def get_liquidation_map(self, symbol: str = "ETHUSDT"):
        print("WARN: Liquidation Map data source not yet implemented.")
        return None

    async def close(self):
        await self.client.aclose()

