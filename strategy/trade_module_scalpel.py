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
        # The EMA100 trend gate is OFF by default: it added no measurable edge and locked each session to one
        # direction (see config.scalpel_require_trend). With it off, a retest is tradeable both ways.
        if self.config.scalpel_require_trend:
            trend_is_up = live_close > ema100
            trend_is_down = live_close < ema100
        else:
            trend_is_up = trend_is_down = True
        
        # In 'Base mode', retest is the primary confirmation.
        # The breakout level is considered the high/low of the previously closed candle.
        previous_candle = klines[0]   # newest CLOSED candle (the deque is newest-first)
        breakout_level_high = float(previous_candle[2])
        breakout_level_low = float(previous_candle[3])
        breakout_range = breakout_level_high - breakout_level_low
        
        if breakout_range <= 0:
            return None
        # A retest means price is back AT the level, within a fraction of that candle's own range. The old
        # 0.5%-of-price band (~$12 on ETH, several candle ranges) was true on almost every cycle.
        tolerance = breakout_range * self.config.scalpel_retest_range_fraction
        retest_of_high_confirmed = abs(live_close - breakout_level_high) <= tolerance
        retest_of_low_confirmed = abs(live_close - breakout_level_low) <= tolerance

        # When both levels are in range (a tiny candle), take the nearer one rather than always the high.
        if retest_of_high_confirmed and retest_of_low_confirmed and trend_is_up and trend_is_down:
            if abs(live_close - breakout_level_low) < abs(live_close - breakout_level_high):
                retest_of_high_confirmed = False
            else:
                retest_of_low_confirmed = False

        if trend_is_up and retest_of_high_confirmed:
            entry_price = live_close
            stop_loss = entry_price - breakout_range
            take_profit = entry_price + (breakout_range * 1.5)
            return {"trade_type": "Scalpel", "direction": "LONG", "entry_price": entry_price, "take_profit": take_profit, "stop_loss": stop_loss, "reason": "Scalpel: LONG on retest of the prior high."}
        
        elif trend_is_down and retest_of_low_confirmed:
            entry_price = live_close
            stop_loss = entry_price + breakout_range
            take_profit = entry_price - (breakout_range * 1.5)
            return {"trade_type": "Scalpel", "direction": "SHORT", "entry_price": entry_price, "take_profit": take_profit, "stop_loss": stop_loss, "reason": "Scalpel: SHORT on retest of the prior low."}
            
        return None
