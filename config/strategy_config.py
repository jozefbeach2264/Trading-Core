# TradingCore/config/strategy_config.py
from typing import Dict, Any

def get_strategy_config(strategy_name: str) -> Dict[str, Any]:
    """
    Returns a dictionary of parameters for a given strategy.
    This will allow for easy tuning of strategies.
    """
    if strategy_name.lower() == 'trapx':
        return {
            "compression_period": 5,
            "compression_threshold_pct": 0.5,
            "tpsl_atr_multiplier": 1.5,
            # Add other trapx-specific parameters here
        }
    
    # Add other strategies like 'scalpel' here in the future
    # if strategy_name.lower() == 'scalpel':
    #     return { ... }

    # Default empty config if strategy is not found
    return {}

