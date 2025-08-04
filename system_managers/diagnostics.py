import logging
from datetime import datetime
import asyncio

# Get the specific logger for diagnostics
logger = logging.getLogger(__name__)

def _log_r5_buffer(r5_engine):
    """Logs the contents of the Rolling5 candle buffer."""
    buffer = r5_engine.get_buffer()
    logger.info("=============== R5 BUFFER DEBUG ===============")
    logger.info(f"Total candles in buffer: {len(buffer)}")

    # Each 'c' is a candle object, which we assume has a 'timestamp' attribute
    # Bybit/OKX timestamps are often in milliseconds, so we divide by 1000
    for i, c in enumerate(buffer):
        # Convert Unix MS timestamp to a readable datetime object
        ts = datetime.fromtimestamp(c.timestamp / 1000) if hasattr(c, 'timestamp') else "N/A"
        logger.info(
            f"[{i}] Timestamp: {ts:%Y-%m-%d %H:%M:%S} | "
            f"Open: {c.open} | Close: {c.close} | Volume: {c.volume}"
        )
    logger.info("=" * 45)


def _log_memory_tracker(memory_tracker):
    """Logs the trades stored in the MemoryTracker."""
    trades = memory_tracker.get_memory().get("trades", [])
    logger.info("=============== MEMORY TRACKER DEBUG ===============")
    logger.info(f"Total trades tracked: {len(trades)}")

    for i, trade in enumerate(trades):
        # The trade dictionary already contains a formatted timestamp string
        trade_ts = trade.get('timestamp', 'N/A')
        verdict = trade.get('ai_verdict', {})

        logger.info(
            f"Trade [{i}] @ {trade_ts} → "
            f"Direction: {trade.get('direction', 'N/A')} | "
            f"Entry: {trade.get('entry_price', 0.0)} | "
            f"Verdict: {verdict.get('action', 'N/A')} | "
            f"Confidence: {verdict.get('confidence', 'N/A')} | "
            f"Reason: {verdict.get('reasoning', 'N/A')}"
        )
    logger.info("=" * 52)


async def run_diagnostics(r5_engine, memory_tracker, interval_seconds=15):
    """Periodically runs all diagnostic logging functions."""
    while True:
        try:
            _log_r5_buffer(r5_engine)
            _log_memory_tracker(memory_tracker)
        except Exception as e:
            logger.error(f"Error during diagnostics run: {e}", exc_info=True)
        await asyncio.sleep(interval_seconds)


def debug_r5_and_memory_state(r5_engine, memory_tracker):
    """
    Runs a one-time debug log of both the R5 engine buffer and memory tracker state.
    This is the public function your engine.py should import.
    """
    try:
        _log_r5_buffer(r5_engine)
        _log_memory_tracker(memory_tracker)
    except Exception as e:
        logger.error(f"Error during debug_r5_and_memory_state: {e}", exc_info=True)