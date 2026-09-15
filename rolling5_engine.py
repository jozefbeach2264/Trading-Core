import logging
from typing import Dict, Any, List, Optional
import numpy as np
from config.config import Config
from data_managers.market_state import MarketState

logger = logging.getLogger(__name__)

class RollingLifecycleState:
    """
    Tracks the per-trade Rolling5 lifecycle (C1–C5 + REM extensions).
    This is intentionally lightweight: call start_lifecycle when a trade begins,
    and optionally mark_orderbook_rechecked after the C4/C5 OB check.
    """
    def __init__(self):
        self.active: bool = False
        self.start_candle_ts: Optional[int] = None
        self.last_candle_ts: Optional[int] = None
        self.candle_count: int = 0
        self.ob_rechecked: bool = False

    def start(self, candle_ts: int):
        self.active = True
        self.start_candle_ts = candle_ts
        self.last_candle_ts = candle_ts
        self.candle_count = 1
        self.ob_rechecked = False

    def stop(self):
        self.active = False
        self.start_candle_ts = None
        self.last_candle_ts = None
        self.candle_count = 0
        self.ob_rechecked = False

    def mark_orderbook_rechecked(self):
        self.ob_rechecked = True

    def update(self, candle_ts: Optional[int]) -> Dict[str, Any]:
        if not self.active or candle_ts is None:
            return {}
        if self.last_candle_ts is None:
            self.last_candle_ts = candle_ts
        elif candle_ts > self.last_candle_ts:
            # New candle observed; advance lifecycle
            self.candle_count += 1
            self.last_candle_ts = candle_ts

        lifecycle_stage = min(self.candle_count, 5)
        rem_extensions = max(0, self.candle_count - 5)
        ob_recheck_due = self.candle_count >= 4 and not self.ob_rechecked

        return {
            "active": True,
            "candle_count": self.candle_count,
            "lifecycle_stage": lifecycle_stage,  # 1-5 for C1–C5
            "rem_extensions": rem_extensions,
            "ob_recheck_due": ob_recheck_due,
            "ob_rechecked": self.ob_rechecked,
            "start_candle_ts": self.start_candle_ts,
            "last_candle_ts": self.last_candle_ts
        }

class Rolling5Engine:
    def __init__(self, config: Config):
        self.config = config
        self.lifecycle = RollingLifecycleState()
        logger.debug("Rolling5Engine (Forecaster) Initialized.")

    def _calculate_trend(self, klines: List[List[Any]]) -> Dict[str, float]:
        """Calculates the linear regression trendline for the given klines."""
        # MarketState stores klines newest-first; reverse to chronological for regression
        recent_klines = list(reversed(klines[:10]))
        y = [float(k[4]) for k in recent_klines]  # Closing prices in time order
        x = list(range(len(y)))
        n = len(y)

        if n < 2:
            logger.debug("Insufficient klines for trend calculation: %d", n)
            return {"slope": 0, "intercept": y[0] if y else 0}

        try:
            # Using numpy for a more stable linear regression calculation
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

    def _current_candle_ts(self, market_state: MarketState) -> Optional[int]:
        if market_state.live_reconstructed_candle and len(market_state.live_reconstructed_candle) > 0:
            try:
                return int(market_state.live_reconstructed_candle[0])
            except (TypeError, ValueError):
                pass
        if market_state.klines and len(market_state.klines) > 0:
            try:
                return int(market_state.klines[0][0])
            except (TypeError, ValueError):
                pass
        return None

    async def generate_forecast(self, market_state: MarketState) -> Dict[str, Any]:
        """
        Generates a 6-candle forecast including a projected high/low range and a
        reversal likelihood score based on trend, volatility, and order book pressure.
        Also returns lifecycle metadata if a lifecycle session is active.
        """
        klines = list(market_state.klines)
        mark_price = market_state.mark_price or 0.0
        lifecycle_meta = self.lifecycle.update(self._current_candle_ts(market_state))

        report = {
            "forecast_generated": False,
            "reversal_zone_strength": 0.0,
            "forecast": {},
            "order_book_metrics": {
                "bid_pressure": market_state.order_book_pressure.get("bid_pressure", 0.0),
                "ask_pressure": market_state.order_book_pressure.get("ask_pressure", 0.0),
                "bid_walls": market_state.order_book_walls.get("bid_walls", []),
                "ask_walls": market_state.order_book_walls.get("ask_walls", [])
            },
            "lifecycle": lifecycle_meta
        }

        if len(klines) < 10:
            logger.debug("Insufficient klines for forecast: %d", len(klines))
            return report

        trend = self._calculate_trend(klines)
        slope, intercept = trend["slope"], trend["intercept"]
        average_range = self._calculate_average_range(klines)
        
        # Project the next 6 candle close prices based on the trend
        recent_len = min(len(klines), 10)
        last_index = max(recent_len - 1, 0)
        projected_prices = [intercept + slope * (last_index + i) for i in range(1, 7)]
        
        predictions = {}
        for i, pred_price in enumerate(projected_prices, 1):
            # Create a high/low range using the average volatility
            projected_high = pred_price + (average_range / 2)
            projected_low = pred_price - (average_range / 2)
            
            # The forecast now includes the necessary high and low values
            predictions[f"c{i}"] = {
                "high": round(projected_high, 4),
                "low": round(projected_low, 4)
            }

        # --- Reversal Score Calculation (remains the same) ---
        sentiment_report = market_state.filter_audit_report.get("SentimentDivergenceFilter", {})
        
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

        mark_price_factor = 0.0
        if mark_price > 0 and peak_price > 0:
            mark_price_factor = 1 - (abs(mark_price - peak_price) / mark_price) * 0.1
            
        reversal_score = internal_score + (external_booster * 0.5) + pressure_adjustment + mark_price_factor

        report.update({
            "forecast_generated": True,
            "reversal_zone_strength": round(max(0, min(reversal_score, 1.0)), 4),
            "forecast": predictions,
            "lifecycle": lifecycle_meta
        })

        logger.debug("Forecast generated: %s", report)
        return report

    # Lifecycle control helpers (opt-in; call when a trade session starts/ends)
    def start_lifecycle(self, market_state: MarketState):
        ts = self._current_candle_ts(market_state)
        if ts is not None:
            self.lifecycle.start(ts)

    def stop_lifecycle(self):
        self.lifecycle.stop()

    def mark_orderbook_rechecked(self):
        self.lifecycle.mark_orderbook_rechecked()
