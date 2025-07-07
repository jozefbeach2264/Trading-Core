TradingCore Autonomous Trading System


About The Project:

TradingCore is a sophisticated, modular trading bot designed for autonomous operation. It uses a series of configurable filters to analyze market data, compiles a detailed pre-analysis report, and sends this report to an external AI service for a final trade decision.
The system is built on a "trinity of programs" architecture:



 * TradingCore: The main engine responsible for analysis, decision-making, and trade execution.
   
 * NeuroSync: The communication hub and system monitor.
   
 * Rolling5: The user interface and notification bot.



   
This document details the configuration for the TradingCore application.

CONFIGURATION:


All system parameters are configured via environment variables, typically in a .env file at the root of the project.


Core & API Settings
These variables are for essential credentials and service endpoints.

| Variable | Description | Min / Max / Type | Default |

| ASTERDEX_API_KEY | Your API key for the exchange. | string | none |

| ASTERDEX_API_SECRET | Your API secret for the exchange. | string | none |

| AI_PROVIDER_API_KEY | Your API key for the external AI service. | string | none |

| AI_PROVIDER_URL | The URL for the AI service's API endpoint. | string | none |

| NEUROSYNC_VOLUME_DATA_URL | URL to fetch volume data from NeuroSync. | string | none |

| ROLLING5_ALERT_URL | URL to send alerts to the Rolling5 UI bot. | string | none |

| TRADINGCORE_URL | Health check URL for this service. | string | none |

| NEUROSYNC_URL | Health check URL for the NeuroSync service. | string | none |

| ROLLING5_URL | Health check URL for the Rolling5 service. | string | none |


RISK & TRADING PARAMETERS:

These control the core behavior of trades.
| Variable | Description | Min / Max / Type | Default |

| TRADING_SYMBOL | The market symbol to trade (e.g., ETHUSDT). | string | ETHUSDT |

| LEVERAGE | The leverage to use for trades. | 1 - 250 (int) | 250 |

| RISK_CAP_PERCENT | Max percentage of total capital to risk on a single trade. | 0.01 - 1.0 (float) | 0.25 |

| MAX_ROI_LIMIT | Sets a maximum Return on Investment limit for a trade. 0 means no limit. | 0 - 1000 (float) | 0 |


AUTONOMOUS MODE & TIME FILTER:

These settings control the main autonomous loop and its schedule.
| Variable | Description | Min / Max / Type | Default |

| AUTONOMOUS_MODE_ENABLED | Master switch to turn the entire autonomous engine on (True) or off (False). | bool | False |

| TRADE_WINDOWS | Comma-separated list of allowed UTC hour ranges (e.g., "6-7,9-11,21-22"). | string | "0-23" |

| USE_TIME_OF_DAY_FILTER | Master switch to enable (True) or disable (False) the time window check. | bool | True |

| TRADING_START_HOUR | Legacy Setting. Defines the start of a single trading window (UTC). | 0 - 23 (int) | 0 |

| TRADING_END_HOUR | Legacy Setting. Defines the end of a single trading window (UTC). | 0 - 23 (int) | 23 |


FILTER PARAMETERS: CTS FILTER 
Settings for the Compression Trap Scenario filter.

| Variable | Description | Min / Max / Type | Default |

| CTS_LOOKBACK_PERIOD | Number of candles to calculate the average range for compression detection. | 5 - 100 (int) | 20 |

| CTS_NARROW_RANGE_RATIO | A candle is "narrow" if its range is less than this ratio of the average range. | 0.1 - 0.9 (float) | 0.5 |

| CTS_WICK_REJECTION_MULTIPLIER | A wick is considered a "rejection" if it is this many times larger than the candle body. | 1.1 - 5.0 (float) | 2.0 |


FILTER PARAMETERS: SPOOF FILTER 
Settings for detecting order book spoofing.

| Variable | Description | Min / Max / Type | Default |

| SPOOF_IMBALANCE_THRESHOLD | Triggers if total bid vs. ask volume imbalance exceeds this ratio (e.g., 0.7 = 70%). | 0.5 - 0.95 (float) | 0.70 |

| SPOOF_DISTANCE_PERCENT | How far from the current price (in %) to look for spoofing walls. | 0.1 - 10.0 (float) | 2.0 |

| SPOOF_LARGE_ORDER_MULTIPLIER | An order is a "large wall" if it is this many times larger than the volume at the best bid/ask. | 5 - 50 (int) | 10 |


FILTER PARAMETERS: ALL OTHERS 
Settings for the remaining specialized filters.

| Variable | Description | Min / Max / Type | Default |

| COMPRESSION_LOOKBACK_PERIOD | Number of candles to establish the average range for compression detection. | 5 - 100 (int) | 15 |

| COMPRESSION_RANGE_RATIO | A candle is "compressed" if its range is this ratio of the average or less. | 0.1 - 0.9 (float) | 0.6 |

| BREAKOUT_ZONE_LOOKBACK | Number of candles to analyze as the "origin zone" before a breakout. | 5 - 50 (int) | 10 |

| BREAKOUT_ZONE_VOLATILITY_RATIO | A breakout origin is valid if its volatility was this ratio of the pre-breakout volatility. | 0.1 - 0.9 (float) | 0.4 |

| RETEST_LOOKBACK | Number of candles to look back to find a significant high/low for a retest. | 10 - 500 (int) | 50 |

| RETEST_PROXIMITY_PERCENT | How close (in %) the price must be to a level to be considered a retest. | 0.01 - 1.0 (float) | 0.1 |

| LOW_VOLUME_LOOKBACK | Number of candles to calculate average volume. | 10 - 500 (int) | 100 |

| LOW_VOLUME_RATIO | Triggers the guard if current volume is below this ratio of the average. | 0.1 - 1.0 (float) | 0.5 |

| SENTIMENT_DIVERGENCE_LOOKBACK | Number of candles to look for price/CVD divergence. | 5 - 50 (int) | 14 |

| ORDERBOOK_REVERSAL_DEPTH_PERCENT | How far from the mark price (in %) to scan for reversal walls. | 0.1 - 5.0 (float) | 1.0 |

| ORDERBOOK_REVERSAL_WALL_MULTIPLIER | A reversal wall must be this many times larger than the volume at the best bid/ask. | 5 - 50 (int) | 15 |


OPERATIONAL PARAMETERS:
General application behavior settings.

| Variable | Description | Min / Max / Type | Default |

| DRY_RUN_MODE | True to run in simulation mode, False for live trading. | bool | True |

| KLINE_DEQUE_MAXLEN | Max number of recent klines to keep in memory. | 100 - 1000 (int) | 500 |

| AI_CLIENT_TIMEOUT | Seconds to wait for a response from the AI service before timing out. | 5 - 60 (int) | 15 |

| SIMULATION_INITIAL_CAPITAL | Starting capital for simulation mode. | float | 10.00 |