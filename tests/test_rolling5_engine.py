"""Defect G (found 2026-09-15, not in the review): the reversal score saturated at 1.0 on
every cycle (mark_price_factor ≈ 1.0 alone maxed it). It must be direction-aware, span
[0, 1], and be low for a trade WITH the trend and high for a trade AGAINST it."""
from conftest import run, make_market_state
from rolling5_engine import Rolling5Engine


def _forecast(config, direction, trend, bid=100.0, ask=100.0, divergence=None):
    ms = make_market_state(config, n_klines=30, trend=trend, kline_range=6.0)
    ms.order_book_pressure = {"bid_pressure": bid, "ask_pressure": ask, "total_pressure": bid + ask}
    if divergence:
        ms.filter_audit_report["SentimentDivergenceFilter"] = {"score": 0.40, "metrics": {"divergence_type": divergence}}
    return run(Rolling5Engine(config).generate_forecast(ms, direction))


def test_trend_no_longer_moves_the_score(config):
    """The regression slope was measured at coin-flip accuracy (48%); it must carry no weight."""
    against = _forecast(config, "LONG", trend=-1.5)["reversal_likelihood_score"]
    with_trend = _forecast(config, "LONG", trend=+1.5)["reversal_likelihood_score"]
    assert against == with_trend


def test_short_mirrors_long(config):
    a = _forecast(config, "SHORT", trend=0.0, bid=20.0, ask=180.0)["reversal_likelihood_score"]
    b = _forecast(config, "LONG", trend=0.0, bid=180.0, ask=20.0)["reversal_likelihood_score"]
    assert a == b


def test_book_pressure_and_divergence_move_the_score(config):
    base = _forecast(config, "LONG", trend=0.0)["reversal_likelihood_score"]
    sellers = _forecast(config, "LONG", trend=0.0, bid=20.0, ask=180.0)["reversal_likelihood_score"]
    buyers = _forecast(config, "LONG", trend=0.0, bid=180.0, ask=20.0)["reversal_likelihood_score"]
    bearish = _forecast(config, "LONG", trend=0.0, divergence="bearish")["reversal_likelihood_score"]
    bullish = _forecast(config, "LONG", trend=0.0, divergence="bullish")["reversal_likelihood_score"]
    assert sellers > base > buyers
    assert bearish > base
    assert bullish == base, "a divergence in the trade's favour is not reversal risk"


def test_score_is_never_saturated_and_moves_with_the_book(config):
    scores = [_forecast(config, "LONG", trend=0.0, bid=b, ask=200.0 - b)["reversal_likelihood_score"] for b in (20, 60, 100, 140, 180)]
    assert all(0.0 <= s <= 1.0 for s in scores)
    assert len(set(scores)) >= 4, f"score barely moves: {scores}"
    assert scores[2] not in (0.0, 1.0)
    assert scores[0] > scores[-1]                      # sellers dominate → higher reversal risk for a LONG


def test_forecast_band_is_volatility_around_the_mark_and_widens(config):
    report = _forecast(config, "LONG", trend=0.0)      # flat candles → average range exactly 6.0
    assert report["forecast_generated"] is True
    assert set(report["forecast"]) == {f"c{i}" for i in range(1, 7)}
    f = report["forecast"]
    mids = [(f[f"c{i}"]["high"] + f[f"c{i}"]["low"]) / 2 for i in range(1, 7)]
    assert max(mids) - min(mids) < 1e-6, "no drift: every band is centred on the same anchor"
    widths = [f[f"c{i}"]["high"] - f[f"c{i}"]["low"] for i in range(1, 7)]
    assert all(b > a for a, b in zip(widths, widths[1:])), "band widens with horizon"
    assert abs(widths[0] - 6.0) < 1e-6                 # avg range 6 → c1 width = 2 × 0.5 × 6 × √1


def test_unknown_direction_is_neutral_not_saturated(config):
    score = _forecast(config, None, trend=-1.5)["reversal_likelihood_score"]
    assert 0.2 <= score <= 0.6
