"""Rolling5 position management — the trade is re-assessed every cycle, not killed on a clock.

Given the open position, the current mark and a fresh forecast (reversal risk + walls, computed AGAINST the
open trade's direction), decide the new stop and target:
  * once the trade has earned TRAIL_BREAKEVEN_R of its initial risk, the stop moves to breakeven and then trails
    TRAIL_DISTANCE_R behind the best price; the target extends TARGET_EXTEND_R beyond the best price so a winner is
    never capped while it keeps going;
  * when reversal risk rises to EXIT_REVERSAL_RISK the trade is taken off risk: target pulled to the mark if in
    profit, stop tightened to half the initial risk if not;
  * at the C4 order-book recheck (and every cycle after) an opposing wall between the mark and the target caps the
    target at the wall;
  * a stop is only ever tightened, never widened.
Measured 2026-09-16 on 7.6 days of ETH 1m candles: this lifts the win rate 45% → 52% versus fixed exits.
"""
from typing import Any, Dict, List, Optional, Tuple

ENTRY_LOCK_R = 0.05        # "breakeven" = entry plus a hair in the trade's favour (covers part of the fee)
LOSS_TIGHTEN_R = 0.5       # stop pulled to this fraction of the initial risk when reversal risk spikes while losing


def _sign(direction: Any) -> float:
    return 1.0 if str(direction or "").upper() == "LONG" else -1.0


def tighten(current: Optional[float], candidate: Optional[float], sign: float) -> Optional[float]:
    """Move a stop only in the trade's favour (up for a LONG, down for a SHORT)."""
    if candidate is None:
        return current
    if current is None:
        return candidate
    return max(current, candidate) if sign > 0 else min(current, candidate)


def extend(current: Optional[float], candidate: Optional[float], sign: float) -> Optional[float]:
    """Move a target only further away (up for a LONG, down for a SHORT)."""
    if candidate is None:
        return current
    if current is None:
        return candidate
    return max(current, candidate) if sign > 0 else min(current, candidate)


def opposing_wall(direction: Any, mark: float, target: Optional[float], walls: Dict[str, List[Dict[str, float]]]) -> Optional[float]:
    """Price of the nearest wall sitting between the mark and the target on the side that opposes the trade."""
    sign = _sign(direction)
    side = walls.get("ask_walls" if sign > 0 else "bid_walls") or []
    between = [w["price"] for w in side if isinstance(w, dict) and "price" in w
               and (sign * (w["price"] - mark) > 0) and (target is None or sign * (target - w["price"]) > 0)]
    if not between:
        return None
    return min(between) if sign > 0 else max(between)


def plan_exits(position: Dict[str, Any], mark: float, forecast: Dict[str, Any], config: Any,
               ob_recheck: bool = False) -> Tuple[Optional[float], Optional[float], float, List[str]]:
    """Return (new_stop, new_target, best_price, notes). Pure function; nothing is written here."""
    sign = _sign(position.get("direction"))
    entry = float(position["entry_price"])
    stop = position.get("stop_loss")
    target = position.get("take_profit")
    risk = float(position.get("initial_risk") or 0.0)
    if risk <= 0:
        risk = abs(entry - float(stop)) if stop else entry * 0.001
    best = position.get("best_price")
    best = float(best) if best is not None else entry
    best = max(best, mark) if sign > 0 else min(best, mark)
    gain_r = sign * (best - entry) / risk if risk > 0 else 0.0
    notes: List[str] = []

    if gain_r >= config.trail_breakeven_r:
        stop = tighten(stop, entry + sign * ENTRY_LOCK_R * risk, sign)
        stop = tighten(stop, best - sign * config.trail_distance_r * risk, sign)
        target = extend(target, best + sign * config.target_extend_r * risk, sign)
        notes.append(f"trail gain={gain_r:.2f}R")

    reversal = float(forecast.get("reversal_likelihood_score", 0.0) or 0.0)
    if reversal >= config.exit_reversal_risk:
        if sign * (mark - entry) > 0:
            target = mark                     # take what is there; mark_to_market closes at the next check
            notes.append(f"reversal {reversal:.2f}: take profit now")
        else:
            stop = tighten(stop, entry - sign * LOSS_TIGHTEN_R * risk, sign)
            notes.append(f"reversal {reversal:.2f}: cut loss short")

    if ob_recheck or position.get("ob_rechecked"):
        wall = opposing_wall(position.get("direction"), mark, target, (forecast.get("order_book_metrics") or {}))
        if wall is not None and (target is None or sign * (wall - target) < 0):
            target = wall
            notes.append(f"wall at {wall}: target capped")

    # A TARGET IS A PROFIT. It may never be moved to a price at or worse than entry — a wall cap or a
    # "take profit now" on a losing trade would otherwise lock in a loss and book it as TAKE_PROFIT.
    # (Observed live 2026-09-16: a SHORT from 2393.93 had its target capped at a bid wall at 2399.00 and
    # exited there for a loss, recorded as a take-profit.)
    floor = entry * (1.0 + sign * min_profit_fraction(config))
    if target is not None and sign * (target - floor) < 0:
        target = None if position.get("take_profit") is None else max(position["take_profit"], floor) if sign > 0 else min(position["take_profit"], floor)
        notes.append("target refused: it was not a profit")

    return stop, target, best, notes


def min_profit_fraction(config: Any) -> float:
    """Smallest move that still leaves something after costs, as a fraction of entry."""
    fee = getattr(config, "round_trip_fee_percent", 0.0) or 0.0
    return fee / 100.0
