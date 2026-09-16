"""OKX SWAP sizes are in contracts (ETH-USDT-SWAP ctVal = 0.1 ETH, verified live 2026-09-16). Everything
downstream assumes base-asset units, so conversion happens at ingest."""
import time

from conftest import run, make_market_state, make_live_candle
from data_managers.market_state import MarketState
from filters.low_volume_guard import LowVolumeGuard
from filters.spoof_filter import SpoofFilter
from reconstructors.candle_reconstructor import CandleReconstructor
from strategy.trade_module_scalpel import TradeModuleScalpel


def test_reconstructor_converts_contracts_and_discards_the_partial_first_candle():
    rc = CandleReconstructor(contract_value=0.1)
    minute = 1_699_999_980_000
    t0 = minute + 50_000                          # 50 s into the minute: partial candle
    assert rc.process_trade({"px": "3000", "sz": "5", "ts": str(t0)}) is None
    assert rc.get_live_candle()[5] == 0.5         # 5 contracts → 0.5 ETH
    assert rc.process_trade({"px": "3001", "sz": "5", "ts": str(t0 + 5_000)}) is None
    assert rc.current_is_partial
    completed = rc.process_trade({"px": "3002", "sz": "1", "ts": str(minute + 65_000)})   # next minute
    assert completed is None, "a candle that started mid-minute must not be finalised as closed"
    assert not rc.current_is_partial and rc.get_live_candle()[0] == minute + 60_000
    completed = rc.process_trade({"px": "3003", "sz": "1", "ts": str(minute + 130_000)})  # the minute after
    assert completed is not None and completed[8] == "1"
    assert abs(completed[5] - 0.1) < 1e-12
    rc.reset()
    assert rc.current_candle is None and rc.current_is_partial is False


def test_market_state_converts_trades_and_rest_klines_and_skips_unconfirmed(config):
    ms = MarketState(symbol="ETH-USDT-SWAP", config=config)
    ms.set_contract_value(0.1)
    run(ms.update_from_ws_agg_trade({"ts": "1700000000000", "sz": "20", "side": "buy", "px": "3000"}))
    assert ms.recent_trades[-1]["qty"] == 2.0 and ms.running_cvd == 2.0
    run(ms.update_klines([[1_700_000_060_000, 1, 2, 0, 1, "5121.4", "512.14", "0", "0"],
                          [1_700_000_000_000, 1, 2, 0, 1, "2995.59", "299.559", "0", "1"]]))
    assert len(ms.klines) == 1 and ms.klines[0][0] == 1_700_000_000_000
    assert abs(ms.klines[0][5] - 299.559) < 1e-6


def test_low_volume_threshold_scales_with_candle_age(config):
    config.low_volume_min_notional = 6000.0
    live = make_live_candle(3000.0, 3001.0, 2999.0, 3000.0, volume=0.5)   # 1500 USDT so far
    live[0] = int(time.time() * 1000) - 10_000                            # 10 s in → expect 1/6 of 6000 = 1000
    ms = make_market_state(config, live=live, mark_price=3000.0)
    report = run(LowVolumeGuard(config).generate_report(ms))
    assert report["flag"] == "✅ Hard Pass" and abs(report["metrics"]["min_notional_threshold"] - 1000.0) < 1.0
    live[0] = int(time.time() * 1000) - 59_000                            # end of minute → 5900
    assert run(LowVolumeGuard(config).generate_report(ms))["flag"] == "❌ Block"


def test_spoof_filter_does_not_count_one_snapshot_twice(config):
    flt = SpoofFilter(config)
    ms = make_market_state(config)
    for i in range(10):                            # ten clean, distinct snapshots first (median baseline 0)
        ms.spoof_metrics = {"spoof_thin_rate": 0.0, "wall_delta_pct": 0.0, "snapshot_ts": float(-i)}
        run(flt.generate_report(ms))
    ms.spoof_metrics = {"spoof_thin_rate": 40.0, "wall_delta_pct": -40.0, "snapshot_ts": 1.0}
    first = run(flt.generate_report(ms))
    second = run(flt.generate_report(ms))          # same cached snapshot
    assert first["flag"] == "⚠️ Soft Flag" and second["flag"] == "⚠️ Soft Flag"
    ms.spoof_metrics = {"spoof_thin_rate": 40.0, "wall_delta_pct": -40.0, "snapshot_ts": 2.0}
    assert run(flt.generate_report(ms))["flag"] == "❌ Block"   # a second, distinct pull


def test_spoof_metrics_keep_the_worst_tick_of_the_last_second(config):
    ms = MarketState(symbol="ETH-USDT-SWAP", config=config)
    wall = [["3000", "1", "0", "1"], ["2999.9", "1", "0", "1"], ["2999.8", "60", "0", "1"], ["2999.7", "1", "0", "1"], ["2999.6", "1", "0", "1"]]
    pulled = [["3000", "1", "0", "1"], ["2999.9", "1", "0", "1"], ["2999.8", "1", "0", "1"], ["2999.7", "1", "0", "1"], ["2999.6", "1", "0", "1"]]
    asks = [["3000.1", "1", "0", "1"]] * 5
    run(ms.update_from_ws_books({"bids": wall, "asks": asks})); run(ms.ensure_order_book_metrics_are_current())
    run(ms.update_from_ws_books({"bids": pulled, "asks": asks})); run(ms.ensure_order_book_metrics_are_current())
    assert ms.spoof_metrics["tick_thin_rate"] > 90
    run(ms.update_from_ws_books({"bids": pulled, "asks": asks})); run(ms.ensure_order_book_metrics_are_current())
    assert ms.spoof_metrics["tick_thin_rate"] == 0.0
    assert ms.spoof_metrics["spoof_thin_rate"] > 90, "the pull one tick ago is still visible to the 0.2 s cycle"


def test_scalpel_uses_the_newest_closed_candle(config):
    ms = make_market_state(config, n_klines=120, trend=0.5)
    klines = list(ms.klines)
    ms.live_reconstructed_candle = make_live_candle(klines[0][2] - 0.5, klines[0][2], klines[0][2] - 1.0, klines[0][2] - 0.2)
    signal = run(TradeModuleScalpel(config).generate_signal(ms))
    assert signal is not None
    assert abs(signal["stop_loss"] - (signal["entry_price"] - (klines[0][2] - klines[0][3]))) < 1e-9


def test_scalpel_retest_band_is_a_fraction_of_the_candle_range(config):
    ms = make_market_state(config, n_klines=120, trend=0.5, kline_range=10.0)   # level candle range 10 → band 2.5
    high = list(ms.klines)[0][2]
    ms.live_reconstructed_candle = make_live_candle(high - 4.0, high - 3.0, high - 5.0, high - 4.0)   # 4 away: not a retest
    assert run(TradeModuleScalpel(config).generate_signal(ms)) is None
    ms.live_reconstructed_candle = make_live_candle(high - 2.0, high - 1.0, high - 3.0, high - 2.0)   # 2 away: retest
    assert run(TradeModuleScalpel(config).generate_signal(ms)) is not None
