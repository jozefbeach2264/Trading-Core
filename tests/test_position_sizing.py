"""Sizing must fix the LOSS, not the bet. Measured 2026-09-16: with a fixed 10% margin at 200x, a 0.487% stop
cost 12.9% of the account in one trade, because the loss scales with how wide the stop is."""
from conftest import make_market_state
from system_managers.trade_executor import TradeExecutor


def _ex(config):
    config.leverage = 200
    config.risk_cap_percent = 0.10
    config.risk_per_trade_percent = 2.0
    return TradeExecutor(config, make_market_state(config), None)


def test_loss_at_the_stop_is_constant_whatever_the_stop_width(config):
    ex = _ex(config)
    for stop_pct in (0.10, 0.25, 0.487, 1.0):
        entry = 3000.0
        s = ex.position_size(100.0, entry, entry * (1 - stop_pct / 100))
        assert abs(s["risk_at_stop"] - 2.0) < 1e-6, f"{stop_pct}% stop risked {s['risk_at_stop']}"


def test_a_wide_stop_means_a_smaller_position_not_a_bigger_loss(config):
    ex = _ex(config)
    tight = ex.position_size(100.0, 3000.0, 3000.0 * 0.999)     # 0.1% stop
    wide = ex.position_size(100.0, 3000.0, 3000.0 * 0.995)      # 0.5% stop
    assert wide["notional"] < tight["notional"] / 4
    assert abs(tight["risk_at_stop"] - wide["risk_at_stop"]) < 1e-6


def test_the_ten_percent_margin_rule_is_still_a_hard_cap(config):
    ex = _ex(config)
    s = ex.position_size(100.0, 3000.0, 3000.0 * 0.99999)       # a stop so tight risk-sizing wants a huge position
    assert s["margin"] <= 100.0 * 0.10 + 1e-9 and s["sizing_mode"] == "risk_based_capped"


def test_no_stop_falls_back_to_the_margin_cap(config):
    ex = _ex(config)
    s = ex.position_size(100.0, 3000.0, None)
    assert s["sizing_mode"] == "margin_cap" and abs(s["margin"] - 10.0) < 1e-9


def test_risk_sizing_can_be_switched_off(config):
    ex = _ex(config)
    config.risk_per_trade_percent = 0
    s = ex.position_size(100.0, 3000.0, 3000.0 * 0.995)
    assert s["sizing_mode"] == "margin_cap" and abs(s["margin"] - 10.0) < 1e-9


def test_the_trade_that_cost_129_percent_now_costs_2(config):
    """Replay the real 2026-09-16 LONG: account 72.60, entry 2392.98, stop 2381.32 (0.487%)."""
    ex = _ex(config)
    s = ex.position_size(72.60, 2392.98, 2381.32)
    assert abs(s["risk_at_stop"] - 72.60 * 0.02) < 1e-6
    assert 100 * s["risk_at_stop"] / 72.60 < 2.5, "one stop-out must not cost double digits of the account"
    assert s["notional"] < 1452.05 / 4, "the old sizing used a notional 4x too large for that stop"
