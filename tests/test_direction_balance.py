"""Both directions must be reachable in the same market. Measured 2026-09-16: Scalpel's EMA100 gate locked a
whole session to one side (169 of 174 live minutes below the EMA) for no measurable edge, and TrapX's if/elif
handed every two-wick candle to SHORT (63% short vs 49% with a fair tie-break)."""
from conftest import run, make_market_state, make_live_candle
from strategy.trade_module_scalpel import TradeModuleScalpel
from strategy.trade_module_trapx import TradeModuleTrapX


def _scalpel_state(config, trend, at):
    """`at` = "high" or "low": park the live close at that level of the newest closed candle."""
    ms = make_market_state(config, n_klines=120, trend=trend, kline_range=10.0)
    k = list(ms.klines)[0]
    level = k[2] if at == "high" else k[3]
    ms.live_reconstructed_candle = make_live_candle(level, level + 0.4, level - 0.4, level)
    ms.mark_price = level
    return ms


def test_scalpel_trades_both_ways_regardless_of_trend(config):
    """A retest of the prior high is a LONG and of the prior low a SHORT, in an up- OR down-trending market."""
    scalpel = TradeModuleScalpel(config)
    for trend in (+1.5, -1.5):
        long_signal = run(scalpel.generate_signal(_scalpel_state(config, trend, "high")))
        short_signal = run(scalpel.generate_signal(_scalpel_state(config, trend, "low")))
        assert long_signal and long_signal["direction"] == "LONG", f"no LONG available with trend {trend}"
        assert short_signal and short_signal["direction"] == "SHORT", f"no SHORT available with trend {trend}"
        assert long_signal["stop_loss"] < long_signal["entry_price"] < long_signal["take_profit"]
        assert short_signal["stop_loss"] > short_signal["entry_price"] > short_signal["take_profit"]


def test_scalpel_trend_gate_still_available_when_asked(config):
    config.scalpel_require_trend = True
    scalpel = TradeModuleScalpel(config)
    assert run(scalpel.generate_signal(_scalpel_state(config, -1.5, "high"))) is None   # LONG blocked in a downtrend
    assert run(scalpel.generate_signal(_scalpel_state(config, -1.5, "low")))["direction"] == "SHORT"


def _trapx_state(config, live, spoof=6.0):
    ms = make_market_state(config, n_klines=30, kline_range=2.0)
    klines = list(ms.klines)
    trap = list(klines[0]); trap[2] = trap[1] + 6.0; trap[3] = trap[1] - 6.0     # a trap candle >= 2x the range
    ms.klines[0] = trap
    ms.live_reconstructed_candle = live
    ms.spoof_metrics = {"spoof_thin_rate": spoof}
    ms.order_book_walls = {"bid_walls": [{"price": 2995.0, "qty": 50.0}], "ask_walls": [{"price": 3005.0, "qty": 50.0}]}
    return ms


def test_trapx_tie_goes_to_the_bigger_wick_not_always_short(config):
    trapx = TradeModuleTrapX(config)
    # near-zero body, LOWER wick much bigger → must be a LONG (the old if/elif said SHORT)
    long_live = make_live_candle(3000.0, 3000.2, 2997.0, 3000.0)
    assert run(trapx.generate_signal(_trapx_state(config, long_live)))["direction"] == "LONG"
    # mirror image → SHORT
    short_live = make_live_candle(3000.0, 3003.0, 2999.8, 3000.0)
    assert run(trapx.generate_signal(_trapx_state(config, short_live)))["direction"] == "SHORT"
    # perfectly symmetric wicks on a zero body: no signal at all, rather than a coin flip biased to one side
    sym_live = make_live_candle(3000.0, 3002.0, 2998.0, 3000.0)
    assert run(trapx.generate_signal(_trapx_state(config, sym_live))) is None


def test_trapx_ignores_a_wick_that_is_a_sliver_of_the_range(config):
    """Body ~0 used to make ANY tick past the open a 'rejection'. The wick must also be a real part of the range."""
    trapx = TradeModuleTrapX(config)
    live = make_live_candle(3000.0, 3000.05, 2997.0, 3000.0)      # upper wick 0.05 of a 3.05 range = 1.6%
    signal = run(trapx.generate_signal(_trapx_state(config, live)))
    assert signal is None or signal["direction"] == "LONG"         # never SHORT on that sliver
