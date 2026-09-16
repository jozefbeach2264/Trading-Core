import time

from conftest import make_market_state
from freshness import live_candle_is_current, market_data_age_s, stale_decision_reason, stale_market_reason


def _candle_at(offset_s):
    return [int((time.time() + offset_s) * 1000), 1, 1, 1, 1, 1, 0, 0, "0"]


def test_live_candle_current_only_within_its_minute():
    assert live_candle_is_current(_candle_at(-10))
    assert not live_candle_is_current(_candle_at(-70))
    assert not live_candle_is_current(_candle_at(+5))
    assert not live_candle_is_current(None)


def test_stale_market_reasons(config):
    ms = make_market_state(config)
    ms.live_reconstructed_candle = _candle_at(-10)
    ms.last_update_time = time.time()
    assert stale_market_reason(ms, 3.0) is None
    ms.last_update_time = time.time() - 4
    assert "market data" in stale_market_reason(ms, 3.0)
    assert market_data_age_s(ms) >= 4
    ms.last_update_time = time.time()
    ms.live_reconstructed_candle = _candle_at(-90)
    assert "current minute" in stale_market_reason(ms, 3.0)


def test_stale_decision_reasons():
    now = time.time()
    assert stale_decision_reason(now - 1, 3000.0, 3001.0, 5.0, 0.15, now_s=now) is None
    assert "decision" in stale_decision_reason(now - 6, 3000.0, 3000.0, 5.0, 0.15, now_s=now)
    assert "drifted" in stale_decision_reason(now - 1, 3000.0, 3010.0, 5.0, 0.15, now_s=now)
    assert "unavailable" in stale_decision_reason(now - 1, 3000.0, None, 5.0, 0.15, now_s=now)
