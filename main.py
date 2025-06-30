import asyncio
import logging
from fastapi import FastAPI, HTTPException
from typing import Dict, Any
import time

# Import all necessary components using absolute imports
from config import Config
from market_state import MarketState
from exchange_client import ExchangeClient
from internal_api_client import InternalApiClient
from strategy_router import StrategyRouter
from ai_strategy import AIStrategy
from trade_lifecycle_manager import TradeLifecycleManager
from risk.risk_management import CapitalManager
from simulation_account import SimulationAccount
from execution.ExecutionModule import ExecutionModule

# --- Application Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="TradingCore API")
config = Config()

# --- Global State and Module Initialization ---
app_state: Dict[str, Any] = {}

@app.on_event("startup")
async def startup_event():
    """Initializes all required modules on application startup."""
    logger.info("--- TradingCore Startup ---")
    symbol = "ETHUSDT" # Example symbol
    
    market_state = MarketState(symbol)
    exchange_client = ExchangeClient() # Authenticated client for exchange data
    internal_client = InternalApiClient(config) # Client for service-to-service communication
    
    setattr(config, 'dry_run_mode', True) 
    simulation_account = SimulationAccount(leverage=config.leverage)
    execution_module = ExecutionModule(config, simulation_account=simulation_account)

    app_state[symbol] = {
        "market_state": market_state,
        "exchange_client": exchange_client,
        "internal_client": internal_client,
        "strategy_router": StrategyRouter(),
        "ai_strategy": AIStrategy(),
        "trade_lifecycle_manager": TradeLifecycleManager(config, execution_module, market_state),
        "capital_manager": CapitalManager(config)
    }
    
    app_state[symbol]["trade_lifecycle_manager"].start()
    asyncio.create_task(data_fetch_loop(symbol))
    logger.info("--- TradingCore is Running ---")

# ... (data_fetch_loop, shutdown, and API endpoints remain the same, but with corrected client usage) ...
async def data_fetch_loop(symbol: str):
    """A background loop to continuously fetch market data."""
    state = app_state[symbol]
    exchange_client = state["exchange_client"]
    internal_client = state["internal_client"]
    market_state = state["market_state"]
    
    while True:
        try:
            # Fetch data from exchange and internal services
            tasks = [
                exchange_client.get_klines(symbol, "1m", 100),
                exchange_client.get_depth(symbol, 20),
                exchange_client.get_premium_index(symbol),
                internal_client.get_volume_data_from_neurosync() # Fetching from NeuroSync
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            if not isinstance(results[0], Exception): market_state.update_klines(results[0])
            if not isinstance(results[1], Exception): market_state.update_depth_20(results[1])
            if not isinstance(results[2], Exception): market_state.update_premium_index(results[2])
            # We don't update volume here, as NeuroSync is the source of truth for that now
            
        except Exception as e:
            logger.error(f"Error in data fetch loop: {e}")
        
        await asyncio.sleep(5)

@app.on_event("shutdown")
async def shutdown_event():
    """Gracefully shuts down all background tasks and connections."""
    logger.info("--- TradingCore Shutdown ---")
    for symbol, state in app_state.items():
        await state["trade_lifecycle_manager"].stop()
        await state["exchange_client"].close()
        await state["internal_client"].close()
    logger.info("--- TradingCore Shutdown Complete ---")

# --- API Endpoints ---
@app.get("/status")
async def get_status():
    """Returns the current status of the TradingCore."""
    return {"status": "ok", "message": "TradingCore is running."}

@app.post("/command/trigger-strategy")
async def trigger_strategy(command: Dict[str, Any]):
    # ... (logic remains the same)
    strategy_name = command.get("strategy")
    symbol = command.get("symbol", "ETHUSDT")

    if not strategy_name:
        raise HTTPException(status_code=400, detail="Strategy name is required.")
    
    state = app_state.get(symbol)
    if not state:
        raise HTTPException(status_code=404, detail=f"State for symbol {symbol} not found.")

    signal = await state["strategy_router"].run_strategy(strategy_name, state["market_state"])
    if not signal:
        return {"status": "ignored", "reason": "Strategy did not generate a signal."}

    ai_decision = await state["ai_strategy"].get_trade_decision(state["market_state"])
    
    if ai_decision.get("verdict") == "GO":
        trade_id = f"{strategy_name}_{int(time.time())}"
        state["trade_lifecycle_manager"].start_new_trade(trade_id, signal)
        return {"status": "EXECUTING", "decision": ai_decision, "signal": signal}
    else:
        return {"status": "REJECTED", "decision": ai_decision}
