# main.py
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI

# Import all the new, consolidated modules we created
from config import Config
from api_client import ApiClient
from trading_engine import TradingEngine
from neurosync_client import NeuroSyncClient

# A global dictionary to hold our running service instances
services = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages the startup and shutdown of our application's background services.
    This code runs once when the Uvicorn server starts.
    """
    print("--- Trading-Core Service is starting up... ---")
    
    # 1. Initialize all our core components in the correct order
    config = Config()
    api_client = ApiClient(config)
    trading_engine = TradingEngine(config, api_client)
    neurosync_client = NeuroSyncClient(config, trading_engine)
    
    # 2. Store instances in the services dictionary for access elsewhere
    services["config"] = config
    services["api_client"] = api_client
    services["engine"] = trading_engine
    services["neurosync_client"] = neurosync_client
    
    # 3. Start the long-running background tasks
    asyncio.create_task(trading_engine.start_main_loop())
    asyncio.create_task(neurosync_client.connect_and_listen())
    
    print("--- All services started. Trading-Core is now running. ---")
    
    yield # The application runs while the 'yield' is active
    
    # This code runs when the server is shutting down (e.g., you press Ctrl+C)
    print("--- Trading-Core Service is shutting down... ---")
    if "engine" in services:
        await services["engine"].stop()
    if "neurosync_client" in services:
        await services["neurosync_client"].stop()
    print("--- All services stopped gracefully. ---")

# Create the main FastAPI application instance
app = FastAPI(lifespan=lifespan)

# --- API Endpoints from your Design Document ---

@app.get("/status", tags=["Health"])
async def get_status():
    """Endpoint for NeuroSync to check app health and readiness."""
    return {"status": "ok", "service": "Trading-Core", "engine_running": services.get("engine", {}).running}

@app.post("/signal", tags=["Trading"])
async def receive_external_signal(signal: dict):
    """Endpoint to receive external trade calls."""
    print(f"Received external signal via API: {signal}")
    # You can pass this signal to the trading engine
    # await services["engine"].process_signal_from_neurosync(signal)
    return {"status": "signal received"}

