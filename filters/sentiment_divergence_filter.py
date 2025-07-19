import logging
import os
import json
from typing import Dict, Any, List, Tuple
from config.config import Config
from data_managers.market_state import MarketState

def setup_sentiment_logger(config: Config) -> logging.Logger:
    log_path = config.sentiment_filter_log_path
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    logger = logging.getLogger('SentimentDivergenceFilterLogger')
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.FileHandler(log_path, mode='a')
        formatter = logging.Formatter('%(asctime)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger

class SentimentDivergenceFilter:
    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_sentiment_logger(self.config)
        self.lookback = self.config.sentiment_divergence_lookback
        self.min_cvd_threshold = self.config.min_cvd_threshold

    def _calculate_cvd(self, trades: List[Dict[str, Any]]) -> float:
        cvd = 0.0
        for trade in trades:
            qty = trade.get('qty', 0.0)
            side = trade.get('side', '')
            if side == 'buy':
                cvd += qty
            elif side == 'sell':
                cvd -= qty
        return cvd

    async def generate_report(self, market_state: MarketState) -> Dict[str, Any]:
        report = {
            "filter_name": "SentimentDivergenceFilter", "score": 1.0,
            "metrics": {"reason": "NO_DIVERGENCE_DETECTED"}, "flag": "✅ Hard Pass"
        }
        klines = list(market_state.klines)
        trades = list(market_state.recent_trades)
        
        if len(klines) < self.lookback:
            report["metrics"]["reason"] = f"INSUFFICIENT_KLINE_DATA ({len(klines)}/{self.lookback})"
            report["score"] = 0.5; report["flag"] = "⚠️ Soft Flag"
            return report

        if len(trades) < self.lookback * 5:
            report["metrics"]["reason"] = f"INSUFFICIENT_TRADE_DATA ({len(trades)})"
            report["score"] = 0.5; report["flag"] = "⚠️ Soft Flag"
            return report

        recent_klines = klines[:self.lookback]
        start_time_ms = recent_klines[-1][0]
        end_time_ms = recent_klines[0][0] + 60000
        relevant_trades = [t for t in trades if start_time_ms <= t.get('time', 0) < end_time_ms]
        
        cvd_value = self._calculate_cvd(relevant_trades)
        
        price_trend_is_up = float(recent_klines[0][4]) > float(recent_klines[-1][4])
        cvd_trend_is_up = cvd_value > 0
        
        divergence_type = "none"
        if price_trend_is_up and not cvd_trend_is_up:
            divergence_type = "bearish"
        elif not price_trend_is_up and cvd_trend_is_up:
            divergence_type = "bullish"
            
        if divergence_type != "none":
            if abs(cvd_value) < self.min_cvd_threshold:
                report["metrics"]["reason"] = "DIVERGENCE_CVD_NOISE"
            else:
                report["score"] = 0.40; report["flag"] = "⚠️ Soft Flag"
                report["metrics"] = {
                    "divergence_type": divergence_type, "price_trend_up": price_trend_is_up,
                    "cvd_trend_up": cvd_trend_is_up, "net_cvd": round(cvd_value, 2),
                    "reason": f"{divergence_type.upper()}_DIVERGENCE_DETECTED"
                }
        
        self.logger.debug(f"SentimentDivergenceFilter report generated: {json.dumps(report)}")
        return report
