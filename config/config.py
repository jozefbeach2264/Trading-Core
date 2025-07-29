import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    def __init__(self):
        # Credentials & API Keys
        self.asterdex_api_key: str = os.getenv("ASTERDEX_API_KEY")
        self.asterdex_api_secret: str = os.getenv("ASTERDEX_API_SECRET")
        self.xai_api_key: str = os.getenv("XAI_API_KEY")
        self.ai_provider_url: str = os.getenv("AI_PROVIDER_URL", "https://api.x.ai/v1")

        # System & Operational Parameters
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO")
        self.trading_symbol: str = os.getenv("TRADING_SYMBOL", "ETH-USDT-SWAP")
        self.adex_symbol: str = os.getenv("ADEX_SYMBOL", "ETHUSDT")
        self.dry_run_mode: bool = os.getenv('DRY_RUN_MODE', 'True').lower() == 'true'
        self.kline_deque_maxlen: int = int(os.getenv('KLINE_DEQUE_MAXLEN', '500'))
        self.ai_client_timeout: int = int(os.getenv('AI_CLIENT_TIMEOUT', '20'))
        self.engine_cycle_interval: int = int(os.getenv('ENGINE_CYCLE_INTERVAL', '15'))
        self.tlm_poll_interval_seconds: int = int(os.getenv("TLM_POLL_INTERVAL_SECONDS", "5"))

        # Core Trading & Risk Parameters
        self.leverage: int = int(os.getenv('LEVERAGE', '250'))
        self.risk_cap_percent: float = float(os.getenv('RISK_CAP_PERCENT', '0.25'))
        self.max_liquidation_threshold: float = float(os.getenv('MAX_LIQUIDATION_THRESHOLD', '3.50'))
        self.exchange_fee_rate_taker: float = float(os.getenv('EXCHANGE_FEE_RATE_TAKER', '0.08'))
        self.max_roi_limit: float = float(os.getenv('MAX_ROI_LIMIT', '0'))
        self.simulation_initial_capital: float = float(os.getenv("SIMULATION_INITIAL_CAPITAL", "10.00"))

        # Autonomous Mode & Time Filter
        self.autonomous_mode_enabled: bool = os.getenv('AUTONOMOUS_MODE_ENABLED', 'True').lower() == 'true'
        self.allowed_windows: str = os.getenv('ALLOWED_WINDOWS', '00:00-23:59')

        # Filter Parameters
        self.cts_lookback_period: int = int(os.getenv('CTS_LOOKBACK_PERIOD', '15'))
        self.cts_narrow_range_ratio: float = float(os.getenv('CTS_NARROW_RANGE_RATIO', '0.7'))
        self.cts_wick_rejection_multiplier: float = float(os.getenv('CTS_WICK_REJECTION_MULTIPLIER', '1.5'))
        self.spoof_imbalance_threshold: float = float(os.getenv('SPOOF_IMBALANCE_THRESHOLD', '0.20'))
        self.spoof_distance_percent: float = float(os.getenv('SPOOF_DISTANCE_PERCENT', '1.5'))
        self.spoof_large_order_multiplier: int = int(os.getenv('SPOOF_LARGE_ORDER_MULTIPLIER', '5'))
        self.compression_lookback_period: int = int(os.getenv('COMPRESSION_LOOKBACK_PERIOD', '10'))
        self.compression_range_ratio: float = float(os.getenv('COMPRESSION_RANGE_RATIO', '0.8'))
        self.breakout_zone_lookback: int = int(os.getenv('BREAKOUT_ZONE_LOOKBACK', '30'))
        self.breakout_zone_volatility_ratio: float = float(os.getenv('BREAKOUT_ZONE_VOLATILITY_RATIO', '0.5'))
        self.retest_lookback: int = int(os.getenv('RETEST_LOOKBACK', '15'))
        self.retest_proximity_percent: float = float(os.getenv('RETEST_PROXIMITY_PERCENT', '0.2'))
        self.low_volume_lookback: int = int(os.getenv('LOW_VOLUME_LOOKBACK', '15'))
        self.low_volume_ratio: float = float(os.getenv('LOW_VOLUME_RATIO', '0.7'))
        self.low_volume_min_threshold: float = float(os.getenv('LOW_VOLUME_MIN_THRESHOLD', '15000'))
        self.sentiment_divergence_lookback: int = int(os.getenv('SENTIMENT_DIVERGENCE_LOOKBACK', '20'))
        self.min_cvd_threshold: float = float(os.getenv('MIN_CVD_THRESHOLD', '5000.0'))
        self.orderbook_reversal_depth_percent: float = float(os.getenv('ORDERBOOK_REVERSAL_DEPTH_PERCENT', '0.3'))
        self.orderbook_reversal_wall_multiplier: float = float(os.getenv('ORDERBOOK_REVERSAL_WALL_MULTIPLIER', '2.0'))

        # AI Parameters
        self.ai_confidence_threshold: float = float(os.getenv('AI_CONFIDENCE_THRESHOLD', '0.7'))

        # Toggles & UI
        self.live_print_headers: bool = os.getenv('LIVE_PRINT_HEADERS', 'True').lower() == 'true'

        # File & Log Paths
        self.log_file_path: str = os.getenv("LOG_FILE_PATH", "./logs/system.log")
        self.simulation_state_file_path: str = os.getenv("SIMULATION_STATE_FILE_PATH", "./logs/simulation_state.json")
        self.failed_signals_path: str = os.getenv("FAILED_SIGNALS_PATH", "./logs/failed_signals.json")
        self.cts_filter_log_path: str = os.getenv("CTS_FILTER_LOG_PATH", "./logs/filters/cts_filter.log")
        self.spoof_filter_log_path: str = os.getenv("SPOOF_FILTER_LOG_PATH", "./logs/filters/spoof_filter.log")
        self.compression_detector_log_path: str = os.getenv("COMPRESSION_DETECTOR_LOG_PATH", "./logs/filters/compression_detector.log")
        self.breakout_filter_log_path: str = os.getenv("BREAKOUT_FILTER_LOG_PATH", "./logs/filters/breakout_filter.log")
        self.retest_logic_log_path: str = os.getenv("RETEST_LOGIC_LOG_PATH", "./logs/filters/retest_logic.log")
        self.low_volume_guard_log_path: str = os.getenv("LOW_VOLUME_GUARD_LOG_PATH", "./logs/filters/low_volume_guard.log")
        self.sentiment_filter_log_path: str = os.getenv("SENTIMENT_FILTER_LOG_PATH", "./logs/filters/sentiment_filter.log")
        self.orderbook_reversal_log_path: str = os.getenv("ORDERBOOK_REVERSAL_LOG_PATH", "./logs/filters/orderbook_reversal.log")
        self.ai_strategy_log_path: str = os.getenv("AI_STRATEGY_LOG_PATH", "./logs/ai_strategy.log")
        self.diagnostics_log_path: str = os.getenv("DIAGNOSTICS_LOG_PATH", "./logs/diagnostics.log")