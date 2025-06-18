# receiver_ack_handler.py
import json
import os
import time

PING_FILE = "receiver_ping.json"
ACK_FILE = "receiver_ack.json"

def load_ping():
    if not os.path.exists(PING_FILE):
        return None
    with open(PING_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return None

def write_ack(content):
    with open(ACK_FILE, "w") as f:
        json.dump(content, f, indent=2)

def main():
    print("[ACK_HANDLER] Listening for heartbeat ping...")
    while True:
        ping_data = load_ping()
        if ping_data and "signal" in ping_data:
            if ping_data["signal"] == "NEUROSYNC_HEARTBEAT":
                ack_payload = {
                    "ack": "RECEIVED",
                    "timestamp": time.time(),
                    "source": "Trading-Core"
                }
                write_ack(ack_payload)
                print("[ACK_HANDLER] Acknowledged NEUROSYNC_HEARTBEAT")
                time.sleep(2)
        time.sleep(0.5)

if __name__ == "__main__":
    main()