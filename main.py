import asyncio
import logging
import aiohttp
import httpx
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, Request
from pydantic import BaseModel
import os

from config.config import config
from data_managers.market_data_manager import MarketDataManager
from system_managers.partner_checker import PartnerChecker
from system_managers.trade_executor import TradeExecutor
from console_display import format_market_state_for_console

# --- Application Setup: File-Based Logging ---

# Ensure the log directory exists
log_dir = os.path.dirname(config.log_file_path)
if log_dir and not os.path.exists(log_dir):
    os.makedirs(log_dir)

# Get the root logger and set its level
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# Create a formatter
formatter = logging.Formatter('%(asctime)s - [%(levelname)s] - (%(name)s) - %(message)s')

# Create a file handler
file_handler = logging.FileHandler(config.log_file_path)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)

# Create a stream handler for console output
stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.INFO)
stream_handler.setFormatter(formatter)

# Add both handlers to the root logger
if not root_logger.handlers:
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)

# Quieten noisy third-party libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("watchfiles").setLevel(logging.WARNING)
logging.getLogger("uvicorn").setLevel(logging.WARNING)

# --- ADDED: Define the logger for this module ---
logger = logging.getLogger(__name__)

# This will hold shared instances of our manager classes
app_state: dict = {}

class TradeAlert(BaseModel):
    """Defines the structure for an incoming trade alert."""
    symbol: str
    signal: str
    confidence: Optional[float] = None

async def console_display_loop():
    """The main display loop."""
    while True:
        manager = app_state.get("market_data_manager")
        if manager:
            display_string = format_market_state_for_console(manager.market_state)
            print(display_string, end="")
        await asyncio.sleep(1)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("--- TradingCore Startup ---")
    
    aiohttp_session = aiohttp.ClientSession()
    httpx_client = httpx.AsyncClient()
    
    market_manager = MarketDataManager(config, aiohttp_session, httpx_client)
    partner_checker = PartnerChecker(config, httpx_client)
    trade_executor = TradeExecutor(config, market_manager.market_state, httpx_client)
    await trade_executor.initialize()
    
    app_state["market_data_manager"] = market_manager
    app_state["partner_checker"] = partner_checker
    app_state["trade_executor"] = trade_executor
    
    market_manager.start()
    partner_checker.start()

    console_task = asyncio.create_task(console_display_loop())
    logger.info("--- TradingCore Startup Complete. All services running. ---")
    
    yield

    logger.info("--- TradingCore Shutdown ---")
    if console_task: console_task.cancel()
    await partner_checker.stop()
    await market_manager.stop()
    
    await aiohttp_session.close()
    await httpx_client.aclose()
    logger.info("Network sessions closed.")

app = FastAPI(title="TradingCore API", lifespan=lifespan)

@app.get("/status", tags=["Health"])
def get_status():
    """Provides a simple 200 OK health check."""
    return {"status": "ok", "service": "TradingCore"}

@app.post("/api/v1/alert", tags=["Trading"])
async def receive_alert(alert: TradeAlert, request: Request):
    """Receives a validated trade alert and forwards it to the executor."""
    logger.info(f"Signal received: {alert.signal} for {alert.symbol}")
    
    trade_executor: TradeExecutor = request.app.state["trade_executor"]
    await trade_executor.execute_trade(alert)

    return {
        "status": "signal_received_and_forwarded_to_executor",
        "details": alert.dict()
    }
