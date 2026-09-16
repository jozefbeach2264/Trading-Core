import logging
import asyncio
import httpx
import websockets
import json
import time
from typing import Dict, List, Any, Optional
from config.config import Config
from data_managers.market_state import MarketState
from reconstructors.candle_reconstructor import CandleReconstructor

logger = logging.getLogger(__name__)

OKX_HISTORY_CANDLES_MAX = 300   # /market/history-candles silently caps limit at 300


class MarketDataManager:
    def __init__(self, config: Config, market_state: MarketState, httpx_client: httpx.AsyncClient):
        self.config = config
        self.market_state = market_state
        self.client = httpx_client
        self.is_running = False
        self._task: asyncio.Task = None
        self._subscribed_channels = set()
        self.ws_url = self.config.okx_ws_url
        self.inst_id = self.config.trading_symbol
        self.candle_reconstructor = CandleReconstructor()
        self.event_queue: Optional[asyncio.Queue] = None
        self._last_mark_price: Optional[float] = None
        self._last_event_time: Dict[str, float] = {}
        self._last_wall_snapshot: Dict[str, Any] = {}
        self._last_spoof_thin_rate: Optional[float] = None
        self._acknowledged_channels = set()
        self._logged_ws_subscription = False
        self._connections = 0
        logger.debug(f"MarketDataManager configured for OKX with instrument ID: {self.inst_id}")

    def set_event_queue(self, queue: asyncio.Queue):
        self.event_queue = queue

    async def _emit_event(self, event_type: str, payload: Dict[str, Any], cooldown_s: float = 2.0):
        now = time.time()
        last_emitted = self._last_event_time.get(event_type, 0)
        if now - last_emitted < cooldown_s:
            return
        if self.event_queue:
            try:
                self.event_queue.put_nowait({"type": event_type, "payload": payload})
                self._last_event_time[event_type] = now
            except asyncio.QueueFull:
                logger.warning(f"Event queue full. Dropping event: {event_type}")

    async def _maybe_emit_volume_spike(self):
        if not self.event_queue:
            return
        now_ms = int(time.time() * 1000)
        recent_vol = sum(
            float(t.get("qty", 0.0))
            for t in self.market_state.recent_trades
            if (now_ms - 5000) <= int(t.get("time", 0))
        )
        if recent_vol >= self.config.event_volume_spike_threshold:
            await self._emit_event(
                "volume_spike",
                {"volume_5s": recent_vol, "threshold": self.config.event_volume_spike_threshold}
            )

    async def _maybe_emit_price_spike(self, mark_px: float):
        if not self.event_queue or mark_px <= 0:
            return
        if self._last_mark_price is None:
            self._last_mark_price = mark_px
            return
        pct_change = abs(mark_px - self._last_mark_price) / self._last_mark_price * 100
        if pct_change >= self.config.event_price_spike_pct_threshold:
            await self._emit_event(
                "price_spike",
                {
                    "mark_px": mark_px,
                    "prev_mark_px": self._last_mark_price,
                    "pct_change": pct_change,
                    "threshold": self.config.event_price_spike_pct_threshold
                }
            )
        self._last_mark_price = mark_px

    async def _maybe_emit_orderbook_events(self):
        if not self.event_queue:
            return
        await self.market_state.ensure_order_book_metrics_are_current()
        walls = self.market_state.order_book_walls or {}
        bid_walls = walls.get("bid_walls", [])
        ask_walls = walls.get("ask_walls", [])
        def _strongest_wall(wlist):
            if not wlist:
                return None
            return max(wlist, key=lambda x: x.get("qty", 0))
        strongest_bid = _strongest_wall(bid_walls)
        strongest_ask = _strongest_wall(ask_walls)
        last_bid = self._last_wall_snapshot.get("bid")
        last_ask = self._last_wall_snapshot.get("ask")
        wall_change = False
        abs_thresh = self.config.event_wall_abs_change_threshold
        pct_thresh = self.config.event_wall_change_pct_threshold
        if strongest_bid and last_bid:
            abs_delta = abs(strongest_bid["qty"] - last_bid["qty"])
            change_pct = abs_delta / max(last_bid["qty"], 1e-9) * 100
            if change_pct >= pct_thresh and abs_delta >= abs_thresh:
                wall_change = True
        if strongest_ask and last_ask:
            abs_delta = abs(strongest_ask["qty"] - last_ask["qty"])
            change_pct = abs_delta / max(last_ask["qty"], 1e-9) * 100
            if change_pct >= pct_thresh and abs_delta >= abs_thresh:
                wall_change = True
        if wall_change:
            await self._emit_event(
                "wall_change",
                {
                    "bid_wall": strongest_bid,
                    "ask_wall": strongest_ask,
                    "threshold_pct": pct_thresh,
                    "abs_threshold": abs_thresh
                }
            )
        self._last_wall_snapshot = {"bid": strongest_bid, "ask": strongest_ask}

        # Spoof/thinning metric with significance gating
        spoof_rate = self.market_state.spoof_metrics.get("spoof_thin_rate", 0.0)
        if self._last_spoof_thin_rate is None:
            self._last_spoof_thin_rate = spoof_rate
        else:
            delta = abs(spoof_rate - self._last_spoof_thin_rate)
            if abs(spoof_rate) >= self.config.event_spoof_thin_threshold or delta >= self.config.event_spoof_delta_threshold:
                await self._emit_event(
                    "spoof_thin",
                    {
                        "spoof_thin_rate": spoof_rate,
                        "threshold": self.config.event_spoof_thin_threshold,
                        "delta": delta,
                        "delta_threshold": self.config.event_spoof_delta_threshold
                    }
                )
            self._last_spoof_thin_rate = spoof_rate

    async def _validate_inst_id(self):
        endpoint = "/api/v5/public/instruments"
        params = {"instType": "SWAP", "instId": self.inst_id}
        try:
            response = await self.client.get(endpoint, params=params, timeout=15.0)
            response.raise_for_status()
            data = response.json()
            if data.get("code") != "0" or not data.get("data"):
                logger.error("Invalid instId", extra={"instId": self.inst_id, "response": data.get('msg', 'Unknown error')})
                raise ValueError(f"Invalid instId: {self.inst_id}")
            instrument = data["data"][0]
            contract_value = float(instrument.get("ctVal") or 1.0)
            self.market_state.set_contract_value(contract_value)
            self.candle_reconstructor.contract_value = contract_value
            logger.info("Validated instId %s: ctVal=%s %s (sizes are converted from contracts)",
                        self.inst_id, contract_value, instrument.get("ctValCcy"))
        except Exception as e:
            logger.error(f"Failed to validate instId {self.inst_id}", extra={"error": str(e)}, exc_info=True)
            raise

    async def _fetch_initial_data(self):
        async def fetch_klines():
            klines_endpoint = "/api/v5/market/history-candles"
            klines_params = {"instId": self.inst_id, "bar": "1m",
                             "limit": str(min(self.config.kline_deque_maxlen, OKX_HISTORY_CANDLES_MAX))}
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

        async def fetch_books():
            books_endpoint = "/api/v5/market/books"
            books_params = {"instId": self.inst_id, "sz": "50"}
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

        async def fetch_mark_price():
            mark_price_endpoint = "/api/v5/public/mark-price"
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

        async def fetch_open_interest():
            oi_endpoint = "/api/v5/public/open-interest"
            oi_params = {"instId": self.inst_id}
            try:
                response = await self.client.get(oi_endpoint, params=oi_params)
                response.raise_for_status()
                data = response.json()
                if data.get("code") == "0" and data.get("data"):
                    oi_data = data["data"][0]
                    await self.market_state.update_open_interest(oi_data)
                    logger.info(f"Fetched initial open interest: {oi_data.get('oi')}")
                else:
                    logger.error("Failed to fetch initial open interest", extra={"response": data.get('msg')})
            except Exception as e:
                logger.error("Error fetching initial open interest", extra={"error": str(e)}, exc_info=True)

        await asyncio.gather(
            fetch_klines(),
            fetch_books(),
            fetch_mark_price(),
            fetch_open_interest()
        )

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
                    await self._maybe_emit_volume_spike()
                except Exception as e:
                    logger.error("Error processing trade data", extra={"error": str(e)}, exc_info=True)

            elif channel in ("books", "books5"):
                try:
                    if not event_data.get('bids') or not event_data.get('asks'):
                        logger.debug("Empty books update received", extra={"data": event_data})
                        return
                    await self.market_state.update_from_ws_books(event_data)
                    await self._maybe_emit_orderbook_events()
                except Exception as e:
                    logger.error("Error processing book data", extra={"error": str(e)}, exc_info=True)

            elif channel == "tickers":
                try:
                    await self.market_state.update_from_ws_book_ticker(event_data)
                    mark_px = event_data.get("markPx")
                    if mark_px:
                        mpx = float(mark_px)
                        await self.market_state.update_from_ws_mark_price({"markPx": mpx})
                        await self._maybe_emit_price_spike(mpx)
                except Exception as e:
                    logger.error("Error processing ticker data", extra={"error": str(e)}, exc_info=True)
            
            elif channel == "mark-price":
                try:
                    mark_px = event_data.get("markPx")
                    if mark_px:
                        mpx = float(mark_px)
                        await self.market_state.update_from_ws_mark_price({"markPx": mpx})
                        await self._maybe_emit_price_spike(mpx)
                except Exception as e:
                    logger.error("Error processing mark-price data", extra={"error": str(e)}, exc_info=True)
            
            elif channel == "open-interest":
                try:
                    await self.market_state.update_open_interest(event_data)
                except Exception as e:
                    logger.error("Error processing open-interest data", extra={"error": str(e)}, exc_info=True)

    async def _websocket_handler(self):
        ws_payload = {
            "op": "subscribe",
            "args": [
                {"channel": "trades", "instId": self.inst_id},
                {"channel": "books5", "instId": self.inst_id, "sz": "50"},
                {"channel": "tickers", "instId": self.inst_id},
                {"channel": "mark-price", "instId": self.inst_id},
                {"channel": "open-interest", "instId": self.inst_id}
            ]
        }
        while self.is_running:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    logger.info("Connected to OKX WebSocket.")
                    self._acknowledged_channels.clear()
                    self._logged_ws_subscription = False
                    self._connections += 1
                    if self._connections > 1:
                        # Reconnect: the candle being built has a gap and whole minutes may be missing.
                        self.candle_reconstructor.reset()
                        asyncio.create_task(self._fetch_initial_data())
                    await ws.send(json.dumps(ws_payload))
                    while self.is_running:
                        try:
                            message = await asyncio.wait_for(ws.recv(), timeout=30)
                            if message == 'pong':
                                continue
                            
                            data = json.loads(message)
                            
                            if data.get("event") == "subscribe":
                                self._subscribed_channels = {arg["channel"] for arg in ws_payload["args"]}
                                acknowledged_channel = data.get("arg", {}).get("channel")
                                if acknowledged_channel:
                                    self._acknowledged_channels.add(acknowledged_channel)
                                if not self._logged_ws_subscription and self._acknowledged_channels >= self._subscribed_channels:
                                    logger.info("Subscribed to WebSocket channels", extra={"channels": list(self._subscribed_channels)})
                                    self._logged_ws_subscription = True
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
                self._acknowledged_channels.clear()
                self._logged_ws_subscription = False
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
