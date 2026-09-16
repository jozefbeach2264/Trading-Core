import logging
import statistics
from typing import Any, Dict, List, Optional, Tuple
import time

logger = logging.getLogger(__name__)

class WallTracker:
    """Tracks resting whale liquidity BY PRICE LEVEL, and reports when a wall ends and how.

    Measured live on ETH-USDT-SWAP 2026-09-16: price levels persist — median 38 s, and levels of 200+
    contracts live a median of 77 s with 62% lasting over a minute. The previous implementation re-tested a
    depth-share threshold every tick against a denominator that itself moved every tick, so one motionless
    90-second whale order was counted as dozens of separate 0.1-second "walls" (median reported lifetime
    0.1 s, and 176 of 193 recorded walls "faded" without the order changing at all).

    Persistence is a property of the LEVEL. This tracker follows each price level for as long as it is in the
    book; the size threshold only decides whether the level is big enough to care about, and is compared
    against a slow baseline so ordinary churn cannot flicker it on and off.

    A wall ENDS when its price leaves the book or its size collapses, and the ending is classified:
      * absorbed — price traded through it: real liquidity that got eaten
      * pulled   — the size vanished while price never reached it: the trap being sprung
      * expired  — it simply left the visible window (usually because price walked away)
    """

    BASELINE_ALPHA = 0.02        # EWMA over ~50 ticks (~5 s at 10 ticks/s): slow enough not to chase churn
    BASELINE_LEVELS = 20         # measure "typical" size across this many levels beyond the touch
    COLLAPSE_FRACTION = 0.35     # size below this share of its peak counts as gone

    def __init__(self, size_multiple: float = 6.0, skip_levels: int = 3, min_age_s: float = 5.0,
                 max_distance_pct: float = 0.15):
        self.size_multiple = size_multiple
        self.skip_levels = skip_levels
        self.min_age_s = min_age_s
        # Only liquidity within striking distance of price can trap anyone. Levels parked far away are
        # inventory, not a trap, and on a 400-level book most of them are ordinary algorithmic churn.
        self.max_distance_pct = max_distance_pct
        self._levels: Dict[Tuple[str, float], Dict[str, Any]] = {}
        self._baseline: Dict[str, float] = {}

    def _update_baseline(self, side: str, quantities: List[float]) -> float:
        """Typical level size on this side, smoothed. Uses the median of the levels beyond the touch, which
        is robust to both the huge top-of-book and the dust levels deeper in."""
        window = quantities[: self.BASELINE_LEVELS]
        if not window:
            return self._baseline.get(side, 0.0)
        current = statistics.median(window)
        previous = self._baseline.get(side)
        smoothed = current if previous is None else previous + self.BASELINE_ALPHA * (current - previous)
        self._baseline[side] = smoothed
        return smoothed

    def update(self, depth: Dict[str, Any], now: float, mid: Optional[float] = None) -> Dict[str, Any]:
        """Advance the tracker one book snapshot.

        Returns {"bid_walls": [...], "ask_walls": [...], "events": [...]} where each event describes a wall
        that ended this tick: {"side", "price", "peak_qty", "lifetime_s", "outcome", "mid"}.
        """
        events: List[Dict[str, Any]] = []
        walls: Dict[str, List[Dict[str, Any]]] = {"bid_walls": [], "ask_walls": []}
        present = set()

        for side in ("bids", "asks"):
            levels = [(float(p), float(q)) for p, q in depth.get(side, [])]
            if not levels:
                continue
            body = levels[self.skip_levels:]
            baseline = self._update_baseline(side, [q for _, q in body])
            threshold = baseline * self.size_multiple
            for price, qty in body:
                if mid and self.max_distance_pct > 0 and abs(price - mid) / mid * 100.0 > self.max_distance_pct:
                    continue                                # parked far from price: not in play
                key = (side, price)
                present.add(key)
                state = self._levels.get(key)
                if state is None:
                    state = self._levels[key] = {"first_seen": now, "peak_qty": qty, "last_qty": qty,
                                                 "threshold": threshold}
                state["threshold"] = threshold              # keep it current; the baseline drifts slowly
                state["peak_qty"] = max(state["peak_qty"], qty)
                state["last_qty"] = qty
                age = now - state["first_seen"]
                if state["peak_qty"] >= threshold and age >= self.min_age_s and qty >= state["peak_qty"] * self.COLLAPSE_FRACTION:
                    walls["bid_walls" if side == "bids" else "ask_walls"].append(
                        {"price": price, "qty": qty, "peak_qty": state["peak_qty"], "age_s": round(age, 1),
                         "baseline": round(baseline, 2)})

        # levels that left the book, or whose size collapsed while still listed
        # Bounds of what we can actually see, per side. A level outside them has not disappeared — it has
        # simply fallen out of the visible window because price walked away, which must NOT read as a pull.
        visible = {}
        for side in ("bids", "asks"):
            prices = [float(p) for p, _ in depth.get(side, [])]
            if prices:
                visible[side] = (min(prices), max(prices))

        for key in list(self._levels):
            state = self._levels[key]
            side, price = key
            in_range = (mid is None or self.max_distance_pct <= 0
                        or abs(price - mid) / mid * 100.0 <= self.max_distance_pct)
            in_view = side in visible and visible[side][0] <= price <= visible[side][1] and in_range
            gone = key not in present
            collapsed = (not gone) and state["last_qty"] < state["peak_qty"] * self.COLLAPSE_FRACTION
            if not (gone or collapsed):
                continue
            if gone and not in_view:
                del self._levels[key]                       # out of view: no claim about what happened
                continue
            del self._levels[key]
            age = now - state["first_seen"]
            if state["peak_qty"] < state["threshold"] or age < self.min_age_s:
                continue                                    # never was a wall worth reporting
            if mid is not None:
                traded_through = mid <= price if side == "bids" else mid >= price
            else:
                traded_through = False
            outcome = "absorbed" if traded_through else "pulled"
            events.append({"side": "bid" if side == "bids" else "ask", "price": price,
                           "peak_qty": state["peak_qty"], "last_qty": state["last_qty"],
                           "lifetime_s": round(age, 1), "outcome": outcome, "mid": mid,
                           "distance_pct": round((price - mid) / mid * 100.0, 4) if mid else None})
        walls["events"] = events
        return walls


