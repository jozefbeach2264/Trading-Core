import logging
from typing import Dict, Any
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)

class TimeOfDayFilter:
    """
    Filters trades to only allow execution during pre-defined high-volume trading windows.
    """
    def __init__(self):
        logger.info("TimeOfDayFilter initialized.")
        # Define trading windows in UTC
        self.approved_windows_utc = [
            {"name": "London Open", "start_hour": 7, "end_hour": 9},    # 7:00 - 9:00 UTC
            {"name": "NY Open", "start_hour": 13, "end_hour": 15}, # 13:00 - 15:00 UTC
            {"name": "London Close", "start_hour": 15, "end_hour": 17} # 15:00 - 17:00 UTC
        ]

    async def validate(self, signal_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Checks if the current time is within an approved trading window.

        Args:
            signal_data (Dict[str, Any]): The market state data.

        Returns:
            Dict[str, Any]: A dictionary containing the analysis result.
        """
        now_utc = datetime.now(pytz.utc)
        current_hour = now_utc.hour

        for window in self.approved_windows_utc:
            if window["start_hour"] <= current_hour < window["end_hour"]:
                return {
                    "filter_name": "TimeOfDayFilter",
                    "status": "pass",
                    "current_window": window["name"],
                    "reason": f"Currently within the {window['name']} trading window."
                }
        
        return {
            "filter_name": "TimeOfDayFilter",
            "status": "fail",
            "current_window": None,
            "reason": "Outside of approved trading windows."
        }
