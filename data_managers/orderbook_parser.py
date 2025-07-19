import logging
from typing import List, Tuple, Dict, Any
import time

logger = logging.getLogger(__name__)

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
        bids = depth_20.get('bids', [])
        asks = depth_20.get('asks', [])

        if not bids or not asks:
            return {"bid_walls": [], "ask_walls": []}

        try:
            top_bid_qty = float(bids[0][1])
            top_ask_qty = float(asks[0][1])
            bid_wall_threshold = top_bid_qty * multiplier
            ask_wall_threshold = top_ask_qty * multiplier

            bid_walls = [{"price": float(p), "qty": float(q)} for p, q in bids if float(q) >= bid_wall_threshold]
            ask_walls = [{"price": float(p), "qty": float(q)} for p, q in asks if float(q) >= ask_wall_threshold]
            
            return {"bid_walls": bid_walls, "ask_walls": ask_walls}
        except (ValueError, TypeError, IndexError) as e:
            logger.warning("Failed to find wall clusters", extra={"error": str(e)})
            return {"bid_walls": [], "ask_walls": []}

    def analyze_thinning_and_spoofing(
        self, previous_ob: Dict[str, Any], current_ob: Dict[str, Any], distance_percent: float = 2.0
    ) -> Dict[str, Any]:
        """
        Compares two consecutive order book snapshots to detect wall thinning.
        """
        # The following verbose log has been removed to prevent console flooding.
        # logger.debug("Analyzing thinning/spoofing: prev_ob=%s, curr_ob=%s", previous_ob, current_ob)
        
        if not previous_ob.get('bids') or not current_ob.get('bids'):
            return {"spoof_thin_rate": 0.0, "wall_delta_pct": 0.0}
            
        try:
            prev_walls = self.find_wall_clusters(previous_ob)
            curr_walls = self.find_wall_clusters(current_ob)
            
            prev_bid_wall_qty = sum(w['qty'] for w in prev_walls['bid_walls'])
            curr_bid_wall_qty = sum(w['qty'] for w in curr_walls['bid_walls'])
            
            wall_delta = curr_bid_wall_qty - prev_bid_wall_qty
            wall_delta_pct = (wall_delta / prev_bid_wall_qty) * 100 if prev_bid_wall_qty > 0 else 0
            
            logger.debug("Spoofing metrics calculated", extra={"wall_delta_pct": wall_delta_pct})
            
            return {
                "spoof_thin_rate": -wall_delta_pct if wall_delta < 0 else 0.0,
                "wall_delta_pct": wall_delta_pct
            }
        except (ValueError, TypeError) as e:
            logger.warning("Failed to analyze thinning/spoofing", extra={"error": str(e)})
            return {"spoof_thin_rate": 0.0, "wall_delta_pct": 0.0}
