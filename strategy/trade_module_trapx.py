import logging
from typing import Dict, Any, Optional

from config.config import Config
from data_managers.market_state import MarketState

logger = logging.getLogger(__name__)

class TradeModuleTrapX:
    def __init__(self, config: Config):
        self.config = config
        logger.info("TradeModuleTrapX initialized.")

    async def generate_signal(self, market_state: MarketState) -> Optional[Dict[str, Any]]:
        klines = market_state.klines
        live_candle = market_state.live_reconstructed_candle
        spoof_metrics = market_state.spoof_metrics
        order_book_walls = market_state.order_book_walls

        if not live_candle or len(klines) < 5 or not order_book_walls:
            return None

        compression_klines = list(klines)[1:4]
        compression_ranges = [float(k[2]) - float(k[3]) for k in compression_klines]
        avg_compression_range = sum(compression_ranges) / len(compression_ranges) if compression_ranges else 0
        if avg_compression_range == 0: return None

        trap_candle = klines[0]
        trap_range = float(trap_candle[2]) - float(trap_candle[3])
        if trap_range < (avg_compression_range * 2.0): return None
        
        live_o, live_h, live_l, live_c = map(float, live_candle[1:5])
        live_body = abs(live_c - live_o)
        upper_wick = live_h - max(live_o, live_c)
        lower_wick = min(live_o, live_c) - live_l
        spoof_thin_rate = spoof_metrics.get("spoof_thin_rate", 0.0)

        direction = None
        entry_price = live_c
        
        if upper_wick > (live_body * 1.5) and spoof_thin_rate > 5.0:
            direction = "SHORT"
            stop_loss = live_h + (self.config.max_liquidation_threshold / 2)
            bid_walls = order_book_walls.get("bid_walls", [])
            potential_tps = [wall['price'] for wall in bid_walls if wall['price'] < entry_price]
            take_profit = max(potential_tps) if potential_tps else entry_price - self.config.max_liquidation_threshold

        elif lower_wick > (live_body * 1.5) and spoof_thin_rate > 5.0:
            direction = "LONG"
            stop_loss = live_l - (self.config.max_liquidation_threshold / 2)
            ask_walls = order_book_walls.get("ask_walls", [])
            potential_tps = [wall['price'] for wall in ask_walls if wall['price'] > entry_price]
            take_profit = min(potential_tps) if potential_tps else entry_price + self.config.max_liquidation_threshold

        if direction:
            return {"trade_type": "TrapX", "direction": direction, "entry_price": round(entry_price, 2), "take_profit": round(take_profit, 2), "stop_loss": round(stop_loss, 2), "reason": f"GENESIS TrapX: {direction} signal identified."}
        return None
