import logging
import os
import json
from typing import Dict, Any, Set, List, Tuple
from datetime import datetime

from config.config import Config
from data_managers.market_state import MarketState

def setup_sentiment_logger(config: Config) -> logging.Logger:
    log_path = config.sentiment_filter_log_path
    log_dir = os.path.dirname(log_path) if os.path.dirname(log_path) else '.'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logger = logging.getLogger('SentimentDivergenceFilterLogger')
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.FileHandler(log_path, mode='w')
        formatter = logging.Formatter('%(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger

class SentimentDivergenceFilter:
    """
    Analyzes divergence between price and Cumulative Volume Delta (CVD)
    to detect conflicts in market sentiment versus price action.
    """
    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_sentiment_logger(self.config)
        self.lookback = self.config.sentiment_divergence_lookback
        self.min_cvd_threshold = self.config.min_cvd_threshold

    def _calculate_cvd(self, trades: List[Dict[str, Any]]) -> float:
        """Calculates Cumulative Volume Delta from a list of trades."""
        cvd = 0.0
        for trade in trades:
            if trade.get('side') == 'buy':
                cvd += trade.get('qty', 0.0)
            elif trade.get('side') == 'sell':
                cvd -= trade.get('qty', 0.0)
        return cvd

    def _find_extrema(self, data: List[float]) -> Tuple[float, float]:
        """Finds the min and max values in a list."""
        if not data:
            return (0.0, 0.0)
        return (min(data), max(data))

    async def generate_report(self, market_state: MarketState) -> Dict[str, Any]:
        """
        Generates a weighted report based on price/CVD divergence.
        """
        report = {
            "filter_name": "SentimentDivergenceFilter",
            "score": 1.0,
            "metrics": {"reason": "NO_DIVERGENCE_DETECTED"},
            "flag": "✅ Hard Pass"
        }

        klines = list(market_state.klines)
        trades = list(market_state.recent_trades)

        if len(klines) < self.lookback:
            report["metrics"]["reason"] = f"INSUFFICIENT_KLINE_DATA ({len(klines)}/{self.lookback})"
            report["score"] = 0.5
            report["flag"] = "⚠️ Soft Flag"
            return report
        
        if len(trades) < self.lookback * 5:
            report["metrics"]["reason"] = f"INSUFFICIENT_TRADE_DATA ({len(trades)})"
            report["score"] = 0.5
            report["flag"] = "⚠️ Soft Flag"
            return report

        # --- Analysis Logic ---
        recent_klines = klines[:self.lookback]
        cvd_trades = trades[-len(recent_klines)*10:]
        cvd_value = self._calculate_cvd(cvd_trades)
        
        price_trend_is_up = float(recent_klines[0][4]) > float(recent_klines[-1][4])
        cvd_trend_is_up = cvd_value > 0

        divergence_type = "none"
        if price_trend_is_up and not cvd_trend_is_up:
            divergence_type = "bearish"
        elif not price_trend_is_up and cvd_trend_is_up:
            divergence_type = "bullish"

        # --- Scoring & Flagging ---
        if divergence_type != "none":
            if abs(cvd_value) < self.min_cvd_threshold:
                report["metrics"]["reason"] = "DIVERGENCE_CVD_NOISE"
            else:
                report["score"] = 0.40
                report["flag"] = "⚠️ Soft Flag"
                report["metrics"] = {
                    "divergence_type": divergence_type,
                    "price_trend_up": price_trend_is_up,
                    "cvd_trend_up": cvd_trend_is_up,
                    "net_cvd": round(cvd_value, 2),
                    "reason": f"{divergence_type.upper()}_DIVERGENCE_DETECTED"
                }

        return report
