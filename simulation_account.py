import logging
import math

logger = logging.getLogger(__name__)

class SimulationAccount:
    """
    Manages a fictional account for dry_run mode.
    It tracks capital, simulates trade PnL, and handles the auto-reset logic.
    """
    def __init__(self, starting_capital: float = 10.0, leverage: int = 250):
        self.starting_capital = starting_capital
        self.leverage = leverage
        self.balance = starting_capital
        self.open_positions = {}
        logger.info(f"SimulationAccount initialized with ${self.balance:.2f} capital and {self.leverage}x leverage.")

    def open_trade(self, trade_id: str, trade_size_usd: float, entry_price: float, direction: str) -> bool:
        """Simulates opening a new trade."""
        if self.balance <= 0:
            logger.warning("Cannot open trade, insufficient balance.")
            return False

        position_size_asset = (trade_size_usd * self.leverage) / entry_price
        
        self.open_positions[trade_id] = {
            "entry_price": entry_price,
            "direction": direction,
            "trade_size_usd": trade_size_usd,
            "position_size_asset": position_size_asset
        }
        logger.info(f"SIM: Opened trade {trade_id}. Position size: {position_size_asset:.4f}")
        return True

    def close_trade(self, trade_id: str, exit_price: float, fee_rate: float) -> float:
        """Simulates closing a trade and calculates the PnL."""
        if trade_id not in self.open_positions:
            logger.error(f"Cannot close trade {trade_id}, not found in open positions.")
            return 0.0

        position = self.open_positions.pop(trade_id)
        
        # Calculate PnL
        if position["direction"] == "LONG":
            price_change = exit_price - position["entry_price"]
        else: # SHORT
            price_change = position["entry_price"] - exit_price
            
        gross_pnl_usd = price_change * position["position_size_asset"]
        
        # Calculate fees
        total_volume = (position["trade_size_usd"] * self.leverage) * 2 # Entry and Exit
        total_fees = total_volume * (fee_rate / 100) # Assuming fee rate is in percent, e.g., 0.08
        
        net_pnl = gross_pnl_usd - total_fees
        
        self.balance += net_pnl
        logger.info(f"SIM: Closed trade {trade_id}. Net PnL: ${net_pnl:.2f}. New balance: ${self.balance:.2f}")

        # Check for auto-reset condition
        if self.balance <= 0:
            logger.warning(f"Simulation account balance depleted. Resetting to ${self.starting_capital:.2f}.")
            self.balance = self.starting_capital
            
        return net_pnl

    def get_balance(self) -> float:
        """Returns the current account balance."""
        return self.balance
