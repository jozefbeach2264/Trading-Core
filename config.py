import os
import logging
from dotenv import load_dotenv

# Load environment variables from a .env file or Replit Secrets
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger(__name__)

class Config:
    """
    Manages all configuration for the TradingCore application.
    It loads settings from environment variables and provides them with sensible defaults.
    """
    def __init__(self):
        logger.info("Initializing TradingCore configuration...")

        # --- Primary Parameters – Core Logic Control ---
        self.use_trade_window: bool = os.getenv('USE_TRADE_WINDOW', 'True').lower() == 'true'
        self.leverage: int = int(os.getenv('LEVERAGE', '250'))
        self.risk_cap_percent: float = float(os.getenv('RISK_CAP_PERCENT', '0.25'))
        self.max_liquidation_threshold: float = float(os.getenv('MAX_LIQUIDATION_THRESHOLD', '10.00'))
        self.exchange_fee_rate_taker: float = float(os.getenv('EXCHANGE_FEE_RATE_TAKER', '0.08'))
        self.max_roi_limit: float = float(os.getenv('MAX_ROI_LIMIT', '0'))

        # --- Auxiliary Parameters – Logging, Tracking, & Recovery ---
        self.log_file_path: str = os.getenv('LOG_FILE_PATH', './logs/trades.log')
        self.live_print_headers: bool = os.getenv('LIVE_PRINT_HEADERS', 'True').lower() == 'true'
        self.success_rate_tracking: bool = os.getenv('SUCCESS_RATE_TRACKING', 'True').lower() == 'true'
        
        # --- Inter-Service Communication ---
        self.neurosync_volume_data_url: str = os.getenv("NEUROSYNC_VOLUME_DATA_URL")
        # NEW: URL for sending alerts to the Rolling5 bot
        self.rolling5_alert_url: str = os.getenv("ROLLING5_ALERT_URL")

        self._validate_parameters()
        logger.info("TradingCore configuration loaded successfully.")

    def _validate_parameters(self):
        """Performs basic validation on the loaded parameters."""
        # ... (validation logic remains the same)
