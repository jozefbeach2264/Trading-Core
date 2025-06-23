# TradingCore/trade_lifecycle_manager.py
import logging
import asyncio
from typing import Dict, Any
import uuid

# --- NEW: Import all the new modules ---
from market_state import MarketState
from execution.ExecutionModule import ExecutionModule
from managers.TPSLManager import TPSLManager
from tuning_control.RollingExtensionModule import RollingExtensionModule
from sensors.OrderBookReversalZoneDetector import OrderBookReversalZoneDetector


logger = logging.getLogger(__name__)

class TradeLifecycleManager:
    """
    Manages the state and progression of an active trade from entry,
    through the "rolling candle" cycle, to the final exit.
    """
    def __init__(self, market_state: MarketState):
        """
        Initializes the manager and its sub-modules.
        """
        # --- NEW: Now holds the market state and instances of our modules ---
        self.market_state = market_state
        self.execution_module = ExecutionModule()
        self.tpsl_manager = TPSLManager()
        self.extension_module = RollingExtensionModule()
        self.reversal_detector = OrderBookReversalZoneDetector()
        
        self.active_trades: Dict[str, Dict] = {}
        logger.info("TradeLifecycleManager initialized with all sub-modules.")

    async def start_new_trade_cycle(self, initial_signal_data: Dict[str, Any]):
        """
        Main entry point. Called after a signal passes initial validation.
        It executes the entry and starts the monitoring loop.
        """
        # --- NEW: Simulates placing the entry order ---
        entry_result = await self.execution_module.enter_trade(initial_signal_data)
        if entry_result.get("status") != "success":
            logger.error("Trade entry failed. Aborting lifecycle.")
            return {"status": "trade_entry_failed"}

        trade_id = str(uuid.uuid4())
        self.active_trades[trade_id] = initial_signal_data
        
        logger.info(
            "Successfully entered trade for strategy '%s'. Starting rolling cycle. Trade ID: %s",
            initial_signal_data.get('strategy'),
            trade_id
        )

        # Start the monitoring loop for this trade in the background
        asyncio.create_task(self._trade_monitoring_loop(trade_id))

        return {"status": "trade_cycle_started", "trade_id": trade_id}

    async def _trade_monitoring_loop(self, trade_id: str):
        """
        This is the "Rolling Candle Cycle". It re-evaluates the trade
        on each new candle until an exit condition is met.
        """
        is_trade_active = True
        while is_trade_active:
            await asyncio.sleep(60) # Wait for the next 1-minute candle
            
            trade_data = self.active_trades.get(trade_id)
            if not trade_data:
                logger.warning("Trade data for %s not found. Ending loop.", trade_id)
                break

            logger.info("Re-evaluating trade ID %s on new candle...", trade_id)
            
            # --- NEW: Use our modules to make decisions ---
            latest_market_data = self.market_state.get_signal_data()
            
            # Check for reversal signals
            reversal_detected = await self.reversal_detector.check_for_failure(latest_market_data)
            if reversal_detected:
                logger.warning("Reversal detected for trade %s. Triggering exit.", trade_id)
                await self.execution_module.exit_trade({"symbol": trade_data['symbol'], "reason": "Reversal Signal"})
                is_trade_active = False
                continue

            # Check for trend continuation
            should_continue = await self.extension_module.check_continuation(latest_market_data)
            if not should_continue:
                logger.info("Trend momentum fading for trade %s. Triggering exit.", trade_id)
                await self.execution_module.exit_trade({"symbol": trade_data['symbol'], "reason": "Trend Fading"})
                is_trade_active = False
                continue
            
            # Adjust TP/SL targets
            await self.tpsl_manager.adjust_targets(latest_market_data)
        
        # Once the loop exits, clean up the trade
        self.end_trade_cycle(trade_id)

    def end_trade_cycle(self, trade_id: str):
        """Removes a trade from active management."""
        if trade_id in self.active_trades:
            del self.active_trades[trade_id]
            logger.info("Trade cycle ended and cleaned up for trade ID: %s", trade_id)

