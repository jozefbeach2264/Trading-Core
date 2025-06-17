from trade_simulator import simulate_trade
from metric_logger import log_metrics
from telemetry_stream import stream_telemetry
from orderbook_reader import fetch_orderbook
from orderbook_parser import parse_orderbook

def run_core_cycle():
    orderbook = fetch_orderbook()
    bids, asks = parse_orderbook(orderbook)
    
    metrics = {
        "top_bid": bids[0] if bids else (0, 0),
        "top_ask": asks[0] if asks else (0, 0),
        "spread": round(asks[0][0] - bids[0][0], 2) if bids and asks else 0
    }
    
    stream_telemetry(metrics)
    result = simulate_trade(direction="LONG", size=0.001)
    log_metrics(result)
    
    print(f"[EXECUTION] Entry: {result['entry']} | Fill: {result['fill']} | Status: {result['status']}")