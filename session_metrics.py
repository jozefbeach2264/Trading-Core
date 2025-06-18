import time
import json
import os

class SessionMetrics:
    def __init__(self, filepath="session_metrics.json"):
        self.filepath = filepath
        self.data = {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "avg_roi": 0.0,
            "avg_latency": 0.0,
            "module_accuracy": {},
            "last_update": time.time()
        }
        self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            with open(self.filepath, "r") as f:
                try:
                    self.data = json.load(f)
                except json.JSONDecodeError:
                    pass  # fallback to fresh

    def _save(self):
        with open(self.filepath, "w") as f:
            json.dump(self.data, f, indent=2)

    def log_trade(self, result, roi, latency_ms, module_name):
        self.data["total_trades"] += 1
        if result == "win":
            self.data["wins"] += 1
        else:
            self.data["losses"] += 1

        self.data["avg_roi"] = self._running_avg(
            self.data["avg_roi"], roi, self.data["total_trades"]
        )
        self.data["avg_latency"] = self._running_avg(
            self.data["avg_latency"], latency_ms, self.data["total_trades"]
        )

        if module_name not in self.data["module_accuracy"]:
            self.data["module_accuracy"][module_name] = {"wins": 0, "losses": 0}

        if result == "win":
            self.data["module_accuracy"][module_name]["wins"] += 1
        else:
            self.data["module_accuracy"][module_name]["losses"] += 1

        self.data["last_update"] = time.time()
        self._save()

    def _running_avg(self, current_avg, new_value, count):
        return round(((current_avg * (count - 1)) + new_value) / count, 4)

    def get_summary(self):
        return self.data