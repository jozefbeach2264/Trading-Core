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

    def _calculate_cvd(self, trades: List[Dict[str, Any]]) -> float:
        """Calculates Cumulative Volume Delta from a list of trades."""
        cvd = 0.0
        for trade in trades:
            # OKX 'side' field: 'buy' (taker buys) or 'sell' (taker sells)
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
            "score": 1.0, # Default to pass
            "metrics": {"reason": "No divergence detected."},
            "flag": "✅ Hard Pass"
        }

        klines = list(market_state.klines)
        trades = list(market_state.recent_trades)

        if len(klines) < self.lookback:
            report["metrics"]["reason"] = f"Not enough kline data ({len(klines)}/{self.lookback})."
            report["score"] = 0.5
            report["flag"] = "⚠️ Soft Flag"
            return report
        
        if len(trades) < self.lookback * 5: # Require a reasonable number of trades for CVD
            report["metrics"]["reason"] = f"Not enough trade data ({len(trades)}) for CVD calculation."
            report["score"] = 0.5
            report["flag"] = "⚠️ Soft Flag"
            return report

        # --- Analysis Logic ---
        # Analyze the most recent 'lookback' period of klines
        recent_klines = klines[:self.lookback]
        price_highs = [float(k[2]) for k in recent_klines]
        price_lows = [float(k[3]) for k in recent_klines]

        # Calculate CVD over the same approximate time period
        # This is an approximation; for perfect sync, trades would need to be mapped to klines
        cvd_trades = trades[-len(recent_klines)*10:] # Estimate ~10 trades per kline
        cvd_value = self._calculate_cvd(cvd_trades)
        
        # We need historical CVD values to detect a trend, which this simple model doesn't store.
        # As a proxy, we check for divergence between recent price action and the net CVD.
        # A more advanced version would store a CVD history deque in market_state.
        
        price_trend_is_up = float(recent_klines[0][4]) > float(recent_klines[-1][4]) # New close > old close
        cvd_trend_is_up = cvd_value > 0

        divergence_type = "none"
        if price_trend_is_up and not cvd_trend_is_up:
            divergence_type = "bearish" # Price making new highs, but net volume is selling
        elif not price_trend_is_up and cvd_trend_is_up:
            divergence_type = "bullish" # Price making new lows, but net volume is buying

        # --- Scoring & Flagging ---
        if divergence_type != "none":
            # A simple score based on the presence of any divergence.
            # A more advanced model could score based on the magnitude of the divergence.
            score = 0.40 # Divergence is a strong warning
            report["score"] = score
            report["flag"] = "⚠️ Soft Flag"
            report["metrics"] = {
                "divergence_type": divergence_type,
                "price_trend_up": price_trend_is_up,
                "cvd_trend_up": cvd_trend_is_up,
                "net_cvd": round(cvd_value, 2)
            }

        return report
