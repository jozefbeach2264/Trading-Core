"""Age-aware expectations for the in-progress (live reconstructed) 1-minute candle.

The live candle starts every minute with high == low (candle_reconstructor seeds both with the
first trade), so any filter that compares its range with the average range of CLOSED candles sees
"compression" in the opening seconds of every minute by construction. For a diffusive price the
range of a partial candle grows ≈ √(elapsed fraction), so filters compare against
`expected_partial_range` instead of the full-candle average, and report a young candle as a
Soft Flag rather than a Block.
"""
import math
import time
from typing import Any, List, Optional

CANDLE_MS = 60_000
MIN_CANDLE_AGE_S = 5.0          # below this the live candle has too few trades to judge structure
MIN_AGE_FRACTION = MIN_CANDLE_AGE_S / (CANDLE_MS / 1000.0)


def candle_age_fraction(live_candle: Optional[List[Any]], now_ms: Optional[float] = None) -> float:
    """Elapsed fraction [0, 1] of the live candle's minute. Unknown/invalid timestamp → 1.0 (no scaling)."""
    if not live_candle:
        return 1.0
    try:
        start_ms = float(live_candle[0])
    except (TypeError, ValueError, IndexError):
        return 1.0
    if start_ms <= 0:
        return 1.0
    now = time.time() * 1000.0 if now_ms is None else now_ms
    return max(0.0, min((now - start_ms) / CANDLE_MS, 1.0))


def expected_partial_range(average_range: float, age_fraction: float) -> float:
    """Range a normal candle would have shown after `age_fraction` of its minute (√t scaling)."""
    return average_range * math.sqrt(max(0.0, min(age_fraction, 1.0)))


def is_too_young(age_fraction: float) -> bool:
    return age_fraction < MIN_AGE_FRACTION
