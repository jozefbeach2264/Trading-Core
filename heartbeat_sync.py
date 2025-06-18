import time
import json
import os
from datetime import datetime

def send_heartbeat():
    data = {
        "module": "Trading-Core",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }

    with open("receiver_ping.json", "w") as f:
        json.dump(data, f)

if __name__ == "__main__":
    while True:
        send_heartbeat()
        time.sleep(3)  # Sends a ping every 3 seconds