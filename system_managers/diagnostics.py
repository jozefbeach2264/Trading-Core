import logging
import json
import os
from typing import Deque
from memory_tracker import MemoryTracker
from config.config import Config

def setup_diagnostics_logger(config: Config) -> logging.Logger:
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

# Persist last logged trade id so we don't spam diagnostics each cycle
def _state_paths(config: Config):
    state_dir = os.path.dirname(config.diagnostics_log_path)
    os.makedirs(state_dir, exist_ok=True)
    return os.path.join(state_dir, "diagnostics_state.json")

def _load_state(config: Config) -> dict:
    path = _state_paths(config)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _save_state(config: Config, state: dict):
    path = _state_paths(config)
    try:
        with open(path, "w") as f:
            json.dump(state, f)
    except Exception:
        pass

config = Config()
diagnostics_logger = setup_diagnostics_logger(config)
_state = _load_state(config)

def debug_r5_and_memory_state(r5_buffer: Deque, memory_tracker: MemoryTracker):
    """
    Logs a diagnostic report for:
      - R5 buffer (open/close/volume)
      - Recent trades from DB

    Behavior:
      - Always prints a rolling window of the most recent 5 trades (every cycle).
      - Additionally logs ONLY new trades since the last run to avoid spam.
    """
    diagnostics_logger.info("="*15 + " R5 BUFFER DEBUG " + "="*15)
    diagnostics_logger.info(f"Total candles in buffer: {len(r5_buffer)}")

    for i, candle in enumerate(r5_buffer):
        try:
            ts = candle[0] if len(candle) > 0 else "N/A"  # original candle ts (ms) if present
            diagnostics_logger.info(f"[{i}] Timestamp(ms): {ts} | Open: {candle[1]} | Close: {candle[4]} | Volume: {candle[5]}")
        except (IndexError, TypeError):
            diagnostics_logger.warning(f"[{i}] Malformed candle data: {candle}")

    if len(r5_buffer) != 5:
        diagnostics_logger.warning("R5 buffer length is incorrect! Expected 5.")

    diagnostics_logger.info("="*15 + " MEMORY TRACKER DEBUG " + "="*15)

    counts = memory_tracker.get_counts()
    # FIX: correct key name is 'trades_count'
    diagnostics_logger.info(f"Total trades tracked: {counts.get('trades_count', 0)}")

    # NEW: Always show a rolling window of the most recent 5 trades (latest first)
    try:
        recent5 = memory_tracker.get_recent_trades(limit=5)  # returns DESC by id
    except Exception as e:
        diagnostics_logger.error("Diagnostics: failed to fetch recent trades", extra={"error": str(e)})
        recent5 = []

    if recent5:
        diagnostics_logger.info("Most recent 5 trades (latest first):")
        for t in recent5:
            ai = t.get("ai_verdict", {}) or {}
            verdict = ai.get("action", "N/A")
            confidence = ai.get("confidence", "N/A")
            reason = ai.get("reasoning", ai.get("reason", "N/A"))
            diagnostics_logger.info(
                "  [id=%s] module_ts=%s | candle_ts=%s | %s | entry=%s | verdict=%s | conf=%s | reason=%s",
                t["id"], t.get("module_timestamp"), t.get("candle_timestamp"),
                t.get("direction"), t.get("entry_price"), verdict, confidence, reason
            )
    else:
        diagnostics_logger.info("Most recent 5 trades: none recorded yet.")

    # EXISTING: Log only new trades since last diagnostics cycle
    last_logged_id = int(_state.get("last_logged_trade_id", 0))

    # Pull the most recent 20, then filter out anything we've already logged
    recent_trades = memory_tracker.get_recent_trades(limit=20)
    # recent_trades are ordered DESC by id; we want to log oldest first among the NEW ones
    new_trades = [t for t in reversed(recent_trades) if t["id"] > last_logged_id]

    if not new_trades:
        diagnostics_logger.info("No new trades since last diagnostics cycle.")
    else:
        for idx, t in enumerate(new_trades):
            # Raw trade packet (for debugging mismatches)
            diagnostics_logger.info(f"Raw TRADE DEBUG [id={t['id']}] {t}")

            ai = t.get("ai_verdict", {}) or {}
            verdict = ai.get("action", "N/A")
            confidence = ai.get("confidence", "N/A")
            reason = ai.get("reasoning", ai.get("reason", "N/A"))

            diagnostics_logger.info(
                "Trade[id=%s] → module_ts: %s | candle_ts: %s | Direction: %s | Entry: %s | "
                "Verdict: %s | Confidence: %s | Reason: %s",
                t["id"], t.get("module_timestamp"), t.get("candle_timestamp"), t.get("direction"),
                t.get("entry_price"), verdict, confidence, reason
            )

        # Update state with the highest id we saw
        _state["last_logged_trade_id"] = max(t["id"] for t in new_trades)
        _save_state(config, _state)

    diagnostics_logger.info("="*47 + "\n")