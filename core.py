# core.py

import asyncio
import logging
import os
from typing import Dict, Any, List

from dotenv import load_dotenv

# Load environment variables from a .env file
load_dotenv()
logger = logging.getLogger(__name__)

class Config:
    """
    Manages all configuration for the TradingCore application by loading
    from environment variables.
    """
    def __init__(self):
        self.symbol: str = os.getenv("TRADING_SYMBOL", "ETHUSDT")
        self.asterdex_api_key: str = os.getenv("ASTERDEX_API_KEY")
        self.asterdex_api_secret: str = os.getenv("ASTERDEX_API_SECRET")

        # ✅ Added URLs for external services
        self.NEUROSYNC_URL: str = os.getenv("NEUROSYNC_URL", "http://127.0.0.1:8001")
        self.ROLLING5_URL: str = os.getenv("ROLLING5_URL", "http://127.0.0.1:8002")
        
        # ✅ Add the missing tradingcore_url attribute and related URLs
        self.tradingcore_url: str = os.getenv("TRADINGCORE_URL", "http://default-tradingcore-url.com")
        self.neurosync_url: str = os.getenv("NEUROSYNC_URL", "http://default-neurosync-url.com")
        self.rolling5_url: str = os.getenv("ROLLING5_URL", "http://default-rolling5-url.com")

        if not self.asterdex_api_key or not self.asterdex_api_secret:
            error_msg = "Critical Error: ASTERDEX_API_KEY or ASTERDEX_API_SECRET not found in environment variables."
            logger.critical(error_msg)
            raise ValueError(error_msg)

        logger.info("Configuration loaded successfully for symbol: %s", self.symbol)

# Instantiate a global config object for the application
config = Config()


class MarketState:
    """
    A thread-safe class to hold and manage the real-time state of the market
    and the user's account for a single symbol.
    """
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.lock = asyncio.Lock()

        # --- Market Data ---
        self.order_book: Dict[str, List] = {"bids": [], "asks": []}
        self.klines: List[List[Any]] = []
        self.book_ticker: Dict[str, Any] = {}
        self.open_interest_history: List[Dict[str, Any]] = []
        self.premium_index: Dict[str, Any] = {}
        self.ticker_24hr: Dict[str, Any] = {}
        self.force_orders: List[Dict[str, Any]] = []
        self.funding_rate_history: List[Dict[str, Any]] = []
        
        # --- User Data (from authenticated stream) ---
        self.balances: Dict[str, Dict[str, Any]] = {}
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.open_orders: Dict[str, Dict[str, Any]] = {}

        logger.info("MarketState for symbol %s initialized.", self.symbol)

    # --- Update methods for REST Polling ---
    async def update_order_book(self, data: Dict[str, Any]):
        async with self.lock:
            self.order_book['bids'] = data.get('bids', [])
            self.order_book['asks'] = data.get('asks', [])

    async def update_klines(self, data: List[List[Any]]):
        async with self.lock:
            if isinstance(data, list):
                self.klines = data

    async def update_book_ticker(self, data: Dict[str, Any]):
        async with self.lock:
            if isinstance(data, dict):
                self.book_ticker = data

    async def update_open_interest_history(self, data: List[Dict[str, Any]]):
        async with self.lock:
            if isinstance(data, list):
                self.open_interest_history = data

    async def update_premium_index(self, data: Dict[str, Any]):
        async with self.lock:
            if isinstance(data, dict):
                self.premium_index = data

    async def update_ticker_24hr(self, data: Dict[str, Any]):
        async with self.lock:
            if isinstance(data, dict):
                self.ticker_24hr = data
    
    async def update_force_orders(self, data: List[Dict[str, Any]]):
        async with self.lock:
            if isinstance(data, list):
                self.force_orders = data
    
    async def update_funding_rate_history(self, data: List[Dict[str, Any]]):
        async with self.lock:
            if isinstance(data, list):
                self.funding_rate_history = data

    # --- Update methods for WebSocket Stream ---
    async def update_account(self, data: Dict[str, Any]):
        async with self.lock:
            for balance_data in data.get("B", []):
                asset = balance_data.get("a")
                if asset:
                    self.balances[asset] = balance_data
            
            for position_data in data.get("P", []):
                symbol = position_data.get("s")
                if symbol:
                    self.positions[symbol] = position_data

    async def update_order(self, data: Dict[str, Any]):
        async with self.lock:
            order_id = data.get("i")
            if not order_id:
                return

            order_status = data.get("X")
            
            if order_status in ["CANCELED", "FILLED", "EXPIRED", "REJECTED"]:
                self.open_orders.pop(str(order_id), None)
            else:
                self.open_orders[str(order_id)] = data