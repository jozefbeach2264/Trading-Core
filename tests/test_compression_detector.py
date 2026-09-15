"""Defect E (review finding 5): thresholds must not chase the data. A healthy market
must never hard-block by construction, and rolling stats must exclude the current sample."""
from conftest import run, make_market_state, make_live_candle
from filters.compression_detector import CompressionDetector

# avg range 10.0; COMPRESSION_RANGE_RATIO pinned to 0.8 → (old HEAD semantics)
# score = min(ratio / (0.8*1.2), 1) → hard pass at ratio ≥ 0.72, soft ≥ 0.48, block below.


def _state_with_ratio(config, ratio: float):
    rng = 10.0 * ratio
    live = make_live_candle(3000.0, 3000.0 + rng / 2, 3000.0 - rng / 2, 3000.0)
    return make_market_state(config, live=live)


def test_healthy_market_never_hard_blocks(config):
    det = CompressionDetector(config)
    pattern = [0.95, 1.02, 0.97, 1.05, 0.99, 1.01, 0.96, 1.04, 0.98, 1.0]
    flags = [run(det.generate_report(_state_with_ratio(config, pattern[i % len(pattern)])))["flag"] for i in range(60)]
    assert flags.count("❌ Block") == 0
    assert all(f == "✅ Hard Pass" for f in flags)


def test_thresholds_do_not_chase_the_data(config):
    det = CompressionDetector(config)
    for _ in range(30):
        run(det.generate_report(_state_with_ratio(config, 0.95)))
    report = run(det.generate_report(_state_with_ratio(config, 0.94)))
    assert report["flag"] == "✅ Hard Pass"


def test_genuine_compression_blocks(config):
    det = CompressionDetector(config)
    for _ in range(30):
        run(det.generate_report(_state_with_ratio(config, 1.0)))
    report = run(det.generate_report(_state_with_ratio(config, 0.2)))
    assert report["flag"] == "❌ Block"
    assert report["metrics"]["reason"] == "HEAVY_PRICE_COMPRESSION"


def test_mild_compression_soft_flags(config):
    report = run(CompressionDetector(config).generate_report(_state_with_ratio(config, 0.6)))
    assert report["flag"] == "⚠️ Soft Flag"


def test_rolling_stats_exclude_current_sample(config):
    det = CompressionDetector(config)
    for _ in range(25):
        run(det.generate_report(_state_with_ratio(config, 1.0)))
    report = run(det.generate_report(_state_with_ratio(config, 0.5)))
    m = report["metrics"]
    assert m["compression_ratio"] == 0.5
    assert m["median_ratio"] == 1.0, "median must come from the PRIOR window"
    assert m["p20_ratio"] == 1.0


def test_thresholds_are_config_anchored(config):
    report = run(CompressionDetector(config).generate_report(_state_with_ratio(config, 1.0)))
    m = report["metrics"]
    assert m["config_threshold_ratio"] == 0.8
    assert m["hard_threshold"] == 0.72
    assert m["soft_threshold"] == 0.48
