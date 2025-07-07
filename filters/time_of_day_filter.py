import logging
from typing import Dict, Any
from datetime import datetime

from config.config import Config
from data_managers.market_state import MarketState

logger = logging.getLogger("TimeOfDayFilter")
logger.setLevel(logging.INFO)

class TimeOfDayFilter:
    """
    Checks if the current time is within the allowed trading hours.
    """
    def __init__(self, config: Config):
        self.config = config
        self.start_hour = self.config.trading_start_hour
        self.end_hour = self.config.trading_end_hour

        logger.info(
            f"[INIT] TimeOfDayFilter: Trading allowed between {self.start_hour}:00 and {self.end_hour}:59 UTC."
        )

    async def generate_report(self, market_state: MarketState) -> Dict[str, Any]:
        """
        Generates a report indicating if the current time is valid for trading.
        """
        now = datetime.utcnow()
        current_hour = now.hour

        valid = False
        window_type = "standard"

        if self.start_hour <= self.end_hour:
            if self.start_hour <= current_hour <= self.end_hour:
                valid = True
        else:
            window_type = "overnight"
            if current_hour >= self.start_hour or current_hour <= self.end_hour:
                valid = True

        report = {
            "filter_name": "TimeOfDayFilter",
            "time_is_valid": valid,
            "current_hour_utc": current_hour,
            "window_type": window_type
        }

        logger.info({
            "timestamp": now.isoformat() + "Z",
            "hour": current_hour,
            "start_hour": self.start_hour,
            "end_hour": self.end_hour,
            "window_type": window_type,
            "result": valid
        })

        return report