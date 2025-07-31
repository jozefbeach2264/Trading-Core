import logging
import os
import json
from typing import Dict, Any
from config.config import Config
from data_managers.market_state import MarketState

def setup_orderbook_reversal_logger(config: Config) -> logging.Logger:
    log_path = config.orderbook_reversal_log_path
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    
    logger = logging.getLogger('OrderBookReversalZoneDetectorLogger')
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if logger.handlers:
        logger.handlers.clear()

    handler = logging.FileHandler(log_path, mode='a')
    formatter = logging.Formatter('%(asctime)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
        
    return logger

class OrderBookReversalZoneDetector:
    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_orderbook_reversal_logger(self.config)
        self.logger.debug("OrderBookReversalZoneDetector initialized.")

    async def generate_report(self, market_state: MarketState) -> Dict[str, Any]:
        
        # --- NEW: Ensure the latest OB metrics are calculated before proceeding ---
        await market_state.ensure_order_book_metrics_are_current()

        report = {
            "filter_name": "OrderBookReversalZoneDetector", "score": 0.0,
            "metrics": {}, "flag": "⚠️ Soft Flag"
        }
        
        # Now, read the pre-calculated (cached) metrics from the market state
        walls = market_state.order_book_walls
        pressure = market_state.order_book_pressure
        mark_price = market_state.mark_price or 0.0
        
        self.logger.debug(
            f"Using cached metrics: walls={'Yes' if walls else 'No'}, pressure={'Yes' if pressure else 'No'}, mark_price={mark_price}"
        )
        
        if not walls or not pressure:
            report["metrics"]["reason"] = "ORDER_BOOK_METRICS_UNAVAILABLE"
            report["flag"] = "❌ Block"
            self.logger.error(report["metrics"]["reason"])
            await market_state.update_filter_audit_report("OrderBookReversalZoneDetector", report)
            return report

        bid_walls = walls.get("bid_walls", [])
        ask_walls = walls.get("ask_walls", [])
        
        if not bid_walls and not ask_walls:
            report["metrics"]["reason"] = "NO_WALLS_DETECTED"
            self.logger.debug(report["metrics"]["reason"])
            await market_state.update_filter_audit_report("OrderBookReversalZoneDetector", report)
            return report

        strongest_bid_wall = max(bid_walls, key=lambda x: x['qty']) if bid_walls else None
        strongest_ask_wall = max(ask_walls, key=lambda x: x['qty']) if ask_walls else None
        total_pressure = pressure.get("total_pressure", 0)
        
        if total_pressure <= 0:
            report["metrics"]["reason"] = "INVALID_ORDER_BOOK_PRESSURE"
            report["flag"] = "❌ Block"
            self.logger.error(report["metrics"]["reason"])
            await market_state.update_filter_audit_report("OrderBookReversalZoneDetector", report)
            return report

        bid_wall_score = 0.0
        if strongest_bid_wall and mark_price > 0:
            absorption_score = strongest_bid_wall['qty'] / total_pressure
            distance_score = 1 - (abs(mark_price - strongest_bid_wall['price']) / mark_price)
            bid_wall_score = (absorption_score * 0.7) + (distance_score * 0.3)
            self.logger.debug(f"Bid wall score: absorption={absorption_score:.4f}, distance={distance_score:.4f}, total={bid_wall_score:.4f}")

        ask_wall_score = 0.0
        if strongest_ask_wall and mark_price > 0:
            absorption_score = strongest_ask_wall['qty'] / total_pressure
            distance_score = 1 - (abs(strongest_ask_wall['price'] - mark_price) / mark_price)
            ask_wall_score = (absorption_score * 0.7) + (distance_score * 0.3)
            self.logger.debug(f"Ask wall score: absorption={absorption_score:.4f}, distance={distance_score:.4f}, total={ask_wall_score:.4f}")

        if bid_wall_score > ask_wall_score:
            report["score"] = min(round(bid_wall_score * 2, 4), 1.0)
            report["metrics"] = {
                "detected_zone": "support", "wall_price": strongest_bid_wall['price'] if strongest_bid_wall else 0.0,
                "wall_qty": strongest_bid_wall['qty'] if strongest_bid_wall else 0.0
            }
        elif ask_wall_score > bid_wall_score:
            report["score"] = min(round(ask_wall_score * 2, 4), 1.0)
            report["metrics"] = {
                "detected_zone": "resistance", "wall_price": strongest_ask_wall['price'] if strongest_ask_wall else 0.0,
                "wall_qty": strongest_ask_wall['qty'] if strongest_ask_wall else 0.0
            }

        final_score = report["score"]
        if final_score >= 0.75:
            report["flag"] = "✅ Hard Confirmed"
            zone_type = report["metrics"].get("detected_zone", "").upper()
            report["metrics"]["reason"] = f"STRONG_{zone_type}_WALL"
        else:
            report["flag"] = "⚠️ Soft Flag"
            report["metrics"]["reason"] = "WEAK_OR_DISTANT_WALL"
            
        self.logger.debug(f"OrderBookReversalZoneDetector report generated: {json.dumps(report)}")
        await market_state.update_filter_audit_report("OrderBookReversalZoneDetector", report)
        return report
