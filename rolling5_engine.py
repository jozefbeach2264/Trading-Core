import logging
from typing import Dict, Any, List
import numpy as np
from config.config import Config
from data_managers.market_state import MarketState

logger = logging.getLogger(__name__)

class Rolling5Engine:
    def __init__(self, config: Config):
        self.config = config
        logger.debug("Rolling5Engine (Forecaster) Initialized.")

    def _calculate_trend(self, klines: List[List[Any]]) -> Dict[str, float]:
        """Calculates the linear regression trendline for the given klines."""
        recent_klines = klines[:10]
        y = [float(k[4]) for k in recent_klines] # Closing prices
        x = list(range(len(y)))
        n = len(y)

        if n < 2:
            logger.debug("Insufficient klines for trend calculation: %d", n)
            return {"slope": 0, "intercept": y[0] if y else 0}

        try:
            A = np.vstack([x, np.ones(len(x))]).T
            slope, intercept = np.linalg.lstsq(A, y, rcond=None)[0]
        except (np.linalg.LinAlgError, ValueError) as e:
            logger.error("Trend calculation failed due to a numpy error: %s", e)
            return {"slope": 0, "intercept": y[-1] if y else 0}

        logger.debug("Trend calculated: slope=%.4f, intercept=%.4f", slope, intercept)
        return {"slope": slope, "intercept": intercept}

    def _calculate_average_range(self, klines: List[List[Any]]) -> float:
        """Calculates the average candle range (high - low) for volatility."""
        recent_klines = klines[:10]
        if not recent_klines:
            return 0.0

        ranges = [float(k[2]) - float(k[3]) for k in recent_klines]
        average_range = sum(ranges) / len(ranges) if ranges else 0.0
        logger.debug("Calculated average candle range: %.4f", average_range)
        return average_range

    async def generate_forecast(self, market_state: MarketState) -> Dict[str, Any]:
        """
        Generates a 6-candle forecast including a projected high/low range and a
        reversal likelihood score based on trend, volatility, and order book pressure.
        """
        klines = list(market_state.klines)
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
        average_range = self._calculate_average_range(klines)

        projected_prices = [intercept + slope * (len(klines) - 1 + i) for i in range(1, 7)]

        predictions = {}
        for i, pred_price in enumerate(projected_prices, 1):
            projected_high = pred_price + (average_range / 2)
            projected_low = pred_price - (average_range / 2)

            predictions[f"c{i}"] = {
                "high": round(projected_high, 4),
                "low": round(projected_low, 4)
            }

        # --- Reversal Score Calculation ---
        peak_price = max(projected_prices)
        peak_index = projected_prices.index(peak_price)
        internal_score = (6 - peak_index) / 6.0

        bid_pressure = market_state.order_book_pressure.get("bid_pressure", 0.0)
        ask_pressure = market_state.order_book_pressure.get("ask_pressure", 0.0)
        total_pressure = bid_pressure + ask_pressure
        pressure_factor = (bid_pressure - ask_pressure) / total_pressure if total_pressure > 0 else 0.0
        pressure_adjustment = pressure_factor * 0.2

        # --- OI & CVD Divergence Boosters ---
        oi_booster = 0.0
        cvd_booster = 0.0

        if len(market_state.oi_history) > 1:
            current_oi = market_state.open_interest
            previous_oi = market_state.oi_history[-2].get('openInterest', current_oi)
            oi_change = current_oi - previous_oi
            if slope > 0 and oi_change < 0:
                oi_booster = 0.1
            elif slope < 0 and oi_change > 0:
                oi_booster = 0.1

        if slope > 0 and market_state.running_cvd < 0:
            cvd_booster = 0.1
        elif slope < 0 and market_state.running_cvd > 0:
            cvd_booster = 0.1

        reversal_score = internal_score + pressure_adjustment + oi_booster + cvd_booster

        report.update({
            "forecast_generated": True,
            "reversal_likelihood_score": round(max(0, min(reversal_score, 1.0)), 4),
            "forecast": predictions
        })

        logger.debug("Forecast generated: %s", report)
        return report