class OrderBookParser:
    """
    A utility class to parse raw order book data into actionable metrics
    like pressure walls, thinning, and spoofing profiles.
    """
    def __init__(self):
        self.last_log_time = 0

    def _log_bid_ask_counts(self, bids: List, asks: List) -> None:
        """Logs bid/ask counts periodically for user-facing output."""
        current_time = time.time()
        if current_time - self.last_log_time >= 30:
            logger.info("Heartbeat: Order book parser is active.", extra={"bids": len(bids), "asks": len(asks)})
            self.last_log_time = current_time

    def calculate_pressure_vectors(
        self, depth_20: Dict[str, Any], levels: int = 20
    ) -> Dict[str, float]:
        """
        Calculates the total volume for bids and asks up to a certain depth.
        """
        bids = depth_20.get('bids', [])[:levels]
        asks = depth_20.get('asks', [])[:levels]
        self._log_bid_ask_counts(bids, asks)

        if not bids or not asks:
            return {"bid_pressure": 0.0, "ask_pressure": 0.0, "total_pressure": 0.0}

        try:
            bid_pressure = sum(float(qty) for _, qty in bids)
            ask_pressure = sum(float(qty) for _, qty in asks)
            total_pressure = bid_pressure + ask_pressure
            return {
                "bid_pressure": bid_pressure,
                "ask_pressure": ask_pressure,
                "total_pressure": total_pressure
            }
        except (ValueError, TypeError) as e:
            logger.warning("Failed to calculate pressure vectors", extra={"error": str(e)})
            return {"bid_pressure": 0.0, "ask_pressure": 0.0, "total_pressure": 0.0}

    def find_wall_clusters(
        self, depth_20: Dict[str, Any], multiplier: float = 10.0
    ) -> Dict[str, Any]:
        """
        Identifies significant volume walls in the order book.
        """
        bids = depth_20.get('bids', [])[:50]
        asks = depth_20.get('asks', [])[:50]

        if not bids or not asks:
            return {"bid_walls": [], "ask_walls": []}

        try:
            top_bid_qty = float(bids[0][1])
            top_ask_qty = float(asks[0][1])
            bid_wall_threshold = top_bid_qty * multiplier
            ask_wall_threshold = top_ask_qty * multiplier

            bid_walls = [{"price": float(p), "qty": float(q)} for p, q in bids if float(q) >= bid_wall_threshold]
            ask_walls = [{"price": float(p), "qty": float(q)} for p, q in asks if float(q) >= ask_wall_threshold]

            # No fallback (review finding 3): fabricating a "wall" from the largest ordinary level turned
            # routine top-of-book churn on the 5-level feed into permanent SPOOFING blocks. No wall = [].
            return {"bid_walls": bid_walls, "ask_walls": ask_walls}
        except (ValueError, TypeError, IndexError) as e:
            logger.warning("Failed to find wall clusters", extra={"error": str(e)})
            return {"bid_walls": [], "ask_walls": []}

    @staticmethod
    def _mid_price(order_book: Dict[str, Any]) -> float:
        try:
            best_bid = max(float(p) for p, _ in order_book.get('bids', []))
            best_ask = min(float(p) for p, _ in order_book.get('asks', []))
            return (best_bid + best_ask) / 2.0
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _side_thinning(prev_walls: List[Dict[str, float]], current_levels: List, mid: float,
                       distance_percent: float) -> Dict[str, float]:
        """Compare each PREVIOUS wall with the quantity now resting at the SAME price.

        A wall whose price has left the visible window is skipped (unknown, not pulled), and the
        current snapshot's own wall threshold is irrelevant — so a wall does not "disappear" just
        because the top-of-book quantity (the threshold reference) changed between ticks."""
        zero = {"thin_rate": 0.0, "delta_pct": 0.0}
        if not prev_walls or not current_levels:
            return zero
        current_qty = {float(p): float(q) for p, q in current_levels}
        lowest, highest = min(current_qty), max(current_qty)
        prev_total = curr_total = 0.0
        for wall in prev_walls:
            price, qty = wall["price"], wall["qty"]
            if mid > 0 and abs(price - mid) / mid * 100.0 > distance_percent:
                continue
            if price < lowest or price > highest:
                continue
            prev_total += qty
            curr_total += current_qty.get(price, 0.0)
        if prev_total <= 0:
            return zero
        delta_pct = (curr_total - prev_total) / prev_total * 100.0
        return {"thin_rate": max(-delta_pct, 0.0), "delta_pct": delta_pct}

    def thinning_of_walls(self, previous_walls: Dict[str, Any], current_ob: Dict[str, Any]) -> Dict[str, Any]:
        """Spoof metric for tracked walls: compare each previously known wall with the quantity now resting at
        its price (per price level, so a wall never 'vanishes' because the threshold moved)."""
        zero = {"spoof_thin_rate": 0.0, "wall_delta_pct": 0.0, "bid_thin_rate": 0.0, "ask_thin_rate": 0.0}
        if not previous_walls:
            return zero
        mid = self._mid_price(current_ob)
        bid = self._side_thinning(previous_walls.get("bid_walls") or [], current_ob.get("bids", []), mid, 100.0)
        ask = self._side_thinning(previous_walls.get("ask_walls") or [], current_ob.get("asks", []), mid, 100.0)
        worst = bid if bid["thin_rate"] >= ask["thin_rate"] else ask
        return {"spoof_thin_rate": worst["thin_rate"], "wall_delta_pct": worst["delta_pct"],
                "bid_thin_rate": bid["thin_rate"], "ask_thin_rate": ask["thin_rate"]}

    def analyze_thinning_and_spoofing(
        self, previous_ob: Dict[str, Any], current_ob: Dict[str, Any], distance_percent: float = 2.0,
        multiplier: float = 10.0
    ) -> Dict[str, Any]:
        """
        Compares two consecutive order book snapshots to detect wall thinning (pulled liquidity).
        Walls are levels ≥ `multiplier` × top-of-book qty in the PREVIOUS snapshot, within
        `distance_percent` of mid. Both sides are analysed; spoof_thin_rate reports the worse side.
        """
        if not previous_ob.get('bids') or not current_ob.get('bids'):
            return {"spoof_thin_rate": 0.0, "wall_delta_pct": 0.0}

        try:
            prev_walls = self.find_wall_clusters(previous_ob, multiplier)
            mid = self._mid_price(previous_ob)
            bid = self._side_thinning(prev_walls["bid_walls"], current_ob.get('bids', []), mid, distance_percent)
            ask = self._side_thinning(prev_walls["ask_walls"], current_ob.get('asks', []), mid, distance_percent)
            worst = bid if bid["thin_rate"] >= ask["thin_rate"] else ask
            logger.debug("Spoofing metrics calculated", extra={"wall_delta_pct": worst["delta_pct"]})
            return {
                "spoof_thin_rate": worst["thin_rate"],
                "wall_delta_pct": worst["delta_pct"],
                "bid_thin_rate": bid["thin_rate"],
                "ask_thin_rate": ask["thin_rate"],
            }
        except (ValueError, TypeError) as e:
            logger.warning("Failed to analyze thinning/spoofing", extra={"error": str(e)})
            return {"spoof_thin_rate": 0.0, "wall_delta_pct": 0.0}
