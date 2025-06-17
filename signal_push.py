
import json
import os
from datetime import datetime

def push_signal(source, result):
    """
    Pushes signal outcome to a log file for downstream access or webhook relay.
    """
    os.makedirs("signals", exist_ok=True)
    ts = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"signals/{source}_{ts}.json"
    with open(filename, "w") as f:
        json.dump(result, f, indent=2)