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


def test_long_against_downtrend_scores_high_and_with_uptrend_scores_low(config):
    against = _forecast(config, "LONG", trend=-1.5)["reversal_likelihood_score"]
    with_trend = _forecast(config, "LONG", trend=+1.5)["reversal_likelihood_score"]
    assert against > 0.6
    assert with_trend < 0.3
    assert against > with_trend


def test_short_mirrors_long(config):
    assert _forecast(config, "SHORT", trend=+1.5)["reversal_likelihood_score"] == _forecast(config, "LONG", trend=-1.5)["reversal_likelihood_score"]
    assert _forecast(config, "SHORT", trend=-1.5)["reversal_likelihood_score"] == _forecast(config, "LONG", trend=+1.5)["reversal_likelihood_score"]


def test_book_pressure_and_divergence_move_the_score(config):
    base = _forecast(config, "LONG", trend=0.0)["reversal_likelihood_score"]
    sellers = _forecast(config, "LONG", trend=0.0, bid=20.0, ask=180.0)["reversal_likelihood_score"]
    buyers = _forecast(config, "LONG", trend=0.0, bid=180.0, ask=20.0)["reversal_likelihood_score"]
    bearish = _forecast(config, "LONG", trend=0.0, divergence="bearish")["reversal_likelihood_score"]
    bullish = _forecast(config, "LONG", trend=0.0, divergence="bullish")["reversal_likelihood_score"]
    assert sellers > base > buyers
    assert bearish > base
    assert bullish == base, "a divergence in the trade's favour is not reversal risk"


def test_score_is_never_saturated_for_neutral_input(config):
    scores = [_forecast(config, "LONG", trend=t)["reversal_likelihood_score"] for t in (-1.5, -0.5, 0.0, 0.5, 1.5)]
    assert all(0.0 <= s <= 1.0 for s in scores)
    assert len(set(scores)) >= 4, f"score barely moves: {scores}"
    assert scores[2] not in (0.0, 1.0)


def test_forecast_keeps_c1_to_c6_high_low(config):
    report = _forecast(config, "LONG", trend=0.5)
    assert report["forecast_generated"] is True
    assert set(report["forecast"]) == {f"c{i}" for i in range(1, 7)}
    assert all(report["forecast"][k]["high"] > report["forecast"][k]["low"] for k in report["forecast"])


def test_unknown_direction_is_neutral_not_saturated(config):
    score = _forecast(config, None, trend=-1.5)["reversal_likelihood_score"]
    assert 0.2 <= score <= 0.6
