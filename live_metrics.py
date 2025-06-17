from orderbook_reader import fetch_orderbook
from orderbook_parser import parse_orderbook

def get_live_metrics():
    raw_data = fetch_orderbook()
    bids, asks = parse_orderbook(raw_data)
    best_bid = bids[0] if bids else (0, 0)
    best_ask = asks[0] if asks else (0, 0)
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": round(best_ask[0] - best_bid[0], 2)
    }