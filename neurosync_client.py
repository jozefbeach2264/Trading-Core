# TradingCore/neurosync_client.py
import asyncio
import websockets

class NeuroSyncClient:
    """
    Handles the WebSocket connection from TradingCore to the NeuroSync server.
    """
    def __init__(self, config):
        self.ws_url = config.neurosync_ws_url
        self.connection = None
        self.running = False
        print("NeuroSyncClient Initialized.")

    async def connect_and_listen(self):
        """Connects to NeuroSync and listens for incoming signals."""
        self.running = True
        print(f"NeuroSyncClient: Attempting to connect to {self.ws_url}")

        # Define the required Origin Header for Replit's security
        # This prevents the '403 Forbidden' error
        origin_url = self.ws_url.replace("wss://", "https://").split("/ws")[0]
        extra_headers = {"Origin": origin_url}
        print(f"NeuroSyncClient: Using Origin header: {origin_url}")

        while self.running:
            try:
                # Add the extra_headers to the connect call
                async with websockets.connect(self.ws_url, extra_headers=extra_headers) as ws:
                    self.connection = ws
                    print("NeuroSyncClient: Successfully connected to NeuroSync WebSocket.")
                    
                    # Announce connection to the server
                    await ws.send("Trading-Core is connected.")
                    
                    async for message in ws:
                        print(f"Message from NeuroSync: {message}")

            except Exception as e:
                print(f"NeuroSyncClient: An error occurred: {e}. Reconnecting in 5 seconds...")
                self.connection = None
                await asyncio.sleep(5)

    async def send(self, message):
        """Sends a message to the NeuroSync server if connected."""
        if self.connection:
            await self.connection.send(message)
        else:
            print("NeuroSyncClient: Cannot send message, not connected.")

    async def stop(self):
        """Stops the client and closes the connection."""
        self.running = False
        if self.connection:
            await self.connection.close()
        print("NeuroSyncClient stopped.")

