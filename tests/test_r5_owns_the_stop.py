"""Rolling5 owns the stop.

The operator's rule (2026-09-16): *"the other 2 modules can't be the reason R5 shuts down"* and *"setting the
SL is part of the prediction model of the R5 — if the SL isn't considered correctly then the whole thing falls
apart"*.

Scalpel and TrapX find the trade. Their stops come from candle geometry — a fraction of the previous candle's
range, or a fixed dollar offset — which has nothing to do with how far price is actually expected to move.
Measured live on 2026-09-16, Scalpel set stops of 0.05%-0.14% while price moved 0.157% against the one losing
trade: the stop sat inside Rolling5's own predicted noise, so ordinary wander killed the trade and the forecast
was never tested. Rolling5 now places the stop beyond the predicted adverse band.
"""
from types import SimpleNamespace

import pytest

from conftest import run
from position_manager import apply_predicted_stop, band_half_width, plan_exits, predicted_stop
from strategy.ai_strategy import AIStrategy
from tests.test_ai_strategy import _AIClient, _Forecaster, _Gate, _Memory, _Simulator, fresh_state

CFG = SimpleNamespace(trail_breakeven_r=0.5, trail_distance_r=1.0, target_extend_r=1.5, exit_reversal_risk=0.8,
                      r5_stop_horizon_candles=5, r5_stop_band_multiple=1.5, r5_trail_band_multiple=1.0)
BAND = {f"c{i}": {"high": 3000.0 + 2.0 * i, "low": 3000.0 - 2.0 * i} for i in range(1, 7)}   # half = 2*i


def test_band_half_width_reads_the_requested_horizon():
    assert band_half_width(BAND, 5) == pytest.approx(10.0)
    assert band_half_width(BAND, 1) == pytest.approx(2.0)
    assert band_half_width(BAND, 9) is None          # beyond the forecast horizon
    assert band_half_width({}, 5) is None


def test_the_stop_sits_beyond_the_predicted_adverse_wander():
    """Half the c5 band is 10, so at 1.5x the stop is 15 away — price has to do something the forecast did
    not predict to reach it."""
    assert predicted_stop("LONG", 3000.0, BAND, CFG) == pytest.approx(2985.0)
    assert predicted_stop("SHORT", 3000.0, BAND, CFG) == pytest.approx(3015.0)


def test_a_module_stop_inside_the_predicted_noise_is_widened():
    signal = {"direction": "LONG", "entry_price": 3000.0, "stop_loss": 2997.0}   # 3 wide, band wants 15
    note = apply_predicted_stop(signal, BAND, CFG)
    assert signal["stop_loss"] == pytest.approx(2985.0)
    assert note and "widened the stop" in note


def test_a_module_stop_already_wider_than_the_prediction_is_left_alone():
    """Only ever widens. A narrower R5 stop would buy a bigger position for the same risk budget and hand the
    fee a bigger notional to feed on."""
    signal = {"direction": "LONG", "entry_price": 3000.0, "stop_loss": 2950.0}   # 50 wide, band wants 15
    assert apply_predicted_stop(signal, BAND, CFG) is None
    assert signal["stop_loss"] == pytest.approx(2950.0)


def test_short_is_mirrored():
    signal = {"direction": "SHORT", "entry_price": 3000.0, "stop_loss": 3003.0}
    apply_predicted_stop(signal, BAND, CFG)
    assert signal["stop_loss"] == pytest.approx(3015.0)


def test_no_band_leaves_the_signal_untouched():
    signal = {"direction": "LONG", "entry_price": 3000.0, "stop_loss": 2997.0}
    assert apply_predicted_stop(signal, {}, CFG) is None
    assert signal["stop_loss"] == pytest.approx(2997.0)


def test_the_trail_follows_predicted_noise_not_a_fixed_risk_multiple():
    """The fixed 0.5R giveback cost exactly 0.500R on every live trade. The trail now gives back the band."""
    position = {"direction": "LONG", "entry_price": 3000.0, "stop_loss": 2985.0, "take_profit": 3100.0,
                "initial_risk": 15.0, "best_price": 3000.0}
    forecast = {"reversal_likelihood_score": 0.0, "forecast": BAND}
    stop, _target, best, _notes = plan_exits(position, 3040.0, forecast, CFG)
    assert best == pytest.approx(3040.0)
    assert stop == pytest.approx(3030.0)              # best - 1.0 x band half (10), not best - 1.0R (15)


def test_the_trail_falls_back_to_the_risk_multiple_without_a_band():
    position = {"direction": "LONG", "entry_price": 3000.0, "stop_loss": 2985.0, "take_profit": 3100.0,
                "initial_risk": 15.0, "best_price": 3000.0}
    forecast = {"reversal_likelihood_score": 0.0, "forecast": {}}
    stop, _target, _best, notes = plan_exits(position, 3040.0, forecast, CFG)
    assert stop == pytest.approx(3025.0)              # best - trail_distance_r(1.0) x risk(15)
    assert any("no band" in n for n in notes)


# --- the whole signal path -------------------------------------------------------------------------------

class _TightRouter:
    """Scalpel's real shape: a stop a few cents wide, taken from the previous candle's range."""
    async def route_and_generate_signal(self, _ms, _report):
        return {"trade_type": "Scalpel", "direction": "LONG", "entry_price": 3000.0,
                "stop_loss": 2998.5, "take_profit": 3030.0}


def test_rolling5_widens_scalpels_stop_before_the_trade_is_judged_or_sized(config):
    """End to end: the stop the guards see, and that sizing will use, is Rolling5's — not Scalpel's."""
    forecaster = _Forecaster()
    forecaster.band = BAND
    ai = _AIClient()
    strategy = AIStrategy(config, _TightRouter(), forecaster, ai, _Simulator(), _Memory())
    result = run(strategy.generate_signal(fresh_state(config), _Gate()))
    assert len(ai.packets) == 1, "the trade should reach the model, not be refused"
    # 1.5 x the c5 half-width of 10 = 15 below a 3000 entry, and it is Rolling5's number that survives
    assert result["stop_loss"] == pytest.approx(2985.0)
    assert result["stop_loss"] != 2998.5, "Scalpel's geometry must not decide when the trade dies"
