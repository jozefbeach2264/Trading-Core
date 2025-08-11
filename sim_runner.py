# sim_runner.py
# Offline runner that reuses your live stack but drives MarketState from a CSV.
# No MarketDataManager. Feeds candles at 'speed' seconds per bar and lets Engine
# do its normal autonomous cycle.

import asyncio
import csv
import os
from collections import deque
from typing import List

# ==== keep your project imports consistent with your codebase ====
from config.config import Config
from data_managers.market_state import MarketState
from validator_stack import ValidatorStack
from rolling5_engine import Rolling5Engine
from simulators.entry_range_simulator import EntryRangeSimulator
from strategy.strategy_router import StrategyRouter
from strategy.ai_strategy import AIStrategy
from ai_client import AIClient
from memory_tracker import MemoryTracker
from system_managers.trade_executor import TradeExecutor
from system_managers.engine import Engine
from data_managers.trade_lifecycle_manager import TradeLifecycleManager
from execution.simulation_account import SimulationAccount
from tracking.performance_tracker import PerformanceTracker
import httpx


# ---------- CSV LOADER ----------
def load_klines_from_csv(csv_path: str) -> List[List[float]]:
    """
    Expected columns (header ok):
    open_time_ms, open, high, low, close, volume
    """
    rows: List[List[float]] = []
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        rdr = csv.reader(f)
        for raw in rdr:
            if not raw:
                continue
            # skip header if present
            if raw[0].strip().lower().startswith("open"):
                continue
            try:
                ts = int(float(raw[0]))
                o = float(raw[1]); h = float(raw[2]); l = float(raw[3]); c = float(raw[4]); v = float(raw[5])
                rows.append([ts, o, h, l, c, v])
            except Exception:
                # ignore malformed line
                continue
    if not rows:
        raise RuntimeError(f"No valid rows parsed from {csv_path}")
    rows.sort(key=lambda r: r[0])  # oldest -> newest
    return rows


# ---------- FEED CSV INTO MARKET STATE ----------
async def play_csv(ms: MarketState, candles: List[List[float]], *, delay_s: float, maxlen: int):
    """
    Pushes candles into ms.klines with newest at index 0 (to match your system),
    updates ms.mark_price, and refreshes order-book metrics each tick so
    OrderBookReversalZoneDetector & friends see current data.
    """
    ms.klines = deque(maxlen=maxlen)

    # seed history up to maxlen (oldest first), then reverse orientation
    seed = candles[:maxlen]
    for c in seed:
        ms.klines.appendleft(c)

    # stream the remainder forward
    for c in candles[maxlen:]:
        ms.klines.appendleft(c)   # newest becomes index 0
        ms.mark_price = c[4]

        # make sure any filters that rely on cached OB metrics can read something
        try:
            # your MarketState method—safe if it’s a no-op offline
            await ms.ensure_order_book_metrics_are_current()
        except Exception:
            # don’t crash the sim if OB metrics can’t be built offline
            pass

        await asyncio.sleep(delay_s)


# ---------- MAIN ----------
async def main(csv_path: str, symbol: str = "ETHUSDT", speed: float = 0.05):
    # 1) Load data
    candles = load_klines_from_csv(csv_path)

    # 2) Build the stack EXACTLY like your live wiring (minus MarketDataManager)
    config = Config()

    http_client = httpx.AsyncClient()
    market_state = MarketState(config=config, symbol=symbol)
    memory_tracker = MemoryTracker(config)
    r5_forecaster = Rolling5Engine(config)
    strategy_router = StrategyRouter(config)
    validator_stack = ValidatorStack(config)
    entry_simulator = EntryRangeSimulator(config)
    ai_client = AIClient(config)
    performance_tracker = PerformanceTracker(config)
    simulation_account = SimulationAccount(config)

    # circular dep: TLM <-> Executor <-> AIStrategy. Create then link.
    trade_lifecycle_manager = TradeLifecycleManager(config, None, market_state, None)

    trade_executor = TradeExecutor(
        config,
        market_state,
        http_client,
        trade_lifecycle_manager,
        memory_tracker,
        simulation_account,
        performance_tracker,
    )

    ai_strategy = AIStrategy(
        config,
        strategy_router,
        r5_forecaster,
        ai_client,
        entry_simulator,
        memory_tracker,
        trade_executor,
    )

    trade_lifecycle_manager.execution_module = trade_executor
    trade_lifecycle_manager.ai_strategy = ai_strategy

    engine = Engine(
        config=config,
        market_state=market_state,
        validator_stack=validator_stack,
        ai_strategy=ai_strategy,
        trade_executor=trade_executor,
    )

    # 3) Start engine + TLM; then stream CSV
    await trade_executor.initialize()
    trade_lifecycle_manager.start()  # background monitoring thread in your design

    await engine.start()

    # run feeder
    feeder = asyncio.create_task(
        play_csv(
            market_state,
            candles,
            delay_s=speed,
            maxlen=getattr(config, "kline_deque_maxlen", 1000),
        )
    )

    await feeder
    # allow one last engine cycle after final candle
    await asyncio.sleep(max(getattr(config, "engine_cycle_interval", 1.0), 0.5))
    await engine.stop()

    # teardown http client
    await http_client.aclose()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Offline CSV simulator for your Trading-Core")
    parser.add_argument("--csv", required=True, help="Path to candles CSV (open_time_ms,open,high,low,close,volume)")
    parser.add_argument("--symbol", default="ETHUSDT")
    parser.add_argument("--speed", type=float, default=0.05, help="Seconds per candle during simulation")
    args = parser.parse_args()
    asyncio.run(main(args.csv, symbol=args.symbol, speed=args.speed))