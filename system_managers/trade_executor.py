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

    async def execute_trade(self, trade_details: Dict[str, Any], candle_timestamp: int = None) -> bool:
        """
        Execute a trade order (live or simulated) and log the result.
        """
        try:
            logger.info(f"Executing trade: {trade_details}")

            # Add timestamp to trade details for memory tracking
            if candle_timestamp:
                trade_details["candle_timestamp"] = candle_timestamp

            if self.config.dry_run_mode:
                # Simulate the trade execution
                success = await self.sim_account.execute_trade(trade_details)
                if success:
                    logger.info(f"✅ Simulated trade executed successfully: {trade_details}")
                    await self.performance_tracker.log_trade(trade_details, success=True)
                    # Log successful trade to memory tracker
                    await self.memory_tracker.update_memory(trade_data={
                        "direction": trade_details.get("direction"),
                        "quantity": trade_details.get("size", 0.0),
                        "entry_price": trade_details.get("entry_price", 0.0),
                        "simulated": True,
                        "failed": False,
                        "reason": "Trade executed successfully",
                        "order_data": trade_details,
                        "candle_timestamp": candle_timestamp
                    })
                else:
                    logger.warning(f"❌ Simulated trade failed: {trade_details}")
                    await self.performance_tracker.log_trade(trade_details, success=False)
                    # Log failed trade to memory tracker
                    await self.memory_tracker.update_memory(trade_data={
                        "direction": trade_details.get("direction"),
                        "quantity": trade_details.get("size", 0.0),
                        "entry_price": trade_details.get("entry_price", 0.0),
                        "simulated": True,
                        "failed": True,
                        "reason": "Simulated trade execution failed",
                        "order_data": trade_details,
                        "candle_timestamp": candle_timestamp
                    })
                return success
            else:
                # Execute real trade (placeholder for actual implementation)
                logger.info(f"🚀 LIVE TRADE would be executed: {trade_details}")
                await self.performance_tracker.log_trade(trade_details, success=True)
                await self.memory_tracker.update_memory(trade_data={
                    "direction": trade_details.get("direction"),
                    "quantity": trade_details.get("size", 0.0),
                    "entry_price": trade_details.get("entry_price", 0.0),
                    "simulated": False,
                    "failed": False,
                    "reason": "Live trade executed",
                    "order_data": trade_details,
                    "candle_timestamp": candle_timestamp
                })
                return True
        except Exception as e:
            logger.error(f"Error executing trade: {e}", exc_info=True)
            await self.performance_tracker.log_trade(trade_details, success=False)
            await self.memory_tracker.update_memory(trade_data={
                "direction": trade_details.get("direction"),
                "quantity": trade_details.get("size", 0.0),
                "entry_price": trade_details.get("entry_price", 0.0),
                "simulated": self.config.dry_run_mode,
                "failed": True,
                "reason": f"Trade execution error: {str(e)}",
                "order_data": trade_details,
                "candle_timestamp": candle_timestamp
            })
            return False

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