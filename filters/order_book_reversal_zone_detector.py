import logging
import os
import json
from typing import Dict, Any, Set
from datetime import datetime
import asyncio
import httpx

from config.config import Config
from data_managers.market_state import MarketState

def setup_orderbook_logger(config: Config) -> logging.Logger:
    log_path = config.orderbook_reversal_log_path
    log_dir = os.path.dirname(log_path)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logger = logging.getLogger('OrderBookReversalZoneDetectorLogger')
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.FileHandler(log_path)
        formatter = logging.Formatter('%(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
    return logger

class OrderBookReversalZoneDetector:
    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_orderbook_logger(self.config)
        self.depth_percent = self.config.orderbook_reversal_depth_percent
        self.wall_multiplier = self.config.orderbook_reversal_wall_multiplier
        self.allowed_hours = self._parse_trade_windows(config.trade_windows)
        self.min_levels = 15  # Allow slightly incomplete data
        self.client = httpx.AsyncClient(base_url="https://www.okx.com")

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

    async def _fetch_mark_price(self) -> float:
        """Fetch mark price via REST API if not available."""
        endpoint = "/api/v5/market/mark-price"
        params = {"instId": f"{self.config.symbol.replace('USDT', '')}-USDT-SWAP"}
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                response = await self.client.get(endpoint, params=params)
                response.raise_for_status()
                data = response.json()
                if data.get("code") != "0" or not data.get("data"):
                    self.logger.error(f"Failed to fetch mark price: {data.get('msg', 'Unknown error')}")
                    if attempt < max_retries:
                        await asyncio.sleep(2)
                    continue
                mark_price = float(data["data"][0]["markPx"])
                self.logger.info(f"Fetched mark price: {mark_price}")
                return mark_price
            except Exception as e:
                self.logger.error(f"Error fetching mark price on attempt {attempt}: {e}", exc_info=True)
                if attempt < max_retries:
                    await asyncio.sleep(2)
        self.logger.error(f"Failed to fetch mark price after {max_retries} attempts")
        return None

    async def generate_report(self, market_state: MarketState) -> Dict[str, Any]:
        report = {
            "filter_name": "OrderBookReversalZoneDetector",
            "reversal_zone_detected": False,
            "zone_type": "none",
            "total_zone_volume": 0.0,
            "notes": "Not in trade window or not autonomous.",
            "pressure_levels": []
        }

        if not self.config.autonomous_mode_enabled or not self._is_within_trade_window():
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "result": False,
                "denial_reason": "Not in trade window or autonomous mode off"
            }))
            return report

        bids = market_state.depth_20.get("bids", [])
        asks = market_state.depth_20.get("asks", [])
        mark_price = market_state.mark_price or await self._fetch_mark_price()

        if len(bids) < self.min_levels or len(asks) < self.min_levels or not mark_price:
            report["notes"] = f"Insufficient order book data: {len(bids)} bids, {len(asks)} asks, mark_price={mark_price}"
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "result": False,
                "denial_reason": f"Missing order book data ({len(bids)} bids, {len(asks)} asks, mark_price={mark_price})"
            }))
            return report

        # Ensure 20 levels by padding with zeros if necessary
        bids = bids[:20] + [(mark_price - (i + 1) * 0.01, 0.0) for i in range(len(bids), 20)]
        asks = asks[:20] + [(mark_price + (i + 1) * 0.01, 0.0) for i in range(len(asks), 20)]

        # Analyze pressure at each level
        pressure_levels = []
        total_bid_volume = 0.0
        total_ask_volume = 0.0
        reversal_price = None
        reversal_type = "none"

        for i in range(20):
            bid_price, bid_qty = bids[-(i + 1)]  # Start from highest bid
            ask_price, ask_qty = asks[i]  # Start from lowest ask
            bid_qty = float(bid_qty)
            ask_qty = float(ask_qty)
            threshold = max(bid_qty, ask_qty) * self.wall_multiplier

            level_info = {
                "level": i + 1,
                "bid_price": bid_price,
                "bid_qty": bid_qty,
                "ask_price": ask_price,
                "ask_qty": ask_qty,
                "pressure": "neutral"
            }

            if bid_qty > ask_qty * self.wall_multiplier:
                level_info["pressure"] = "buy"
                total_bid_volume += bid_qty
                if bid_qty > threshold and not reversal_price:
                    reversal_price = bid_price
                    reversal_type = "support"
            elif ask_qty > bid_qty * self.wall_multiplier:
                level_info["pressure"] = "sell"
                total_ask_volume += ask_qty
                if ask_qty > threshold and not reversal_price:
                    reversal_price = ask_price
                    reversal_type = "resistance"

            pressure_levels.append(level_info)

        if reversal_price:
            report.update({
                "reversal_zone_detected": True,
                "zone_type": reversal_type,
                "total_zone_volume": total_bid_volume if reversal_type == "support" else total_ask_volume,
                "notes": f"{reversal_type.capitalize()} zone at {reversal_price} with volume {report['total_zone_volume']:.2f}",
                "pressure_levels": pressure_levels
            })
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "zone_type": reversal_type,
                "zone_price": reversal_price,
                "zone_volume": round(report["total_zone_volume"], 2),
                "result": True,
                "pressure_levels": pressure_levels
            }))
        else:
            report.update({
                "notes": "No significant reversal zone detected",
                "pressure_levels": pressure_levels
            })
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "result": False,
                "denial_reason": "No significant volume imbalance",
                "total_bid_volume": round(total_bid_volume, 2),
                "total_ask_volume": round(total_ask_volume, 2),
                "pressure_levels": pressure_levels
            }))

        return report