import logging
import asyncio
import os
from fastapi import FastAPI
from contextlib import asynccontextmanager
import httpx
from pythonjsonlogger import jsonlogger

from config.config import Config
from data_managers.market_state import MarketState
from data_managers.market_data_manager import MarketDataManager
from ai_client import AIClient
from validator_stack import ValidatorStack
from simulators.entry_range_simulator import EntryRangeSimulator
from rolling5_engine import Rolling5Engine
from strategy.strategy_router import StrategyRouter
from strategy.ai_strategy import AIStrategy
from system_managers.trade_executor import TradeExecutor
from system_managers.engine import Engine
from memory_tracker import MemoryTracker
import log_utils
from freshness import market_data_age_s

config = Config()

logger = logging.getLogger()
logger.setLevel(getattr(logging, config.log_level.upper(), logging.INFO))

if logger.hasHandlers():
    logger.handlers.clear()

formatter = jsonlogger.JsonFormatter('%(asctime)s %(name)s %(levelname)s %(message)s')

logHandler = logging.StreamHandler()
logHandler.setFormatter(formatter)

os.makedirs(os.path.dirname(os.path.abspath(config.log_file_path)), exist_ok=True)
fileHandler = logging.FileHandler(config.log_file_path, mode='a')
fileHandler.setFormatter(formatter)
# Both handlers sit behind one queue so the event loop never blocks on stdout/disk.
log_utils.make_async(logger, [logHandler, fileHandler])

app_state = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("--- REALITY_CORE (GENESIS) Bootstrap Initializing ---")
    
    # Shared exchange client: long keep-alive so a live order does not pay a fresh TLS handshake.
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(10.0, connect=3.0),
        limits=httpx.Limits(max_keepalive_connections=10, keepalive_expiry=90.0),
    )
    market_state = MarketState(config=config, symbol=config.trading_symbol)
    okx_data_manager = MarketDataManager(config=config, market_state=market_state, httpx_client=httpx.AsyncClient(base_url=config.okx_base_url))
    memory_tracker = MemoryTracker(config)
    
    r5_forecaster = Rolling5Engine(config)
    strategy_router = StrategyRouter(config)
    validator_stack = ValidatorStack(config)
    entry_simulator = EntryRangeSimulator(config)
    ai_client = AIClient(config)
    trade_executor = TradeExecutor(config, market_state, http_client)
    
    ai_strategy = AIStrategy(config, strategy_router, r5_forecaster, ai_client, entry_simulator, memory_tracker)
    
    engine = Engine(config=config, market_state=market_state, validator_stack=validator_stack, ai_strategy=ai_strategy, trade_executor=trade_executor)
    
    app_state.update({
        "engine": engine, "market_data_manager": okx_data_manager,
        "http_client": http_client, "memory_tracker": memory_tracker,
        "ai_client": ai_client
    })
    
    await trade_executor.initialize()
    await ai_client.check_provider()
    # Link event queue for intra-candle triggers
    okx_data_manager.set_event_queue(engine.event_queue)
    await okx_data_manager.start()

    # --- Efficient Startup Sequence ---
    # This now waits for the 'initial_data_ready' event from MarketState
    # instead of using an inefficient busy-wait loop.
    logger.info("Waiting for initial market data from OKX...")
    await market_state.initial_data_ready.wait()
    logger.info("Initial market data received. Proceeding with engine start.")
    
    await engine.start()
    
    logger.info("--- REALITY_CORE Bootstrap Complete. System is LIVE. ---")
    
    try:
        yield
    finally:
        logger.info("--- REALITY_CORE Shutting Down ---")
        if app_state.get("engine"):
            await app_state["engine"].stop()
        await trade_executor.close()
        if app_state.get("market_data_manager"):
            await app_state["market_data_manager"].stop()
        if app_state.get("ai_client"):
            await app_state["ai_client"].close()
        if app_state.get("http_client"):
            await app_state["http_client"].aclose()
        logger.info("--- REALITY_CORE Shutdown Complete ---")
        log_utils.flush_all()

app = FastAPI(lifespan=lifespan)

@app.get("/status")
async def get_status():
    return {"status": "ok", "service": "REALITY_CORE"}


@app.get("/stats")
async def get_stats():
    """Dry-run scoreboard: simulation statistics, the open position, lifecycle and feed freshness."""
    engine = app_state.get("engine")
    executor = engine.trade_executor if engine else None
    market_state = engine.market_state if engine else None
    state = await asyncio.to_thread(executor._get_simulation_state) if executor and config.dry_run_mode else {}
    lifecycle = engine._lifecycle() if engine else None
    return {
        "mode": "DRY_RUN" if config.dry_run_mode else "LIVE",
        "model": config.ai_model, "provider": config.ai_provider_url,
        "balance": state.get("balance"), "initial_capital": state.get("initial_capital"),
        "open_position": (state.get("positions") or {}).get(config.adex_symbol),
        "stats": state.get("stats"),
        "lifecycle": {"active": lifecycle.active, "candle_count": lifecycle.candle_count} if lifecycle else None,
        "mark_price": market_state.mark_price if market_state else None,
        "market_data_age_s": round(market_data_age_s(market_state), 2) if market_state else None,
        "klines": len(market_state.klines) if market_state else 0,
        "book_levels": {"bids": len(market_state.depth_20.get("bids", [])), "asks": len(market_state.depth_20.get("asks", [])),
                        "l2_updates": market_state.l2_book.updates, "channel": config.orderbook_channel} if market_state else None,
        "walls": {k: len(v) for k, v in (market_state.order_book_walls or {}).items()} if market_state else None,
        "spoof_metrics": market_state.spoof_metrics if market_state else None,
        "verdict_cache_hits": getattr(engine.ai_strategy, "cache_hits", None) if engine else None,
        "cycles_while_position_open": getattr(engine, "cycles_while_open", None) if engine else None,
    }

@app.get("/")
async def root():
    return {"message": "REALITY_CORE is active."}
