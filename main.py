# TradingCore/main.py (Simplified)
from contextlib import asynccontextmanager
from fastapi import FastAPI

from config import Config
from rolling5_manager import Rolling5Manager # Import the new manager

manager = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    The FastAPI lifespan manager. It now only deals with the top-level manager.
    """
    print("--- Trading-Core application starting... ---")
    global manager
    
    # Initialize the master manager with the application config
    config = Config()
    manager = Rolling5Manager(config)
    
    # Setup and start all modules through the manager
    manager.setup_modules()
    await manager.start()
    
    yield
    # --- Code below this line runs on shutdown ---
    print("--- Trading-Core application shutting down... ---")
    await manager.stop()

# Create the FastAPI app
app = FastAPI(lifespan=lifespan)

# Your API endpoints remain the same
@app.get("/status")
async def get_status():
    """Health check endpoint for NeuroSync to ping."""
    return {"status": "ok", "service": "Trading-Core"}

@app.get("/market_state")
async def get_market_state():
    """An endpoint to view the current market state."""
    # Ensure manager is initialized before accessing state
    if manager and "market_state" in manager.app_state:
        async with manager.app_state["market_state"].lock:
            # Return a copy for thread-safety
            return manager.app_state["market_state"].__dict__.copy()
    return {"error": "Market state not initialized."}



