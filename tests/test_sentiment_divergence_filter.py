"""Flow divergence against the trade is a veto; with the trade it is confirmation; unknown direction soft-flags."""
from conftest import run, make_market_state
from filters.sentiment_divergence_filter import SentimentDivergenceFilter


def _state(config, price_trend, cvd):
    ms = make_market_state(config, n_klines=30, trend=price_trend, kline_range=10.0)   # trend > 0 = price rising
    ms.running_cvd = cvd
    return ms


def test_divergence_against_the_trade_blocks(config):
    config.min_cvd_threshold = 100.0
    ms = _state(config, +1.0, -5000.0)            # price up, flow down = bearish divergence
    ms.pending_signal_direction = "LONG"
    report = run(SentimentDivergenceFilter(config).generate_report(ms))
    assert report["flag"] == "❌ Block" and report["metrics"]["reason"] == "BEARISH_DIVERGENCE_AGAINST_LONG"
    ms = _state(config, -1.0, +5000.0)            # price down, flow up = bullish divergence
    ms.pending_signal_direction = "SHORT"
    assert run(SentimentDivergenceFilter(config).generate_report(ms))["flag"] == "❌ Block"


def test_divergence_with_the_trade_confirms(config):
    config.min_cvd_threshold = 100.0
    ms = _state(config, +1.0, -5000.0)
    ms.pending_signal_direction = "SHORT"
    report = run(SentimentDivergenceFilter(config).generate_report(ms))
    assert report["flag"] == "✅ Hard Pass" and report["metrics"]["reason"] == "BEARISH_DIVERGENCE_CONFIRMS_SHORT"


def test_unknown_direction_or_veto_disabled_soft_flags(config):
    config.min_cvd_threshold = 100.0
    ms = _state(config, +1.0, -5000.0)
    assert run(SentimentDivergenceFilter(config).generate_report(ms))["flag"] == "⚠️ Soft Flag"
    config.sentiment_divergence_blocks = False
    ms.pending_signal_direction = "LONG"
    assert run(SentimentDivergenceFilter(config).generate_report(ms))["flag"] == "⚠️ Soft Flag"


def test_no_divergence_or_noise_passes(config):
    config.min_cvd_threshold = 100.0
    ms = _state(config, +1.0, +5000.0)             # price up, flow up
    ms.pending_signal_direction = "LONG"
    assert run(SentimentDivergenceFilter(config).generate_report(ms))["flag"] == "✅ Hard Pass"
    ms.running_cvd = -50.0                          # divergence but below the noise floor
    assert run(SentimentDivergenceFilter(config).generate_report(ms))["metrics"]["reason"] == "DIVERGENCE_CVD_NOISE"
