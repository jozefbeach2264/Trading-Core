import logging
from typing import Dict, Any, Set, Tuple
from datetime import datetime, time as dt_time

from config.config import Config
from data_managers.market_state import MarketState

logger = logging.getLogger(__name__)

class TimeOfDayFilter:
    def __init__(self, config: Config):
        self.config = config
        self.allowed_windows = self._parse_trade_windows(config.allowed_windows)

    def _parse_trade_windows(self, window_str: str) -> Set[Tuple[dt_time, dt_time]]:
        allowed = set()
        if not window_str: return allowed
        try:
            for part in window_str.split(','):
                if '-' in part:
                    start_str, end_str = part.split('-')
                    start_time = dt_time.fromisoformat(start_str)
                    end_time = dt_time.fromisoformat(end_str)
                    allowed.add((start_time, end_time))
        except ValueError as e:
            logger.error(f"Invalid trade_windows format in config: '{window_str}'. Error: {e}")
        return allowed

    def _is_within_trade_window(self) -> bool:
        if not self.allowed_windows: return True # Default to always allowed if not set
        now_utc = datetime.utcnow().time()
        for start, end in self.allowed_windows:
            if start <= end:
                if start <= now_utc <= end: return True
            else: # Handles overnight windows like 22:00-04:00
                if start <= now_utc or now_utc <= end: return True
        return False

    async def generate_report(self, market_state: MarketState) -> Dict[str, Any]:
        candle_timestamp = market_state.get_current_candle_timestamp()
        report = {
            "filter_name": "TimeOfDayFilter",
            "score": 1.0,
            "metrics": {"current_utc_time": datetime.utcnow().strftime("%H:%M")},
            "flag": "✅ Hard Pass",
            "candle_timestamp": candle_timestamp
        }
        
        if self._is_within_trade_window():
            report["metrics"]["reason"] = "WITHIN_TRADING_WINDOW"
        else:
            report["score"] = 0.0
            report["flag"] = "❌ Block"
            report["metrics"]["reason"] = "OUT_OF_TRADING_WINDOW"
            
        return report
