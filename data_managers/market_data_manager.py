import logging
import asyncio
import httpx
import websockets
import json
from typing import Dict, Any

from config.config import Config
from data_managers.market_state import MarketState

logger = logging.getLogger(__name__)

class MarketDataManager:
    """
    Manages the connection to the OKX data streams. It uses REST for an
    initial state snapshot and a single, robust WebSocket for all live public data.
    """
    def __init__(
        self,
        config: Config,
        market_state: MarketState,
        httpx_client: httpx.AsyncClient
    ):
        self.config = config
        self.market_state = market_state
        self.client = httpx_client
        self.is_running = False
        self._task: asyncio.Task = None
        
        # ✅ FINAL FIX: Using the standard public WebSocket URL for all channels.
        self.ws_url = "wss://ws.okx.com:8443/ws/v5/public"
        self.inst_id = f"{self.config.symbol.replace('USDT', '')}-USDT"
        logger.info(f"MarketDataManager configured for OKX with instrument ID: {self.inst_id}")

    async def _fetch_initial_state(self):
        """
        Fetches the complete initial market state via OKX REST API.
        """
        try:
            logger.info("Fetching initial state from OKX...")
            
            # ✅ FINAL FIX: Corrected the endpoint path for open interest.
            endpoints = {
                "klines": f"/api/v5/market/candles?instId={self.inst_id}&bar=1m&limit={self.config.kline_deque_maxlen}",
                "depth": f"/api/v5/market/books?instId={self.inst_id}&sz=50",
                "open_interest": f"/api/v5/public/open-interest?instId={self.inst_id}"
            }
            
            tasks = [self.client.get(url) for url in endpoints.values()]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            responses = dict(zip(endpoints.keys(), results))

            # Process all responses
            if isinstance(responses.get("klines"), httpx.Response) and responses["klines"].status_code == 200:
                await self.market_state.update_klines(responses["klines"].json().get("data", []))
            
            if isinstance(responses.get("depth"), httpx.Response) and responses["depth"].status_code == 200:
                book_data = responses["depth"].json().get("data", [])
                if book_data: await self.market_state.update_depth_20(book_data[0])

            if isinstance(responses.get("open_interest"), httpx.Response) and responses["open_interest"].status_code == 200:
                oi_data = responses["open_interest"].json().get("data", [])
                if oi_data: await self.market_state.update_open_interest(oi_data[0])

            logger.info("Initial state fetched successfully from OKX.")
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching initial state from OKX: {e.response.text}")
        except Exception as e:
            logger.error(f"Error fetching initial state from OKX: {e}", exc_info=True)

    async def _websocket_handler(self):
        """
        Connects to the single OKX public WebSocket and handles all incoming data.
        """
        await self._fetch_initial_state()
        
        # ✅ FINAL FIX: All subscriptions go to the single public endpoint.
        # 'candle1m' is the correct channel name.
        ws_payload = {
            "op": "subscribe",
            "args": [
                {"channel": "candle1m", "instId": self.inst_id},
                {"channel": "trades", "instId": self.inst_id},
                {"channel": "books", "instId": self.inst_id},
                {"channel": "books5", "instId": self.inst_id},
                {"channel": "tickers", "instId": self.inst_id},
                {"channel": "mark-price", "instId": self.inst_id}
            ]
        }
        
        while self.is_running:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    logger.info("MarketDataManager connected to OKX WebSocket.")
                    await ws.send(json.dumps(ws_payload))
                    
                    while self.is_running:
                        message = await ws.recv()
                        if message == 'pong':
                            try:
                                await ws.send('ping')
                            except websockets.exceptions.ConnectionClosed:
                                break
                            continue
                        
                        data = json.loads(message)

                        if "event" in data:
                            if data.get("event") == "error":
                                logger.error(f"OKX WebSocket error: {data.get('msg')}")
                            continue

                        if "arg" in data and "data" in data:
                            await self._route_ws_data(data)
                            
            except websockets.exceptions.ConnectionClosed:
                logger.warning("OKX WebSocket connection closed. Reconnecting in 5s...")
            except Exception as e:
                logger.error(f"OKX WebSocket error: {e}", exc_info=True)
            finally:
                if self.is_running:
                    await asyncio.sleep(5)

    async def _route_ws_data(self, data: Dict):
        """Routes incoming WebSocket data to the correct MarketState method."""
        channel = data.get("arg", {}).get("channel")
        event_data_list = data.get("data", [])
        
        if not channel or not event_data_list:
            return

        for event_data in event_data_list:
            if channel == "candle1m":  # ✅ FIXED
                await self.market_state.update_from_ws_kline(event_data)
            elif channel == "trades":
                await self.market_state.update_from_ws_agg_trade(event_data)
            elif channel == "books":
                await self.market_state.update_from_ws_books(event_data)
            elif channel == "books5":
                await self.market_state.update_from_ws_books5(event_data)
            elif channel == "tickers":
                await self.market_state.update_from_ws_book_ticker(event_data)
            elif channel == "mark-price":
                await self.market_state.update_from_ws_mark_price(event_data)

    async def start(self):
        if not self.is_running:
            self.is_running = True
            self._task = asyncio.create_task(self._websocket_handler())
            logger.info("MarketDataManager started.")

    async def stop(self):
        if self.is_running and self._task:
            self.is_running = False
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("MarketDataManager stopped.")