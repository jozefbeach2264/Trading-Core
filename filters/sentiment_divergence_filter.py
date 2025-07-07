import logging
import os
import json
from typing import Dict, Any, Set, List, Tuple
from datetime import datetime

from config.config import Config
from data_managers.market_state import MarketState

def setup_sentiment_logger(config: Config) -> logging.Logger:
    log_path = config.sentiment_filter_log_path
    log_dir = os.path.dirname(log_path)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logger = logging.getLogger('SentimentDivergenceFilterLogger')
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.FileHandler(log_path)
        formatter = logging.Formatter('%(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger

class SentimentDivergenceFilter:
    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_sentiment_logger(self.config)
        self.lookback = self.config.sentiment_divergence_lookback
        self.allowed_hours = self._parse_trade_windows(config.trade_windows)

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

    def _calculate_cvd(self, trades: List[Dict[str, Any]]) -> float:
        cvd = 0.0
        for trade in trades:
            qty = trade.get('qty', 0.0)
            if trade.get('isBuyerMaker', False):
                cvd -= qty
            else:
                cvd += qty
        return cvd

    def _find_recent_extrema(self, data: List[float]) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        if not data:
            return (0.0, 0.0), (0.0, 0.0)
        midpoint = len(data) // 2
        first_half = data[:midpoint]
        second_half = data[midpoint:]
        if not first_half or not second_half:
            return (0.0, 0.0), (0.0, 0.0)
        return (
            (max(first_half), max(second_half)),
            (min(first_half), min(second_half))
        )

    async def generate_report(self, market_state: MarketState) -> Dict[str, Any]:
        report = {
            "filter_name": "SentimentDivergenceFilter",
            "divergence_detected": False,
            "divergence_type": "none",
            "confidence_score": 0.0,
            "notes": "Not in trade window or not autonomous."
        }

        if not self.config.autonomous_mode_enabled:
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "reason": "Autonomous mode disabled",
                "result": False
            }))
            return report

        if not self._is_within_trade_window():
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "reason": "Outside of trade window",
                "result": False
            }))
            return report

        klines = list(market_state.klines)
        trades = list(market_state.recent_trades)

        if len(klines) < self.lookback:
            report["notes"] = f"Not enough kline data ({len(klines)}/{self.lookback})."
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "reason": "Insufficient kline data",
                "klines_available": len(klines),
                "required": self.lookback,
                "result": False
            }))
            return report

        chunk_size = len(trades) // self.lookback if self.lookback > 0 else len(trades)
        if chunk_size == 0:
            report["notes"] = "Not enough trade data to evaluate CVD."
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "reason": "Insufficient trade data",
                "trades_available": len(trades),
                "result": False
            }))
            return report

        prices_high = [float(k[2]) for k in klines[-self.lookback:]]
        prices_low = [float(k[3]) for k in klines[-self.lookback:]]
        cvd_history = [self._calculate_cvd(trades[i:i + chunk_size]) for i in range(0, len(trades), chunk_size)]

        (prev_price_high, recent_price_high), (prev_price_low, recent_price_low) = self._find_recent_extrema(prices_high)
        (prev_cvd_high, recent_cvd_high), (prev_cvd_low, recent_cvd_low) = self._find_recent_extrema(cvd_history)

        divergence_type = "none"
        confidence = 0.0

        if recent_price_high > prev_price_high and recent_cvd_high < prev_cvd_high:
            divergence_type = "bearish"
            confidence = abs(recent_cvd_high - prev_cvd_high) / (abs(prev_cvd_high) + 1e-9)
        elif recent_price_low < prev_price_low and recent_cvd_low > prev_cvd_low:
            divergence_type = "bullish"
            confidence = abs(recent_cvd_low - prev_cvd_low) / (abs(prev_cvd_low) + 1e-9)

        if divergence_type != "none":
            report.update({
                "divergence_detected": True,
                "divergence_type": divergence_type,
                "confidence_score": min(round(confidence, 4), 1.0),
                "notes": f"Potential {divergence_type} divergence detected."
            })
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "divergence_type": divergence_type,
                "price_extrema": [prev_price_high, recent_price_high] if divergence_type == "bearish" else [prev_price_low, recent_price_low],
                "cvd_extrema": [prev_cvd_high, recent_cvd_high] if divergence_type == "bearish" else [prev_cvd_low, recent_cvd_low],
                "confidence": min(round(confidence, 4), 1.0),
                "result": True
            }))
        else:
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "reason": "No valid divergence match found",
                "price_extrema": {
                    "highs": [prev_price_high, recent_price_high],
                    "lows": [prev_price_low, recent_price_low]
                },
                "cvd_extrema": {
                    "highs": [prev_cvd_high, recent_cvd_high],
                    "lows": [prev_cvd_low, recent_cvd_low]
                },
                "result": False
            }))

        return report