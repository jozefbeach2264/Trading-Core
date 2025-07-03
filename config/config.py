import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    def __init__(self):
        # === Credentials & API Keys ===
        self.asterdex_api_key: str = os.getenv("ASTERDEX_API_KEY")
        self.asterdex_api_secret: str = os.getenv("ASTERDEX_API_SECRET")
        self.ai_provider_url: str = os.getenv("AI_PROVIDER_URL")
        self.ai_provider_api_key: str = os.getenv("AI_PROVIDER_API_KEY")

        # === Inter-Service Communication ===
        self.neurosync_volume_data_url: str = os.getenv("NEUROSYNC_VOLUME_DATA_URL")
        self.rolling5_alert_url: str = os.getenv("ROLLING5_ALERT_URL")
        self.tradingcore_url: str = os.getenv("TRADINGCORE_URL")
        self.neurosync_url: str = os.getenv("NEUROSYNC_URL")
        self.rolling5_url: str = os.getenv("ROLLING5_URL")

        # === Core Trading & Risk Parameters ===
        self.symbol: str = os.getenv("TRADING_SYMBOL", "ETHUSDT")
        self.leverage: int = int(os.getenv('LEVERAGE', '250'))
        self.risk_cap_percent: float = float(os.getenv('RISK_CAP_PERCENT', '0.25'))
        self.max_liquidation_threshold: float = float(os.getenv('MAX_LIQUIDATION_THRESHOLD', '10.00'))
        self.exchange_fee_rate_taker: float = float(os.getenv('EXCHANGE_FEE_RATE_TAKER', '0.08'))
        self.max_roi_limit: float = float(os.getenv('MAX_ROI_LIMIT', '0'))

        # === Guardian & Filter Parameters ===
        self.use_time_filter: bool = os.getenv('USE_TIME_OF_DAY_FILTER', 'True').lower() == 'true'
        self.trading_start_hour: int = int(os.getenv('TRADING_START_HOUR', '0')) # Hour in UTC (0-23)
        self.trading_end_hour: int = int(os.getenv('TRADING_END_HOUR', '23'))   # Hour in UTC (0-23)

        # === Operational & Module Parameters ===
        self.dry_run_mode: bool = os.getenv('DRY_RUN_MODE', 'True').lower() == 'true'
        self.kline_deque_maxlen: int = int(os.getenv('KLINE_DEQUE_MAXLEN', '500'))
        self.ai_client_timeout: int = int(os.getenv('AI_CLIENT_TIMEOUT', '15'))

        # === Toggles ===
        self.live_print_headers: bool = os.getenv('LIVE_PRINT_HEADERS', 'True').lower() == 'true'
        self.success_rate_tracking: bool = os.getenv('SUCCESS_RATE_TRACKING', 'True').lower() == 'true'

        # === File Paths ===
        self.log_file_path: str = os.getenv("LOG_FILE_PATH", "./logs/system.log")
        self.simulation_state_file_path: str = os.getenv("SIMULATION_STATE_FILE_PATH", "./simulation_state.json")

        # === Simulation Only Parameters ===
        self.simulation_initial_capital: float = float(os.getenv("SIMULATION_INITIAL_CAPITAL", "10.00"))

config = Config()
