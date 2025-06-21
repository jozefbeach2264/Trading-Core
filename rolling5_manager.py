# TradingCore/rolling5_manager.py (Corrected)
import asyncio

class Rolling5Manager:
    """
    The master orchestrator for the TradingCore. It initializes and manages
    all subsystems like the data fetcher, trading engine, and network clients.
    """
    def __init__(self, config):
        self.config = config
        self.services = {}
        self.app_state = {}
        print("Rolling5Manager Initialized.")

    def setup_modules(self):
        """Initializes all the necessary components for the trading core."""
        from market_state import MarketState
        from api_client import ApiClient
        from neurosync_client import NeuroSyncClient
        from data_orchestrator import DataOrchestrator
        from trading_engine import TradingEngine
        from execution_module import ExecutionModule

        print("Rolling5Manager: Setting up all modules...")
        self.app_state["market_state"] = MarketState()
        
        self.services["api_client"] = ApiClient(self.config)
        self.services["neurosync_client"] = NeuroSyncClient(self.config)
        self.services["data_orchestrator"] = DataOrchestrator(
            self.services["api_client"], self.app_state["market_state"]
        )
        self.services["execution_module"] = ExecutionModule(self.services["api_client"])
        
        # This line is now correct, passing both required arguments
        self.services["trading_engine"] = TradingEngine(
            self.app_state["market_state"], self.services["execution_module"]
        )
        print("Rolling5Manager: All modules created.")

    async def start(self):
        """Starts all background tasks and services."""
        print("Rolling5Manager: Starting all services...")
        await self.services["data_orchestrator"].start()
        asyncio.create_task(self.services["neurosync_client"].connect_and_listen())
        asyncio.create_task(self.services["trading_engine"].start_main_loop())
        print("Rolling5Manager: All services are running.")

    async def stop(self):
        """Gracefully stops all running services."""
        print("Rolling5Manager: Stopping all services...")
        stop_tasks = [
            s.stop() for s in self.services.values() if hasattr(s, 'stop')
        ]
        await asyncio.gather(*stop_tasks, return_exceptions=True)
        await self.services["api_client"].close()
        print("Rolling5Manager: All services stopped.")
