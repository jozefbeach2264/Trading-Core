import logging
from typing import List, Tuple, Dict, Any
import time

logger = logging.getLogger(__name__)

class WallTracker:
    """Whale-sized resting liquidity, measured on the 50-level book (2026-09-16 live calibration).

    A wall is a level that (1) sits beyond the best `skip_levels` (the touch holds ~23% of depth just by being the
    touch), (2) holds at least `min_share` of the side's visible depth (the largest non-touch level is ~13% at the
    median, ~20% at the 90th percentile) and (3) has been there for at least `min_age_s` (most outsized levels
    live ~1 s; whales park size). Neighbour-relative tests were useless: the window is mostly dust levels."""

    def __init__(self, min_share: float = 0.10, skip_levels: int = 3, min_age_s: float = 5.0):
        self.min_share = min_share
        self.skip_levels = skip_levels
        self.min_age_s = min_age_s
        self._first_seen: Dict[Tuple[str, float], float] = {}

    def update(self, depth: Dict[str, Any], now: float) -> Dict[str, Any]:
        result = {"bid_walls": [], "ask_walls": []}
        alive = set()
        for side in ("bids", "asks"):
            levels = [(float(p), float(q)) for p, q in depth.get(side, [])]
            total = sum(q for _, q in levels)
            if total <= 0:
                continue
            for price, qty in levels[self.skip_levels:]:
                if qty / total < self.min_share:
                    continue
                key = (side, price)
                alive.add(key)
                born = self._first_seen.setdefault(key, now)
                age = now - born
                if age >= self.min_age_s:
                    result["bid_walls" if side == "bids" else "ask_walls"].append(
                        {"price": price, "qty": qty, "share": round(qty / total, 4), "age_s": round(age, 1)})
        for key in list(self._first_seen):
            if key not in alive:
                del self._first_seen[key]
        return result


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
