import logging
import os
import json
from typing import Dict, Any, List
from config.config import Config
from data_managers.market_state import MarketState

def setup_sentiment_logger(config: Config) -> logging.Logger:
    log_path = config.sentiment_filter_log_path
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    logger = logging.getLogger('SentimentDivergenceFilterLogger')
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if logger.handlers:
        logger.handlers.clear()

    handler = logging.FileHandler(log_path, mode='a')
    formatter = logging.Formatter('%(asctime)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger

class SentimentDivergenceFilter:
    """
    Analyzes divergence between price and a live, running Cumulative Volume Delta (CVD)
    to detect conflicts in market sentiment versus price action.
    """
    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_sentiment_logger(self.config)
        self.lookback = self.config.sentiment_divergence_lookback
        self.min_cvd_threshold = self.config.min_cvd_threshold

    async def generate_report(self, market_state: MarketState) -> Dict[str, Any]:
        """
        Generates a weighted report based on price/CVD divergence using a high-speed
        running CVD total from the MarketState.
        """
        report = {
            "filter_name": "SentimentDivergenceFilter",
            "score": 1.0,
            "metrics": {"reason": "NO_DIVERGENCE_DETECTED"},
            "flag": "✅ Hard Pass"
        }
        klines = list(market_state.klines)
        
        if len(klines) < self.lookback:
            report["metrics"]["reason"] = f"INSUFFICIENT_KLINE_DATA ({len(klines)}/{self.lookback})"
            report["score"] = 0.5
            report["flag"] = "⚠️ Soft Flag"
            return report

        # --- High-Speed Analysis Logic ---
        recent_klines = klines[:self.lookback]
        
        # Get the live, pre-calculated running CVD directly from market state
        cvd_value = market_state.running_cvd
        
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
        
        self.logger.debug(f"SentimentDivergenceFilter report generated: {json.dumps(report)}")
        return report
