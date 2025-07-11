import os
import logging  # Added for log_level
from dotenv import load_dotenv

load_dotenv()

class Config:
    def __init__(self):
        # === Credentials & API Keys ===
        self.asterdex_api_key: str = os.getenv("ASTERDEX_API_KEY")
        self.asterdex_api_secret: str = os.getenv("ASTERDEX_API_SECRET")
        self.ai_provider_url: str = os.getenv("AI_PROVIDER_URL")
        self.xai_api_key: str = os.getenv("XAI_API_KEY")

        # === Inter-Service Communication ===
        self.neurosync_volume_data_url: str = os.getenv("NEUROSYNC_VOLUME_DATA_URL")
        self.rolling5_alert_url: str = os.getenv("ROLLING5_ALERT_URL")
        self.tradingcore_url: str = os.getenv("TRADINGCORE_URL")
        self.neurosync_url: str = os.getenv("NEUROSYNC_URL")
        self.rolling5_url: str = os.getenv("ROLLING5_URL")

        # === Core Trading & Risk Parameters ===
        self.symbol: str = os.getenv("TRADING_SYMBOL", "ETH")
        self.leverage: int = int(os.getenv('LEVERAGE', '250'))
        self.risk_cap_percent: float = float(os.getenv('RISK_CAP_PERCENT', '0.25'))
        self.max_liquidation_threshold: float = float(os.getenv('MAX_LIQUIDATION_THRESHOLD', '10.00'))
        self.exchange_fee_rate_taker: float = float(os.getenv('EXCHANGE_FEE_RATE_TAKER', '0.08'))
        self.max_roi_limit: float = float(os.getenv('MAX_ROI_LIMIT', '0'))

        # === Autonomous Mode ===
        self.autonomous_mode_enabled: bool = os.getenv('AUTONOMOUS_MODE_ENABLED', 'False').lower() == 'true'
        self.trade_windows: str = os.getenv('TRADE_WINDOWS', '0-23')

        # === CTS Filter Parameters ===
        self.cts_lookback_period: int = int(os.getenv('CTS_LOOKBACK_PERIOD', '15'))
        self.cts_narrow_range_ratio: float = float(os.getenv('CTS_NARROW_RANGE_RATIO', '0.7'))
        self.cts_wick_rejection_multiplier: float = float(os.getenv('CTS_WICK_REJECTION_MULTIPLIER', '1.5'))

        # === Spoof Filter Parameters ===
        self.spoof_imbalance_threshold: float = float(os.getenv('SPOOF_IMBALANCE_THRESHOLD', '0.20'))
        self.spoof_distance_percent: float = float(os.getenv('SPOOF_DISTANCE_PERCENT', '1.5'))
        self.spoof_large_order_multiplier: float = float(os.getenv('SPOOF_LARGE_ORDER_MULTIPLIER', '5.0'))

        # === Compression Detector Parameters ===
        self.compression_lookback_period: int = int(os.getenv('COMPRESSION_LOOKBACK_PERIOD', '10'))
        self.compression_range_ratio: float = float(os.getenv('COMPRESSION_RANGE_RATIO', '0.9'))

        # === Breakout Zone Origin Filter Parameters ===
        self.breakout_zone_lookback: int = int(os.getenv('BREAKOUT_ZONE_LOOKBACK', '30'))
        self.breakout_zone_volatility_ratio: float = float(os.getenv('BREAKOUT_ZONE_VOLATILITY_RATIO', '0.4'))

        # === Retest Entry Logic Parameters ===
        self.retest_lookback: int = int(os.getenv('RETEST_LOOKBACK', '15'))
        self.retest_proximity_percent: float = float(os.getenv('RETEST_PROXIMITY_PERCENT', '0.2'))

        # === Low Volume Guard Parameters ===
        self.low_volume_lookback: int = int(os.getenv('LOW_VOLUME_LOOKBACK', '15'))
        self.low_volume_ratio: float = float(os.getenv('LOW_VOLUME_RATIO', '0.7'))

        # === Sentiment Divergence Filter Parameters ===
        self.sentiment_divergence_lookback: int = int(os.getenv('SENTIMENT_DIVERGENCE_LOOKBACK', '20'))

        # === OrderBook Reversal Zone Detector Parameters ===
        self.orderbook_reversal_depth_percent: float = float(os.getenv('ORDERBOOK_REVERSAL_DEPTH_PERCENT', '0.3'))
        self.orderbook_reversal_wall_multiplier: float = float(os.getenv('ORDERBOOK_REVERSAL_WALL_MULTIPLIER', '2.0'))

        # === Guardian & Filter Parameters ===
        self.use_time_of_day_filter: bool = os.getenv('USE_TIME_OF_DAY_FILTER', 'False').lower() == 'true'
        self.trading_start_hour: int = int(os.getenv('TRADING_START_HOUR', '0'))
        self.trading_end_hour: int = int(os.getenv('TRADING_END_HOUR', '23'))

        # === Operational & Module Parameters ===
        self.dry_run_mode: bool = os.getenv('DRY_RUN_MODE', 'True').lower() == 'true'
        self.kline_deque_maxlen: int = int(os.getenv('KLINE_DEQUE_MAXLEN', '500'))
        self.ai_client_timeout: int = int(os.getenv('AI_CLIENT_TIMEOUT', '20'))

        # === Toggles ===
        self.live_print_headers: bool = os.getenv('LIVE_PRINT_HEADERS', 'True').lower() == 'true'
        self.success_rate_tracking: bool = os.getenv('SUCCESS_RATE_TRACKING', 'True').lower() == 'true'

        # === File Paths ===
        self.log_file_path: str = os.getenv("LOG_FILE_PATH", "./logs/system.log")
        self.simulation_state_file_path: str = os.getenv("SIMULATION_STATE_FILE_PATH", "./simulation_state.json")

        # === Module Log Paths ===
        self.cts_filter_log_path: str = os.getenv("CTS_FILTER_LOG_PATH", "./logs/cts_filter.log")
        self.spoof_filter_log_path: str = os.getenv("SPOOF_FILTER_LOG_PATH", "./logs/spoof_filter.log")
        self.compression_detector_log_path: str = os.getenv("COMPRESSION_DETECTOR_LOG_PATH", "./logs/compression_detector.log")
        self.breakout_filter_log_path: str = os.getenv("BREAKOUT_FILTER_LOG_PATH", "./logs/breakout_filter.log")
        self.retest_logic_log_path: str = os.getenv("RETEST_LOGIC_LOG_PATH", "./logs/retest_logic.log")
        self.low_volume_guard_log_path: str = os.getenv("LOW_VOLUME_GUARD_LOG_PATH", "./logs/low_volume_guard.log")
        self.sentiment_filter_log_path: str = os.getenv("SENTIMENT_FILTER_LOG_PATH", "./logs/sentiment_filter.log")
        self.orderbook_reversal_log_path: str = os.getenv("ORDERBOOK_REVERSAL_LOG_PATH", "./logs/orderbook_reversal.log")

        # === Simulation Only Parameters ===
        self.simulation_initial_capital: float = float(os.getenv("SIMULATION_INITIAL_CAPITAL", "10.00"))

        # === Logging Level === (New addition)
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO")
        logging.getLogger().setLevel(logging.getLevelName(self.log_level))

config = Config()