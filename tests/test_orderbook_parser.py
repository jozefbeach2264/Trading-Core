"""Defect F (review finding 3): no synthetic walls. A book without a real wall must
yield no walls and therefore a zero thinning rate."""
from data_managers.orderbook_parser import OrderBookParser


def _book(bid_qtys, ask_qtys, price=3000.0):
    bids = [(price - i * 0.1, q) for i, q in enumerate(bid_qtys)]
    asks = [(price + 0.1 + i * 0.1, q) for i, q in enumerate(ask_qtys)]
    return {"bids": bids, "asks": asks}


def test_no_wall_returns_empty_lists():
    walls = OrderBookParser().find_wall_clusters(_book([1.0, 2.0, 3.0, 2.5, 1.5], [1.2, 2.2, 3.1, 2.0, 1.0]))
    assert walls == {"bid_walls": [], "ask_walls": []}


def test_real_wall_is_detected():
    walls = OrderBookParser().find_wall_clusters(_book([1.0, 2.0, 30.0, 2.5, 1.5], [1.0, 1.0, 1.0, 1.0, 1.0]), multiplier=10.0)
    assert walls["bid_walls"] == [{"price": 2999.8, "qty": 30.0}]
    assert walls["ask_walls"] == []


def test_ordinary_churn_is_not_thinning():
    parser = OrderBookParser()
    prev = _book([1.0, 2.0, 3.0, 2.5, 1.5], [1.0, 1.0, 1.0, 1.0, 1.0])
    curr = _book([1.0, 2.0, 2.1, 2.5, 1.5], [1.0, 1.0, 1.0, 1.0, 1.0])  # largest level shrank 30%
    metrics = parser.analyze_thinning_and_spoofing(prev, curr)
    assert metrics["spoof_thin_rate"] == 0.0 and metrics["wall_delta_pct"] == 0.0


def test_real_wall_thinning_is_measured():
    parser = OrderBookParser()
    prev = _book([1.0, 2.0, 100.0, 2.5, 1.5], [1.0, 1.0, 1.0, 1.0, 1.0])
    curr = _book([1.0, 2.0, 70.0, 2.5, 1.5], [1.0, 1.0, 1.0, 1.0, 1.0])
    metrics = parser.analyze_thinning_and_spoofing(prev, curr)
    assert abs(metrics["spoof_thin_rate"] - 30.0) < 1e-9
    assert abs(metrics["wall_delta_pct"] + 30.0) < 1e-9


def test_consumed_top_of_book_does_not_fake_a_pulled_wall():
    """The wall threshold is relative to the top-of-book qty; when the top order fills, the
    threshold jumps and the unchanged wall no longer qualifies in the NEW snapshot. Thinning must
    be measured per price level against the previous walls, so this reads as 0%, not 100%."""
    parser = OrderBookParser()
    prev = {"bids": [(3000.0, 0.5), (2999.9, 1.0), (2999.8, 6.0), (2999.7, 1.2), (2999.6, 0.9)],
            "asks": [(3000.1, 1.0)] * 5}
    curr = {"bids": [(2999.9, 1.0), (2999.8, 6.0), (2999.7, 1.2), (2999.6, 0.9), (2999.5, 0.8)],
            "asks": [(3000.1, 1.0)] * 5}
    metrics = parser.analyze_thinning_and_spoofing(prev, curr, distance_percent=2.0, multiplier=10.0)
    assert metrics["spoof_thin_rate"] == 0.0


def test_wall_that_left_the_visible_window_is_not_a_pull():
    parser = OrderBookParser()
    prev = {"bids": [(3000.0, 1.0), (2999.9, 1.0), (2999.8, 60.0), (2999.7, 1.0), (2999.6, 1.0)], "asks": [(3000.1, 1.0)] * 5}
    curr = {"bids": [(3000.3, 1.0), (3000.2, 1.0), (3000.1, 1.0), (3000.0, 1.0), (2999.9, 1.0)], "asks": [(3000.4, 1.0)] * 5}
    assert parser.analyze_thinning_and_spoofing(prev, curr, multiplier=10.0)["spoof_thin_rate"] == 0.0


def test_wall_pulled_at_the_same_price_is_measured_on_both_sides():
    parser = OrderBookParser()
    prev = {"bids": [(3000.0, 1.0), (2999.9, 1.0), (2999.8, 50.0), (2999.7, 1.0), (2999.6, 1.0)],
            "asks": [(3000.1, 1.0), (3000.2, 1.0), (3000.3, 40.0), (3000.4, 1.0), (3000.5, 1.0)]}
    curr = {"bids": [(3000.0, 1.0), (2999.9, 1.0), (2999.8, 50.0), (2999.7, 1.0), (2999.6, 1.0)],
            "asks": [(3000.1, 1.0), (3000.2, 1.0), (3000.3, 10.0), (3000.4, 1.0), (3000.5, 1.0)]}
    metrics = parser.analyze_thinning_and_spoofing(prev, curr, multiplier=10.0)
    assert abs(metrics["ask_thin_rate"] - 75.0) < 1e-9 and metrics["bid_thin_rate"] == 0.0
    assert abs(metrics["spoof_thin_rate"] - 75.0) < 1e-9


def test_wall_threshold_uses_best_ask_not_deepest():
    walls = OrderBookParser().find_wall_clusters(
        {"bids": [(3000.0, 1.0)] * 5, "asks": [(3000.1, 1.0), (3000.2, 1.0), (3000.3, 12.0), (3000.4, 1.0), (3000.5, 30.0)]},
        multiplier=10.0)
    assert [w["qty"] for w in walls["ask_walls"]] == [12.0, 30.0]
