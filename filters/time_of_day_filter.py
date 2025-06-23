# TradingCore/filters/time_of_day_filter.py
from datetime import datetime
import pytz

class TimeOfDayFilter:
    """
    Blocks trades outside of specified trading sessions.
    """
    def __init__(self):
        # Define trading sessions in UTC
        self.sessions = {
            "london": (7, 16), # 7:00 - 16:00 UTC
            "new_york": (12, 21), # 12:00 - 21:00 UTC
            "tokyo": (23, 8) # 23:00 - 8:00 UTC
        }
        self.active_sessions = ["london", "new_york"] # Only trade during these sessions
        print("TimeOfDayFilter Initialized.")

    def check(self) -> bool:
        """Returns True if the current time is within an active session, False otherwise."""
        current_hour = datetime.now(pytz.utc).hour
        
        for session_name in self.active_sessions:
            start_hour, end_hour = self.sessions[session_name]
            # Handle overnight sessions like Tokyo
            if start_hour > end_hour:
                if current_hour >= start_hour or current_hour < end_hour:
                    return True
            else:
                if start_hour <= current_hour < end_hour:
                    return True
        
        return False

