"""Rolling5 position management — the trade is re-assessed every cycle, not killed on a clock.

ROLLING5 OWNS THE STOP. Scalpel and TrapX say where and which way to trade; they do not get to decide when the
trade dies. Their stops come from candle geometry and have nothing to do with how far price is expected to move,
so when that geometry lands inside R5's own predicted band the trade is killed by movement the forecast
anticipated and the forecast never gets to be right or wrong. predicted_stop() places the stop beyond the
predicted adverse wander; apply_predicted_stop() widens an incoming signal to it before the trade is sized.

Given the open position, the current mark and a fresh forecast (reversal risk + walls, computed AGAINST the
open trade's direction), decide the new stop and target:
  * once the trade has earned TRAIL_BREAKEVEN_R of its initial risk, the stop moves to breakeven and then trails
    the PREDICTED noise behind the best price (R5_TRAIL_BAND_MULTIPLE x the band half-width, falling back to
    TRAIL_DISTANCE_R when no band is available); the target extends TARGET_EXTEND_R beyond the best price so a
    winner is never capped while it keeps going;
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


def band_half_width(band: Optional[Dict[str, Dict[str, float]]], horizon: int) -> Optional[float]:
    """Half the width of Rolling5's predicted price band at `horizon` candles — how far price is expected to
    wander either way by then. Anchor-independent, so it can be applied to any entry price."""
    if not band:
        return None
    cell = band.get(f"c{horizon}")
    if not isinstance(cell, dict) or "high" not in cell or "low" not in cell:
        return None
    half = (float(cell["high"]) - float(cell["low"])) / 2.0
    return half if half > 0 else None


def predicted_stop(direction: Any, entry: float, band: Optional[Dict[str, Dict[str, float]]],
                   config: Any) -> Optional[float]:
    """The stop Rolling5's forecast implies: far enough beyond the predicted adverse wander that the trade is
    stopped only when the forecast is WRONG.

    This is the whole point of the module. Scalpel and TrapX size their stops from candle geometry — a
    fraction of the previous candle's range, or a fixed dollar offset — which has nothing to do with how far
    price is actually expected to move. When that geometry lands inside R5's own predicted noise the trade is
    killed by ordinary movement the forecast anticipated, and the forecast never gets to be right or wrong.
    """
    sign = _sign(direction)
    half = band_half_width(band, config.r5_stop_horizon_candles)
    if half is None or entry <= 0:
        return None
    return entry - sign * half * config.r5_stop_band_multiple


def apply_predicted_stop(signal: Dict[str, Any], band: Optional[Dict[str, Dict[str, float]]],
                         config: Any) -> Optional[str]:
    """Widen a signal's stop to Rolling5's predicted stop, in place. Returns a note when it moved.

    Only ever WIDENS. A narrower R5 stop would buy a larger position for the same risk budget and hand the
    fee a bigger notional to feed on, so the entry module's stop stays the floor.
    """
    entry = float(signal.get("entry_price") or 0.0)
    proposed = predicted_stop(signal.get("direction"), entry, band, config)
    if proposed is None:
        return None
    sign = _sign(signal.get("direction"))
    current = signal.get("stop_loss")
    if current is not None and sign * (float(current) - proposed) <= 0:
        return None                                   # the module's stop is already at least this wide
    signal["stop_loss"] = proposed
    was = f"{abs(float(current) - entry) / entry * 100:.4f}%" if current is not None else "none"
    return (f"Rolling5 widened the stop from {was} to {abs(proposed - entry) / entry * 100:.4f}% "
            f"(predicted {config.r5_stop_horizon_candles}-candle band x{config.r5_stop_band_multiple:g})")


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
        # The trail follows the PREDICTED noise, not a fixed multiple of the original risk. Measured live
        # 2026-09-16: a fixed 0.5R giveback cost exactly 0.500R on every trade (capture 53%, 38%, 27% as the
        # trades ran shorter), because on stops this tight half a risk-unit is ordinary one-minute wander.
        half = band_half_width((forecast or {}).get("forecast"), config.r5_stop_horizon_candles)
        trail_distance = half * config.r5_trail_band_multiple if half else config.trail_distance_r * risk
        stop = tighten(stop, entry + sign * ENTRY_LOCK_R * risk, sign)
        stop = tighten(stop, best - sign * trail_distance, sign)
        target = extend(target, best + sign * config.target_extend_r * risk, sign)
        notes.append(f"trail gain={gain_r:.2f}R" + ("" if half else " (no band; fixed R)"))

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
