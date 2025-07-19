import logging
import asyncio
from typing import Dict, Any, Optional
from config.config import Config
from data_managers.market_state import MarketState
from strategy.trade_module_trapx import TradeModuleTrapX
from strategy.trade_module_scalpel import TradeModuleScalpel

logger = logging.getLogger(__name__)

class StrategyRouter:
    def __init__(self, config: Config):
        self.config = config
        self.trapx_module = TradeModuleTrapX(config)
        self.scalpel_module = TradeModuleScalpel(config)
        logger.info("StrategyRouter initialized for CONSENSUS mode.")

    async def route_and_generate_signal(self, market_state: MarketState, validator_report: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Runs both TrapX and Scalpel modules in parallel and only returns a signal
        if both modules agree on the trade direction.
        """
        logger.debug("Attempting to generate consensus signal from TrapX and Scalpel.")
        
        # Run both modules concurrently to get their independent signals
        trapx_signal_task = self.trapx_module.generate_signal(market_state)
        scalpel_signal_task = self.scalpel_module.generate_signal(market_state)
        
        trapx_signal, scalpel_signal = await asyncio.gather(trapx_signal_task, scalpel_signal_task)

        if not trapx_signal:
            logger.debug("Consensus failed: TrapX module did not generate a signal.")
            return None
        
        if not scalpel_signal:
            logger.debug("Consensus failed: Scalpel module did not generate a signal.")
            return None

        # Check for unanimous agreement on direction
        trapx_direction = trapx_signal.get("direction")
        scalpel_direction = scalpel_signal.get("direction")

        if trapx_direction and trapx_direction == scalpel_direction:
            logger.info(f"CONSENSUS ACHIEVED: Both modules agree on a {trapx_direction} signal.")
            
            # Per protocol, TrapX is the primary pattern detector. We return its signal packet.
            return trapx_signal
        else:
            logger.debug(
                f"Consensus failed: Directional mismatch. TrapX: {trapx_direction}, Scalpel: {scalpel_direction}"
            )
            return None
