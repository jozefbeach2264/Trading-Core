import logging
import asyncio
import httpx
import websockets
import json
from typing import Dict, List, Any
from config.config import Config
from data_managers.market_state import MarketState
from reconstructors.candle_reconstructor import CandleReconstructor

logger = logging.getLogger(__name__)

class MarketDataManager:
    def __init__(self, config: Config, market_state: MarketState, httpx_client: httpx.AsyncClient):
        self.config = config
        self.market_state = market_state
        self.client = httpx_client
        self.is_running = False
        self._task: asyncio.Task = None
        self._subscribed_channels = set()
        self.ws_url = "wss://ws.okx.com:8443/ws/v5/public"
        self.inst_id = self.config.trading_symbol
        self.candle_reconstructor = CandleReconstructor()
        logger.debug(f"MarketDataManager configured for OKX with instrument ID: {self.inst_id}")

    async def _validate_inst_id(self):
        endpoint = "https://www.okx.com/api/v5/public/instruments"
        params = {"instType": "SWAP", "instId": self.inst_id}
        try:
            response = await self.client.get(endpoint, params=params)
            response.raise_for_status()
            data = response.json()
            if data.get("code") != "0" or not data.get("data"):
                logger.error("Invalid instId", extra={"instId": self.inst_id, "response": data.get('msg', 'Unknown error')})
                raise ValueError(f"Invalid instId: {self.inst_id}")
            logger.debug(f"Validated instId: {self.inst_id}")
        except Exception as e:
            logger.error(f"Failed to validate instId {self.inst_id}", extra={"error": str(e)}, exc_info=True)
            raise

    async def _fetch_initial_data(self):
        # Fetch historical klines
        klines_endpoint = "https://www.okx.com/api/v5/market/history-candles"
        klines_params = {"instId": self.inst_id, "bar": "1m", "limit": str(self.config.kline_deque_maxlen)}
        try:
            response = await self.client.get(klines_endpoint, params=klines_params)
            response.raise_for_status()
            data = response.json()
            if data.get("code") == "0" and data.get("data"):
                await self.market_state.update_klines(data["data"])
                logger.info(f"Fetched {len(data['data'])} historical klines.")
            else:
                logger.error("Failed to fetch klines", extra={"response": data.get('msg')})
        except Exception as e:
            logger.error("Error fetching historical klines", extra={"error": str(e)}, exc_info=True)

        # Fetch initial order book snapshot
        books_endpoint = "https://www.okx.com/api/v5/market/books"
        books_params = {"instId": self.inst_id, "sz": "20"}
        try:
            response = await self.client.get(books_endpoint, params=books_params)
            response.raise_for_status()
            data = response.json()
            if data.get("code") == "0" and data.get("data"):
                await self.market_state.update_from_ws_books(data["data"][0])
                logger.info("Fetched initial order book snapshot.")
            else:
                logger.error("Failed to fetch order book", extra={"response": data.get('msg')})
        except Exception as e:
            logger.error("Error fetching order book", extra={"error": str(e)}, exc_info=True)

        # --- NEW: Fetch initial mark price via REST ---
        mark_price_endpoint = "https://www.okx.com/api/v5/public/mark-price"
        mark_price_params = {"instType": "SWAP", "instId": self.inst_id}
        try:
            response = await self.client.get(mark_price_endpoint, params=mark_price_params)
            response.raise_for_status()
            data = response.json()
            if data.get("code") == "0" and data.get("data"):
                mark_px_data = data["data"][0]
                await self.market_state.update_from_ws_mark_price(mark_px_data)
                logger.info(f"Fetched initial mark price: {mark_px_data.get('markPx')}")
            else:
                logger.error("Failed to fetch initial mark price", extra={"response": data.get('msg')})
        except Exception as e:
            logger.error("Error fetching initial mark price", extra={"error": str(e)}, exc_info=True)


        # Signal that initial data is ready
        self.market_state.initial_data_ready.set()
        logger.info("Initial data ready event has been set.")

    async def _route_ws_data(self, data: Dict):
        """Routes incoming WebSocket data to the appropriate MarketState update method."""
        channel = data.get("arg", {}).get("channel")
        event_data_list = data.get("data", [])

        if not channel or not event_data_list:
            logger.debug("Invalid WebSocket data packet received", extra={"data": data})
            return

        for event_data in event_data_list:
            if channel not in self._subscribed_channels:
                continue
            
            if channel == "trades":
                try:
                    completed_candle = self.candle_reconstructor.process_trade(event_data)
                    if completed_candle:
                        await self.market_state.update_from_ws_kline(completed_candle)
                    
                    live_candle = self.candle_reconstructor.get_live_candle()
                    if live_candle:
                        await self.market_state.update_live_reconstructed_candle(live_candle)

                    await self.market_state.update_from_ws_agg_trade(event_data)
                except Exception as e:
                    logger.error("Error processing trade data", extra={"error": str(e)}, exc_info=True)

            elif channel == "books":
                try:
                    if not event_data.get('bids') or not event_data.get('asks'):
                        logger.debug("Empty books update received", extra={"data": event_data})
                        return
                    await self.market_state.update_from_ws_books(event_data)
                except Exception as e:
                    logger.error("Error processing book data", extra={"error": str(e)}, exc_info=True)

            elif channel == "tickers":
                try:
                    await self.market_state.update_from_ws_book_ticker(event_data)
                    mark_px = event_data.get("markPx")
                    if mark_px:
                        await self.market_state.update_from_ws_mark_price({"markPx": float(mark_px)})
                except Exception as e:
                    logger.error("Error processing ticker data", extra={"error": str(e)}, exc_info=True)
            
            elif channel == "mark-price":
                try:
                    mark_px = event_data.get("markPx")
                    if mark_px:
                        await self.market_state.update_from_ws_mark_price({"markPx": float(mark_px)})
                except Exception as e:
                    logger.error("Error processing mark-price data", extra={"error": str(e)}, exc_info=True)

    async def _websocket_handler(self):
        ws_payload = {
            "op": "subscribe",
            "args": [
                {"channel": "trades", "instId": self.inst_id},
                {"channel": "books", "instId": self.inst_id},
                {"channel": "tickers", "instId": self.inst_id},
                {"channel": "mark-price", "instId": self.inst_id}
            ]
        }
        while self.is_running:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    logger.info("Connected to OKX WebSocket.")
                    await ws.send(json.dumps(ws_payload))
                    while self.is_running:
                        try:
                            message = await asyncio.wait_for(ws.recv(), timeout=30)
                            if message == 'pong':
                                continue
                            
                            data = json.loads(message)
                            
                            if data.get("event") == "subscribe":
                                self._subscribed_channels = {arg["channel"] for arg in ws_payload["args"]}
                                logger.info("Subscribed to WebSocket channels", extra={"channels": list(self._subscribed_channels)})
                            elif data.get("event") == "error":
                                logger.error("WebSocket subscription error", extra={"error_data": data})
                            elif "data" in data:
                                await self._route_ws_data(data)
                        except asyncio.TimeoutError:
                            await ws.send('ping')
                        except websockets.exceptions.ConnectionClosed:
                            logger.warning("WebSocket connection closed. Reconnecting...")
                            break

            except Exception as e:
                logger.error("WebSocket connection error", extra={"error": str(e)}, exc_info=True)
                self._subscribed_channels.clear()
                await asyncio.sleep(5)

    async def start(self):
        if not self.is_running:
            self.is_running = True
            await self._validate_inst_id()
            asyncio.create_task(self._fetch_initial_data())
            self._task = asyncio.create_task(self._websocket_handler())
            logger.info("MarketDataManager started.")

    async def stop(self):
        if self.is_running and self._task:
            self.is_running = False
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                logger.info("MarketDataManager stopped.")
            self._task = None
