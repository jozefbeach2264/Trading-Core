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
    assert parser.analyze_thinning_and_spoofing(prev, curr) == {"spoof_thin_rate": 0.0, "wall_delta_pct": 0.0}


def test_real_wall_thinning_is_measured():
    parser = OrderBookParser()
    prev = _book([1.0, 2.0, 100.0, 2.5, 1.5], [1.0, 1.0, 1.0, 1.0, 1.0])
    curr = _book([1.0, 2.0, 70.0, 2.5, 1.5], [1.0, 1.0, 1.0, 1.0, 1.0])
    metrics = parser.analyze_thinning_and_spoofing(prev, curr)
    assert abs(metrics["spoof_thin_rate"] - 30.0) < 1e-9
    assert abs(metrics["wall_delta_pct"] + 30.0) < 1e-9
