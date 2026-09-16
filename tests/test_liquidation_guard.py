"""A stop beyond the liquidation price is fiction: the position is liquidated first, so the stated risk/reward
is meaningless and the real risk is the whole margin. Observed live 2026-09-16: a 4.670% stop at 200x, where
liquidation is 0.500% — the stop was 9.3x beyond reach."""
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


def test_liquidation_distance(config):
    config.leverage = 200
    assert abs(config.liquidation_distance_percent - 0.5) < 1e-9
    config.leverage = 25
    assert abs(config.liquidation_distance_percent - 4.0) < 1e-9


def test_a_stop_beyond_liquidation_is_refused(config):
    config.leverage = 200                      # liquidation 0.50%, cap 0.8x = 0.40%
    result, ai = _run(config, 4.67)            # the real trade that liquidated
    assert result["reason"].startswith("Rejected - STOP BEYOND LIQUIDATION")
    assert "could never be reached" in result["reason"] and ai.packets == []


def test_a_stop_inside_the_liquidation_distance_proceeds(config):
    config.leverage = 200
    result, ai = _run(config, 0.35)            # inside 0.40%, and above the 0.32% fee floor
    assert "LIQUIDATION" not in str(result.get("reason")) and len(ai.packets) == 1


def test_lower_leverage_opens_the_window(config):
    config.leverage = 25                       # liquidation 4.0%, cap 3.2%
    result, ai = _run(config, 1.5)
    assert "LIQUIDATION" not in str(result.get("reason")) and len(ai.packets) == 1


def test_config_refuses_settings_where_no_stop_can_work(monkeypatch):
    """At 200x with taker fees the workable band is 0.32%-0.40%. Make the fee floor exceed it and start-up fails."""
    monkeypatch.setenv("LEVERAGE", "200")
    monkeypatch.setenv("MIN_STOP_FEE_MULTIPLE", "4")      # demands >= 0.64%, but liquidation caps at 0.40%
    with pytest.raises(ValueError, match="No stop width"):
        Config()
