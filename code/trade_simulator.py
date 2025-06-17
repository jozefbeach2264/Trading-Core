from live_metrics import get_live_metrics
import random

def simulate_trade(direction="LONG", size=0.001):
    metrics = get_live_metrics()
    entry_price = metrics["best_ask"][0] if direction == "LONG" else metrics["best_bid"][0]
    slippage = random.uniform(0.01, 0.05)
    fill_price = entry_price + slippage if direction == "LONG" else entry_price - slippage
    return {
        "direction": direction,
        "entry": round(entry_price, 2),
        "fill": round(fill_price, 2),
        "status": "simulated"
    }