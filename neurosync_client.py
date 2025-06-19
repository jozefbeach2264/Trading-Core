# neurosync_client.py
import asyncio
import json
import websockets
from trading_engine import TradingEngine
from config import Config

class NeuroSyncClient:
    """
    Handles the persistent WebSocket connection to the NeuroSync service,
    listening for and processing real-time signals.
    """
    def __init__(self, config: Config, trading_engine: TradingEngine):
        self.ws_url = config.neurosync_ws_url
        self.trading_engine = trading_engine
        self.running = False
        self.connection = None
        print("NeuroSyncClient: Initialized.")

    async def connect_and_listen(self):
        """Connects to NeuroSync and listens for incoming signals."""
        self.running = True
        print(f"NeuroSyncClient: Starting connection to {self.ws_url}")
        
        while self.running:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    self.connection = ws
                    print("NeuroSyncClient: Connection established. Listening for signals...")
                    while True:
                        message = await ws.recv()
                        try:
                            # We assume signals from NeuroSync are JSON strings
                            signal_data = json.loads(message)
                            # Pass the structured data to the trading engine
                            await self.trading_engine.process_signal_from_neurosync(signal_data)
                        except json.JSONDecodeError:
                            print(f"NeuroSyncClient: Received non-JSON message: {message}")

            except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError) as e:
                print(f"NeuroSyncClient: Connection closed ({e}). Reconnecting in 5 seconds...")
            except Exception as e:
                print(f"NeuroSyncClient: An unexpected error occurred: {e}. Reconnecting in 5 seconds...")
            
            self.connection = None
            await asyncio.sleep(5)

    async def stop(self):
        """Stops the client and closes the connection."""
        self.running = False
        if self.connection:
            await self.connection.close()
        print("NeuroSyncClient: Stopped.")



