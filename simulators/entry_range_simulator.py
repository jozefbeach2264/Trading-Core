import logging
from typing import Dict, Any, Tuple
from config.config import Config
import statistics

logger = logging.getLogger(__name__)

class EntryRangeSimulator:
                            """
                            A fail-safe module that simulates potential adverse trade moves using probabilistic
                            risk assessment based on forecast, ATR, and historical retrace data, ensuring realistic
                            risk estimates while checking against the liquidation threshold.
                            """
                            def __init__(self, config: Config):
                                self.config = config
                                self.liquidation_risk_threshold = self.config.max_liquidation_threshold
                                self.atr_multiplier = getattr(getattr(self.config, 'risk_management', {}), 'atr_multiplier', 2.5)
                                self.max_risk_as_atr_multiple = getattr(getattr(self.config, 'risk_management', {}), 'max_risk_as_atr_multiple', 5.0)
                                self.max_forecast_range = 10.0  # Hard limit: ±$10 from entry price
                                logger.info(
                                    f"EntryRangeSimulator initialized with max liquidation risk threshold of ${self.liquidation_risk_threshold:.2f}, "
                                    f"ATR multiplier of {self.atr_multiplier}x, max risk cap of {self.max_risk_as_atr_multiple}x ATR, "
                                    f"and max forecast range of ±${self.max_forecast_range}."
                                )

                            def _calculate_historical_retrace(self, forecast_data: Dict[str, Any]) -> float:
                                """Calculates average historical retrace from recent candles in forecast_data."""
                                forecast = forecast_data.get("forecast", {})
                                retraces = []
                                for candle in forecast.values():
                                    if "high" in candle and "low" in candle:
                                        retrace = abs(candle["high"] - candle["low"])
                                        retraces.append(retrace)
                                return statistics.mean(retraces) if retraces else self.max_forecast_range

                            def check_liquidation_risk(
                                self,
                                entry_price: float,
                                trade_direction: str,
                                forecast_data: Dict[str, Any],
                                atr_value: float = None  # Optional ATR value
                            ) -> Tuple[bool, str]:
                                """
                                Projects potential adverse move using a probabilistic model combining forecast,
                                ATR, and historical retrace data, weighted by reversal likelihood. Caps risk at
                                ±$10 and ATR-based limits, ensuring realistic estimates.

                                Args:
                                    entry_price: The trade entry price.
                                    trade_direction: 'LONG' or 'SHORT'.
                                    forecast_data: Dictionary containing forecast and reversal_likelihood_score.
                                    atr_value: Optional ATR value for volatility-based risk.

                                Returns:
                                    Tuple[bool, str]: (True if safe, False if risk too high, reason string).
                                """
                                forecast = forecast_data.get("forecast", {})
                                reversal_likelihood = forecast_data.get("reversal_likelihood_score", 0.5)  # Default to 0.5
                                logger.warning(f"[DEBUG] Forecast received: {forecast}")
                                logger.warning(f"[DEBUG] Entry Price: {entry_price:.2f}, Direction: {trade_direction}, "
                                              f"ATR: {atr_value if atr_value is not None else 'Not provided'}, "
                                              f"Reversal Likelihood: {reversal_likelihood:.2f}")

                                # --- Forecast-based Risk Calculation ---
                                forecast_risk_move = 0.0
                                if not forecast or "c1" not in forecast or "c2" not in forecast:
                                    logger.warning("Missing C1/C2 forecast data. Using historical retrace or ATR.")
                                else:
                                    try:
                                        if trade_direction.upper() == "LONG":
                                            projected_pullback_price = min(forecast["c1"]["low"], forecast["c2"]["low"])
                                            forecast_risk_move = entry_price - projected_pullback_price
                                        elif trade_direction.upper() == "SHORT":
                                            projected_spike_price = max(forecast["c1"]["high"], forecast["c2"]["high"])
                                            forecast_risk_move = projected_spike_price - entry_price
                                        # Weight by reversal likelihood to reduce risk when retrace is unlikely
                                        forecast_risk_move *= reversal_likelihood
                                        if abs(forecast_risk_move) > self.max_forecast_range:
                                            forecast_risk_move = self.max_forecast_range if forecast_risk_move > 0 else -self.max_forecast_range
                                            logger.warning(f"Forecast risk capped at ±${self.max_forecast_range} for {trade_direction}.")
                                    except KeyError as e:
                                        return False, f"Liquidation risk check failed: Forecast data has incorrect structure. Missing key: {e}"

                                # --- ATR-based Risk Calculation ---
                                atr_risk_move = 0.0
                                if atr_value is not None:
                                    atr_risk_move = self.atr_multiplier * atr_value * reversal_likelihood
                                else:
                                    logger.warning("ATR value not provided. Using historical retrace or max forecast range.")
                                    atr_risk_move = self.max_forecast_range * reversal_likelihood

                                # --- Historical Retrace Calculation ---
                                historical_risk_move = self._calculate_historical_retrace(forecast_data) * reversal_likelihood

                                # --- Final Risk Assessment ---
                                # Use weighted average: 50% forecast, 30% historical, 20% ATR
                                weights = [0.5, 0.3, 0.2]
                                risk_moves = [forecast_risk_move, historical_risk_move, atr_risk_move]
                                valid_risks = [r for r in risk_moves if r != 0.0]
                                if valid_risks:
                                    final_risk_move = sum(w * r for w, r in zip(weights[:len(valid_risks)], valid_risks)) / sum(weights[:len(valid_risks)])
                                else:
                                    final_risk_move = self.max_forecast_range * reversal_likelihood
                                    logger.warning("No valid risk moves. Using capped default risk.")

                                # --- Dynamic Hard Limit Sanity Check ---
                                dynamic_hard_limit = self.max_risk_as_atr_multiple * atr_value if atr_value is not None else self.max_forecast_range
                                if abs(final_risk_move) > dynamic_hard_limit:
                                    logger.warning(
                                        f"Calculated risk (${abs(final_risk_move):.2f}) exceeded dynamic hard limit (${dynamic_hard_limit:.2f}). "
                                        f"Risk capped at limit."
                                    )
                                    final_risk_move = dynamic_hard_limit if final_risk_move > 0 else -dynamic_hard_limit

                                if final_risk_move < 0:
                                    final_risk_move = 0.0

                                if final_risk_move >= self.liquidation_risk_threshold:
                                    reason = (
                                        f"Trade blocked. Projected adverse move of ${final_risk_move:.2f} "
                                        f"(Forecast: ${forecast_risk_move:.2f}, Historical: ${historical_risk_move:.2f}, "
                                        f"ATR: ${atr_risk_move:.2f}, Reversal Likelihood: {reversal_likelihood:.2f}) "
                                        f"exceeds the liquidation risk threshold of ${self.liquidation_risk_threshold:.2f}."
                                    )
                                    logger.warning(reason)
                                    return False, reason

                                reason = (
                                    f"Trade passed liquidation risk check. "
                                    f"Projected adverse move: ${final_risk_move:.2f}."
                                )
                                logger.debug(reason)
                                return True, reason