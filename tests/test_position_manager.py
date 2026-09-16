"""Rolling5 management: trail, extend, take off risk, cap at a wall, never widen a stop."""
from types import SimpleNamespace

from position_manager import opposing_wall, plan_exits, tighten

CFG = SimpleNamespace(trail_breakeven_r=0.5, trail_distance_r=1.0, target_extend_r=1.5, exit_reversal_risk=0.8)


def _pos(direction="LONG", entry=3000.0, stop=2990.0, target=3015.0, best=None, risk=10.0):
    # initial_risk is fixed at open time in the real record; it must not follow the moved stop
    return {"direction": direction, "entry_price": entry, "stop_loss": stop, "take_profit": target,
            "initial_risk": risk, "best_price": best or entry}


def test_nothing_changes_before_the_trade_has_earned_it():
    stop, target, best, notes = plan_exits(_pos(), 3003.0, {"reversal_likelihood_score": 0.2}, CFG)
    assert (stop, target) == (2990.0, 3015.0) and best == 3003.0 and notes == []


def test_breakeven_then_trailing_stop_and_extending_target():
    stop, target, best, notes = plan_exits(_pos(), 3005.0, {"reversal_likelihood_score": 0.2}, CFG)   # +0.5R
    assert stop == 3000.5 and target == 3020.0 and best == 3005.0          # BE + 0.05R lock, target best + 1.5R
    stop, target, best, _ = plan_exits(_pos(stop=stop, target=target, best=best), 3030.0, {"reversal_likelihood_score": 0.2}, CFG)
    assert stop == 3020.0 and target == 3045.0                             # trail 1R behind, extend 1.5R beyond
    stop2, target2, best2, _ = plan_exits(_pos(stop=stop, target=target, best=best), 3022.0, {"reversal_likelihood_score": 0.2}, CFG)
    assert stop2 == 3020.0 and target2 == 3045.0 and best2 == 3030.0       # pullback: nothing loosens


def test_short_mirrors_long():
    stop, target, best, _ = plan_exits(_pos("SHORT", 3000.0, 3010.0, 2985.0), 2995.0, {"reversal_likelihood_score": 0.2}, CFG)
    assert stop == 2999.5 and target == 2980.0 and best == 2995.0


def test_high_reversal_risk_takes_profit_or_cuts_loss():
    stop, target, _, notes = plan_exits(_pos(), 3004.0, {"reversal_likelihood_score": 0.9}, CFG)
    assert target == 3004.0 and "take profit now" in notes[-1]
    stop, target, _, notes = plan_exits(_pos(), 2996.0, {"reversal_likelihood_score": 0.9}, CFG)
    assert stop == 2995.0 and target == 3015.0 and "cut loss short" in notes[-1]


def test_opposing_wall_caps_the_target_at_the_recheck():
    walls = {"ask_walls": [{"price": 3012.0, "qty": 50.0}, {"price": 3030.0, "qty": 80.0}], "bid_walls": [{"price": 2995.0, "qty": 40.0}]}
    assert opposing_wall("LONG", 3003.0, 3015.0, walls) == 3012.0
    assert opposing_wall("SHORT", 3003.0, 2985.0, walls) == 2995.0
    assert opposing_wall("LONG", 3003.0, 3010.0, walls) is None           # wall beyond the target is irrelevant
    _, target, _, notes = plan_exits(_pos(), 3003.0, {"reversal_likelihood_score": 0.1, "order_book_metrics": walls}, CFG, ob_recheck=True)
    assert target == 3012.0 and "target capped" in notes[-1]


def test_stops_never_widen():
    assert tighten(2990.0, 2985.0, 1.0) == 2990.0 and tighten(2990.0, 2995.0, 1.0) == 2995.0
    assert tighten(3010.0, 3015.0, -1.0) == 3010.0 and tighten(3010.0, 3005.0, -1.0) == 3005.0
