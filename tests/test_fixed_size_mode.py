"""Fixed-size mode: "$10 per trade and we allow it to move against us by $10 before close".

Margin is a fixed number of dollars instead of a share of the account, and the stop sits wherever that many
dollars are lost. The stop stops being a prediction and becomes arithmetic: a $1,000 position ($10 at 100x)
loses $10 when price moves 1% against it. That deliberately overrides both the entry module's geometry and
Rolling5's forecast band — the operator is pinning the risk rather than inferring it.
"""
import pytest

from conftest import run, make_market_state
from config.config import Config
from position_manager import apply_fixed_stop
from system_managers.trade_executor import TradeExecutor
from tests.test_trade_executor import _Memory


@pytest.fixture
def fixed(config):
    config.fixed_margin_usd = 10.0
    config.max_loss_usd = 10.0
    config.leverage = 100
    return config


def test_the_stop_is_where_the_dollar_allowance_runs_out(fixed):
    assert fixed.fixed_size_mode is True
    assert fixed.fixed_notional == pytest.approx(1000.0)          # $10 at 100x
    assert fixed.fixed_stop_fraction == pytest.approx(0.01)       # $10 of $1,000 is 1%


def test_the_allowance_and_the_leverage_both_move_the_stop(fixed):
    fixed.max_loss_usd = 5.0
    assert fixed.fixed_stop_fraction == pytest.approx(0.005)      # half the dollars, half the distance
    fixed.max_loss_usd = 10.0
    fixed.leverage = 200
    assert fixed.fixed_stop_fraction == pytest.approx(0.005)      # twice the notional, half the distance


def test_the_stop_is_placed_at_that_distance_either_way(fixed):
    long_signal = {"direction": "LONG", "entry_price": 3000.0, "stop_loss": 2999.0}
    note = apply_fixed_stop(long_signal, fixed)
    assert long_signal["stop_loss"] == pytest.approx(2970.0)      # 1% below
    assert note and "$10" in note

    short_signal = {"direction": "SHORT", "entry_price": 3000.0, "stop_loss": 3001.0}
    apply_fixed_stop(short_signal, fixed)
    assert short_signal["stop_loss"] == pytest.approx(3030.0)


def test_it_overrides_a_wider_module_stop_too(fixed):
    """Unlike Rolling5's band, which only ever widens, this is the operator pinning the number."""
    signal = {"direction": "LONG", "entry_price": 3000.0, "stop_loss": 2800.0}   # far wider than 1%
    apply_fixed_stop(signal, fixed)
    assert signal["stop_loss"] == pytest.approx(2970.0)
    assert signal["module_stop"] == pytest.approx(2800.0), "what the module wanted is still recorded"


def test_the_position_posts_exactly_the_fixed_margin(fixed, tmp_path):
    fixed.dry_run_mode = True
    fixed.simulation_state_file_path = str(tmp_path / "sim.json")
    ex = TradeExecutor(fixed, make_market_state(fixed), None)
    ex.memory_tracker = _Memory()
    sizing = ex.position_size(balance=96.0, entry_price=3000.0, stop_loss=2970.0)
    assert sizing["margin"] == pytest.approx(10.0)
    assert sizing["notional"] == pytest.approx(1000.0)
    assert sizing["sizing_mode"] == "fixed"
    assert sizing["risk_at_stop"] == pytest.approx(10.0), "a stop-out costs exactly the allowance"


def test_it_never_posts_more_margin_than_the_wallet_holds(fixed, tmp_path):
    fixed.dry_run_mode = True
    fixed.simulation_state_file_path = str(tmp_path / "sim.json")
    ex = TradeExecutor(fixed, make_market_state(fixed), None)
    ex.memory_tracker = _Memory()
    sizing = ex.position_size(balance=4.0, entry_price=3000.0, stop_loss=2970.0)
    assert sizing["margin"] == pytest.approx(4.0)
    assert sizing["sizing_mode"] == "fixed_capped_by_balance"


def test_both_numbers_must_be_set_together(monkeypatch):
    monkeypatch.setenv("FIXED_MARGIN_USD", "10")
    monkeypatch.setenv("MAX_LOSS_USD", "0")
    with pytest.raises(ValueError, match="must be set together"):
        Config()


def test_leaving_them_at_zero_keeps_risk_based_sizing(config):
    assert config.fixed_size_mode is False
    assert config.fixed_stop_fraction is None
    assert apply_fixed_stop({"direction": "LONG", "entry_price": 3000.0}, config) is None
