import logging
from typing import Dict, Any
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)

class TimeOfDayFilter:
    """
    Checks if the current time is within an approved, high-volume trading window.
    The windows are hardcoded here as per the design.
    """
    def __init__(self):
        # The approved trading windows are defined here, in UTC time.
        # Example below represents the London/New York overlap session.
        self.approved_windows = [
            (13, 00, 21, 00), 
        ]
        logger.info("TimeOfDayFilter Initialized.")

    def generate_report(self, market_state: Any) -> Dict[str, Any]:
        """Generates a report indicating if the current time is approved for trading."""
        now_utc = datetime.now(pytz.utc)
        current_time = now_utc.time()
        
        is_in_window = False
        for start_hour, start_min, end_hour, end_min in self.approved_windows:
            start_time = datetime.strptime(f"{start_hour}:{start_min}", "%H:%M").time()
            end_time = datetime.strptime(f"{end_hour}:{end_min}", "%H:%M").time()
            if start_time <= current_time <= end_time:
                is_in_window = True
                break
        
        return {
            "filter_name": self.__class__.__name__,
            "is_in_approved_window": is_in_window,
            "current_utc_time": current_time.strftime("%H:%M:%S")
        }
