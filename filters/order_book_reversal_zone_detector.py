import logging
import os
from typing import Dict, Any, Set
from datetime import datetime

from config.config import Config
from data_managers.market_state import MarketState

def setup_orderbook_reversal_logger(config: Config) -> logging.Logger:
    log_path = config.orderbook_reversal_log_path
    log_dir = os.path.dirname(log_path) if os.path.dirname(log_path) else '.'
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger('OrderBookReversalZoneDetectorLogger')
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.FileHandler(log_path, mode='a')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger

class OrderBookReversalZoneDetector:
    """
    Analyzes order book depth snapshots to identify strong support/resistance
    walls and calculates their probability of causing a price reversal.
    """
    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_orderbook_reversal_logger(self.config)
        self.logger.debug("OrderBookReversalZoneDetector initialized.")

    async def generate_report(self, market_state: MarketState) -> Dict[str, Any]:
        """
        Generates a weighted report on the strength of potential reversal zones.
        """
        report = {
            "filter_name": "OrderBookReversalZoneDetector",
            "score": 0.0,
            "metrics": {"reason": "No significant reversal zones detected."},
            "flag": "⚠️ Soft Flag"
        }

        walls = market_state.order_book_walls or {"bid_walls": [], "ask_walls": []}
        pressure = market_state.order_book_pressure or {"bid_pressure": 0.0, "ask_pressure": 0.0, "total_pressure": 0.0}
        mark_price = market_state.mark_price or 0.0
        depth_20 = market_state.depth_20 or {"bids": [], "asks": []}

        self.logger.debug("MarketState data: walls=%s, pressure=%s, mark_price=%s, depth_20=%s",
                         walls, pressure, mark_price, depth_20)

        if not (walls.get("bid_walls") or walls.get("ask_walls") or pressure.get("total_pressure", 0) > 0 or depth_20.get("bids") or depth_20.get("asks")):
            report["metrics"]["reason"] = "Market state is missing order book data (walls, pressure, or depth)."
            self.logger.error(report["metrics"]["reason"])
            await market_state.update_filter_audit_report("OrderBookReversalZoneDetector", report)
            return report

        bid_walls = walls.get("bid_walls", [])
        ask_walls = walls.get("ask_walls", [])
        
        if not bid_walls and not ask_walls:
            self.logger.debug("No bid or ask walls detected.")
            await market_state.update_filter_audit_report("OrderBookReversalZoneDetector", report)
            return report

        strongest_bid_wall = max(bid_walls, key=lambda x: x['qty']) if bid_walls else None
        strongest_ask_wall = max(ask_walls, key=lambda x: x['qty']) if ask_walls else None
        
        total_pressure = pressure.get("total_pressure", 0)
        if total_pressure <= 0 and (strongest_bid_wall or strongest_ask_wall):
            total_pressure = (strongest_bid_wall['qty'] if strongest_bid_wall else 0) + (strongest_ask_wall['qty'] if strongest_ask_wall else 0)
            self.logger.debug("Recalculated total_pressure from walls: %.2f", total_pressure)

        if total_pressure <= 0:
            report["metrics"]["reason"] = "Total order book pressure is zero or invalid."
            self.logger.error(report["metrics"]["reason"])
            await market_state.update_filter_audit_report("OrderBookReversalZoneDetector", report)
            return report

        bid_wall_score = 0
        if strongest_bid_wall and mark_price > 0:
            absorption_score = strongest_bid_wall['qty'] / total_pressure
            distance_score = 1 - (abs(mark_price - strongest_bid_wall['price']) / mark_price)
            bid_wall_score = (absorption_score * 0.7) + (distance_score * 0.3)
            self.logger.debug("Bid wall score: absorption=%.4f, distance=%.4f, total=%.4f",
                             absorption_score, distance_score, bid_wall_score)

        ask_wall_score = 0
        if strongest_ask_wall and mark_price > 0:
            absorption_score = strongest_ask_wall['qty'] / total_pressure
            distance_score = 1 - (abs(strongest_ask_wall['price'] - mark_price) / mark_price)
            ask_wall_score = (absorption_score * 0.7) + (distance_score * 0.3)
            self.logger.debug("Ask wall score: absorption=%.4f, distance=%.4f, total=%.4f",
                             absorption_score, distance_score, ask_wall_score)

        if bid_wall_score > ask_wall_score:
            report["score"] = min(round(bid_wall_score * 2, 4), 1.0)
            report["metrics"] = {
                "detected_zone": "support",
                "wall_price": strongest_bid_wall['price'] if strongest_bid_wall else 0.0,
                "wall_qty": strongest_bid_wall['qty'] if strongest_bid_wall else 0.0
            }
        elif ask_wall_score > bid_wall_score:
            report["score"] = min(round(ask_wall_score * 2, 4), 1.0)
            report["metrics"] = {
                "detected_zone": "resistance",
                "wall_price": strongest_ask_wall['price'] if strongest_ask_wall else 0.0,
                "wall_qty": strongest_ask_wall['qty'] if strongest_ask_wall else 0.0
            }
        
        final_score = report["score"]
        if final_score >= 0.75:
            report["flag"] = "✅ Hard Confirmed"
        elif final_score >= 0.50:
            report["flag"] = "⚠️ Soft Flag"
        else:
            report["flag"] = "⚠️ Soft Flag"
            report["metrics"]["reason"] = "Detected wall is weak or distant."

        self.logger.debug("OrderBookReversalZoneDetector report: score=%.4f, flag=%s, metrics=%s",
                         report["score"], report["flag"], report["metrics"])
        await market_state.update_filter_audit_report("OrderBookReversalZoneDetector", report)
        return report