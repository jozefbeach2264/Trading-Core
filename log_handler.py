import json
from datetime import datetime

class LogHandler:
    def __init__(self, filename="trade_log.json"):
        self.filename = filename

    def log(self, entry):
        entry["timestamp"] = datetime.utcnow().isoformat()
        try:
            with open(self.filename, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            print(f"[LogHandler] Error writing log: {e}")