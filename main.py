import logging
import httpx
import asyncio
from contextlib import asynccontextmanager
from typing import Dict, Any
from fastapi import FastAPI
import os

from config.config import Config
from data_managers.market_state import (
    MarketState
)
from data_managers.market_data_manager import (
    MarketDataManager
)
from validator_stack import ValidatorStack
from system_managers.trade_executor import (
    TradeExecutor
)
from rolling5_engine import Rolling5Engine
from ai_client import AIClient

# --- Logging Setup ---
log_dir = os.path.dirname(Config().log_file_path)
if log_dir and not os.path.exists(log_dir):
    os.makedirs(log_dir)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - (%(name)s) - %(message)s',
    handlers=[
        logging.FileHandler(Config().log_file_path),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# --- App Lifespan Manager ---
app_state: Dict[str, Any] = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages the application's startup
    and shutdown procedures.
    """
    logger.info(
        "--- TradingCore Starting Up ---"
    )
    
    # 1. Initialize core components
    config = Config()
    app_state["config"] = config
    
    # ✅ NECESSARY UPDATE: Using the REST URL from the provided documentation.
    http_client = httpx.AsyncClient(
        base_url="https://eea.okx.com"
    )
    app_state["http_client"] = http_client
    
    market_state = MarketState(
        config=config, symbol=config.symbol
    )
    app_state["market_state"] = market_state
    
    market_data_manager = MarketDataManager(
        config=config,
        market_state=market_state,
        httpx_client=http_client
    )
    app_state["market_data_manager"] = (
        market_data_manager
    )
    
    trade_executor = TradeExecutor(
        config=config,
        market_state=market_state,
        httpx_client=http_client
    )
    app_state["trade_executor"] = (
        trade_executor
    )
    
    # 2. Initialize autonomous components
    app_state["validator_stack"] = (
        ValidatorStack(config)
    )
    app_state["ai_client"] = AIClient(config)
    app_state["engine"] = Rolling5Engine(
        config=config,
        market_state=market_state,
        validator_stack=(
            app_state["validator_stack"]
        ),
        trade_executor=trade_executor,
        ai_client=app_state["ai_client"]
    )
    
    # 3. Start background tasks
    await app_state["market_data_manager"].start()
    await app_state["engine"].start()
    
    logger.info(
        "--- TradingCore Startup Complete ---"
    )
    
    try:
        yield
    finally:
        # 4. Gracefully shut down
        logger.info(
            "--- TradingCore Shutting Down ---"
        )
        await app_state["engine"].stop()
        await app_state["ai_client"].close()
        await (
            app_state["market_data_manager"]
            .stop()
        )
        await app_state["http_client"].aclose()
        logger.info(
            "--- TradingCore Shutdown Complete ---"
        )

app = FastAPI(lifespan=lifespan)

# --- API Endpoints ---
@app.get("/status")
async def get_status():
    return {"status": "ok"}
