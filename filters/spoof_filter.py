import logging
import os
import json
from typing import Dict, Any, Set
from datetime import datetime

from config.config import Config
from data_managers.market_state import MarketState

def setup_spoof_logger(config: Config) -> logging.Logger:
    log_path = config.spoof_filter_log_path
    log_dir = os.path.dirname(log_path)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logger = logging.getLogger('SpoofFilterLogger')
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.FileHandler(log_path)
        formatter = logging.Formatter('%(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger

class SpoofFilter:
    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_spoof_logger(self.config)
        self.imbalance_threshold = self.config.spoof_imbalance_threshold
        self.distance_percent = self.config.spoof_distance_percent
        self.large_order_multiplier = self.config.spoof_large_order_multiplier
        self.allowed_hours = self._parse_trade_windows(config.trade_windows)

        self.logger.info(json.dumps({
            "level": "INFO",
            "message": "SpoofFilter Initialized",
            "settings": {
                "imbalance_threshold": self.imbalance_threshold,
                "distance_percent": self.distance_percent,
                "large_order_multiplier": self.large_order_multiplier
            }
        }))

    def _parse_trade_windows(self, window_str: str) -> Set[int]:
        allowed_hours = set()
        try:
            parts = window_str.split(',')
            for part in parts:
                if '-' in part:
                    start, end = map(int, part.split('-'))
                    for hour in range(start, end + 1):
                        allowed_hours.add(hour)
                else:
                    allowed_hours.add(int(part))
        except ValueError as e:
            logging.getLogger(__name__).error(f"Invalid trade_windows format: '{window_str}'. Error: {e}")
        return allowed_hours

    def _is_within_trade_window(self) -> bool:
        return datetime.utcnow().hour in self.allowed_hours

    async def generate_report(self, market_state: MarketState) -> Dict[str, Any]:
        report = {
            "filter_name": "SpoofFilter",
            "spoofing_detected": False,
            "spoof_score": 0.0,
            "notes": "Not in trade window or not autonomous."
        }

        if not self.config.autonomous_mode_enabled or not self._is_within_trade_window():
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "reason": "Disabled or outside trade window",
                "spoof_score": 0.0,
                "result": False
            }))
            return report

        bids = market_state.depth_20.get("bids", [])
        asks = market_state.depth_20.get("asks", [])
        mark_price = market_state.mark_price

        if len(bids) < 2 or len(asks) < 2 or not mark_price:
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "reason": "Insufficient order book data",
                "bids": len(bids),
                "asks": len(asks),
                "mark_price": mark_price,
                "result": False
            }))
            report["notes"] = "Not enough order book data (requires at least 2 levels)."
            return report

        spoof_score = 0.0
        detection_notes = []
        denial_reasons = []

        top_bid_qty = float(bids[0][1])
        second_bid_qty = float(bids[1][1])
        top_ask_qty = float(asks[0][1])
        second_ask_qty = float(asks[1][1])

        total_bid_volume = sum(float(q) for _, q in bids)
        total_ask_volume = sum(float(q) for _, q in asks)
        denominator = total_bid_volume + total_ask_volume
        imbalance = (total_bid_volume - total_ask_volume) / denominator if denominator > 0 else 0.0

        if abs(imbalance) > self.imbalance_threshold:
            spoof_score += 0.5
            detection_notes.append(f"High imbalance ({imbalance:.2%})")
        else:
            denial_reasons.append(f"Imbalance {imbalance:.2%} below threshold")

        spoof_bid_threshold = mark_price * (1 - self.distance_percent / 100)
        spoof_ask_threshold = mark_price * (1 + self.distance_percent / 100)

        distant_bid_found = any(
            float(price) < spoof_bid_threshold and float(qty) > top_bid_qty * self.large_order_multiplier
            for price, qty in bids
        )

        if distant_bid_found:
            spoof_score += 0.5
            detection_notes.append("Large distant bid")
        else:
            denial_reasons.append("No large distant bid found")

        if spoof_score < 1.0:
            distant_ask_found = any(
                float(price) > spoof_ask_threshold and float(qty) > top_ask_qty * self.large_order_multiplier
                for price, qty in asks
            )
            if distant_ask_found:
                spoof_score += 0.5
                detection_notes.append("Large distant ask")
            else:
                denial_reasons.append("No large distant ask found")

        spoof_detected = spoof_score > 0.4

        if spoof_detected:
            report.update({
                "spoofing_detected": True,
                "spoof_score": round(spoof_score, 2),
                "notes": ", ".join(detection_notes)
            })
        else:
            report["notes"] = "; ".join(denial_reasons)

        self.logger.info(json.dumps({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "spoof_score": round(spoof_score, 2),
            "imbalance": round(imbalance, 4),
            "top_bid_qty": top_bid_qty,
            "second_bid_qty": second_bid_qty,
            "top_ask_qty": top_ask_qty,
            "second_ask_qty": second_ask_qty,
            "result": spoof_detected,
            "notes": detection_notes if spoof_detected else denial_reasons
        }))

        return report