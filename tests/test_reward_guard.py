"""A trade whose target cannot clear the round-trip fee loses money even when it wins. Measured live
2026-09-16: stop 0.099% / target 0.140% against a 0.160% fee → break-even win rate 108%, impossible."""
import time

from conftest import run, make_market_state, make_live_candle
from strategy.ai_strategy import AIStrategy
from strategy.trade_module_scalpel import TradeModuleScalpel
from tests.test_ai_strategy import _AIClient, _Forecaster, _Gate, _Memory, _Simulator, fresh_state


class _TinyTargetRouter:
    async def route_and_generate_signal(self, _ms, _report):
        return {"trade_type": "Scalpel", "direction": "LONG", "entry_price": 3000.0,
                "take_profit": 3003.0, "stop_loss": 2997.0}          # 0.10% target vs a 0.16% fee


class _FatTargetRouter:
    async def route_and_generate_signal(self, _ms, _report):
        return {"trade_type": "Scalpel", "direction": "LONG", "entry_price": 3000.0,
                "take_profit": 3018.0, "stop_loss": 2988.0}   # target 0.60% (3.75x fee), stop 0.40% (2.5x fee)


def test_round_trip_fee_is_both_sides(config):
    config.exchange_fee_rate_taker = 0.08
    assert abs(config.round_trip_fee_percent - 0.16) < 1e-9


def test_target_below_the_fee_threshold_is_refused_without_a_model_call(config):
    ai = _AIClient()
    strategy = AIStrategy(config, _TinyTargetRouter(), _Forecaster(), ai, _Simulator(), _Memory())
    result = run(strategy.generate_signal(fresh_state(config), _Gate()))
    assert result["reason"].startswith("Rejected - REWARD BELOW FEES")
    assert "0.100%" in result["reason"] and ai.packets == [], "must not spend a verdict on a doomed trade"


def test_a_target_that_clears_the_fee_proceeds(config):
    ai = _AIClient()
    strategy = AIStrategy(config, _FatTargetRouter(), _Forecaster(), ai, _Simulator(), _Memory())
    result = run(strategy.generate_signal(fresh_state(config), _Gate()))
    assert "REWARD BELOW FEES" not in str(result.get("reason")) and len(ai.packets) == 1


def test_guard_can_be_disabled(config):
    config.min_reward_fee_multiple = 0
    config.min_stop_fee_multiple = 0     # the tiny-target fixture also has a tight stop; isolate the reward guard
    ai = _AIClient()
    strategy = AIStrategy(config, _TinyTargetRouter(), _Forecaster(), ai, _Simulator(), _Memory())
    run(strategy.generate_signal(fresh_state(config), _Gate()))
    assert len(ai.packets) == 1


def test_scalpel_multiples_are_configurable_and_clear_the_fee(config):
    config.scalpel_stop_range_multiple = 3.0
    config.scalpel_target_range_multiple = 8.0
    ms = make_market_state(config, n_klines=120, kline_range=10.0)
    k = list(ms.klines)[0]
    ms.live_reconstructed_candle = make_live_candle(k[2], k[2] + 0.4, k[2] - 0.4, k[2])
    ms.mark_price = k[2]
    signal = run(TradeModuleScalpel(config).generate_signal(ms))
    assert signal["direction"] == "LONG"
    rng = k[2] - k[3]
    assert abs((signal["entry_price"] - signal["stop_loss"]) - 3.0 * rng) < 1e-9
    assert abs((signal["take_profit"] - signal["entry_price"]) - 8.0 * rng) < 1e-9
    reward_pct = (signal["take_profit"] - signal["entry_price"]) / signal["entry_price"] * 100
    assert reward_pct > 3 * config.round_trip_fee_percent, "default multiples must clear the guard"
