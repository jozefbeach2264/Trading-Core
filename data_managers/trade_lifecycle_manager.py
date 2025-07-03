import asyncio
import logging
from typing import Dict, Any

from config.config import Config
from managers.market_state import MarketState
from execution.ExecutionModule import ExecutionModule
from ai_strategy import AIStrategy

logger = logging.getLogger(__name__)

class ActiveTrade:
    """A simple data class to hold information about a single active trade."""
    def __init__(self, trade_id: str, trade_data: Dict[str, Any]):
        self.trade_id: str = trade_id
        self.symbol: str = trade_data.get("symbol")
        self.direction: str = trade_data.get("direction")
        self.entry_price: float = trade_data.get("entry_price")
        self.current_tp: float = trade_data.get("tp")
        self.current_sl: float = trade_data.get("sl")
        self.size: float = trade_data.get("size")

class TradeLifecycleManager:
    """
    Monitors all active trades and manages their exit conditions.
    Dynamically fetches updated TP/SL targets from the AI on each cycle.
    """
    def __init__(self, config: Config, execution_module: ExecutionModule, market_state: MarketState, ai_strategy: AIStrategy):
        self.config = config
        self.execution_module = execution_module
        self.market_state = market_state
        self.ai_strategy = ai_strategy
        self.active_trades: Dict[str, ActiveTrade] = {}
        self.running = False
        self.task = None
        logger.info("TradeLifecycleManager initialized for dynamic target management.")

    def start_new_trade(self, trade_id: str, trade_data: Dict[str, Any]):
        """Adds a new trade to the monitoring list."""
        if trade_id in self.active_trades:
            logger.warning(f"Trade {trade_id} is already being managed.")
            return
        try:
            self.active_trades[trade_id] = ActiveTrade(trade_id, trade_data)
            logger.info(f"Now managing new trade: {trade_id}")
        except Exception as e:
            logger.error(f"Could not start managing trade {trade_id}: {e}")

    async def _run_monitoring_cycle(self):
        """The main monitoring loop that runs periodically as an asyncio task."""
        while self.running:
            try:
                if not self.active_trades:
                    await asyncio.sleep(self.config.tlm_poll_interval_seconds)
                    continue

                for trade_id in list(self.active_trades.keys()):
                    await self._check_trade(trade_id)
                
                await asyncio.sleep(self.config.tlm_poll_interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in TLM monitoring cycle: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def _check_trade(self, trade_id: str):
        """Checks a single trade for exit conditions using dynamically updated targets."""
        trade = self.active_trades.get(trade_id)
        if not trade: return
        
        # This is the placeholder for the dynamic target logic we discussed.
        # A full implementation requires a new 'get_dynamic_targets' method in AIStrategy.
        # For now, we will use the existing TP/SL to ensure the system runs.
        # dynamic_targets = await self.ai_strategy.get_dynamic_targets(self.market_state.get_latest_data_snapshot())
        
        current_price = self.market_state.mark_price
        if not current_price: return

        exit_reason = None
        # Check against TP/SL
        if trade.direction == "LONG":
            if current_price >= trade.current_tp: exit_reason = "TP_HIT"
            elif current_price <= trade.current_sl: exit_reason = "SL_HIT"
        elif trade.direction == "SHORT":
            if current_price <= trade.current_tp: exit_reason = "TP_HIT"
            elif current_price >= trade.current_sl: exit_reason = "SL_HIT"
        
        # Use MAX_ROI_LIMIT from the final, restored config
        if self.config.max_roi_limit > 0 and not exit_reason:
            pnl_ratio = (current_price - trade.entry_price) / trade.entry_price if trade.direction == "LONG" else (trade.entry_price - current_price) / trade.entry_price
            current_roi = pnl_ratio * self.config.leverage
            if current_roi >= self.config.max_roi_limit:
                exit_reason = "MAX_ROI_HIT"

        if exit_reason:
            logger.info(f"Exit condition '{exit_reason}' met for trade {trade.trade_id} at price {current_price}")
            # Pass the exit reason to the execution module for logging
            await self.execution_module.exit_trade(trade.trade_id, current_price, exit_reason)
            del self.active_trades[trade_id]

    def start(self):
        """Starts the TLM background monitoring task."""
        if not self.running:
            self.running = True
            self.task = asyncio.create_task(self._run_monitoring_cycle())
            logger.info("TradeLifecycleManager monitoring has started.")
    
    async def stop(self):
        """Stops the TLM background task gracefully."""
        if self.running and self.task:
            self.running = False
            self.task.cancel()
            try: await self.task
            except asyncio.CancelledError: pass
            logger.info("TradeLifecycleManager monitoring has stopped.")
