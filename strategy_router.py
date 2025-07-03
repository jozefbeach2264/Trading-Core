import logging
from typing import Dict, Any, Optional

from managers.market_state import MarketState
from trade_module_scalpel import TradeModuleScalpel
from trade_module_trapx import TradeModuleTrapx # <-- NEW IMPORT

logger = logging.getLogger(__name__)

class StrategyRouter:
    """
    Selects and runs the appropriate initial signal generation strategy.
    Updated to handle both 'scalpel' and 'trapx' strategies.
    """
    def __init__(self):
        self.strategies = {
            "scalpel": TradeModuleScalpel(),
            "trapx": TradeModuleTrapx() # <-- NEW STRATEGY ADDED
        }
        logger.info("StrategyRouter initialized with available strategies: %s", list(self.strategies.keys()))

    def run_strategy(self, strategy_name: str, market_state: MarketState) -> Optional[Dict[str, Any]]:
        """
        Looks up the strategy by name and calls its signal generation method.
        """
        strategy = self.strategies.get(strategy_name.lower())
        
        if not strategy:
            logger.warning(f"Strategy '{strategy_name}' not found in router.")
            return None
            
        return strategy.generate_signal(market_state)
