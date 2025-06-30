import logging
from typing import Dict, Any, Optional
import time

logger = logging.getLogger(__name__)

class ScalpelStrategy:
    """
    A simple example strategy that generates a trade signal based on a
    moving average crossover. This serves as a testable signal generator
    for the rest of the system.
    """
    def __init__(self):
        self.short_ma_period = 5
        self.long_ma_period = 20
        logger.info("ScalpelStrategy initialized (EMA Crossover).")

    async def generate_signal(self, market_state: Any) -> Optional[Dict[str, Any]]:
        """
        Analyzes market state for a crossover signal.

        Args:
            market_state (Any): The current MarketState object.

        Returns:
            Optional[Dict[str, Any]]: A signal dictionary if conditions are met.
        """
        klines = market_state.klines
        if len(klines) < self.long_ma_period:
            return None # Not enough data

        try:
            closes = [float(k[4]) for k in klines]
            
            # Calculate short and long simple moving averages
            short_ma = sum(closes[-self.short_ma_period:]) / self.short_ma_period
            long_ma = sum(closes[-self.long_ma_period:]) / self.long_ma_period
            
            prev_short_ma = sum(closes[-self.short_ma_period-1:-1]) / self.short_ma_period
            prev_long_ma = sum(closes[-self.long_ma_period-1:-1]) / self.long_ma_period

        except (ValueError, TypeError, IndexError) as e:
            logger.error(f"Scalpel could not calculate MAs due to data issue: {e}")
            return None
        
        signal = None
        current_price = market_state.mark_price

        # Bullish crossover
        if prev_short_ma <= prev_long_ma and short_ma > long_ma:
            signal = {
                "strategy": "scalpel",
                "trigger_type": "ema_crossover_long",
                "direction": "LONG",
                "entry_price": current_price,
                "tp": current_price * 1.01, # Example TP
                "sl": current_price * 0.995, # Example SL
                "timestamp": int(time.time() * 1000)
            }
            logger.info(f"ScalpelStrategy: Bullish crossover detected. Signal generated.")

        # Bearish crossover
        elif prev_short_ma >= prev_long_ma and short_ma < long_ma:
            signal = {
                "strategy": "scalpel",
                "trigger_type": "ema_crossover_short",
                "direction": "SHORT",
                "entry_price": current_price,
                "tp": current_price * 0.99, # Example TP
                "sl": current_price * 1.005, # Example SL
                "timestamp": int(time.time() * 1000)
            }
            logger.info(f"ScalpelStrategy: Bearish crossover detected. Signal generated.")

        return signal
