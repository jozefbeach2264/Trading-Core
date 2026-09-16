"""OKX payload ordering (verified against the live REST API 2026-09-15): history candles are newest-first
and both book sides arrive best-first. MarketState must keep both conventions."""
from conftest import run
from data_managers.market_state import MarketState


def test_rest_klines_are_stored_newest_first(config):
    ms = MarketState(symbol="ETH-USDT-SWAP", config=config)
    newest_first = [[1_700_000_120_000, 1, 2, 0, 1, 1, 0, 0, "1"], [1_700_000_060_000, 1, 2, 0, 1, 1, 0, 0, "1"],
                    [1_700_000_000_000, 1, 2, 0, 1, 1, 0, 0, "1"]]
    run(ms.update_klines(newest_first))
    assert [k[0] for k in ms.klines] == [1_700_000_120_000, 1_700_000_060_000, 1_700_000_000_000]
    run(ms.update_from_ws_kline([1_700_000_180_000, 1, 2, 0, 1, 1, 0, 0, "1"]))
    assert ms.klines[0][0] == 1_700_000_180_000 and ms.klines[1][0] == 1_700_000_120_000


def test_book_sides_keep_best_first_order(config):
    ms = MarketState(symbol="ETH-USDT-SWAP", config=config)
    run(ms.update_from_ws_books({"bids": [["2405.52", "1", "0", "1"], ["2405.49", "2", "0", "1"]],
                                 "asks": [["2405.53", "3", "0", "1"], ["2405.54", "4", "0", "1"]]}))
    assert ms.depth_20["bids"][0] == (2405.52, 1.0)
    assert ms.depth_20["asks"][0] == (2405.53, 3.0)
