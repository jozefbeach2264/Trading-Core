"""OKX `books` merge: snapshot, deltas, deletes, ordering, sequence-gap detection, checksum format."""
import pytest

from conftest import run
from data_managers.market_state import MarketState
from data_managers.orderbook_l2 import L2Book, SequenceGap

SNAP = {"bids": [["2392.35", "17.9", "0", "3"], ["2392.30", "5", "0", "1"], ["2392.00", "40", "0", "2"]],
        "asks": [["2392.36", "2507.15", "0", "9"], ["2392.40", "1", "0", "1"]], "ts": "1", "seqId": "100", "prevSeqId": "-1", "checksum": 0}


def test_snapshot_then_updates_and_deletes():
    book = L2Book()
    book.apply("snapshot", SNAP)
    assert book.depth() == (3, 2) and book.seq_id == 100 and book.ready
    book.apply("update", {"bids": [["2392.35", "22.45", "0", "4"], ["2392.30", "0", "0", "0"], ["2391.90", "3", "0", "1"]],
                          "asks": [["2392.40", "0", "0", "0"]], "ts": "2", "seqId": "101", "prevSeqId": "100", "checksum": 0})
    top = book.top(50)
    assert top["bids"] == [(2392.35, 22.45), (2392.0, 40.0), (2391.9, 3.0)]     # best first, deleted level gone
    assert top["asks"] == [(2392.36, 2507.15)]
    assert book.top(1)["bids"] == [(2392.35, 22.45)]


def test_sequence_gap_is_detected_and_update_before_snapshot_rejected():
    book = L2Book()
    with pytest.raises(SequenceGap):
        book.apply("update", {"bids": [], "asks": [], "seqId": "5", "prevSeqId": "4"})
    book.apply("snapshot", SNAP)
    with pytest.raises(SequenceGap):
        book.apply("update", {"bids": [], "asks": [], "seqId": "103", "prevSeqId": "102"})    # 101 never arrived


def test_checksum_string_is_interleaved_top25_and_signed():
    book = L2Book()
    book.apply("snapshot", {"bids": [["3366.1", "7"], ["3366", "6"]], "asks": [["3366.8", "9"], ["3368", "8"]]})
    import struct, zlib
    expected = zlib.crc32(b"3366.1:7:3366.8:9:3366:6:3368:8")
    assert book.checksum() == struct.unpack("i", struct.pack("I", expected))[0]
    book2 = L2Book()
    with pytest.raises(SequenceGap):                                                 # a wrong non-zero checksum is rejected
        book2.apply("snapshot", {"bids": [["1", "1"]], "asks": [["2", "1"]], "checksum": 12345})


def test_market_state_publishes_top_n_and_keeps_previous(config):
    config.orderbook_depth_levels = 2
    ms = MarketState(symbol="ETH-USDT-SWAP", config=config)
    assert run(ms.apply_l2_message("snapshot", SNAP)) is True
    assert ms.depth_20["bids"] == [(2392.35, 17.9), (2392.3, 5.0)] and ms.depth_20["asks"][0] == (2392.36, 2507.15)
    assert run(ms.apply_l2_message("update", {"bids": [["2392.35", "1", "0", "1"]], "asks": [], "seqId": "101", "prevSeqId": "100"})) is True
    assert ms.previous_depth_20["bids"][0] == (2392.35, 17.9) and ms.depth_20["bids"][0] == (2392.35, 1.0)
    assert run(ms.apply_l2_message("update", {"bids": [], "asks": [], "seqId": "109", "prevSeqId": "108"})) is False
    assert not ms.l2_book.ready
