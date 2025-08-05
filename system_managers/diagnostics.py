import logging
import os
from typing import Deque, Dict, Any
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
    formatter = logging.Formatter('%(asctime)s - %(message)s')
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
    diagnostics_logger.info("="*15 + " R5 BUFFER DEBUG " + "="*15)
    diagnostics_logger.info(f"Total candles in buffer: {len(r5_buffer)}")

    for i, candle in enumerate(r5_buffer):
        try:
            diagnostics_logger.info(f"[{i}] Open: {candle[1]} | Close: {candle[4]} | Volume: {candle[5]}")
        except (IndexError, TypeError):
            diagnostics_logger.warning(f"[{i}] Malformed candle data: {candle}")

    if len(r5_buffer) != 5:
        diagnostics_logger.warning("R5 buffer length is incorrect! Expected 5.")

    diagnostics_logger.info("="*15 + " MEMORY TRACKER DEBUG " + "="*15)
    memory_state = memory_tracker.get_memory()

    trades = memory_state.get('trades', [])
    verdicts = memory_state.get('verdicts', [])
    diagnostics_logger.info(f"Total trades tracked: {len(trades)}")

    for idx, trade in enumerate(trades[-5:]):
        # --- Log raw trade payload for inspection ---
        diagnostics_logger.warning(f"Raw TRADE DEBUG [{idx}]: {trade}")

        # --- Match to verdict ---
        trade_time = trade.get("timestamp", "")
        matched_verdict = next(
            (v for v in reversed(verdicts) if v.get("timestamp", "") <= trade_time), None
        )

        diagnostics_logger.info(
            f"Trade [{idx}] → Direction: {trade.get('direction')} | "
            f"Entry: {trade.get('entry_price')} | Verdict: {matched_verdict.get('verdict') if matched_verdict else 'None'} | "
            f"Confidence: {matched_verdict.get('confidence') if matched_verdict else 'None'} | "
            f"Reason: {matched_verdict.get('reason') if matched_verdict else 'N/A'}"
        )

    if not trades:
        diagnostics_logger.warning("MemoryTracker is empty or not updating.")

    diagnostics_logger.info("="*47 + "\n")