import asyncio
import websockets
import json
from rolling5_engine import Rolling5

class SignalInterface:
    def __init__(self):
        self.trader = Rolling5()
        self.ws_url = "wss://neurosync.jozefbeach2264.repl.co"

    async def listen(self):
        print("[LISTENER] Connecting to core signal network...")
        try:
            async with websockets.connect(self.ws_url) as ws:
                while True:
                    msg = await ws.recv()
                    print(f"[LISTENER] Signal received: {msg}")
                    try:
                        data = json.loads(msg)
                        entry = float(data.get("entry_price"))
                        exit_ = float(data.get("exit_price"))
                        self.process_signal(entry, exit_)
                    except Exception as e:
                        print(f"[PROCESSING ERROR] {e}")
        except Exception as e:
            print(f"[LISTENER ERROR] {e}")

    def process_signal(self, entry_price, exit_price):
        result = self.trader.simulate_trade(entry_price=entry_price, exit_price=exit_price)
        self.display_result(result)

    def display_result(self, result):
        print(f"\n--- Trade Summary ---")
        print(f"Entry Price: {result['entry']}")
        print(f"Exit Price: {result['exit']}")
        print(f"ROI: {result['roi']}%")
        print(f"Net Profit: ${result['net_profit']}")
        print(f"Fee Paid: ${result['fee']}")
        print(f"New Balance: ${result['final_balance']}")
        print(f"----------------------\n")