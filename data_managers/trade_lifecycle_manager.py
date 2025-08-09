import asyncio
import logging
from typing import Dict, Any, TYPE_CHECKING

from config.config import Config
from data_managers.market_state import MarketState
# We keep the forward reference for TradeExecutor
if TYPE_CHECKING:
    from system_managers.trade_executor import TradeExecutor
    # --- THIS IS THE FIX ---
    # We add a forward reference for AIStrategy to break the new circular import.
    from strategy.ai_strategy import AIStrategy
from data_managers.orderbook_parser import OrderBookParser

logger = logging.getLogger(__name__)

class ActiveTrade:
    """
    An upgraded data class to hold detailed information for high-fidelity simulation.
    """
    def __init__(self, trade_id: str, trade_data: Dict[str, Any], entry_candle: list, liquidation_price: float):
        self.trade_id: str = trade_id
        self.symbol: str = trade_data.get("symbol")
        self.direction: str = trade_data.get("direction")
        self.entry_price: float = trade_data.get("entry_price")
        self.size: float = trade_data.get("size")
        self.leverage: int = trade_data.get("leverage")

        self.liquidation_price: float = liquidation_price
        self.entry_candle_ohlcv: list = entry_candle
        self.status: str = "open"
        self.pnl: float = 0.0

class TradeLifecycleManager:
    """
    Upgraded to act as a high-fidelity virtual exchange for simulations,
    managing the full lifecycle of trades with realistic market conditions.
    """
    # --- THIS IS THE FIX ---
    # We use string hints for the types to avoid runtime import issues.
    def __init__(self, config: Config, execution_module: 'TradeExecutor', market_state: MarketState, ai_strategy: 'AIStrategy'):
        self.config = config
        self.execution_module = execution_module
        self.market_state = market_state
        self.ai_strategy = ai_strategy
        self.active_trades: Dict[str, ActiveTrade] = {}
        self.running = False
        self.task = None
        self.orderbook_parser = OrderBookParser()
        logger.info("TradeLifecycleManager upgraded and initialized for high-fidelity simulation.")

    async def start_new_trade(self, trade_id: str, trade_data: Dict[str, Any]):
        """
        Acts as the entry point to the virtual exchange.
        Calculates realistic entry price, fees, and liquidation price.
        """
        if trade_id in self.active_trades:
            logger.warning(f"Trade {trade_id} is already being managed.")
            return

        try:
            order_book = self.market_state.get_latest_data_snapshot().get('order_book', {'bids': [], 'asks': []})

            # Hardened: compute VWAP with graceful fallback to best price if depth is insufficient
            try:
                simulated_entry_price = self.orderbook_parser.calculate_vwap_for_size(
                    order_book, trade_data['direction'], trade_data['size']
                )
            except ValueError as e:
                logger.warning(f"VWAP calc failed: {e}; falling back to best price")
                if str(trade_data['direction']).lower() in ('long', 'buy'):
                    asks = order_book.get('asks') or []
                    if not asks:
                        raise
                    first = asks[0]
                    simulated_entry_price = float(first.get('price', first.get('p'))) if isinstance(first, dict) else float(first[0])
                else:
                    bids = order_book.get('bids') or []
                    if not bids:
                        raise
                    first = bids[0]
                    simulated_entry_price = float(first.get('price', first.get('p'))) if isinstance(first, dict) else float(first[0])

            trade_data['entry_price'] = simulated_entry_price

            entry_value = trade_data['size'] * simulated_entry_price
            margin = entry_value / self.config.leverage
            if trade_data['direction'] == 'LONG':
                liquidation_price = simulated_entry_price - (margin / trade_data['size'])
            else: # SHORT
                liquidation_price = simulated_entry_price + (margin / trade_data['size'])

            entry_candle = self.market_state.get_latest_data_snapshot().get('live_reconstructed_candle', [])

            trade_data['leverage'] = self.config.leverage

            self.active_trades[trade_id] = ActiveTrade(trade_id, trade_data, entry_candle, liquidation_price)
            logger.info(f"SIMULATED: New trade {trade_id} started. Entry: ${simulated_entry_price:.2f}, Liq. Price: ${liquidation_price:.2f}")

        except Exception as e:
            logger.error(f"Could not start managing trade {trade_id}: {e}", exc_info=True)

    async def _run_monitoring_cycle(self):
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
        """
        Upgraded monitoring logic for an open trade.
        1. Checks for liquidation first.
        2. If not liquidated, consults the AI for a dynamic exit decision.
        """
        trade = self.active_trades.get(trade_id)
        if not trade: return

        current_price = self.market_state.mark_price
        if not current_price: return

        exit_reason = None
        exit_price = current_price

        if trade.direction == "LONG" and current_price <= trade.liquidation_price:
            exit_reason = "LIQUIDATED"
            exit_price = trade.liquidation_price
        elif trade.direction == "SHORT" and current_price >= trade.liquidation_price:
            exit_reason = "LIQUIDATED"
            exit_price = trade.liquidation_price

        if not exit_reason:
            exit_verdict = await self.ai_strategy.get_dynamic_exit_verdict(trade, self.market_state)
            action = exit_verdict.get("action")
            if action == "EXIT_PROFIT":
                exit_reason = "AI_TAKE_PROFIT"
            elif action == "EXIT_LOSS":
                exit_reason = "AI_STOP_LOSS"

        if exit_reason:
            logger.info(f"Exit condition '{exit_reason}' met for trade {trade.trade_id} at price {exit_price}")

            await self.execution_module.exit_trade(trade.trade_id, exit_price, exit_reason)
            # Remove the trade from active monitoring
            if trade_id in self.active_trades:
                del self.active_trades[trade_id]

    def start(self):
        if not self.running:
            self.running = True
            self.task = asyncio.create_task(self._run_monitoring_cycle())
            logger.info("TradeLifecycleManager monitoring has started.")

    async def stop(self):
        if self.running and self.task:
            self.running = False
            self.task.cancel()
            try: await self.task
            except asyncio.CancelledError: pass
            logger.info("TradeLifecycleManager monitoring has stopped.")