import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class OrderBookReversalZoneDetector:
    """
    Watches the order book for signs of reversal, such as large buy or sell walls
    appearing, which might absorb the current price momentum.
    """
    def __init__(self):
        logger.info("OrderBookReversalZoneDetector initialized.")
        # Define what constitutes a "large" wall relative to other levels
        self.wall_size_multiplier = 10.0 

    async def validate(self, signal_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyzes the order book depth to identify significant liquidity walls.

        Args:
            signal_data (Dict[str, Any]): Market state data, must include 'depth_20'.

        Returns:
            Dict[str, Any]: A dictionary containing the analysis result.
        """
        depth = signal_data.get('depth_20', {})
        bids = depth.get('bids', [])
        asks = depth.get('asks', [])
        
        result = {
            "filter_name": "OrderBookReversalZoneDetector",
            "wall_detected": False,
            "wall_type": None,
            "wall_price": None,
            "wall_size": None,
            "reason": "No significant liquidity walls detected."
        }

        if not bids or not asks:
            result["reason"] = "Order book data is incomplete."
            return result

        try:
            # Calculate average size of the first 10 levels
            avg_bid_size = sum(qty for _, qty in bids[:10]) / 10 if bids[:10] else 1
            avg_ask_size = sum(qty for _, qty in asks[:10]) / 10 if asks[:10] else 1

            # Check for a large bid wall
            for price, qty in bids[:10]:
                if qty > avg_bid_size * self.wall_size_multiplier:
                    result.update({
                        "wall_detected": True,
                        "wall_type": "SUPPORT",
                        "wall_price": price,
                        "wall_size": qty,
                        "reason": f"Large support wall detected at {price} ({qty:.2f})."
                    })
                    return result

            # Check for a large ask wall
            for price, qty in asks[:10]:
                if qty > avg_ask_size * self.wall_size_multiplier:
                    result.update({
                        "wall_detected": True,
                        "wall_type": "RESISTANCE",
                        "wall_price": price,
                        "wall_size": qty,
                        "reason": f"Large resistance wall detected at {price} ({qty:.2f})."
                    })
                    return result
        
        except (ValueError, TypeError, ZeroDivisionError) as e:
            logger.error(f"Error processing order book data in ReversalZoneDetector: {e}")
            result["reason"] = "Malformed order book data."

        return result
