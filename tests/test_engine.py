"""Engine: only fully approved signals execute, and never while a position is open."""
from conftest import run, make_market_state
from rolling5_engine import Rolling5Engine
from system_managers.engine import Engine


class _Executor:
    def __init__(self):
        self.executed, self.closed, self.updates = [], [], []
        self.position = None

    async def execute_trade(self, signal):
        self.executed.append(signal)

    async def close_position(self, mark_price, reason):
        self.closed.append((mark_price, reason)); self.position = None

    async def mark_to_market(self, mark_price):
        return False

    async def get_open_position(self):
        return self.position

    async def update_position_exits(self, stop_loss, take_profit, best_price=None, note=""):
        self.updates.append((stop_loss, take_profit, best_price, note))
        self.position.update({"stop_loss": stop_loss, "take_profit": take_profit, "best_price": best_price})


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


def test_position_guard_holds_while_the_trade_lives_and_manages_exits(config):
    engine, ms = _engine(config)
    ex = engine.trade_executor
    assert not engine._position_is_open()
    ex.position = {"direction": "SHORT", "entry_price": 3000.0, "stop_loss": 3010.0, "take_profit": 2985.0,
                   "initial_risk": 10.0, "best_price": 3000.0}
    engine.ai_strategy.forecaster.start_lifecycle(ms)
    assert engine._position_is_open()
    ms.mark_price = 2994.0                                             # +0.6R in the SHORT's favour
    run(engine._settle_open_position())
    assert engine._position_is_open() and ex.closed == []
    assert ex.updates and ex.updates[-1][0] == 2999.5 and ex.updates[-1][1] == 2979.0   # BE lock + extended target
    # the safety ceiling, not a 5-candle kill, ends a trade that never resolves
    lc = engine._lifecycle()
    for i in range(1, config.max_position_candles + 1):
        lc.update(ms.live_reconstructed_candle[0] + i * 60_000)
    run(engine._settle_open_position())
    assert ex.closed and ex.closed[0][1] == "MAX_CANDLES" and not engine._position_is_open()
