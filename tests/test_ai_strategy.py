"""Defect A (findings 1/9/10): the context packet must carry the forecaster's real
reversal score under ONE canonical key, and the forecaster must know the trade direction."""
import time

from conftest import run, make_market_state
from strategy.ai_strategy import AIStrategy


def fresh_state(config, **kw):
    """A market state whose live candle belongs to the current minute (the freshness gate requires it)."""
    ms = make_market_state(config, **kw)
    ms.live_reconstructed_candle[0] = int(time.time() * 1000) - 20_000
    ms.last_update_time = time.time()
    return ms


class _Gate:
    def __init__(self):
        self.calls = 0
        self.seen_direction = None

    async def run_primary_gate(self, _ms):
        return {"filters": {"CtsFilter": {"score": 0.9, "flag": "✅ Hard Pass"}}, "hard_blocks": 0}

    async def run_post_signal_validators(self, ms):
        self.seen_direction = ms.pending_signal_direction     # filters may judge context against the trade
        return {"filters": {"OrderBookReversalZoneDetector": {"score": 0.8, "flag": "✅ Hard Confirmed"}}, "hard_blocks": 0}


class _Router:
    async def route_and_generate_signal(self, _ms, _report):
        return {"trade_type": "TrapX", "direction": "SHORT", "entry_price": 3000.0, "take_profit": 2990.0, "stop_loss": 3005.0,
                "reason": "GENESIS TrapX: SHORT signal identified."}   # the strategies' own descriptive key


