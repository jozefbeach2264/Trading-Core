"""Defect A (findings 1/9/10): the context packet must carry the forecaster's real
reversal score under ONE canonical key, and the forecaster must know the trade direction."""
from conftest import run, make_market_state
from strategy.ai_strategy import AIStrategy


class _Gate:
    def __init__(self):
        self.calls = 0

    async def run_primary_gate(self, _ms):
        return {"filters": {"CtsFilter": {"score": 0.9, "flag": "✅ Hard Pass"}}, "hard_blocks": 0}

    async def run_post_signal_validators(self, _ms):
        return {"filters": {"OrderBookReversalZoneDetector": {"score": 0.8, "flag": "✅ Hard Confirmed"}}, "hard_blocks": 0}


class _Router:
    async def route_and_generate_signal(self, _ms, _report):
        return {"trade_type": "TrapX", "direction": "SHORT", "entry_price": 3000.0, "take_profit": 2990.0, "stop_loss": 3005.0}


class _Forecaster:
    def __init__(self):
        self.calls = []

    async def generate_forecast(self, market_state, direction=None):
        self.calls.append(direction)
        return {"forecast_generated": True, "reversal_likelihood_score": 0.83,
                "forecast": {"c1": {"high": 3001.0, "low": 2999.0}, "c2": {"high": 3001.0, "low": 2999.0}}}

    def start_lifecycle(self, _ms):
        pass

    def stop_lifecycle(self):
        pass


class _AIClient:
    def __init__(self):
        self.packets = []

    async def get_ai_verdict(self, packet):
        self.packets.append(packet)
        return {"action": "Abort", "confidence": 0.9, "reasoning": "test"}


class _Simulator:
    def check_liquidation_risk(self, *_a):
        return True, "ok"


class _Memory:
    async def update_memory(self, **_kw):
        pass


def test_context_packet_carries_real_reversal_score(config):
    forecaster, ai = _Forecaster(), _AIClient()
    strategy = AIStrategy(config, _Router(), forecaster, ai, _Simulator(), _Memory())
    result = run(strategy.generate_signal(make_market_state(config), _Gate()))
    assert result["ai_verdict"]["action"] == "⛔ Abort"
    packet = ai.packets[0]
    assert packet["reversal_likelihood_score"] == 0.83
    assert "reversal_zone_strength" not in packet
    assert packet["cts_score"] == 0.9 and packet["orderbook_score"] == 0.8
    assert packet["direction"] == "SHORT"
    assert forecaster.calls == ["SHORT"]


def test_non_execute_verdict_carries_an_explicit_reason(config):
    strategy = AIStrategy(config, _Router(), _Forecaster(), _AIClient(), _Simulator(), _Memory())
    result = run(strategy.generate_signal(make_market_state(config), _Gate()))
    assert result["reason"].startswith("Rejected - AI VERDICT: ⛔ Abort")


def test_missing_forecast_skips_the_ai_call(config):
    class _NoForecast(_Forecaster):
        async def generate_forecast(self, market_state, direction=None):
            return {"forecast_generated": False, "reversal_likelihood_score": 0.0, "forecast": {}}
    ai = _AIClient()
    strategy = AIStrategy(config, _Router(), _NoForecast(), ai, _Simulator(), _Memory())
    result = run(strategy.generate_signal(make_market_state(config), _Gate()))
    assert result["reason"] == "Rejected - FORECAST UNAVAILABLE" and ai.packets == []
