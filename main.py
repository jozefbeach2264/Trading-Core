import logging
import os
import asyncio
from fastapi import FastAPI
from contextlib import asynccontextmanager
import httpx

from config.config import Config
from data_managers.market_state import MarketState
from data_managers.market_data_manager import MarketDataManager
from ai_client import AIClient
from validator_stack import ValidatorStack
from simulators.entry_range_simulator import EntryRangeSimulator
from rolling5_engine import Rolling5Engine
from strategy.trade_module_trapx import TradeModuleTrapX
from strategy.trade_module_scalpel import TradeModuleScalpel
from strategy.strategy_router import StrategyRouter
from strategy.ai_strategy import AIStrategy
from system_managers.trade_executor import TradeExecutor
from system_managers.engine import Engine
from memory_tracker import MemoryTracker

config = Config()

class LogLevelFilter(logging.Filter):
    def __init__(self, level):
        self.level = level
        super().__init__()

    def filter(self, record):
        return record.levelno >= self.level

logging.basicConfig(
    level=getattr(logging, config.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(config.log_file_path)
    ]
)
for handler in logging.getLogger().handlers:
    if isinstance(handler, logging.FileHandler):
        handler.addFilter(LogLevelFilter(getattr(logging, config.log_level.upper(), logging.INFO)))

logger = logging.getLogger(__name__)

app_state = {}
app = FastAPI()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.debug("--- REALITY_CORE (GENESIS) Bootstrap Initializing ---")
    
    http_client = httpx.AsyncClient()
    market_state = MarketState(config=config, symbol=config.trading_symbol)
    okx_data_manager = MarketDataManager(config=config, market_state=market_state, httpx_client=httpx.AsyncClient(base_url="https://www.okx.com"))
    memory_tracker = MemoryTracker(config)
    
    r5_forecaster = Rolling5Engine(config)
    strategy_router = StrategyRouter(config)
    validator_stack = ValidatorStack(config)
    entry_simulator = EntryRangeSimulator(config)
    ai_client = AIClient(config)
    trade_executor = TradeExecutor(config, market_state, http_client)
    
    ai_strategy = AIStrategy(config, strategy_router, r5_forecaster, ai_client, entry_simulator, memory_tracker)
    
    engine = Engine(config=config, market_state=market_state, validator_stack=validator_stack, ai_strategy=ai_strategy, trade_executor=trade_executor)
    app_state.update({"engine": engine, "market_data_manager": okx_data_manager, "http_client": http_client, "memory_tracker": memory_tracker})

    await trade_executor.initialize()
    await okx_data_manager.start()
    while not (market_state.depth_20.get("bids") and market_state.depth_20.get("asks") and market_state.mark_price):
        logger.debug("Waiting for MarketState data: depth_20=%s, mark_price=%s", market_state.depth_20, market_state.mark_price)
        await asyncio.sleep(0.05)
    logger.debug("MarketState data ready: depth_20=%s, mark_price=%s", market_state.depth_20, market_state.mark_price)
    await engine.start()

    logger.debug("--- REALITY_CORE Bootstrap Complete. System is LIVE. ---")
    
    try:
        yield
    finally:
        logger.debug("--- REALITY_CORE Shutting Down ---")
        if app_state.get("engine"): await app_state["engine"].stop()
        if app_state.get("market_data_manager"): await app_state["market_data_manager"].stop()
        if app_state.get("http_client"): await app_state["http_client"].aclose()
        logger.debug("--- REALITY_CORE Shutdown Complete ---")

app = FastAPI(lifespan=lifespan)

@app.get("/status")
async def get_status(): return {"status": "ok", "service": "REALITY_CORE"}
@app.get("/")
async def root(): return {"message": "REALITY_CORE is active."}
