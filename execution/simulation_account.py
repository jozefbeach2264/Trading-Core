import logging
import json
import os
from typing import Dict, Any

from config.config import Config

logger = logging.getLogger(__name__)

class SimulationAccount:
    """
    Manages a persistent, simulated trading account for paper trading.
    - Uses a JSON file to save progress between sessions.
    - Starts with $10 capital.
    - Auto-replenishes to $10 if balance is depleted.
    - Does NOT store its own leverage; uses the global leverage passed from ExecutionModule.
    """
    def __init__(self, config: Config):
        self.config = config
        self.state_file_path = self.config.simulation_state_file_path
        self.balance: float = self.config.simulation_initial_capital
        self.open_positions: Dict[str, Any] = {}
        self._load_state() # Load previous state or initialize

    def _load_state(self):
        """Loads the account state from a file, or initializes it if not found."""
        if os.path.exists(self.state_file_path):
            try:
                with open(self.state_file_path, 'r') as f:
                    state = json.load(f)
                    self.balance = float(state.get("balance", self.config.simulation_initial_capital))

                # As per your requirement, replenish if balance is zero or less.
                if self.balance <= 0:
                    logger.warning("Simulation balance was at or below zero. Replenishing to $10.")
                    self.balance = self.config.simulation_initial_capital
                    self._save_state()

                logger.info(f"SimulationAccount state loaded. Current Balance: ${self.balance:.2f}")

            except (json.JSONDecodeError, TypeError) as e:
                logger.error(f"Could not read simulation state file, initializing with default: {e}")
                self._save_state()
        else:
            logger.info(f"No simulation state file found. Initializing with ${self.balance:.2f} capital.")
            self._save_state()

    def _save_state(self):
        """Saves the current account balance to the state file."""
        try:
            # FIX: Ensure the directory exists before writing to the file.
            os.makedirs(os.path.dirname(self.state_file_path), exist_ok=True)
            with open(self.state_file_path, 'w') as f:
                json.dump({"balance": self.balance}, f, indent=4)
        except IOError as e:
            logger.error(f"Could not save simulation state to file: {e}")

    def get_balance(self) -> float:
        return self.balance

    def open_trade(self, trade_id: str, symbol: str, direction: str, size: float, entry_price: float):
        self.open_positions[trade_id] = {"direction": direction, "size": size, "entry_price": entry_price}
        logger.info(f"SIMULATED: Opened {direction} trade {trade_id} for {size} {symbol} at ${entry_price:.2f}")

    def close_trade(self, trade_id: str, exit_price: float, leverage: int) -> float:
        """Closes a trade and calculates PnL using the provided leverage."""
        position = self.open_positions.pop(trade_id, None)
        if not position: return 0.0

        pnl_per_unit = exit_price - position['entry_price']
        if position['direction'] == 'SHORT':
            pnl_per_unit = -pnl_per_unit

        total_pnl = pnl_per_unit * position['size'] * leverage
        self.balance += total_pnl

        logger.info(f"SIMULATED: Closed trade {trade_id} at ${exit_price:.2f} with {leverage}x leverage. PnL: ${total_pnl:.2f}. New Balance: ${self.balance:.2f}")
        self._save_state() # Save progress after every trade
        return total_pnl