from typing import Dict, Any

def get_strategy_config(strategy_name: str) -> Dict[str, Any]:
    """
    Returns a dictionary of parameters for a given strategy.
    This logic is taken directly from your replit_combined_code.txt.
    """
    if strategy_name.lower() == 'trapx':
        return {
            "compression_period": 5,
            "compression_threshold_pct": 0.5,
            "tpsl_atr_multiplier": 1.5,
        }
    
    if strategy_name.lower() == 'scalpel':
        return {
            "momentum_candles": 5,
            "momentum_threshold_pct": 0.1,
        }

    # Default empty config if strategy is not found
    return {}
