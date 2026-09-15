import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

class Config:
    def __init__(self):
        # Credentials & API Keys
        self.asterdex_api_key: str = os.getenv("ASTERDEX_API_KEY")
        self.asterdex_api_secret: str = os.getenv("ASTERDEX_API_SECRET")
        # AI verdict provider: any OpenAI-compatible chat-completions endpoint.
        # Default = local llama-server (llm-serve <profile>) — Grok/xAI was retired 2026-09-15.
        self.ai_provider_url: str = os.getenv("AI_PROVIDER_URL", "http://127.0.0.1:8081/v1").rstrip("/")
        self.ai_api_key: str = os.getenv("AI_API_KEY") or os.getenv("XAI_API_KEY") or ""
        self.ai_model: str = os.getenv("AI_MODEL", "local")
        self.okx_base_url: str = os.getenv("OKX_BASE_URL", "https://www.okx.com")
        self.asterdex_base_url: str = os.getenv("ASTERDEX_BASE_URL", "https://fapi.asterdex.com")
        self.okx_ws_url: str = os.getenv("OKX_WS_URL", "wss://ws.okx.com:8443/ws/v5/public")
        
        # System & Operational Parameters
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO")
        self.trading_symbol: str = os.getenv("TRADING_SYMBOL", "ETH-USDT-SWAP")
        self.adex_symbol: str = os.getenv("ADEX_SYMBOL", "ETHUSDT")
        self.dry_run_mode: bool = os.getenv('DRY_RUN_MODE', 'True').lower() == 'true'
        self.kline_deque_maxlen: int = int(os.getenv('KLINE_DEQUE_MAXLEN', '500'))
        self.ai_client_timeout: float = float(os.getenv('AI_CLIENT_TIMEOUT', '10'))
        self.engine_cycle_interval: float = float(os.getenv('ENGINE_CYCLE_INTERVAL', '0.2'))

        # Core Trading & Risk Parameters
        self.leverage: int = int(os.getenv('LEVERAGE', '200'))
        self.risk_cap_percent: float = float(os.getenv('RISK_CAP_PERCENT', '0.25'))
        self.max_liquidation_threshold: float = float(os.getenv('MAX_LIQUIDATION_THRESHOLD', '8.0'))
        self.exchange_fee_rate_taker: float = float(os.getenv('EXCHANGE_FEE_RATE_TAKER', '0.08'))
        self.max_roi_limit: float = float(os.getenv('MAX_ROI_LIMIT', '0'))
        self.simulation_initial_capital: float = float(os.getenv("SIMULATION_INITIAL_CAPITAL", "10.00"))
        
        # Autonomous Mode & Time Filter
        self.autonomous_mode_enabled: bool = os.getenv('AUTONOMOUS_MODE_ENABLED', 'True').lower() == 'true'
        self.allowed_windows: str = os.getenv('ALLOWED_WINDOWS', '00:00-23:59')
        
        # Filter Parameters
        self.cts_lookback_period: int = int(os.getenv('CTS_LOOKBACK_PERIOD', '15'))
        self.cts_narrow_range_ratio: float = float(os.getenv('CTS_NARROW_RANGE_RATIO', '0.8'))
        self.cts_wick_rejection_multiplier: float = float(os.getenv('CTS_WICK_REJECTION_MULTIPLIER', '1.2'))
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
        # Notional threshold (in quote currency, e.g., USDT) for volume guard
        self.low_volume_min_notional: float = float(os.getenv('LOW_VOLUME_MIN_NOTIONAL', '2000'))
        self.sentiment_divergence_lookback: int = int(os.getenv('SENTIMENT_DIVERGENCE_LOOKBACK', '20'))
        self.min_cvd_threshold: float = float(os.getenv('MIN_CVD_THRESHOLD', '5000.0'))
        self.orderbook_reversal_depth_percent: float = float(os.getenv('ORDERBOOK_REVERSAL_DEPTH_PERCENT', '0.3'))
        self.orderbook_reversal_wall_multiplier: float = float(os.getenv('ORDERBOOK_REVERSAL_WALL_MULTIPLIER', '2.0'))

        # Event-driven triggers (intra-candle vision)
        self.event_volume_spike_threshold: float = float(os.getenv('EVENT_VOLUME_SPIKE_THRESHOLD', '15000'))
        self.event_price_spike_pct_threshold: float = float(os.getenv('EVENT_PRICE_SPIKE_PCT_THRESHOLD', '0.15'))
        self.event_wall_change_pct_threshold: float = float(os.getenv('EVENT_WALL_CHANGE_PCT_THRESHOLD', '50'))
        self.event_spoof_thin_threshold: float = float(os.getenv('EVENT_SPOOF_THIN_THRESHOLD', '20'))
        self.event_wall_abs_change_threshold: float = float(os.getenv('EVENT_WALL_ABS_CHANGE_THRESHOLD', '200'))
        self.event_spoof_delta_threshold: float = float(os.getenv('EVENT_SPOOF_DELTA_THRESHOLD', '5'))
        self.event_queue_max_size: int = int(os.getenv('EVENT_QUEUE_MAX_SIZE', '10'))
        
        # AI Parameters
        self.ai_confidence_threshold: float = float(os.getenv('AI_CONFIDENCE_THRESHOLD', '0.7'))
        # Verdict generation budget. The reasoning string is only logged, so keep it short: fewer
        # tokens = lower latency. Thinking/reasoning modes burn thousands of hidden tokens → off.
        self.ai_max_tokens: int = int(os.getenv('AI_MAX_TOKENS', '160'))
        self.ai_disable_thinking: bool = os.getenv('AI_DISABLE_THINKING', 'True').lower() == 'true'
        self.ai_temperature: float = float(os.getenv('AI_TEMPERATURE', '0.2'))
        # Hard cap on the logged reasoning string, enforced in the JSON grammar. 0 = omit the field.
        self.ai_reasoning_max_chars: int = int(os.getenv('AI_REASONING_MAX_CHARS', '200'))

        # Memory tracker (SQLite). Filter history is write-only data at ~45 rows/s — off by default.
        self.memory_db_path: str = os.getenv("MEMORY_DB_PATH", "./logs/memory_tracker.db")
        self.memory_filter_history: bool = os.getenv('MEMORY_FILTER_HISTORY', 'False').lower() == 'true'

        # Exchange HTTP keep-alive (live mode): ping so the TLS session is warm when an order fires.
        self.exchange_keepalive_seconds: float = float(os.getenv('EXCHANGE_KEEPALIVE_SECONDS', '20'))
        
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
        
        # --- NEW: Dedicated log for AI Strategy ---
        self.ai_strategy_log_path: str = os.getenv("AI_STRATEGY_LOG_PATH", "./logs/ai_strategy.log")

        self._validate()

    def _validate(self):
        # Validate Credentials
        if not self.dry_run_mode:
            if not self.asterdex_api_key or not self.asterdex_api_secret:
                raise ValueError("ASTERDEX_API_KEY and ASTERDEX_API_SECRET must be provided when not in dry run mode.")
        if not self.ai_provider_url:
            raise ValueError("AI_PROVIDER_URL must be set (OpenAI-compatible chat-completions base URL).")

        # Validate Numerical Ranges
        if not 0 < self.risk_cap_percent <= 1.0:
            raise ValueError("RISK_CAP_PERCENT must be between 0 and 1.0.")
        if self.leverage <= 0:
            raise ValueError("LEVERAGE must be a positive integer.")
        if self.ai_client_timeout <= 0:
            raise ValueError("AI_CLIENT_TIMEOUT must be a positive number of seconds.")
        if self.ai_max_tokens <= 0:
            raise ValueError("AI_MAX_TOKENS must be a positive integer.")
        if self.engine_cycle_interval <= 0:
            raise ValueError("ENGINE_CYCLE_INTERVAL must be a positive float.")
        if not 0 <= self.cts_narrow_range_ratio <= 1.0:
            raise ValueError("CTS_NARROW_RANGE_RATIO must be between 0 and 1.0.")
        if not 0 < self.compression_range_ratio <= 1.0:
            raise ValueError("COMPRESSION_RANGE_RATIO must be greater than 0 and at most 1.0.")
        if self.cts_wick_rejection_multiplier < 1.0:
            raise ValueError("CTS_WICK_REJECTION_MULTIPLIER must be >= 1.0.")
        if self.ai_confidence_threshold < 0 or self.ai_confidence_threshold > 1.0:
            raise ValueError("AI_CONFIDENCE_THRESHOLD must be between 0 and 1.0.")
        if self.event_queue_max_size <= 0:
            raise ValueError("EVENT_QUEUE_MAX_SIZE must be a positive integer.")
