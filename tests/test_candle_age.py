"""Age-aware compression: a live candle is compared with what a candle of its age should show."""
import time

from conftest import run, make_market_state, make_live_candle
from filters.candle_age import candle_age_fraction, expected_partial_range, is_too_young
from filters.compression_detector import CompressionDetector
from filters.cts_filter import CtsFilter


def _live_aged(age_s: float, o, h, l, c):
    candle = make_live_candle(o, h, l, c)
    candle[0] = int(time.time() * 1000 - age_s * 1000)
    return candle


def test_age_fraction_and_sqrt_scaling():
    assert candle_age_fraction(_live_aged(15, 1, 1, 1, 1)) - 0.25 < 0.01
    assert abs(expected_partial_range(10.0, 0.25) - 5.0) < 1e-9
    assert candle_age_fraction(None) == 1.0 and candle_age_fraction([0]) == 1.0
    assert is_too_young(candle_age_fraction(_live_aged(2, 1, 1, 1, 1)))


def test_young_candle_is_a_soft_flag_not_a_block(config):
    ms = make_market_state(config, live=_live_aged(2, 3000.0, 3000.2, 2999.8, 3000.1), mark_price=3000.1)
    for flt in (CtsFilter(config), CompressionDetector(config)):
        report = run(flt.generate_report(ms))
        assert report["flag"] == "⚠️ Soft Flag" and report["metrics"]["reason"] == "CANDLE_TOO_YOUNG"


def test_partial_candle_with_normal_pace_is_not_compressed(config):
    # 15 s in: a normal candle has ≈ √0.25 = 0.5 of the 10.0 average range → 5.0. Full-body 5.0 range.
    ms = make_market_state(config, live=_live_aged(15, 2997.5, 3002.5, 2997.5, 3002.5), mark_price=3000.0)
    cts = run(CtsFilter(config).generate_report(ms))
    assert cts["flag"] == "✅ Hard Pass" and cts["metrics"]["is_compressed"] is False
    comp = run(CompressionDetector(config).generate_report(ms))
    assert comp["flag"] == "✅ Hard Pass" and abs(comp["metrics"]["compression_ratio"] - 1.0) < 0.05


def test_partial_candle_that_is_really_compressed_still_blocks(config):
    # 30 s in: expected ≈ 7.07; a 1.0 range full-body candle is genuine compression.
    ms = make_market_state(config, live=_live_aged(30, 2999.5, 3000.5, 2999.5, 3000.5), mark_price=3000.0)
    assert run(CtsFilter(config).generate_report(ms))["flag"] == "❌ Block"
    assert run(CompressionDetector(config).generate_report(ms))["flag"] == "❌ Block"


def test_zero_range_young_candle_is_too_young_not_invalid(config):
    ms = make_market_state(config, live=_live_aged(2, 3000.0, 3000.0, 3000.0, 3000.0), mark_price=3000.0)
    report = run(CtsFilter(config).generate_report(ms))
    assert report["metrics"]["reason"] == "CANDLE_TOO_YOUNG" and report["flag"] == "⚠️ Soft Flag"
