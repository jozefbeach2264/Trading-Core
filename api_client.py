# api_client.py
import time
import hmac
import hashlib
import requests

class ApiClient:
    """
    A dedicated client to handle all signed API requests to the exchange.
    This consolidates logic from all the old request/auth/fetcher files.
    """
    
    def __init__(self, config):
        self.base_url = "https://fapi.asterdex.com"
        self.api_key = config.api_key
        self.secret_key = config.secret_key
        self.uid = config.uid
        print("ApiClient: Initialized.")

    def _generate_signature(self, params: dict) -> str:
        """Creates the required SHA256 signature for a request."""
        query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
        return hmac.new(
            self.secret_key.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

    def _send_request(self, method: str, endpoint: str, params: dict = None):
        """Builds and sends the signed request, handling errors."""
        if params is None:
            params = {}
            
        params["timestamp"] = int(time.time() * 1000)
        params["uid"] = self.uid
        params["signature"] = self._generate_signature(params)
        
        headers = {"X-API-KEY": self.api_key}
        url = f"{self.base_url}{endpoint}"
        
        try:
            if method.upper() == "GET":
                response = requests.get(url, headers=headers, params=params, timeout=10)
            elif method.upper() == "POST":
                response = requests.post(url, headers=headers, data=params, timeout=10)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"ApiClient: Request to {endpoint} failed: {e}")
            return None

    # --- Public Methods ---
    # Other modules will call these simple, clean methods.

    def get_klines(self, symbol="ETHUSDT", interval="1m", limit=100):
        """Fetches Kline/candlestick data."""
        return self._send_request("GET", "/fapi/v1/indexPriceKlines", {
            "pair": symbol,
            "interval": interval,
            "limit": limit
        })

    def place_order(self, symbol: str, side: str, order_type: str, quantity: float):
        """Places a new order."""
        return self._send_request("POST", "/fapi/v1/order", {
            "symbol": symbol,
            "side": side.upper(),    # e.g., "BUY" or "SELL"
            "type": order_type.upper(), # e.g., "MARKET" or "LIMIT"
            "quantity": quantity
        })

    def get_server_time(self):
        """Fetches the exchange's server time to check connectivity."""
        return self._send_request("GET", "/fapi/v1/time")


