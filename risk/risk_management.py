import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class CapitalManager:
    """
    Manages capital allocation and risk per trade.
    This module ensures that no single trade exceeds the defined risk parameters.
    """
    def __init__(self, config: Any):
        """
        Initializes the CapitalManager with configuration.
        
        Args:
            config (Any): The main application configuration object.
        """
        self.config = config
        logger.info("CapitalManager initialized.")

    def calculate_trade_size(self, total_capital: float) -> float:
        """
        Calculates the amount of capital to be used for a single trade
        based on the risk_cap_percent parameter.

        Args:
            total_capital (float): The total available capital in the account.

        Returns:
            float: The calculated capital amount for the next trade.
        """
        trade_size = total_capital * self.config.risk_cap_percent
        logger.info(f"Calculated trade size: {trade_size:.2f} based on risk cap of {self.config.risk_cap_percent:%}")
        return trade_size

    def validate_liquidation_risk(self, entry_price: float, liquidation_price: float) -> bool:
        """
        Validates if a potential trade setup is within the acceptable liquidation threshold.

        Args:
            entry_price (float): The potential entry price of the trade.
            liquidation_price (float): The estimated liquidation price.

        Returns:
            bool: True if the risk is acceptable, False otherwise.
        """
        distance_to_liquidation = abs(entry_price - liquidation_price)
        
        if distance_to_liquidation > self.config.max_liquidation_threshold:
            logger.warning(
                f"Liquidation risk validation FAILED. "
                f"Distance (${distance_to_liquidation:.2f}) exceeds threshold "
                f"(${self.config.max_liquidation_threshold:.2f})."
            )
            return False
            
        logger.info("Liquidation risk validation PASSED.")
        return True

