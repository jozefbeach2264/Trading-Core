import logging
from typing import Dict, Any, Tuple
from config.config import Config

logger = logging.getLogger(__name__)

class EntryRangeSimulator:
    """
    A fail-safe module that simulates the potential adverse move of a trade
    to check against the maximum liquidation risk before entry.
    """
    def __init__(self, config: Config):
        self.config = config
        self.liquidation_risk_threshold = self.config.max_liquidation_threshold
        logger.info(
            f"EntryRangeSimulator initialized with a max liquidation risk threshold of ${self.liquidation_risk_threshold:.2f}"
        )

    def check_liquidation_risk(
        self,
        entry_price: float,
        trade_direction: str,
        forecast_data: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """
        Projects the potential pullback based on the C1-C2 forecast and checks
        if it violates the maximum liquidation threshold.

        Returns:
            A tuple containing a boolean (True if safe, False if risk too high)
            and a reason string.
        """
        forecast = forecast_data.get("forecast", {})
        
        if not forecast or "c1" not in forecast or "c2" not in forecast:
            return False, "Liquidation risk check failed: Missing C1/C2 forecast data."

        try:
            # Correctly parse the high/low values from the new forecast structure
            projected_c1_low = forecast["c1"]["low"]
            projected_c2_low = forecast["c2"]["low"]
            projected_c1_high = forecast["c1"]["high"]
            projected_c2_high = forecast["c2"]["high"]
        except KeyError as e:
            return False, f"Liquidation risk check failed: Forecast data has incorrect structure. Missing key: {e}"

        risk_move = 0.0

        if trade_direction.upper() == "LONG":
            # For a LONG trade, the risk is the lowest projected price in the near-term forecast
            projected_pullback_price = min(projected_c1_low, projected_c2_low)
            risk_move = entry_price - projected_pullback_price
        elif trade_direction.upper() == "SHORT":
            # For a SHORT trade, the risk is the highest projected price in the near-term forecast
            projected_spike_price = max(projected_c1_high, projected_c2_high)
            risk_move = projected_spike_price - entry_price
        else:
            return False, f"Invalid trade direction '{trade_direction}' for risk check."

        if risk_move < 0:
            # A negative risk_move means the forecast is entirely favorable, so there's no projected adverse move.
            risk_move = 0.0

        if risk_move >= self.liquidation_risk_threshold:
            reason = (
                f"Trade blocked. Projected adverse move of ${risk_move:.2f} "
                f"exceeds the liquidation risk threshold of ${self.liquidation_risk_threshold:.2f}."
            )
            logger.warning(reason)
            return False, reason

        reason = (
            f"Trade passed liquidation risk check. "
            f"Projected adverse move: ${risk_move:.2f}."
        )
        logger.debug(reason)
        return True, reason

