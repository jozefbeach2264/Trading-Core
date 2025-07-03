import asyncio
import logging
import httpx
import aiohttp
import time
from typing import Dict, Any, Callable

from config.config import Config
from data_managers.market_state import MarketState
from data_managers.asterdex_client import AsterdexWsClient
from data_managers.market_data_ws_client import MarketDataWsClient

logger = logging.getLogger(__name__)

class MarketDataManager:
    def __init__(
        self, 
        config: Config, 
        aiohttp_session: aiohttp.ClientSession, 
        httpx_client: httpx.AsyncClient
    ):
        self._config = config
        self.market_state = MarketState(symbol=self._config.symbol, config=self._config)
        
        self.user_ws_client = AsterdexWsClient(
            api_key=self._config.asterdex_api_key,
            on_message_callback=self._handle_user_ws_message,
            session=aiohttp_session
        )
        
        self.market_ws_client = MarketDataWsClient(
            symbol=self._config.symbol,
            on_message_callback=self._handle_market_ws_message
        )
        
        self.running = False
        self._tasks: list[asyncio.Task] = []
        self._rest_client = httpx_client
        self._base_rest_url = "https://fapi.asterdex.com"

    async def _handle_user_ws_message(self, data: dict):
        event_type = data.get('e')
        if event_type == 'ACCOUNT_UPDATE':
            if hasattr(self.market_state, 'update_account'):
                await self.market_state.update_account(data.get('a', {}))
        elif event_type == 'ORDER_TRADE_UPDATE':
            if hasattr(self.market_state, 'update_order'):
                await self.market_state.update_order(data.get('o', {}))

    async def _handle_market_ws_message(self, stream: str, data: dict):
        if "@depth" in stream:
            await self.market_state.update_from_ws_depth(data)
        elif "@aggTrade" in stream:
            await self.market_state.update_from_ws_agg_trade(data)
        elif "@kline" in stream:
            await self.market_state.update_from_ws_kline(data)
        elif "@bookTicker" in stream:
            await self.market_state.update_from_ws_book_ticker(data)
        elif "@markPrice" in stream:
            await self.market_state.update_from_ws_mark_price(data)

    async def _oi_polling_loop(self):
        """Polls for the CURRENT Open Interest value."""
        url = f"{self._base_rest_url}/fapi/v1/openInterest?symbol={self._config.symbol}"
        while self.running:
            try:
                response = await self._rest_client.get(url, timeout=5.0)
                response.raise_for_status()
                await self.market_state.update_open_interest(response.json())
            except Exception:
                pass
            await asyncio.sleep(3) # Polls every 3 seconds

    # --- NEW POLLING LOOP ADDED ---
    async def _oi_history_polling_loop(self):
        """Polls for HISTORICAL Open Interest data for the display."""
        url = f"{self._base_rest_url}/fapi/v1/openInterestHist?symbol={self._config.symbol}&period=5m&limit=30"
        while self.running:
            try:
                response = await self._rest_client.get(url, timeout=5.0)
                response.raise_for_status()
                # The updater for OI history needs to be async
                if hasattr(self.market_state, 'update_oi_history'):
                    await self.market_state.update_oi_history(response.json())
            except Exception:
                pass
            await asyncio.sleep(15) # History doesn't need to be fetched as often

    def start(self):
        if self.running:
            return
        logger.info("Starting MarketDataManager with WebSocket-first architecture...")
        self.running = True
        self.user_ws_client.start()
        self.market_ws_client.start()
        # Add both OI polling tasks to the background tasks
        self._tasks.append(asyncio.create_task(self._oi_polling_loop()))
        self._tasks.append(asyncio.create_task(self._oi_history_polling_loop()))

    async def stop(self):
        if not self.running:
            return
        self.running = False
        await self.user_ws_client.stop()
        await self.market_ws_client.stop()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        logger.info("MarketDataManager stopped.")

