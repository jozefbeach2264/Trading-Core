import asyncio
import websockets

NETWORK_URL = "wss://neurosync.jozefbeach2264.repl.co/ws"

async def send_to_network(message: str):
    try:
        async with websockets.connect(NETWORK_URL) as ws:
            await ws.send(message)
            response = await ws.recv()
            print(f"[RESPONSE FROM NETWORK] {response}")
            return response
    except Exception as e:
        print(f"[NETWORK BRIDGE ERROR] {e}")
        return None