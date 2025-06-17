from trade_simulator import simulate_trade
from metric_logger import log_metrics

def run_core_cycle():
    result = simulate_trade()
    log_metrics(result)
    return result