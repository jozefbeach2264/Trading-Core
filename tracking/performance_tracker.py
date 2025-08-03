import logging
import json
import os
from datetime import datetime
from typing import Dict, Any

logger = logging.getLogger(__name__)

class PerformanceTracker:
    """
    Logs every completed trade to a file and calculates success rate.
    """
    def __init__(self, config_or_path: Any = "trade_performance.jsonl"):
        if isinstance(config_or_path, str):
            self.log_file = os.environ.get("PERFORMANCE_LOG_PATH", config_or_path)
        else:
            self.log_file = getattr(config_or_path, "performance_log_path", "trade_performance.jsonl")
        self.trades_logged = 0
        self.successful_trades = 0
        self._load_history()

    def _load_history(self):
        try:
            with open(self.log_file, 'r') as f:
                for line in f:
                    self.trades_logged += 1
                    trade = json.loads(line)
                    if trade.get('pnl', 0) > 0:
                        self.successful_trades += 1
            logger.info(f"Loaded {self.trades_logged} past trades from performance log.")
        except FileNotFoundError:
            logger.info("Performance log not found. Starting fresh.")
        except Exception as e:
            logger.error(f"Error loading performance history: {e}")

    def log_trade(self, trade_result: Dict[str, Any]):
        """Logs a completed trade to the performance file."""
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "trade_id": trade_result.get("trade_id"),
            "symbol": trade_result.get("symbol"),
            "direction": trade_result.get("direction"),
            "pnl": trade_result.get("pnl"),
            "roi_percent": trade_result.get("roi_percent"),
            "exit_reason": trade_result.get("exit_reason"),
        }

        try:
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')

            self.trades_logged += 1
            if log_entry['pnl'] > 0:
                self.successful_trades += 1

        except Exception as e:
            logger.error(f"Failed to log trade performance: {e}")

    def get_success_rate(self) -> float:
        """Calculates the current success rate."""
        if self.trades_logged == 0:
            return 0.0
        return (self.successful_trades / self.trades_logged) * 100.0