import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class ExecutionModule:
    """
    Handles the execution of trades. In dry_run mode, it interacts with the
    SimulationAccount. In live mode, it would interact with the real exchange API client.
    """
    def __init__(self, config: Any, simulation_account: Optional[Any] = None, exchange_client: Optional[Any] = None):
        self.is_dry_run = config.dry_run_mode # Assumes config has this attribute
        self.simulation_account = simulation_account
        self.exchange_client = exchange_client
        self.config = config

        if self.is_dry_run and not self.simulation_account:
            raise ValueError("SimulationAccount must be provided in dry_run mode.")
        if not self.is_dry_run and not self.exchange_client:
            raise ValueError("ExchangeClient must be provided in live mode.")
            
        logger.info(f"ExecutionModule initialized in {'DRY RUN' if self.is_dry_run else 'LIVE'} mode.")

    async def enter_trade(self, trade_id: str, trade_size_usd: float, entry_price: float, direction: str) -> Dict[str, Any]:
        """Enters a trade, either simulated or live."""
        if self.is_dry_run:
            success = self.simulation_account.open_trade(trade_id, trade_size_usd, entry_price, direction)
            if success:
                return {"status": "success", "order_id": f"sim_{trade_id}", "message": "Simulated trade opened."}
            else:
                return {"status": "error", "message": "Failed to open simulated trade."}
        else:
            # ▼▼▼ INSERT LIVE EXCHANGE API LOGIC HERE ▼▼▼
            logger.info(f"LIVE: Firing entry order for {trade_id}...")
            # response = await self.exchange_client.create_order(...)
            return {"status": "success", "order_id": "live_mock_123", "message": "Live trade opened (mocked)."}

    async def exit_trade(self, trade_id: str, exit_price: float) -> Dict[str, Any]:
        """Exits a trade, either simulated or live."""
        if self.is_dry_run:
            fee_rate_percent = (self.config.exchange_fee_rate_taker / 100) * 2 * self.config.leverage
            pnl = self.simulation_account.close_trade(trade_id, exit_price, fee_rate_percent)
            return {"status": "success", "pnl": pnl, "message": "Simulated trade closed."}
        else:
            # ▼▼▼ INSERT LIVE EXCHANGE API LOGIC HERE ▼▼▼
            logger.info(f"LIVE: Firing exit order for {trade_id}...")
            # response = await self.exchange_client.create_order(...)
            return {"status": "success", "pnl": "live_pnl_mock", "message": "Live trade closed (mocked)."}
