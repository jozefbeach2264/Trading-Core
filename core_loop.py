import json
from strategy_runner import run_strategy
from trap_signal_handler import evaluate_trap_signals
from rolling5_module import Rolling5

r5 = Rolling5()

def load_schema():
    with open("schema_link.json", "r") as f:
        return json.load(f)

def run_core_cycle():
    schema = load_schema()
    result = None

    if schema.get("runtime_logging"):
        print("[CORE] Runtime logging is enabled")

    strategy = schema.get("strategy_mode")

    if strategy == "Rolling5":
        entry = 2600.0
        exit = 2615.0
        result = r5.simulate_trade(entry_price=entry, exit_price=exit)
    else:
        if strategy in schema.get("active_modules", []):
            result = run_strategy(strategy)

    if "TrapX" in schema.get("active_modules", []):
        evaluate_trap_signals()

    return result