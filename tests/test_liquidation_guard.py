"""What makes a trade valid.

The operator's rule (2026-09-16): *"if the trade doesn't zero the wallet or a set allowed capital amount then
the trade is valid"*, and *"we trade in cross mode so we don't liquidate in 0.5% — we liquidate based off the
wallet size"*.

That matters because the guard used to compute liquidation as 100/LEVERAGE, which is the ISOLATED-margin rule:
the move that consumes the position's own posted margin. Under CROSS margin the whole wallet is collateral, so
a small position against a healthy wallet survives a very long way out no matter what the leverage says. On
2026-09-16 the isolated rule refused 57 of 60 signals for stops that were nowhere near liquidation.
"""
import pytest

from conftest import run
from config.config import Config
from strategy.ai_strategy import AIStrategy
from tests.test_ai_strategy import _AIClient, _Forecaster, _Gate, _Memory, _Simulator, fresh_state


class _Router:
    def __init__(self, stop_pct):
        self.stop_pct = stop_pct

    async def route_and_generate_signal(self, _ms, _report):
        e = 3000.0
        return {"trade_type": "Scalpel", "direction": "LONG", "entry_price": e,
                "stop_loss": e * (1 - self.stop_pct / 100), "take_profit": e * 1.01}


def _run(config, stop_pct):
    ai = _AIClient()
    strategy = AIStrategy(config, _Router(stop_pct), _Forecaster(), ai, _Simulator(), _Memory())
    return run(strategy.generate_signal(fresh_state(config), _Gate())), ai


# --- the model -------------------------------------------------------------------------------------------

def test_cross_liquidation_is_set_by_wallet_versus_notional_not_by_leverage(config):
    """The headline correction. Risk-based sizing fixes the LOSS at 2% of the wallet, so a 4% stop buys a
    position worth half the wallet — and half-a-wallet of notional is liquidated ~200% away, not 0.5%."""
    config.margin_mode = "cross"
    four_percent_stop = 0.04
    assert config.notional_to_equity_ratio(four_percent_stop) == pytest.approx(0.5, rel=1e-6)
    # (equity - maintenance) / notional = (1 - 0.005*0.5) / 0.5, expressed as a fraction of entry
    assert config.liquidation_distance_fraction(four_percent_stop) == pytest.approx(2.0 - 0.005, rel=1e-6)


def test_leverage_does_not_move_the_cross_liquidation_point(config):
    """Since sizing became risk-based, leverage sets margin posted — not size, not edge, not liquidation."""
    config.margin_mode = "cross"
    stop = 0.01
    config.leverage = 200
    at_200 = config.liquidation_distance_fraction(stop)
    config.leverage = 100
    assert config.liquidation_distance_fraction(stop) == pytest.approx(at_200, rel=1e-9)


def test_isolated_liquidation_still_follows_leverage(config):
    config.margin_mode = "isolated"
    config.leverage = 200
    assert config.liquidation_distance_fraction(0.01) == pytest.approx(0.005)
    config.leverage = 25
    assert config.liquidation_distance_fraction(0.01) == pytest.approx(0.04)


def test_a_stop_out_never_costs_more_than_the_risk_setting(config):
    """Risk-based sizing is what makes the operator's rule safe: whatever the stop width, the loss is capped."""
    for stop in (0.0005, 0.005, 0.02, 0.05, 0.10):
        assert config.loss_fraction_at_stop(stop) <= config.risk_per_trade_percent / 100.0 + 1e-12


# --- the guard -------------------------------------------------------------------------------------------

def test_the_wide_stop_the_old_guard_refused_is_valid_under_cross_margin(config):
    """The 4.67% stop that the isolated rule called '9.3x beyond reach'. It costs 2% of the wallet, so by the
    operator's rule it is a valid trade."""
    config.margin_mode = "cross"
    config.leverage = 200
    result, ai = _run(config, 4.67)
    assert "LIQUIDATION" not in str(result.get("reason"))
    assert len(ai.packets) == 1


def test_a_stop_that_would_exceed_the_allowed_capital_is_refused(config):
    """The other half of the rule: a set allowed capital amount. Allow 1% but risk 2% and the trade is refused."""
    config.margin_mode = "cross"
    config.max_trade_loss_percent = 1.0
    result, ai = _run(config, 0.35)
    assert result["reason"].startswith("Rejected - STOP BEYOND LIQUIDATION")
    assert "of the wallet" in result["reason"] and "1% allowed" in result["reason"]
    assert ai.packets == []


def test_a_stop_liquidation_would_beat_is_refused(config):
    """A stop is fiction if liquidation arrives first. Cross margin makes that rare, not impossible — here the
    maintenance margin alone exceeds the equity behind the position."""
    config.margin_mode = "cross"
    config.maintenance_margin_percent = 300.0
    result, ai = _run(config, 0.35)
    assert result["reason"].startswith("Rejected - STOP BEYOND LIQUIDATION")
    assert "liquidation would come first" in result["reason"]
    assert ai.packets == []


def test_isolated_margin_still_refuses_the_unreachable_stop(config):
    config.margin_mode = "isolated"
    config.leverage = 200                      # liquidation 0.50%, buffer 0.8x = 0.40%
    result, ai = _run(config, 4.67)
    assert result["reason"].startswith("Rejected - STOP BEYOND LIQUIDATION")
    assert "liquidation would come first" in result["reason"] and ai.packets == []


# --- start-up validation ---------------------------------------------------------------------------------

def test_isolated_settings_where_no_stop_can_work_are_refused_at_start_up(monkeypatch):
    """At 200x isolated with taker fees the workable band is 0.32%-0.40%. Make the fee floor exceed it."""
    monkeypatch.setenv("MARGIN_MODE", "isolated")
    monkeypatch.setenv("LEVERAGE", "200")
    monkeypatch.setenv("MIN_STOP_FEE_MULTIPLE", "4")      # demands >= 0.64%, liquidation caps at 0.40%
    with pytest.raises(ValueError, match="No stop width"):
        Config()


def test_cross_margin_has_no_such_ceiling_to_collide_with(monkeypatch):
    """The same settings are fine under cross margin: there is no fixed leverage-derived ceiling."""
    monkeypatch.setenv("MARGIN_MODE", "cross")
    monkeypatch.setenv("LEVERAGE", "200")
    monkeypatch.setenv("MIN_STOP_FEE_MULTIPLE", "4")
    assert Config().margin_mode == "cross"
