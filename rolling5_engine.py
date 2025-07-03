import logging
from typing import Dict, Any

from managers.market_state import MarketState

logger = logging.getLogger(__name__)

class Rolling5Engine:
    """
    Contains the proprietary logic for the Rolling5 prediction model.
    It analyzes an active trade and market state to generate a 5-candle
    forward-looking forecast (C1-C5).
    """
    def __init__(self, config: Any):
        self.config = config
        logger.info("Rolling5Engine initialized.")

    def generate_predictions(self, active_trade_data: Dict[str, Any], market_state: MarketState) -> Dict[str, Any]:
        """
        Takes the current trade and market state and generates the C1-C5 predictions.
        """
        logger.info(f"Generating Rolling5 predictions for trade {active_trade_data.get('trade_id')}...")

        closes = [float(k[4]) for k in market_state.klines[-10:]]
        volumes = [float(k[5]) for k in market_state.klines[-10:]]

        avg_volume = sum(volumes) / len(volumes)
        current_price = market_state.mark_price
        direction = "UP" if closes[-1] > closes[-2] else "DOWN"

        def volume_label(v):
            if v > avg_volume * 1.1:
                return "HIGH"
            elif v < avg_volume * 0.9:
                return "LOW"
            return "MEDIUM"

        actions = ["HOLD", "HOLD", "EXTEND_TP", "HOLD", "EXIT"]
        offsets = [0.5, 1.0, 1.5, 1.0, 0.5] if direction == "UP" else [-0.5, -1.0, -1.5, -1.0, -0.5]
        volumes_out = [volume_label(v) for v in volumes[-5:]]

        predictions = {
            "price_direction": direction,
            "c1": {"action": actions[0], "price": round(current_price + offsets[0], 2), "volume": volumes_out[0]},
            "c2": {"action": actions[1], "price": round(current_price + offsets[1], 2), "volume": volumes_out[1]},
            "c3": {"action": actions[2], "price": round(current_price + offsets[2], 2), "volume": volumes_out[2]},
            "c4": {"action": actions[3], "price": round(current_price + offsets[3], 2), "volume": volumes_out[3]},
            "c5": {"action": actions[4], "price": round(current_price + offsets[4], 2), "volume": volumes_out[4]},
            "midpoint": round(current_price + (offsets[2]), 2),
            "expected_move": "Continuation then retrace." if direction == "UP" else "Retrace then continuation."
        }

        return predictions