import logging
import time
import os  # Added to fix NameError
from typing import Dict, Any, List
import numpy as np
from config.config import Config
from data_managers.market_state import MarketState

# Configure logger to use a dedicated file handler
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.propagate = False  # Prevent logs from propagating to parent loggers (e.g., root with console handler)

class Rolling5Engine:
    def __init__(self, config: Config):
        self.config = config
        self.buffer = []  # Initialize buffer to store last 5 candles with timestamps

        # Set up dedicated file handler for Rolling5Engine
        log_path = getattr(self.config, "rolling5engine_log_path", "logs/rolling5engine.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        file_handler = logging.FileHandler(log_path, mode='a')
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        logger.handlers = [file_handler]  # Replace any existing handlers with file handler only

        logger.debug("Rolling5Engine (Forecaster) Initialized.")

    def _update_buffer(self, klines: List[List[Any]]) -> List[Dict[str, Any]]:
        """Updates rolling buffer with new candles, ensuring unique timestamps."""
        current_time = int(time.time() * 1000)  # Current timestamp in milliseconds
        new_buffer = []

        for kline in klines[:10]:
            # Extract or assign timestamp (assuming kline[0] is timestamp or generate new)
            timestamp = kline[0] if kline[0] != "0" else current_time
            if not any(candle["timestamp"] == timestamp for candle in self.buffer):
                new_buffer.append({
                    "timestamp": timestamp,
                    "open": float(kline[1]),
                    "high": float(kline[2]),
                    "low": float(kline[3]),
                    "close": float(kline[4]),
                    "volume": float(kline[5])
                })
                current_time += 1  # Increment to ensure uniqueness if timestamp is generated

        # Merge new candles with existing buffer, keeping latest 5
        self.buffer = sorted(new_buffer + self.buffer, key=lambda x: x["timestamp"], reverse=True)[:5]
        logger.debug("Buffer updated: %s", [{"timestamp": c["timestamp"]} for c in self.buffer])
        return self.buffer

    def _calculate_trend(self, klines: List[Dict[str, Any]]) -> Dict[str, float]:
        """Calculates the linear regression trendline for the given klines."""
        y = [candle["close"] for candle in klines]
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

    def _calculate_average_range(self, klines: List[Dict[str, Any]]) -> float:
        """Calculates the average candle range (high - low) for volatility."""
        if not klines:
            return 0.0
        
        ranges = [candle["high"] - candle["low"] for candle in klines]
        average_range = sum(ranges) / len(ranges) if ranges else 0.0
        logger.debug("Calculated average candle range: %.4f", average_range)
        return average_range

    async def generate_forecast(self, market_state: MarketState) -> Dict[str, Any]:
        """
        Generates a 6-candle forecast with projected high/low range and reversal likelihood score.
        Includes timestamp for each forecast candle.
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

        # Update buffer with unique timestamps
        buffer = self._update_buffer(klines)
        if len(buffer) < 5:
            logger.debug("Insufficient buffer candles for forecast: %d", len(buffer))
            return report

        trend = self._calculate_trend(buffer)
        slope, intercept = trend["slope"], trend["intercept"]
        average_range = self._calculate_average_range(buffer)
        
        # Project next 6 candle close prices with timestamps
        current_time = buffer[0]["timestamp"] if buffer else int(time.time() * 1000)
        predictions = {}
        for i in range(1, 7):
            pred_price = intercept + slope * (len(buffer) - 1 + i)
            projected_high = pred_price + (average_range / 2)
            projected_low = pred_price - (average_range / 2)
            predictions[f"c{i}"] = {
                "timestamp": current_time + (i * 60000),  # Add 1 minute (60000ms) per candle
                "high": round(projected_high, 4),
                "low": round(projected_low, 4)
            }

        # Reversal Score Calculation
        sentiment_report = market_state.filter_audit_report.get("SentimentDivergenceFilter", {})
        peak_price = max(pred["high"] for pred in predictions.values())
        peak_index = next(i for i, pred in enumerate(predictions.values(), 1) if pred["high"] == peak_price)
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