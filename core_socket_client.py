import asyncio
import websockets
import json
import threading

SERVER_URI = "wss://bac4d511-16b6-482e-8ccc-eb134f27ce6a-00-2fdyzur7p8drl.riker.replit.dev/ws"  # Replace with live IP if needed

class CoreSocketClient:
    def __init__(self):
        self.uri = SERVER_URI
        self.connected = False

    async def connect(self):
        while True:
            try:
                async with websockets.connect(self.uri, ping_interval=10, ping_timeout=5) as websocket:
                    self.connected = True
                    await self.listen_loop(websocket)
            except Exception as e:
                print(f"[CORE] Reconnecting in 3s: {e}")
                self.connected = False
                await asyncio.sleep(3)

    async def listen_loop(self, websocket):
        async for message in websocket:
            try:
                data = json.loads(message)
                print(f"[CORE] Incoming command: {data}")
                # You can hook this into execution logic below
                if data.get("type") == "command":
                    self.handle_command(data["payload"])
            except json.JSONDecodeError:
                print("[CORE] Invalid JSON")

    def handle_command(self, payload):
        print(f"[CORE] Command received: {payload}")
        # Inject execution logic here

    def send_update(self, update_data):
        asyncio.run(self._send_data(update_data))

    async def _send_data(self, data):
        try:
            async with websockets.connect(self.uri) as websocket:
                await websocket.send(json.dumps(data))
        except Exception as e:
            print(f"[CORE] Failed to send update: {e}")

def launch_socket():
    client = CoreSocketClient()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(client.connect())

def start_core_socket():
    thread = threading.Thread(target=launch_socket, daemon=True)
    thread.start()