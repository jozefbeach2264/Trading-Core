import logging
from typing import Any, Dict

from config.config import Config
from data_managers.market_state import MarketState
from execution.simulation_account import SimulationAccount
from data_managers.trade_lifecycle_manager import TradeLifecycleManager
from memory_tracker import MemoryTracker
# --- FIX: Import the PerformanceTracker ---
from tracking.performance_tracker import PerformanceTracker

logger = logging.getLogger(__name__)

class TradeExecutor:
    """
    Upgraded to connect to the PerformanceTracker, logging the final financial
    outcome of every completed trade.
    """
    def __init__(self, config: Config, market_state: MarketState, http_client: Any, 
                 trade_lifecycle_manager: TradeLifecycleManager, 
                 memory_tracker: MemoryTracker,
                 simulation_account: SimulationAccount,
                 # --- FIX: Accept the PerformanceTracker instance ---
                 performance_tracker: PerformanceTracker):
        self.config = config
        self.market_state = market_state
        self.http_client = http_client
        self.sim_account = simulation_account
        self.trade_lifecycle_manager = trade_lifecycle_manager
        self.memory_tracker = memory_tracker
        # --- FIX: Store the PerformanceTracker instance ---
        self.performance_tracker = performance_tracker
        logger.info(f"TradeExecutor initialized and linked with PerformanceTracker. Dry Run Mode: {self.config.dry_run_mode}")

    async def initialize(self):
        logger.info("TradeExecutor initialized.")
        pass

    async def execute_trade(self, trade_details: Dict[str, Any]):
        """
        This function is UNCHANGED. It correctly routes new trades to the TLM.
        """
        if self.config.dry_run_mode:
            logger.info(f"Routing new simulated trade {trade_details.get('trade_id')} to TradeLifecycleManager.")
            await self.trade_lifecycle_manager.start_new_trade(
                trade_details.get('trade_id'),
                trade_details
            )
        else:
            logger.info(f"LIVE EXECUTION: Would place new trade {trade_details.get('trade_id')}.")
        return True

    async def exit_trade(self, trade_id: str, exit_price: float, exit_reason: str):
        """
        Upgraded to log the final trade result to the PerformanceTracker.
        """
        final_trade_record = None
        if self.config.dry_run_mode:
            trade = self.trade_lifecycle_manager.active_trades.get(trade_id)
            if not trade:
                logger.warning(f"Attempted to exit trade {trade_id}, but it was not found in TLM.")
                return False

            pnl = self.sim_account.close_trade(trade_id, exit_price, trade.leverage)

            # Calculate ROI for performance logging
            entry_value = trade.entry_price * trade.size
            roi_percent = (pnl / (entry_value / trade.leverage)) * 100 if entry_value > 0 else 0

            # --- FIX: Log to PerformanceTracker ---
            # Create the result packet for the performance tracker
            performance_result = {
                "trade_id": trade.trade_id,
                "symbol": trade.symbol,
                "direction": trade.direction,
                "pnl": pnl,
                "roi_percent": roi_percent,
                "exit_reason": exit_reason,
            }
            self.performance_tracker.log_trade(performance_result)

            # Prepare the detailed record for the MemoryTracker (for AI debugging)
            final_trade_record = {
                "trade_id": trade.trade_id,
                "direction": trade.direction,
                "quantity": trade.size,
                "entry_price": trade.entry_price,
                "exit_price": exit_price,
                "pnl": pnl,
                "simulated": True,
                "failed": pnl <= 0,
                "reason": exit_reason,
                "entry_candle_ohlcv": trade.entry_candle_ohlcv,
                "exit_candle_ohlcv": self.market_state.get_latest_data_snapshot().get('live_reconstructed_candle', [])
            }

        else:
            logger.info(f"LIVE EXECUTION: Would close trade {trade_id}.")

        # This part remains, logging the detailed debug data to MemoryTracker
        if final_trade_record:
            await self.memory_tracker.update_memory(trade_data=final_trade_record)
            logger.info(f"Logged final debug record for trade {trade_id} to MemoryTracker.")

        return True
