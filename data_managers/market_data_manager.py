import logging
import asyncio
import httpx
import websockets
import json
from typing import Dict

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
        self._books_update_count = 0
        self._last_bid_count = 0
        self._last_ask_count = 0
        self._subscribed_channels = set()
        
        self.ws_url = "wss://ws.okx.com:8443/ws/v5/public"
        self.inst_id = "ETH-USDT-SWAP"
        self.candle_reconstructor = CandleReconstructor()
        logger.info(f"MarketDataManager configured for OKX with instrument ID: {self.inst_id}")

    async def _validate_inst_id(self):
        endpoint = "https://www.okx.com/api/v5/public/instruments"
        params = {"instType": "SWAP", "instId": self.inst_id}
        try:
            response = await self.client.get(endpoint, params=params)
            response.raise_for_status()
            data = response.json()
            if data.get("code") != "0" or not data.get("data"):
                logger.error(f"Invalid instId: {self.inst_id}. OKX response: {data.get('msg', 'Unknown error')}")
                raise ValueError(f"Invalid instId: {self.inst_id}")
            logger.info(f"Validated instId: {self.inst_id}")
        except Exception as e:
            logger.error(f"Failed to validate instId {self.inst_id}: {e}", exc_info=True)
            raise

    async def _fetch_historical_klines(self):
        required_candles = 50
        max_retries = 5

        endpoint = "https://www.okx.com/api/v5/market/history-candles"
        params = {
            "instId": self.inst_id,
            "bar": "1m",
            "limit": str(required_candles)
        }
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"Attempt {attempt}/{max_retries} to fetch historical klines")
                response = await self.client.get(endpoint, params=params)
                response.raise_for_status()
                data = response.json()
                if data.get("code") != "0" or not data.get("data"):
                    logger.error(f"Failed to fetch klines: {data.get('msg', 'Unknown error')}")
                    await asyncio.sleep(2)
                    continue
                klines = data["data"]
                await self.market_state.update_klines(klines)
                logger.info(f"Updated MarketState with {len(self.market_state.klines)} klines")
                break
            except Exception as e:
                logger.error(f"Kline fetch attempt {attempt} failed: {e}", exc_info=True)
                await asyncio.sleep(2)

        endpoint = "https://www.okx.com/api/v5/market/books"
        params = {"instId": self.inst_id, "sz": "20"}
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"Attempt {attempt}/{max_retries} to fetch order book")
                response = await self.client.get(endpoint, params=params)
                response.raise_for_status()
                data = response.json()
                if data.get("code") != "0" or not data.get("data"):
                    logger.error(f"Failed to fetch order book: {data.get('msg', 'Unknown error')}")
                    await asyncio.sleep(2)
                    continue
                order_book = data["data"][0]
                await self.market_state.update_depth_20(order_book)
                self._last_bid_count = len(order_book.get('bids', []))
                self._last_ask_count = len(order_book.get('asks', []))
                break
            except Exception as e:
                logger.error(f"Order book fetch attempt {attempt} failed: {e}", exc_info=True)
                await asyncio.sleep(2)

        endpoint = "https://www.okx.com/api/v5/market/ticker"
        params = {"instId": self.inst_id}
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"Attempt {attempt}/{max_retries} to fetch initial mark price via ticker")
                response = await self.client.get(endpoint, params=params)
                response.raise_for_status()
                data = response.json()
                if data.get("code") != "0" or not data.get("data"):
                    logger.error(f"Failed to fetch ticker: {data.get('msg', 'Unknown error')}")
                    await asyncio.sleep(2)
                    continue
                mark_px = float(data["data"][0].get("markPx", data["data"][0]["last"]))
                await self.market_state.update_from_ws_mark_price({"markPx": mark_px})
                logger.info(f"Initialized mark price via ticker: {mark_px}")
                break
            except Exception as e:
                logger.error(f"Mark price fetch via ticker failed: {e}", exc_info=True)
                await asyncio.sleep(2)

        await asyncio.sleep(1)

    async def _websocket_handler(self):
        ws_payload = {
            "op": "subscribe",
            "args": [
                {"channel": "trades", "instId": self.inst_id},
                {"channel": "books", "instId": self.inst_id},
                {"channel": "tickers", "instId": self.inst_id}
            ]
        }

        while self.is_running:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    logger.info("Connected to OKX WebSocket.")
                    await ws.send(json.dumps(ws_payload))

                    while self.is_running:
                        message = await ws.recv()
                        if message == 'pong':
                            await ws.send('ping')
                            continue

                        data = json.loads(message)

                        if data.get("event") == "subscribe":
                            self._subscribed_channels = {arg["channel"] for arg in ws_payload["args"]}
                            logger.info(f"Subscribed to channels: {self._subscribed_channels}")
                        elif data.get("event") == "error":
                            logger.error(f"WebSocket subscription failed: {data.get('msg')}")
                        elif "data" in data:
                            await self._route_ws_data(data)

            except Exception as e:
                logger.error(f"WebSocket connection error: {e}", exc_info=True)
                self._subscribed_channels.clear()
                await asyncio.sleep(5)

    async def _route_ws_data(self, data: Dict):
        channel = data.get("arg", {}).get("channel")
        event_data_list = data.get("data", [])

        if not channel or not event_data_list:
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
                    logger.error(f"Trade parse error: {e}", exc_info=True)

            elif channel == "books":
                self._books_update_count += 1
                try:
                    await self.market_state.update_from_ws_books(event_data)
                    new_bid_count = len(self.market_state.depth_20.get('bids', []))
                    new_ask_count = len(self.market_state.depth_20.get('asks', []))
                    if new_bid_count != self._last_bid_count or new_ask_count != self._last_ask_count:
                        self._last_bid_count = new_bid_count
                        self._last_ask_count = new_ask_count
                except Exception as e:
                    logger.error(f"Books parse error: {e}", exc_info=True)

            elif channel == "tickers":
                try:
                    mark_px = event_data.get("markPx")
                    if mark_px:
                        await self.market_state.update_from_ws_mark_price({"markPx": float(mark_px)})
                    await self.market_state.update_from_ws_book_ticker(event_data)
                except Exception as e:
                    logger.error(f"Ticker parse error: {e}", exc_info=True)

    async def start(self):
        if not self.is_running:
            self.is_running = True
            await self._validate_inst_id()
            await self._fetch_historical_klines()
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