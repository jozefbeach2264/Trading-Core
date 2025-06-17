
import json
from datetime import datetime

def log_metrics(data, filename="execution_log.json"):
    timestamp = datetime.utcnow().isoformat()
    entry = {"timestamp": timestamp, "data": data}
    with open(filename, "a") as f:
        f.write(json.dumps(entry) + "\n")