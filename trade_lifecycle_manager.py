# TradingCore/trade_lifecycle_manager.py
import logging
import asyncio
from typing import Dict, Any
import uuid

from market_state import MarketState
from execution.ExecutionModule import ExecutionModule
from managers.TPSLManager import TPSLManager
from tuning_control.RollingExtensionModule import RollingExtensionModule
from sensors.OrderBookReversalZoneDetector import OrderBookReversalZoneDetector

logger = logging.getLogger(__name__)

class TradeLifecycleManager:
    def __init__(self, market_state: MarketState):
        self.market_state = market_state
        self.execution_module = ExecutionModule()
        self.tpsl_manager = TPSLManager()
        self.extension_module = RollingExtensionModule()
        self.reversal_detector = OrderBookReversalZoneDetector()
        self.active_trades: Dict[str, Dict] = {}
        logger.info("TradeLifecycleManager initialized with all sub-modules.")

    async def start_new_trade_cycle(self, initial_signal_data: Dict[str, Any]):
        entry_result = await self.execution_module.enter_trade(initial_signal_data)
        if entry_result.get("status") != "success":
            logger.error("Trade entry failed. Aborting lifecycle.")
            return {"status": "trade_entry_failed"}

        trade_id = str(uuid.uuid4())
        self.active_trades[trade_id] = initial_signal_data
        logger.info("Successfully entered trade for strategy '%s'. Starting rolling cycle. Trade ID: %s",
                    initial_signal_data.get('strategy'), trade_id)
        asyncio.create_task(self._trade_monitoring_loop(trade_id))
        return {"status": "trade_cycle_started", "trade_id": trade_id}

    async def _trade_monitoring_loop(self, trade_id: str):
        is_trade_active = True
        while is_trade_active:
            await asyncio.sleep(60)
            trade_data = self.active_trades.get(trade_id)
            if not trade_data:
                logger.warning("Trade data for %s not found. Ending loop.", trade_id)
                break
            
            logger.info("Re-evaluating trade ID %s on new candle...", trade_id)
            latest_market_data = self.market_state.get_signal_data()
            
            reversal_detected = await self.reversal_detector.check_for_failure(latest_market_data)
            if reversal_detected:
                logger.warning("Reversal detected for trade %s. Triggering exit.", trade_id)
                await self.execution_module.exit_trade({"symbol": trade_data['symbol'], "reason": "Reversal Signal"})
                is_trade_active = False
                continue

            should_continue = await self.extension_module.check_continuation(latest_market_data)
            if not should_continue:
                logger.info("Trend momentum fading for trade %s. Triggering exit.", trade_id)
                await self.execution_module.exit_trade({"symbol": trade_data['symbol'], "reason": "Trend Fading"})
                is_trade_active = False
                continue
            
            await self.tpsl_manager.adjust_targets(latest_market_data)
        
        self.end_trade_cycle(trade_id)

    def end_trade_cycle(self, trade_id: str):
        if trade_id in self.active_trades:
            del self.active_trades[trade_id]
            logger.info("Trade cycle ended and cleaned up for trade ID: %s", trade_id)
