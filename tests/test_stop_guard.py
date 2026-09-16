"""Under risk-based sizing, fee-to-risk = fee% / stop%. A stop tighter than the fee means paying more in fees
than the trade risks. Measured 2026-09-16: stops of 0.047-0.118% against a 0.16% fee cost 1.3-3.4x the risk."""
from conftest import run
from strategy.ai_strategy import AIStrategy
from tests.test_ai_strategy import _AIClient, _Forecaster, _Gate, _Memory, _Simulator, fresh_state


class _Router:
    def __init__(self, stop_pct, target_pct=1.0):
        self.stop_pct, self.target_pct = stop_pct, target_pct

    async def route_and_generate_signal(self, _ms, _report):
        e = 3000.0
        return {"trade_type": "Scalpel", "direction": "LONG", "entry_price": e,
                "stop_loss": e * (1 - self.stop_pct / 100), "take_profit": e * (1 + self.target_pct / 100)}


def _run(config, stop_pct):
    ai = _AIClient()
    strategy = AIStrategy(config, _Router(stop_pct), _Forecaster(), ai, _Simulator(), _Memory())
    return run(strategy.generate_signal(fresh_state(config), _Gate())), ai


def test_a_stop_tighter_than_twice_the_fee_is_refused(config):
    result, ai = _run(config, 0.10)            # 0.10% stop vs 0.16% fee → fees 1.6x the risk
    assert result["reason"].startswith("Rejected - STOP TOO TIGHT FOR FEES")
    assert "1.6x the risk" in result["reason"] and ai.packets == []


def test_a_stop_comfortably_wider_than_the_fee_proceeds(config):
    result, ai = _run(config, 0.40)            # 0.40% stop vs 0.16% fee → fees 0.4x the risk
    assert "STOP TOO TIGHT" not in str(result.get("reason")) and len(ai.packets) == 1


def test_guard_can_be_disabled(config):
    config.min_stop_fee_multiple = 0
    _, ai = _run(config, 0.05)
    assert len(ai.packets) == 1


def test_the_squeeze_is_visible(config):
    """At 200x, liquidation is 0.50%. The stop guard needs >= 0.32% at taker fees — a narrow band."""
    assert config.min_stop_fee_multiple * config.round_trip_fee_percent < 100.0 / config.leverage, (
        "the minimum workable stop must still sit inside the liquidation distance")