class _Forecaster:
    def __init__(self):
        self.calls = []

    reversal = 0.5

    async def generate_forecast(self, market_state, direction=None):
        self.calls.append(direction)
        return {"forecast_generated": True, "reversal_likelihood_score": self.reversal,
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
    gate = _Gate(); ms = fresh_state(config)
    result = run(strategy.generate_signal(ms, gate))
    assert gate.seen_direction == "SHORT" and ms.pending_signal_direction is None   # set for the filters, cleared after
    assert result["ai_verdict"]["action"] == "⛔ Abort"
    packet = ai.packets[0]
    assert packet["reversal_likelihood_score"] == 0.5
    assert packet["orderbook_zone"] == "none"
    assert "reversal_zone_strength" not in packet
    assert packet["cts_score"] == 0.9 and packet["orderbook_score"] == 0.8
    assert packet["direction"] == "SHORT"
    assert forecaster.calls == ["SHORT"]


def test_non_execute_verdict_carries_an_explicit_reason(config):
    strategy = AIStrategy(config, _Router(), _Forecaster(), _AIClient(), _Simulator(), _Memory())
    result = run(strategy.generate_signal(fresh_state(config), _Gate()))
    assert result["reason"].startswith("Rejected - AI VERDICT: ⛔ Abort")


def test_missing_forecast_skips_the_ai_call(config):
    class _NoForecast(_Forecaster):
        async def generate_forecast(self, market_state, direction=None):
            return {"forecast_generated": False, "reversal_likelihood_score": 0.0, "forecast": {}}
    ai = _AIClient()
    strategy = AIStrategy(config, _Router(), _NoForecast(), ai, _Simulator(), _Memory())
    result = run(strategy.generate_signal(fresh_state(config), _Gate()))
    assert result["reason"] == "Rejected - FORECAST UNAVAILABLE" and ai.packets == []


class _ExecuteAI(_AIClient):
    async def get_ai_verdict(self, packet):
        self.packets.append(packet)
        return {"action": "Execute", "confidence": 0.9, "reasoning": "go"}


class _LowConfidenceAI(_AIClient):
    async def get_ai_verdict(self, packet):
        self.packets.append(packet)
        return {"action": "Execute", "confidence": 0.3, "reasoning": "meh"}


def test_stale_market_data_is_rejected_before_any_gate(config):
    ai = _AIClient()
    strategy = AIStrategy(config, _Router(), _Forecaster(), ai, _Simulator(), _Memory())
    stale = make_market_state(config)            # live candle from 2023, last_update_time now
    result = run(strategy.generate_signal(stale, _Gate()))
    assert result["reason"].startswith("Rejected - STALE MARKET DATA")
    assert ai.packets == []
    frozen = fresh_state(config)
    frozen.last_update_time = time.time() - 10   # feed silent for 10 s
    assert "STALE MARKET DATA" in run(strategy.generate_signal(frozen, _Gate()))["reason"]


def test_high_reversal_risk_is_rejected_without_asking_the_model(config):
    forecaster, ai = _Forecaster(), _AIClient()
    forecaster.reversal = 0.95
    strategy = AIStrategy(config, _Router(), forecaster, ai, _Simulator(), _Memory())
    result = run(strategy.generate_signal(fresh_state(config), _Gate()))
    assert result["reason"].startswith("Rejected - REVERSAL RISK")
    assert ai.packets == []


def test_low_confidence_rejection_never_returns_an_execute_action(config):
    strategy = AIStrategy(config, _Router(), _Forecaster(), _LowConfidenceAI(), _Simulator(), _Memory())
    result = run(strategy.generate_signal(fresh_state(config), _Gate()))
    assert result["reason"].startswith("Rejected - AI CONFIDENCE LOW")
    assert result["ai_verdict"]["action"] == "🤔 Reanalyze"


def test_approved_execute_passes_freshness_and_risk_checks(config):
    strategy = AIStrategy(config, _Router(), _Forecaster(), _ExecuteAI(), _Simulator(), _Memory())
    result = run(strategy.generate_signal(fresh_state(config), _Gate()))
    assert "reason" not in result and result["ai_verdict"]["action"] == "✅ Execute" and result["direction"] == "SHORT"
    assert result["context_packet"]["direction"] == "SHORT" and "CtsFilter" in result["filter_snapshot"]
    assert result["signal_reason"].startswith("GENESIS TrapX")
    from system_managers.engine import Engine
    assert Engine._is_approved(result), "an approved signal must execute despite the strategy's descriptive reason"


def test_price_drift_during_the_verdict_rejects_the_decision(config):
    class _DriftingAI(_AIClient):
        def __init__(self, ms):
            super().__init__(); self.ms = ms

        async def get_ai_verdict(self, packet):
            self.ms.mark_price = self.ms.mark_price * 1.01   # +1% while the model was thinking
            return {"action": "Execute", "confidence": 0.9, "reasoning": "go"}
    ms = fresh_state(config)
    strategy = AIStrategy(config, _Router(), _Forecaster(), _DriftingAI(ms), _Simulator(), _Memory())
    result = run(strategy.generate_signal(ms, _Gate()))
    assert result["reason"].startswith("Rejected - STALE DECISION")


def test_identical_setup_is_not_re_asked_within_the_cache_window(config):
    ai = _AIClient()
    strategy = AIStrategy(config, _Router(), _Forecaster(), ai, _Simulator(), _Memory())
    ms = fresh_state(config)
    first = run(strategy.generate_signal(ms, _Gate()))
    second = run(strategy.generate_signal(ms, _Gate()))
    assert len(ai.packets) == 1 and strategy.cache_hits == 1
    assert first["ai_verdict"] == second["ai_verdict"]
    ms.live_reconstructed_candle[0] += 60_000          # a new candle is a new question
    ms.live_reconstructed_candle[0] = int(time.time() * 1000) - 5_000
    run(strategy.generate_signal(ms, _Gate()))
    assert len(ai.packets) == 2


def test_cache_can_be_disabled(config):
    config.ai_verdict_cache_s = 0
    ai = _AIClient()
    strategy = AIStrategy(config, _Router(), _Forecaster(), ai, _Simulator(), _Memory())
    ms = fresh_state(config)
    run(strategy.generate_signal(ms, _Gate())); run(strategy.generate_signal(ms, _Gate()))
    assert len(ai.packets) == 2
