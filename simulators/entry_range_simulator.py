# simulators/entry_range_simulator.py

import logging
from typing import Dict, Any, Tuple

from config.config import Config

logger = logging.getLogger(__name__)


class EntryRangeSimulator:
    """
    Uses ATR (estimated from recent projected high/low ranges) to bound
    the forecast and make liquidation checks safer / more realistic.

    Public API (unchanged):
      check_liquidation_risk(entry_price: float, direction: str, forecast: Dict[str, Any]) -> Tuple[bool, str]

    Tunables (read from Config if present; otherwise use defaults):
      - ers_atr_floor: float = 1.0
      - ers_max_atr_multiple_total: int = 6
      - ers_max_adverse_move_atr: int = 3
      - ers_liq_buffer_pct: float = 0.80
    """

    def __init__(self, config: Config):
        self.config = config

        # -------- Default tune (can be overridden in Config) --------
        self.atr_floor = float(getattr(self.config, "ers_atr_floor", 1.0))
        self.max_atr_multiple_total = int(getattr(self.config, "ers_max_atr_multiple_total", 6))
        self.max_adverse_move_atr = int(getattr(self.config, "ers_max_adverse_move_atr", 3))
        self.liq_buffer_pct = float(getattr(self.config, "ers_liq_buffer_pct", 0.80))
        # ------------------------------------------------------------

        # Sanity: clamp bad config values
        if self.atr_floor <= 0:
            self.atr_floor = 1.0
        if self.max_atr_multiple_total < 1:
            self.max_atr_multiple_total = 6
        if self.max_adverse_move_atr < 1:
            self.max_adverse_move_atr = 3
        if not (0.0 < self.liq_buffer_pct <= 1.0):
            self.liq_buffer_pct = 0.80

    def _estimate_atr_from_forecast(self, forecast: Dict[str, Any]) -> float:
        """
        Estimate ATR from the forecast dict by averaging the c1..c6 high-low ranges.
        If forecast is missing or malformed, return a minimal floor to avoid division issues.
        """
        try:
            f = forecast.get("forecast", {})
            if not isinstance(f, dict):
                return self.atr_floor

            ranges = []
            for k in ("c1", "c2", "c3", "c4", "c5", "c6"):
                c = f.get(k)
                if not c or "high" not in c or "low" not in c:
                    continue
                hi = float(c["high"])
                lo = float(c["low"])
                if hi > 0 and lo > 0 and hi >= lo:
                    ranges.append(hi - lo)

            if not ranges:
                return self.atr_floor

            atr = sum(ranges) / len(ranges)
            return max(atr, self.atr_floor)
        except Exception as e:
            logger.error("ATR estimation failed from forecast: %s", e, exc_info=True)
            return self.atr_floor

    def _project_total_span(self, forecast: Dict[str, Any]) -> float:
        """
        Compute total min->max span across c1..c6 to sanity check the forecast envelope.
        """
        try:
            f = forecast.get("forecast", {})
            lows, highs = [], []
            for k in ("c1", "c2", "c3", "c4", "c5", "c6"):
                c = f.get(k)
                if not c:
                    continue
                if "low" in c:
                    lows.append(float(c["low"]))
                if "high" in c:
                    highs.append(float(c["high"]))

            if not lows or not highs:
                return 0.0

            return max(highs) - min(lows)
        except Exception as e:
            logger.error("Span calculation failed from forecast: %s", e, exc_info=True)
            return 0.0

    def _adverse_move_vs_entry(self, entry: float, direction: str, forecast: Dict[str, Any]) -> float:
        """
        Worst-case adverse move against the entry using the min/max of the forecast envelope.
        For LONG, adverse is entry - min(low); for SHORT, adverse is max(high) - entry.
        """
        try:
            f = forecast.get("forecast", {})
            lows, highs = [], []
            for k in ("c1", "c2", "c3", "c4", "c5", "c6"):
                c = f.get(k)
                if not c:
                    continue
                if "low" in c:
                    lows.append(float(c["low"]))
                if "high" in c:
                    highs.append(float(c["high"]))

            if not lows or not highs or entry <= 0:
                return 0.0

            worst_low = min(lows)
            worst_high = max(highs)

            d = (direction or "").upper()
            if d == "LONG":
                return max(0.0, entry - worst_low)
            elif d == "SHORT":
                return max(0.0, worst_high - entry)
            else:
                # Unknown direction -> treat as unsafe by saying large adverse
                return float("inf")
        except Exception as e:
            logger.error("Adverse move calc failed: %s", e, exc_info=True)
            return float("inf")

    def _approx_liq_distance(self, entry: float) -> float:
        """
        Very rough liquidation approximation: distance ≈ entry / leverage.
        Apply a buffer (liq_buffer_pct) to be conservative.
        """
        try:
            lev = max(1, int(getattr(self.config, "leverage", 1)))
            return (entry / lev) * self.liq_buffer_pct
        except Exception as e:
            logger.error("Liquidation distance calc failed: %s", e, exc_info=True)
            return 0.0

    def check_liquidation_risk(self, entry_price: float, direction: str, forecast: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Returns (is_safe, reason).
        - Uses ATR to sanity-check total forecast span
        - Compares worst-case adverse move vs an approximate liq distance
        - Flags obviously insane forecasts
        """
        if not entry_price or entry_price <= 0:
            return False, "Invalid entry price."

        # 1) Estimate ATR from forecast c1..c6 ranges
        atr = self._estimate_atr_from_forecast(forecast)

        # 2) Sanity-check total span vs ATR
        total_span = self._project_total_span(forecast)
        if total_span > self.max_atr_multiple_total * atr:
            return False, (
                f"Forecast span ({total_span:.2f}) exceeds {self.max_atr_multiple_total}×ATR "
                f"({atr:.2f}). Forecast deemed unreliable."
            )

        # 3) Compute worst-case adverse move vs entry
        adverse = self._adverse_move_vs_entry(entry_price, direction, forecast)

        # If adverse move is wildly larger than several ATR, flag it
        if adverse > self.max_adverse_move_atr * atr:
            return False, (
                f"Adverse move ({adverse:.2f}) exceeds {self.max_adverse_move_atr}×ATR "
                f"({atr:.2f}). Too risky."
            )

        # 4) Compare adverse move to an approximate liquidation distance
        liq_dist = self._approx_liq_distance(entry_price)
        if adverse >= liq_dist:
            return False, (
                f"Adverse move ({adverse:.2f}) crosses liq buffer (~{liq_dist:.2f}). "
                f"Leverage={getattr(self.config, 'leverage', 'N/A')}x."
            )

        return True, "OK"