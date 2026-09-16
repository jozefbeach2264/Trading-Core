"""Shared fixtures. Pins every env var the code under test reads so results do not
depend on the operator's .env, and routes all log/db paths into a temp dir."""
import asyncio
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

TMP = tempfile.mkdtemp(prefix="tradingcore-tests-")
_PINNED_ENV = {
    "DRY_RUN_MODE": "True",
    "AI_PROVIDER_URL": "http://127.0.0.1:9/v1",   # unroutable on purpose
    "AI_API_KEY": "",
    "XAI_API_KEY": "",
    "AI_MODEL": "test-model",
    "AI_CLIENT_TIMEOUT": "1",
    "AI_MAX_TOKENS": "160",
    "AI_DISABLE_THINKING": "True",
    "AI_CONFIDENCE_THRESHOLD": "0.7",
    # guards: pinned so a data-collection .env that relaxes them cannot silently disable these tests
    "MIN_REWARD_FEE_MULTIPLE": "3.0",
    "MIN_STOP_FEE_MULTIPLE": "2.0",
    "MAX_STOP_LIQUIDATION_FRACTION": "0.8",
    "MARGIN_MODE": "cross",
    "MAINTENANCE_MARGIN_PERCENT": "0.5",
    "MAX_TRADE_LOSS_PERCENT": "100.0",
    "SCALPEL_STOP_RANGE_MULTIPLE": "3.0",
    "SCALPEL_TARGET_RANGE_MULTIPLE": "8.0",
    # exit management: pinned so tuning the live .env cannot change what these tests assert
    "TRAIL_BREAKEVEN_R": "0.5",
    "TRAIL_DISTANCE_R": "1.0",
    "TARGET_EXTEND_R": "1.5",
    "EXIT_REVERSAL_RISK": "0.8",
    # fixed-size mode OFF for the suite: the operator's live .env turns it on, and it changes what every
    # sizing and stop test is measuring. The dedicated tests set it on the config object instead.
    "FIXED_MARGIN_USD": "0",
    "MAX_LOSS_USD": "0",
    "RISK_PER_TRADE_PERCENT": "2.0",
    "RISK_CAP_PERCENT": "0.10",
    "LEVERAGE": "200",
    "EXCHANGE_FEE_RATE_TAKER": "0.08",
    "CTS_LOOKBACK_PERIOD": "15",
    "CTS_NARROW_RANGE_RATIO": "0.8",
    "CTS_WICK_REJECTION_MULTIPLIER": "1.2",
    "COMPRESSION_LOOKBACK_PERIOD": "10",
    "COMPRESSION_RANGE_RATIO": "0.8",
    "MEMORY_FILTER_HISTORY": "False",
    "MEMORY_DB_PATH": os.path.join(TMP, "memory_tracker.db"),
    "LOG_FILE_PATH": os.path.join(TMP, "system.log"),
    "AI_MODEL_LOG_PATH": os.path.join(TMP, "ai_model.log"),
    "AI_STRATEGY_LOG_PATH": os.path.join(TMP, "ai_strategy.log"),
    "FAILED_SIGNALS_PATH": os.path.join(TMP, "failed_signals.json"),
    "SIMULATION_STATE_FILE_PATH": os.path.join(TMP, "simulation_state.json"),
}
for _name in ("CTS_FILTER", "SPOOF_FILTER", "COMPRESSION_DETECTOR", "BREAKOUT_FILTER", "RETEST_LOGIC",
              "LOW_VOLUME_GUARD", "SENTIMENT_FILTER", "ORDERBOOK_REVERSAL"):
    _PINNED_ENV[f"{_name}_LOG_PATH"] = os.path.join(TMP, "filters", f"{_name.lower()}.log")
os.environ.update(_PINNED_ENV)

import pytest  # noqa: E402  (env must be pinned before importing project modules)

from config.config import Config  # noqa: E402
from data_managers.market_state import MarketState  # noqa: E402


def run(coro):
    """Run a coroutine to completion (no pytest-asyncio dependency)."""
    return asyncio.run(coro)


@pytest.fixture
def config() -> Config:
    return Config()


TS0 = 1_700_000_000_000  # newest candle open time (ms)
KLINE_MS = 60_000


def make_klines(n: int, price: float = 3000.0, kline_range: float = 10.0, trend: float = 0.0):
    """Newest-first candles (MarketState convention). `trend` = close-to-close drift per candle,
    positive = price rising into the present."""
    assert abs(trend) < kline_range / 2, "trend must stay inside the candle range"
    klines = []
    for i in range(n):  # i = 0 is the newest closed candle
        close = price - trend * i
        open_ = close - trend
        high = max(open_, close) + kline_range / 2
        low = min(open_, close) - kline_range / 2
        klines.append([TS0 - i * KLINE_MS, open_, high, low, close, 100.0, 0.0, 0.0, "1"])
    return klines


def make_live_candle(open_: float, high: float, low: float, close: float, volume: float = 50.0):
    return [TS0 + KLINE_MS, open_, high, low, close, volume, 0.0, 0.0, "0"]


def make_market_state(config: Config, n_klines: int = 30, price: float = 3000.0, kline_range: float = 10.0,
                      trend: float = 0.0, live=None, mark_price=None) -> MarketState:
    ms = MarketState(symbol="ETH-USDT-SWAP", config=config)
    for k in make_klines(n_klines, price=price, kline_range=kline_range, trend=trend):
        ms.klines.append(k)
    ms.live_reconstructed_candle = live or make_live_candle(price, price + kline_range / 2, price - kline_range / 2, price)
    ms.mark_price = ms.live_reconstructed_candle[4] if mark_price is None else mark_price
    return ms
