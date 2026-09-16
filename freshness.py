"""Freshness gates for a decision loop that trades on a websocket snapshot.

The market state keeps its last values through a feed outage while the engine keeps cycling, and a
verdict takes hundreds of milliseconds (up to AI_CLIENT_TIMEOUT) during which price moves. Nothing in
the original design checked either. These helpers are pure functions over the state + a clock.
"""
import time
from typing import Any, List, Optional

CANDLE_MS = 60_000


def _now_s(now_s: Optional[float]) -> float:
    return time.time() if now_s is None else now_s


def market_data_age_s(market_state: Any, now_s: Optional[float] = None) -> float:
    """Seconds since the last book/trade update reached MarketState."""
    return max(0.0, _now_s(now_s) - float(getattr(market_state, "last_update_time", 0.0) or 0.0))


def live_candle_is_current(live_candle: Optional[List[Any]], now_s: Optional[float] = None) -> bool:
    """True when the reconstructed live candle belongs to the current minute (the reconstructor only rolls
    the candle when the next trade arrives, so a stalled trades channel leaves a stale minute in place)."""
    if not live_candle:
        return False
    try:
        start_ms = float(live_candle[0])
    except (TypeError, ValueError, IndexError):
        return False
    return start_ms <= _now_s(now_s) * 1000.0 < start_ms + CANDLE_MS


def stale_market_reason(market_state: Any, max_age_s: float, now_s: Optional[float] = None) -> Optional[str]:
    """None when the snapshot is fresh enough to trade on; otherwise a short reason."""
    age = market_data_age_s(market_state, now_s)
    if age > max_age_s:
        return f"market data {age:.1f}s old (limit {max_age_s:.1f}s)"
    if not live_candle_is_current(getattr(market_state, "live_reconstructed_candle", None), now_s):
        return "live candle is not from the current minute"
    return None


def stale_decision_reason(decided_at_s: float, signal_price: float, current_price: Optional[float],
                          max_age_s: float, max_drift_pct: float, now_s: Optional[float] = None) -> Optional[str]:
    """None when a verdict is still actionable: young enough and price has not run away from the signal."""
    age = _now_s(now_s) - decided_at_s
    if age > max_age_s:
        return f"decision {age:.1f}s old (limit {max_age_s:.1f}s)"
    if not current_price or current_price <= 0 or signal_price <= 0:
        return "mark price unavailable"
    drift_pct = abs(current_price - signal_price) / signal_price * 100.0
    if drift_pct > max_drift_pct:
        return f"price drifted {drift_pct:.3f}% since the signal (limit {max_drift_pct:.3f}%)"
    return None
