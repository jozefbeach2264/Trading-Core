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
        self._books_update_count = 0  # Track updates for periodic logging
        self._last_bid_count = 0
        self._last_ask_count = 0  # Track last bid/ask counts
        
        self.ws_url = "wss://ws.okx.com:8443/ws/v5/public"
        self.inst_id = f"{self.config.symbol.replace('USDT', '')}-USDT-SWAP"
        self.candle_reconstructor = CandleReconstructor()
        
        logger.info(f"MarketDataManager configured for OKX with instrument ID: {self.inst_id}")

    async def _fetch_historical_klines(self):
        """Fetch 50 historical klines and initial order book from OKX REST API and update MarketState."""
        required_candles = 50
        max_retries = 3

        # Fetch historical klines
        endpoint = f"https://www.okx.com/api/v5/market/history-candles"
        params = {
            "instId": self.inst_id,
            "bar": "1m",
            "limit": str(required_candles)
        }
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"Attempt {attempt}/{max_retries} to fetch {required_candles} historical klines for {self.inst_id}")
                response = await self.client.get(endpoint, params=params)
                response.raise_for_status()
                data = response.json()
                logger.debug(f"OKX API kline response: {data}")
                if data.get("code") != "0" or not data.get("data"):
                    logger.error(f"Failed to fetch historical klines: {data.get('msg', 'Unknown error')}")
                    if attempt < max_retries:
                        logger.info("Retrying after 2 seconds...")
                        await asyncio.sleep(2)
                    continue
                klines = data["data"]
                logger.info(f"Fetched {len(klines)} historical klines")
                if len(klines) < required_candles:
                    logger.warning(f"Received only {len(klines)}/{required_candles} klines")
                await self.market_state.update_klines(klines)
                logger.info(f"Updated MarketState with {len(self.market_state.klines)} klines")
                break
            except httpx.HTTPError as e:
                logger.error(f"HTTP error on attempt {attempt}: {e}", exc_info=True)
            except Exception as e:
                logger.error(f"Unexpected error on attempt {attempt}: {e}", exc_info=True)
            if attempt < max_retries:
                logger.info("Retrying after 2 seconds...")
                await asyncio.sleep(2)
            else:
                logger.error(f"Failed to fetch historical klines after {max_retries} attempts")

        # Fetch initial order book
        endpoint = f"https://www.okx.com/api/v5/market/books"
        params = {
            "instId": self.inst_id,
            "sz": "20"
        }
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"Attempt {attempt}/{max_retries} to fetch order book for {self.inst_id}")
                response = await self.client.get(endpoint, params=params)
                response.raise_for_status()
                data = response.json()
                logger.debug(f"OKX API order book response: {data}")
                if data.get("code") != "0" or not data.get("data"):
                    logger.error(f"Failed to fetch order book: {data.get('msg', 'Unknown error')}")
                    if attempt < max_retries:
                        logger.info("Retrying after 2 seconds...")
                        await asyncio.sleep(2)
                    continue
                order_book = data["data"][0]
                await self.market_state.update_depth_20(order_book)
                logger.info(f"Updated MarketState with order book: {len(order_book.get('bids', []))} bids, {len(order_book.get('asks', []))} asks")
                self._last_bid_count = len(order_book.get('bids', []))
                self._last_ask_count = len(order_book.get('asks', []))
                break
            except httpx.HTTPError as e:
                logger.error(f"HTTP error on attempt {attempt}: {e}", exc_info=True)
            except Exception as e:
                logger.error(f"Unexpected error on attempt {attempt}: {e}", exc_info=True)
            if attempt < max_retries:
                logger.info("Retrying after 2 seconds...")
                await asyncio.sleep(2)
            else:
                logger.error(f"Failed to fetch order book after {max_retries} attempts")

        await asyncio.sleep(1)

    async def _websocket_handler(self):
        ws_payload = {
            "op": "subscribe",
            "args": [
                {"channel": "trades", "instId": self.inst_id},
                {"channel": "books", "instId": self.inst_id},
                {"channel": "tickers", "instId": self.inst_id},
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
                            await ws.send('ping')
                            continue
                        
                        data = json.loads(message)

                        if "event" in data or "data" not in data:
                            continue

                        await self._route_ws_data(data)
                            
            except websockets.exceptions.ConnectionClosed:
                logger.warning("OKX WebSocket connection closed. Reconnecting...")
            except Exception as e:
                logger.error(f"OKX WebSocket error: {e}", exc_info=True)
            finally:
                if self.is_running:
                    await asyncio.sleep(5)

    async def _route_ws_data(self, data: Dict):
        channel = data.get("arg", {}).get("channel")
        event_data_list = data.get("data", [])
        
        if not channel or not event_data_list:
            return

        for event_data in event_data_list:
            if channel == "trades":
                completed_candle = self.candle_reconstructor.process_trade(event_data)
                
                if completed_candle:
                    await self.market_state.update_from_ws_kline(completed_candle)

                live_candle = self.candle_reconstructor.get_live_candle()
                if live_candle:
                    await self.market_state.update_live_reconstructed_candle(live_candle)

            elif channel == "books":
                self._books_update_count += 1
                if self._books_update_count % 100 == 0:
                    logger.debug(f"WebSocket books data received (update {self._books_update_count}): {event_data}")
                try:
                    await self.market_state.update_from_ws_books(event_data)
                    new_bid_count = len(self.market_state.depth_20.get('bids', []))
                    new_ask_count = len(self.market_state.depth_20.get('asks', []))
                    if (new_bid_count != self._last_bid_count or new_ask_count != self._last_ask_count or 
                        self._books_update_count % 100 == 0):
                        logger.info(f"Updated MarketState from WebSocket books: {new_bid_count} bids, {new_ask_count} asks")
                        self._last_bid_count = new_bid_count
                        self._last_ask_count = new_ask_count
                except Exception as e:
                    logger.error(f"Error processing WebSocket books data: {e}", exc_info=True)
            elif channel == "tickers":
                await self.market_state.update_from_ws_book_ticker(event_data)

    async def start(self):
        if not self.is_running:
            self.is_running = True
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