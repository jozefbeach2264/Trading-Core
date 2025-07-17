import logging
from typing import Dict, Any, List

from config.config import Config
from data_managers.market_state import MarketState

logger = logging.getLogger(__name__)

class Rolling5Engine:
    def __init__(self, config: Config):
        self.config = config
        logger.debug("Rolling5Engine (Forecaster) Initialized.")

    def _calculate_trend(self, klines: List[List[Any]]):
        recent_klines = klines[:10]
        x = list(range(len(recent_klines)))
        y = [float(k[4]) for k in recent_klines]
        n = len(y)
        if n < 2:
            logger.debug("Insufficient klines for trend: %d", n)
            return {"slope": 0, "intercept": y[0] if y else 0}
        sum_x, sum_y, sum_xy, sum_x2 = sum(x), sum(y), sum(xi * yi for xi, yi in zip(x, y)), sum(xi**2 for xi in x)
        try:
            slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x**2)
            intercept = (sum_y - slope * sum_x) / n
        except ZeroDivisionError:
            logger.debug("ZeroDivisionError in trend calculation, using last price")
            return {"slope": 0, "intercept": y[-1]}
        logger.debug("Trend calculated: slope=%.4f, intercept=%.4f", slope, intercept)
        return {"slope": slope, "intercept": intercept}

    async def generate_forecast(self, market_state: MarketState) -> Dict[str, Any]:
        klines = list(market_state.klines)
        sentiment_report = market_state.filter_audit_report.get("SentimentDivergenceFilter", {})
        order_book_report = market_state.filter_audit_report.get("OrderBookReversalZoneDetector", {})
        mark_price = market_state.mark_price or 0.0
        report = {
            "forecast_generated": False,
            "reversal_likelihood_score": 0.0,
            "forecast": {},
            "order_book_metrics": {
                "bid_pressure": market_state.order_book_pressure.get("bid_pressure", 0.0),
                "ask_pressure": market_state.order_book_pressure.get("ask_pressure", 0.0),
                "bid_walls": market_state.order_book_walls.get("bid_walls", []),
                "ask_walls": market_state.order_book_walls.get("ask_walls", [])
            }
        }
        if len(klines) < 10:
            logger.debug("Insufficient klines for forecast: %d", len(klines))
            return report

        trend = self._calculate_trend(klines)
        slope, intercept = trend["slope"], trend["intercept"]
        
        predictions = {}
        projected_prices = [intercept + slope * (len(klines) - 1 + i) for i in range(1, 7)]
        for i, pred_price in enumerate(projected_prices, 1):
            # Adjust predictions with mark_price for accuracy
            if mark_price > 0:
                pred_price = (pred_price * 0.5) + (mark_price * 0.5)
            predictions[f"c{i}"] = {"price": round(pred_price, 2)}
        
        peak_price = max(projected_prices)
        peak_index = projected_prices.index(peak_price)
        internal_score = (6 - peak_index) / 6.0 

        sentiment_confidence = sentiment_report.get("score", 1.0)
        sentiment_direction = sentiment_report.get("metrics", {}).get("divergence_type", "none")
        
        external_booster = 0.0
        if sentiment_direction == "bearish" and slope > 0:
            external_booster = (1.0 - sentiment_confidence) * -1
        elif sentiment_direction == "bullish" and slope < 0:
            external_booster = (1.0 - sentiment_confidence) * -1

        bid_pressure = market_state.order_book_pressure.get("bid_pressure", 0.0)
        ask_pressure = market_state.order_book_pressure.get("ask_pressure", 0.0)
        total_pressure = bid_pressure + ask_pressure
        pressure_factor = (bid_pressure - ask_pressure) / total_pressure if total_pressure > 0 else 0.0
        pressure_adjustment = pressure_factor * 0.2

        # Adjust score with mark_price proximity
        mark_price_factor = 0.0
        if mark_price > 0 and peak_price > 0:
            mark_price_factor = 1 - (abs(mark_price - peak_price) / mark_price) * 0.1

        reversal_score = internal_score + (external_booster * 0.5) + pressure_adjustment + mark_price_factor
        
        report.update({
            "forecast_generated": True,
            "reversal_likelihood_score": round(max(0, min(reversal_score, 1.0)), 4),
            "forecast": predictions
        })
        logger.debug("Forecast generated: %s", report)
        return report