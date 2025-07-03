import logging
from config.config import Config

logger = logging.getLogger(__name__)

class CapitalManager:
    """
    Manages capital allocation and calculates trade size based on risk parameters.
    """
    def __init__(self, config: Config):
        self.config = config
        logger.info("CapitalManager initialized.")

    def calculate_trade_size(self, current_balance: float, entry_price: float) -> float:
        """
        Calculates the position size in terms of the base asset (e.g., ETH).
        
        Logic is based on the "Capital per Trade" (risk_cap_percent) variable
        from your Variable_Adjustments.txt document.
        """
        if entry_price <= 0:
            logger.error("Cannot calculate trade size: entry_price must be positive.")
            return 0.0

        # Calculate the dollar amount to risk based on the percentage from config
        capital_to_risk = current_balance * (self.config.risk_cap_percent / 100.0)
        
        # Convert the dollar amount to asset size
        size_in_asset = capital_to_risk / entry_price
        
        logger.info(f"Calculated trade size: {size_in_asset:.4f} ETH based on risk cap of {self.config.risk_cap_percent}%")
        return size_in_asset
