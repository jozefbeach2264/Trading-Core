import logging
import asyncio
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class TradeLifecycleManager:
    """
    Manages the lifecycle of all active trades, from entry to exit.
    This class polls active trades, checks for TP/SL, and triggers exits.
    """
    def __init__(self, config: Any, execution_module: Any, data_provider: Any):
        self.config = config
        self.execution_module = execution_module
        self.data_provider = data_provider
        self.active_trades: Dict[str, Dict[str, Any]] = {}
        self.running = False
        self.task = None
        logger.info("TradeLifecycleManager initialized.")

    def start_new_trade(self, trade_id: str, trade_data: Dict[str, Any]):
        """Adds a new trade to be managed."""
        if trade_id in self.active_trades:
            logger.warning(f"Trade {trade_id} is already being managed.")
            return
        self.active_trades[trade_id] = trade_data
        logger.info(f"Now managing new trade: {trade_id}. Details: {trade_data}")

    def stop_managing_trade(self, trade_id: str):
        """Removes a trade from active management."""
        if trade_id in self.active_trades:
            del self.active_trades[trade_id]
            logger.info(f"Stopped managing trade: {trade_id}")

    async def _run_monitoring_cycle(self):
        """The main monitoring loop that runs periodically."""
        while self.running:
            if not self.active_trades:
                await asyncio.sleep(1)
                continue

            # Create a copy of keys to iterate over, allowing modification during loop
            for trade_id in list(self.active_trades.keys()):
                await self._check_trade(trade_id)
            
            await asyncio.sleep(self.config.get("tlm_poll_interval", 1.0))

    async def _check_trade(self, trade_id: str):
        """Checks a single trade for exit conditions."""
        trade = self.active_trades.get(trade_id)
        if not trade: return
        
        symbol = trade['symbol']
        direction = trade['direction']
        tp = trade['tp']
        sl = trade['sl']
        
        current_price = self.data_provider.get_mark_price(symbol)
        if not current_price: return

        exit_reason = None
        if direction == "LONG" and current_price >= tp: exit_reason = "TP_HIT"
        elif direction == "SHORT" and current_price <= tp: exit_reason = "TP_HIT"
        elif direction == "LONG" and current_price <= sl: exit_reason = "SL_HIT"
        elif direction == "SHORT" and current_price >= sl: exit_reason = "SL_HIT"
        
        # Check for Max ROI Limit
        if self.config.max_roi_limit > 0:
            entry_price = trade['entry_price']
            pnl_ratio = (current_price - entry_price) / entry_price if direction == "LONG" else (entry_price - current_price) / entry_price
            current_roi = pnl_ratio * self.config.leverage
            if current_roi >= self.config.max_roi_limit:
                exit_reason = "MAX_ROI_HIT"

        if exit_reason:
            logger.info(f"Exit condition met for {trade_id}: {exit_reason} at price {current_price}")
            await self.execution_module.exit_trade(trade_id, current_price)
            self.stop_managing_trade(trade_id)

    def start(self):
        """Starts the TLM background task."""
        if not self.running:
            self.running = True
            self.task = asyncio.create_task(self._run_monitoring_cycle())
            logger.info("TradeLifecycleManager monitoring has started.")
    
    async def stop(self):
        """Stops the TLM background task gracefully."""
        if self.running:
            self.running = False
            if self.task:
                self.task.cancel()
                try: await self.task
                except asyncio.CancelledError: pass
            logger.info("TradeLifecycleManager monitoring has stopped.")
