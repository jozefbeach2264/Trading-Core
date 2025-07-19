import logging
from typing import Dict, Any, Optional, List
from config.config import Config
from data_managers.market_state import MarketState

logger = logging.getLogger(__name__)

class TradeModuleScalpel:
    def __init__(self, config: Config):
        self.config = config
        logger.info("TradeModuleScalpel initialized.")

    def _calculate_ema(self, klines: List[List[Any]], period: int) -> Optional[float]:
        if len(klines) < period:
            return None
        closes = [float(k[4]) for k in reversed(klines)]
        sma = sum(closes[:period]) / period
        ema_values = [sma]
        multiplier = 2 / (period + 1)
        for price in closes[period:]:
            ema = (price - ema_values[-1]) * multiplier + ema_values[-1]
            ema_values.append(ema)
        return ema_values[-1]

    async def generate_signal(self, market_state: MarketState) -> Optional[Dict[str, Any]]:
        klines = list(market_state.klines)
        live_candle = market_state.live_reconstructed_candle

        if not live_candle or len(klines) < 100:
            return None
        
        ema100 = self._calculate_ema(klines, 100)
        if not ema100:
            return None

        live_close = float(live_candle[4])
        trend_is_up = live_close > ema100
        trend_is_down = live_close < ema100
        
        # In 'Base mode', retest is the primary confirmation.
        # The breakout level is considered the high/low of the previously closed candle.
        previous_candle = klines[1]
        breakout_level_high = float(previous_candle[2])
        breakout_level_low = float(previous_candle[3])
        breakout_range = breakout_level_high - breakout_level_low
        
        retest_of_high_confirmed = abs(live_close - breakout_level_high) / breakout_level_high < 0.005 # within 0.5%
        retest_of_low_confirmed = abs(live_close - breakout_level_low) / breakout_level_low < 0.005 # within 0.5%

        if trend_is_up and retest_of_high_confirmed:
            entry_price = live_close
            stop_loss = entry_price - breakout_range
            take_profit = entry_price + (breakout_range * 1.5)
            return {"trade_type": "Scalpel", "direction": "LONG", "entry_price": entry_price, "take_profit": take_profit, "stop_loss": stop_loss, "reason": "Scalpel: Uptrend continuation confirmed on retest."}
        
        elif trend_is_down and retest_of_low_confirmed:
            entry_price = live_close
            stop_loss = entry_price + breakout_range
            take_profit = entry_price - (breakout_range * 1.5)
            return {"trade_type": "Scalpel", "direction": "SHORT", "entry_price": entry_price, "take_profit": take_profit, "stop_loss": stop_loss, "reason": "Scalpel: Downtrend continuation confirmed on retest."}
            
        return None
