import logging
import pprint
from typing import Deque, Dict, Any
from memory_tracker import MemoryTracker
from config.config import Config

config = Config()
logger = logging.getLogger("diagnostics")

# Ensure handler is added only once
if not logger.hasHandlers():
    handler = logging.FileHandler(config.diagnostics_log_path)
    formatter = logging.Formatter('%(asctime)s - %(message)s')
    handler.setFormatter(formatter)
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

def debug_r5_and_memory_state(r5_buffer: Deque, memory_tracker: MemoryTracker):
    """
    Prints and logs a diagnostic report for the Rolling 5 candle buffer and the MemoryTracker.
    """
    print("\n\n" + "=" * 15 + " R5 BUFFER DEBUG " + "=" * 15)
    logger.debug("Total candles in buffer: %s", len(r5_buffer))
    print(f"Total candles in buffer: {len(r5_buffer)}")

    for i, candle in enumerate(r5_buffer):
        try:
            ts = candle[0]
            o = candle[1]
            c = candle[4]
            v = candle[5]
            msg = f"[{i}] Timestamp: {ts} | Open: {o} | Close: {c} | Volume: {v}"
            print(msg)
            logger.debug(msg)
        except (IndexError, TypeError):
            malformed_msg = f"[{i}] Malformed candle data: {candle}"
            print(malformed_msg)
            logger.debug(malformed_msg)

    if len(r5_buffer) != 5:
        warn_msg = "⚠️  R5 buffer length is incorrect! Expected 5."
        print(warn_msg)
        logger.debug(warn_msg)

    print("\n" + "=" * 15 + " MEMORY TRACKER DEBUG " + "=" * 15)
    memory_state = memory_tracker.get_memory()
    trades = memory_state.get('trades', [])

    logger.debug("Total trades tracked: %s", len(trades))
    print(f"Total trades tracked: {len(trades)}")

    for idx, trade in enumerate(trades[-5:]):
        logger.debug("Raw TRADE DEBUG [%d]: %s", idx, pprint.pformat(trade))
        print(f"Raw TRADE DEBUG [{idx}]: {pprint.pformat(trade)}")

        ts = trade.get("timestamp", trade.get("module_timestamp", "N/A"))
        direction = trade.get("direction", "N/A")
        entry = trade.get("entry_price", "N/A")
        ai = trade.get("ai_verdict", {})
        verdict = ai.get("action", "N/A")
        confidence = ai.get("confidence", "N/A")
        reason = ai.get("reasoning", ai.get("reason", "N/A"))

        msg = (f"Trade [{idx}] → Timestamp: {ts} | Direction: {direction} | Entry: {entry} | "
               f"Verdict: {verdict} | Confidence: {confidence} | Reason: {reason}")
        print(msg)
        logger.debug(msg)

    if not trades:
        empty_msg = "⚠️  MemoryTracker is empty or not updating."
        print(empty_msg)
        logger.debug(empty_msg)

    print("=" * 47 + "\n")