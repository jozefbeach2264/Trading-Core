import logging
from typing import Dict, Any, List, Optional
import numpy as np
from config.config import Config
from data_managers.market_state import MarketState

logger = logging.getLogger(__name__)

TREND_LOOKBACK_CANDLES = 10
FORECAST_HORIZON_CANDLES = 6
TREND_WEIGHT = 0.5
PRESSURE_WEIGHT = 0.3
SENTIMENT_WEIGHT = 0.2
NEUTRAL_TERM = 0.5


def _clamp01(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


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
        recent_klines = list(reversed(klines[:TREND_LOOKBACK_CANDLES]))
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
        recent_klines = klines[:TREND_LOOKBACK_CANDLES]
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

    @staticmethod
    def _reversal_likelihood(direction: Optional[str], slope: float, average_range: float,
                             bid_pressure: float, ask_pressure: float, sentiment_report: Dict[str, Any]) -> float:
        """Probability-like score in [0, 1] that price reverses AGAINST the trade.

        Rewritten 2026-09-15: the previous formula added a ≈1.0 "mark price factor" to a 0.17–1.0 trend
        term, so after clamping it was 1.0 on every cycle (see logs/ai_model.log history) and the AI
        aborted every trade. Three direction-aware terms, weights sum to 1:
          trend     projected drift over the forecast horizon, in average-range units, mapped so that
                    one full range against the trade → 1.0, flat → 0.5, one full range with it → 0.0
          pressure  order-book imbalance against the trade (0.5 = balanced)
          sentiment CVD divergence against the trade (0 unless the SentimentDivergenceFilter flagged it)
        """
        sign = {"LONG": 1.0, "SHORT": -1.0}.get((direction or "").upper(), 0.0)

        if sign and average_range > 0:
            # Drift over the horizon in average-range units, signed against the trade:
            # +1 range against → 1.0, flat → 0.5, +1 range with the trade → 0.0.
            adverse_ranges = -sign * slope * FORECAST_HORIZON_CANDLES / average_range
            trend_term = _clamp01((1.0 + adverse_ranges) / 2.0)
        else:
            trend_term = NEUTRAL_TERM

        total_pressure = bid_pressure + ask_pressure
        imbalance = (bid_pressure - ask_pressure) / total_pressure if total_pressure > 0 else 0.0  # +1 = all bids
        pressure_term = _clamp01((1.0 - sign * imbalance) / 2.0)

        divergence = (sentiment_report.get("metrics") or {}).get("divergence_type", "none")
        opposes_trade = (sign > 0 and divergence == "bearish") or (sign < 0 and divergence == "bullish")
        sentiment_term = _clamp01(1.0 - float(sentiment_report.get("score", 1.0))) if opposes_trade else 0.0

        score = (TREND_WEIGHT * trend_term + PRESSURE_WEIGHT * pressure_term + SENTIMENT_WEIGHT * sentiment_term)
        return round(_clamp01(score), 4)

    async def generate_forecast(self, market_state: MarketState, direction: Optional[str] = None) -> Dict[str, Any]:
        """
        Generates a 6-candle forecast including a projected high/low range and a
        reversal likelihood score (against `direction`) based on trend, order book
        pressure and CVD divergence. Also returns lifecycle metadata if a lifecycle
        session is active.
        """
        klines = list(market_state.klines)
        lifecycle_meta = self.lifecycle.update(self._current_candle_ts(market_state))
        bid_pressure = market_state.order_book_pressure.get("bid_pressure", 0.0)
        ask_pressure = market_state.order_book_pressure.get("ask_pressure", 0.0)

        report = {
            "forecast_generated": False,
            "reversal_likelihood_score": 0.0,
            "forecast": {},
            "order_book_metrics": {
                "bid_pressure": bid_pressure,
                "ask_pressure": ask_pressure,
                "bid_walls": market_state.order_book_walls.get("bid_walls", []),
                "ask_walls": market_state.order_book_walls.get("ask_walls", [])
            },
            "lifecycle": lifecycle_meta
        }

        if len(klines) < TREND_LOOKBACK_CANDLES:
            logger.debug("Insufficient klines for forecast: %d", len(klines))
            return report

        trend = self._calculate_trend(klines)
        slope, intercept = trend["slope"], trend["intercept"]
        average_range = self._calculate_average_range(klines)

        # Project the next 6 candle close prices based on the trend
        recent_len = min(len(klines), TREND_LOOKBACK_CANDLES)
        last_index = max(recent_len - 1, 0)
        projected_prices = [intercept + slope * (last_index + i) for i in range(1, FORECAST_HORIZON_CANDLES + 1)]

        predictions = {}
        for i, pred_price in enumerate(projected_prices, 1):
            predictions[f"c{i}"] = {
                "high": round(pred_price + (average_range / 2), 4),
                "low": round(pred_price - (average_range / 2), 4)
            }

        sentiment_report = market_state.filter_audit_report.get("SentimentDivergenceFilter", {})
        reversal_score = self._reversal_likelihood(direction, float(slope), average_range,
                                                   bid_pressure, ask_pressure, sentiment_report)

        report.update({
            "forecast_generated": True,
            "reversal_likelihood_score": reversal_score,
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
