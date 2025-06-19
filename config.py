# config.py
import os
from dotenv import load_dotenv

# This function loads the secrets you set in the "Secrets" tool
load_dotenv()

class Config:
    """A single, consolidated configuration class for the Trading-Core."""
    def __init__(self):
        # --- API Keys for Asterdex Exchange ---
        self.api_key = os.getenv("API_KEY")
        self.secret_key = os.getenv("SECRET_KEY")
        self.uid = os.getenv("UID")
        
        # --- Connection URL for the NeuroSync service ---
        self.neurosync_ws_url = os.getenv("NEUROSYNC_WS_URL", "ws://neurosync.jozefbeach2264.repl.co/ws")
        
        # --- Trading Parameters ---
        self.leverage = int(os.getenv("LEVERAGE", "250"))
        self.initial_capital = float(os.getenv("INITIAL_CAPITAL", "10.0"))
        
        # --- Validate that essential secrets are present ---
        if not all([self.api_key, self.secret_key, self.uid]):
            raise ValueError("API_KEY, SECRET_KEY, and UID must be set in the Secrets tool.")
        else:
            print("Config: Secrets loaded successfully.")

