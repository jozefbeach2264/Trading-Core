# TradingCore/data_orchestrator.py
import asyncio
import time

class DataOrchestrator:
    """Manages concurrent data fetching tasks based on different schedules."""
    def __init__(self, api_client, market_state):
        self.api_client = api_client
        self.state = market_state
        self.running = False
        print("DataOrchestrator Initialized.")

    # --- Individual loops for each frequency ---

    async def _loop_500ms(self):
        """Fetches order book data."""
        while self.running:
            start_time = time.time()
            data = await self.api_client.get_order_book(symbol="ETHUSDT", limit=10)
            if data and 'bids' in data and 'asks' in data:
                async with self.state.lock:
                    self.state.bids = [(float(p), float(q)) for p, q in data['bids']]
                    self.state.asks = [(float(p), float(q)) for p, q in data['asks']]
            
            # Precise sleep calculation
            await asyncio.sleep(max(0, 0.5 - (time.time() - start_time)))

    async def _loop_1s(self):
        """Fetches latest price and OHLCV from klines."""
        while self.running:
            start_time = time.time()
            ticker_data = await self.api_client.get_ticker_price(symbol="ETHUSDT")
            kline_data = await self.api_client.get_klines(symbol="ETHUSDT", interval="1m", limit=1)
            
            async with self.state.lock:
                if ticker_data:
                    self.state.price = float(ticker_data['price'])
                if kline_data:
                    candle = kline_data[0] # The API returns a list with one candle
                    self.state.open = float(candle[1])
                    self.state.high = float(candle[2])
                    self.state.low = float(candle[3])
                    self.state.close = float(candle[4])
                    self.state.volume = float(candle[5]) # This is the volume for the latest minute

            await asyncio.sleep(max(0, 1.0 - (time.time() - start_time)))

    async def _loop_2s(self):
        """Fetches open interest."""
        while self.running:
            start_time = time.time()
            # You would add logic here to calculate OI change rate
            oi_data = await self.api_client.get_open_interest(symbol="ETHUSDT")
            if oi_data:
                async with self.state.lock:
                    self.state.open_interest = float(oi_data['openInterest'])
            await asyncio.sleep(max(0, 2.0 - (time.time() - start_time)))
            
    async def _loop_3s(self):
        """Fetches mark price and index price."""
        while self.running:
            start_time = time.time()
            premium_data = await self.api_client.get_premium_index(symbol="ETHUSDT")
            if premium_data:
                 async with self.state.lock:
                    self.state.mark_price = float(premium_data['markPrice'])
                    self.state.index_price = float(premium_data['indexPrice'])
            await asyncio.sleep(max(0, 3.0 - (time.time() - start_time)))

    async def _loop_10s(self):
        """Fetches funding rate and long/short ratio."""
        while self.running:
            start_time = time.time()
            funding_data = await self.api_client.get_funding_rate(symbol="ETHUSDT")
            # long_short_data = await self.api_client.get_long_short_ratio() # Placeholder
            
            async with self.state.lock:
                if funding_data:
                    self.state.funding_rate = float(funding_data['lastFundingRate'])
                # if long_short_data: self.state.long_short_ratio = ...

            await asyncio.sleep(max(0, 10.0 - (time.time() - start_time)))
            
    async def start(self):
        """Starts all concurrent data fetching loops."""
        self.running = True
        print("DataOrchestrator starting all loops...")
        
        # Launch all loops as independent background tasks
        asyncio.create_task(self._loop_500ms())
        asyncio.create_task(self._loop_1s())
        asyncio.create_task(self._loop_2s())
        asyncio.create_task(self._loop_3s())
        asyncio.create_task(self._loop_10s())
        
        # Add a simple loop to print the state periodically for verification
        asyncio.create_task(self._print_state_loop())

    async def _print_state_loop(self):
        """A simple loop to print the current state for debugging."""
        while self.running:
            await asyncio.sleep(5)
            # We don't need the lock here because __str__ handles it
            print(f"[Market State] {self.state}")

    async def stop(self):
        self.running = False
        print("DataOrchestrator stopping all loops...")
