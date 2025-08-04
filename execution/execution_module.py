import logging
from typing import Any, Dict

from config.config import Config
from execution.simulation_account import SimulationAccount

logger = logging.getLogger(__name__)

class ExecutionModule:
    """
    Acts as a switch, routing trade requests to either the live exchange
    or the simulation account based on the dry_run_mode config.
    """
    def __init__(self, config: Config, simulation_account: SimulationAccount):
        self.config = config
        self.sim_account = simulation_account
        logger.info(f"ExecutionModule initialized. Dry Run Mode: {self.config.dry_run_mode}")

    async def execute_trade(self, trade_details: Dict[str, Any]):
        """Places a new trade, routing to sim or live client."""
        if self.config.dry_run_mode:
            self.sim_account.open_trade(
                trade_id=trade_details.get('trade_id'),
                symbol=trade_details.get('symbol'),
                direction=trade_details.get('direction'),
                size=trade_details.get('size'),
                entry_price=trade_details.get('entry_price')
            )
        else:
            logger.info("LIVE EXECUTION: Would place live trade.")
            # Live client logic here
        return True

    async def exit_trade(self, trade_id: str, exit_price: float):
        """Exits a trade, correctly passing global leverage to the simulation."""
        if self.config.dry_run_mode:
            # As per your requirement, the simulation uses the global leverage from config.
            self.sim_account.close_trade(
                trade_id=trade_id,
                exit_price=exit_price,
                leverage=self.config.leverage # Passes the global leverage
            )
        else:
            logger.info("LIVE EXECUTION: Would close live trade.")
            # Live client logic here
        return True
