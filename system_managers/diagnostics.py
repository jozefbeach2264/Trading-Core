import logging
import os
from typing import Deque, Dict, Any
from datetime import datetime
from memory_tracker import MemoryTracker
from config.config import Config

def setup_diagnostics_logger(config: Config) -> logging.Logger:
    """Sets up a dedicated logger for the diagnostic script."""
    log_path = config.diagnostics_log_path
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    logger = logging.getLogger('DiagnosticsLogger')
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if logger.handlers:
        logger.handlers.clear()

    handler = logging.FileHandler(log_path, mode='a')
    # FIX: Formatter is simplified to only output the raw message.
    formatter = logging.Formatter('%(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger

config = Config()
diagnostics_logger = setup_diagnostics_logger(config)

def debug_r5_and_memory_state(r5_buffer: Deque, memory_tracker: MemoryTracker):
    """
    Logs a diagnostic report for the Rolling 5 candle buffer and the MemoryTracker
    to a dedicated file.
    """
    # Log the header with the logger's own timestamp for context.
    diagnostics_logger.info(f"{datetime.now():%Y-%m-%d %H:%M:%S,%f}"[:-3] + " - " + "="*15 + " MEMORY TRACKER DEBUG " + "="*15)

    memory_state = memory_tracker.get_memory()
    trades = memory_state.get('trades', [])
    verdicts = memory_state.get('verdicts', [])

    diagnostics_logger.info(f"Total trades tracked: {len(trades)}")

    for idx, trade in enumerate(trades[-5:]):
        # --- Match to verdict ---
        trade_time = trade.get("timestamp", "")
        matched_verdict = next(
            (v for v in reversed(verdicts) if v.get("timestamp", "") <= trade_time), None
        )

        # FIX: The trade's own timestamp is now part of the log message.
        trade_ts = trade.get('timestamp', 'NO_TIMESTAMP')

        diagnostics_logger.info(
            f"{trade_ts} - Trade [{idx}] → Direction: {trade.get('direction')} | "
            f"Entry: {trade.get('entry_price')} | Verdict: {matched_verdict.get('verdict') if matched_verdict else 'None'} | "
            f"Confidence: {matched_verdict.get('confidence') if matched_verdict else 'None'} | "
            f"Reason: {matched_verdict.get('reason') if matched_verdict else 'N/A'}"
        )

    if not trades:
        diagnostics_logger.warning("MemoryTracker is empty or not updating.")

    diagnostics_logger.info("="*47 + "\n")