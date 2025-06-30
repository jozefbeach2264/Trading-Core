import logging
from typing import Dict, Any, Optional

# Import strategy modules
from .trade_module_scalpel import ScalpelStrategy

logger = logging.getLogger(__name__)

class StrategyRouter:
    """
    Selects and executes a specific trading strategy module based on an
    incoming command or signal trigger.
    """
    def __init__(self):
        # Map strategy names to their respective class instances
        self.strategies = {
            "scalpel": ScalpelStrategy(),
            # "trapx": TrapXStrategy(), # Add other strategies here
        }
        logger.info(f"StrategyRouter initialized with available strategies: {list(self.strategies.keys())}")

    async def run_strategy(self, strategy_name: str, market_state: Any) -> Optional[Dict[str, Any]]:
        """
        Runs the specified strategy to generate a potential trade signal.

        Args:
            strategy_name (str): The name of the strategy to run (e.g., 'scalpel').
            market_state (Any): The current MarketState object.

        Returns:
            Optional[Dict[str, Any]]: A dictionary representing a trade signal if one
                                      is generated, otherwise None.
        """
        strategy_name = strategy_name.lower()
        strategy_module = self.strategies.get(strategy_name)

        if not strategy_module:
            logger.error(f"Strategy '{strategy_name}' not found.")
            return None

        logger.info(f"Running strategy: '{strategy_name}'")
        signal = await strategy_module.generate_signal(market_state)
        
        if signal:
            logger.info(f"Strategy '{strategy_name}' generated a trade signal.")
            return signal
        
        return None
