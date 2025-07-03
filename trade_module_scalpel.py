import logging
from typing import Dict, Any, Optional

from managers.market_state import MarketState

logger = logging.getLogger(__name__)

class TradeModuleScalpel:
    """
    A simple "scalpel" strategy that looks for a basic momentum condition
    to generate a potential trade signal for AI adjudication.
    """
    def __init__(self):
        logger.info("TradeModuleScalpel initialized.")

    def generate_signal(self, market_state: MarketState) -> Optional[Dict[str, Any]]:
        """
        Generates a trade signal if the mark price has moved more than 0.1%
        in the last 5 klines. This is a very basic example of a momentum trigger.
        """
        klines = list(market_state.klines)
        if len(klines) < 5:
            return None # Not enough data to make a decision

        current_price = market_state.mark_price
        if not current_price:
            return None # Cannot proceed without a current price

        start_price = float(klines[-5][4]) # Use the closing price of 5 candles ago

        # Determine direction based on momentum
        if current_price > start_price * 1.001:  # 0.1% upward move
            direction = "LONG"
        elif current_price < start_price * 0.999: # 0.1% downward move
            direction = "SHORT"
        else:
            return None # No significant momentum
            
        # Create a signal dictionary with proposed TP/SL
        signal = {
            "strategy": "scalpel_v1",
            "direction": direction,
            "entry_price": current_price,
            "tp": current_price * 1.005 if direction == "LONG" else current_price * 0.995,
            "sl": current_price * 0.995 if direction == "LONG" else current_price * 1.005,
        }
        logger.info(f"Scalpel strategy generated signal: {signal}")
        return signal

