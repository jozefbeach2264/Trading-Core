import os
import json
from datetime import datetime

class PassiveMemoryLogger:
    base_path = "logs/filters/"

    @classmethod
    def log(cls, filter_name: str, result: dict):
        filename = f"{filter_name.lower()}.memory.jsonl"
        log_path = os.path.join(cls.base_path, filename)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "filter": filter_name,
            "result": result.get("result", result.get("spoofing_detected", False)),
        }

        denial_reason = result.get("denial_reason") or result.get("notes") or result.get("reason")
        if denial_reason:
            log_entry["denial_reason"] = denial_reason

        with open(log_path, "a") as log_file:
            log_file.write(json.dumps(log_entry) + "\n")