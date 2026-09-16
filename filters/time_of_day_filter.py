import logging
from typing import Dict, Any, Set, Tuple
from datetime import datetime, time as dt_time, timezone

from config.config import Config
from data_managers.market_state import MarketState

logger = logging.getLogger(__name__)


def parse_trade_windows(window_str: str) -> Set[Tuple[dt_time, dt_time]]:
    """Parse "HH:MM-HH:MM[,HH:MM-HH:MM...]". Raises ValueError on anything malformed — a typo used to
    silently disable the time gate (empty set == "always allowed")."""
    allowed: Set[Tuple[dt_time, dt_time]] = set()
    if not window_str or not window_str.strip():
        return allowed
    for part in window_str.split(','):
        part = part.strip()
        if '-' not in part:
            raise ValueError(f"ALLOWED_WINDOWS entry {part!r} is not HH:MM-HH:MM")
        start_str, end_str = (x.strip() for x in part.split('-', 1))
        try:
            allowed.add((dt_time.fromisoformat(start_str), dt_time.fromisoformat(end_str)))
        except ValueError as e:
            raise ValueError(f"ALLOWED_WINDOWS entry {part!r}: {e}") from e
    return allowed


class TimeOfDayFilter:
    def __init__(self, config: Config):
        self.config = config
        self.allowed_windows = self._parse_trade_windows(config.allowed_windows)

    def _parse_trade_windows(self, window_str: str) -> Set[Tuple[dt_time, dt_time]]:
        return parse_trade_windows(window_str)

    def _is_within_trade_window(self) -> bool:
        if not self.allowed_windows:
            return True  # no restriction configured
        # Minute resolution: a window ending at 23:59 must include 23:59:59, not just 23:59:00.000000.
        now_utc = datetime.now(timezone.utc).time().replace(second=0, microsecond=0)
        for start, end in self.allowed_windows:
            if start <= end:
                if start <= now_utc <= end:
                    return True
            else:  # overnight window such as 22:00-04:00
                if start <= now_utc or now_utc <= end:
                    return True
        return False

    async def generate_report(self, market_state: MarketState) -> Dict[str, Any]:
        report = {
            "filter_name": "TimeOfDayFilter",
            "score": 1.0,
            "metrics": {"current_utc_time": datetime.now(timezone.utc).strftime("%H:%M")},
            "flag": "✅ Hard Pass"
        }
        
        if self._is_within_trade_window():
            report["metrics"]["reason"] = "WITHIN_TRADING_WINDOW"
        else:
            report["score"] = 0.0
            report["flag"] = "❌ Block"
            report["metrics"]["reason"] = "OUT_OF_TRADING_WINDOW"
            
        return report
