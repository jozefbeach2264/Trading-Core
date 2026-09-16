"""Engine: only fully approved signals execute, and never while a position is open."""
from conftest import run, make_market_state
from rolling5_engine import Rolling5Engine
from system_managers.engine import Engine


class _Executor:
    def __init__(self):
        self.executed, self.closed = [], []

    async def execute_trade(self, signal):
        self.executed.append(signal)

    async def close_position(self, mark_price, reason):
        self.closed.append((mark_price, reason))

    async def mark_to_market(self, mark_price):
        return False


class _Strategy:
    def __init__(self, config):
        self.forecaster = Rolling5Engine(config)


def _engine(config):
    ms = make_market_state(config)
    return Engine(config=config, market_state=ms, validator_stack=None, ai_strategy=_Strategy(config), trade_executor=_Executor()), ms


def test_only_fully_approved_signals_execute():
    ok = {"ai_verdict": {"action": "✅ Execute"}, "direction": "LONG"}
    assert Engine._is_approved(ok)
    assert not Engine._is_approved({**ok, "reason": "Rejected - AI CONFIDENCE LOW"})
    assert not Engine._is_approved({"ai_verdict": {"action": "✅ Execute"}})            # no direction
    assert not Engine._is_approved({"ai_verdict": {"action": "⛔ Abort"}, "direction": "LONG"})
    assert not Engine._is_approved({})


def test_position_guard_blocks_re_entry_until_the_lifecycle_completes(config):
    engine, ms = _engine(config)
    assert not engine._position_is_open()
    engine.ai_strategy.forecaster.start_lifecycle(ms)          # an entry was just executed
    assert engine._position_is_open()
    # advance the candle clock past MAX_POSITION_CANDLES closed candles
    lc = engine._lifecycle()
    for i in range(1, config.max_position_candles):            # start() already counts candle 1
        lc.update(ms.live_reconstructed_candle[0] + i * 60_000)
    assert lc.candle_count == config.max_position_candles
    assert engine._position_is_open()                          # still within the horizon
    lc.update(ms.live_reconstructed_candle[0] + config.max_position_candles * 60_000)
    run(engine._settle_open_position())
    assert not engine._position_is_open()
    assert engine.trade_executor.closed and engine.trade_executor.closed[0][1] == "ROLLING5_COMPLETE"
