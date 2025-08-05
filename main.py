import logging
import asyncio
import sys
import os
from fastapi import FastAPI
from contextlib import asynccontextmanager
import httpx
from pythonjsonlogger import jsonlogger

# --- THIS IS THE PERMANENT FIX ---
# This block of code adds the project's root directory to the Python path.
# It ensures that all modules can be found using absolute imports (e.g., 'from execution.execution_module').
# This must be at the very top, before any other project modules are imported.
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from config.config import Config
from data_managers.market_state import MarketState
from data_managers.market_data_manager import MarketDataManager
from ai_client import AIClient
from validator_stack import ValidatorStack
from simulators.entry_range_simulator import EntryRangeSimulator
from rolling5_engine import Rolling5Engine
from strategy.strategy_router import StrategyRouter
from strategy.ai_strategy import AIStrategy
from execution.execution_module import ExecutionModule
from execution.simulation_account import SimulationAccount
from system_managers.engine import Engine
from services.memory_tracker import MemoryTracker

config = Config()

logger = logging.getLogger()
logger.setLevel(getattr(logging, config.log_level.upper(), logging.INFO))

if logger.hasHandlers():
    logger.handlers.clear()

formatter = jsonlogger.JsonFormatter('%(asctime)s %(name)s %(levelname)s %(message)s')

logHandler = logging.StreamHandler()
logHandler.setFormatter(formatter)
logger.addHandler(logHandler)

fileHandler = logging.FileHandler(config.log_file_path, mode='a')
fileHandler.setFormatter(formatter)
logger.addHandler(fileHandler)

app_state = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("--- REALITY_CORE (GENESIS) Bootstrap Initializing ---")

    http_client = httpx.AsyncClient()
    market_state = MarketState(config=config, symbol=config.trading_symbol)
    okx_data_manager = MarketDataManager(config=config, market_state=market_state, httpx_client=httpx.AsyncClient(base_url="https://www.okx.com"))
    memory_tracker = MemoryTracker(config)

    r5_forecaster = Rolling5Engine(config)
    strategy_router = StrategyRouter(config)
    validator_stack = ValidatorStack(config)
    entry_simulator = EntryRangeSimulator(config)
    ai_client = AIClient(config)

    # Create the simulation account and the execution module that uses it
    simulation_account = SimulationAccount(config)
    execution_module = ExecutionModule(config, simulation_account)

    # The 'execution_module' instance is now correctly passed to the AIStrategy constructor.
    ai_strategy = AIStrategy(
        config,
        strategy_router,
        r5_forecaster,
        ai_client,
        entry_simulator,
        memory_tracker,
        execution_module  # The missing argument
    )

    # Pass all required modules to the Engine
    engine = Engine(
        config=config,
        market_state=market_state,
        validator_stack=validator_stack,
        ai_strategy=ai_strategy,
        trade_executor=execution_module
    )

    app_state.update({
        "engine": engine, "market_data_manager": okx_data_manager,
        "http_client": http_client, "memory_tracker": memory_tracker,
        "ai_client": ai_client, "execution_module": execution_module
    })

    await okx_data_manager.start()

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
        if app_state.get("market_data_manager"):
            await app_state["market_data_manager"].stop()
        if app_state.get("ai_client"):
            await app_state["ai_client"].close()
        if app_state.get("http_client"):
            await app_state["http_client"].aclose()
        logger.info("--- REALITY_CORE Shutdown Complete ---")

app = FastAPI(lifespan=lifespan)

@app.get("/status")
async def get_status():
    return {"status": "ok", "service": "REALITY_CORE"}

@app.get("/")
async def root():
    return {"message": "REALITY_CORE is active."}