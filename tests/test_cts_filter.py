"""Defect D (review findings 4/7/8): CtsFilter must be able to hard-block a compressed,
wick-less candle again, and the streak/cooldown code must be reachable."""
from conftest import run, make_market_state, make_live_candle
from filters.cts_filter import CtsFilter

# 15-candle average range = 10.0 (conftest default). narrow_range_ratio = 0.8 → compressed below 8.0.


def _compressed_no_wick(config):
    # full-body candle, range 2.0, no wicks, mark price inside the body
    live = make_live_candle(2999.0, 3001.0, 2999.0, 3001.0)
    return make_market_state(config, live=live, mark_price=3000.5)


def test_compressed_without_wick_hard_blocks(config):
    report = run(CtsFilter(config).generate_report(_compressed_no_wick(config)))
    assert report["flag"] == "❌ Block"
    assert report["score"] < 0.5
    assert report["metrics"]["is_compressed"] is True
    assert report["metrics"]["wick_signal"] == "none"


def test_repeated_blocks_keep_evaluating_every_cycle(config):
    """No cooldown: the gate must re-evaluate every cycle so the first expansion candle after a
    compressed run is seen immediately (a 3 s blind window is a latency regression on a 200x scalper)."""
    cts = CtsFilter(config)
    ms = _compressed_no_wick(config)
    reports = [run(cts.generate_report(ms)) for _ in range(6)]
    assert all(r["flag"] == "❌ Block" for r in reports)
    assert reports[5]["metrics"]["block_streak"] == 6
    ms.live_reconstructed_candle = make_live_candle(2994.0, 3006.0, 2994.0, 3006.0)  # expansion
    ms.mark_price = 3000.0
    after = run(cts.generate_report(ms))
    assert after["flag"] == "✅ Hard Pass" and after["score"] == 1.0
    assert after["metrics"]["block_streak"] == 0


def test_not_compressed_is_a_hard_pass(config):
    live = make_live_candle(2994.0, 3006.0, 2994.0, 3006.0)  # range 12 > 8
    report = run(CtsFilter(config).generate_report(make_market_state(config, live=live, mark_price=3000.0)))
    assert report["flag"] == "✅ Hard Pass"
    assert report["score"] == 1.0


def test_compressed_with_wick_rejection_is_not_blocked(config):
    # tiny body (0.2), long lower wick (1.5) → bull-trap rejection evidence
    live = make_live_candle(3000.0, 3000.3, 2998.5, 3000.2)
    report = run(CtsFilter(config).generate_report(make_market_state(config, live=live, mark_price=3000.2)))
    assert report["metrics"]["wick_signal"] == "bull_trap_rejection"
    assert report["flag"] != "❌ Block"
    assert 0.6 <= report["score"] <= 1.0


def test_score_floor_is_gone(config):
    """The reviewed diff floored every compressed score at 0.55; no path may do that now."""
    report = run(CtsFilter(config).generate_report(_compressed_no_wick(config)))
    assert report["score"] == 0.0
