import logging
import json
import os
from typing import Deque
from memory_tracker import MemoryTracker
from config.config import Config

_LOGGER_NAME = 'DiagnosticsLogger'
_STATE_FILE = 'diagnostics_state.json'
_CANARY_MSG = 'DIAG_CANARY: initialized'

def setup_diagnostics_logger(config: Config) -> logging.Logger:
    """Dedicated file logger with absolute path and flush."""
    raw_path = config.diagnostics_log_path
    if not raw_path:
        raise RuntimeError("Config.diagnostics_log_path is empty")

    abs_path = os.path.abspath(raw_path)
    log_dir = os.path.dirname(abs_path)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    # Attach exactly one FileHandler to this file
    has_this_file = any(
        isinstance(h, logging.FileHandler)
        and os.path.abspath(getattr(h, "baseFilename", "")) == abs_path
        for h in logger.handlers
    )
    if not has_this_file:
        fh = logging.FileHandler(abs_path, mode='a', encoding='utf-8', delay=False)
        fh.setLevel(logging.INFO)
        fh.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
        logger.addHandler(fh)

    # Canary write + flush so we can verify immediately
    logger.info("%s → %s", _CANARY_MSG, abs_path)
    for h in logger.handlers:
        if hasattr(h, "flush"):
            h.flush()

    return logger

def _state_path(config: Config) -> str:
    abs_log = os.path.abspath(config.diagnostics_log_path)
    state_dir = os.path.dirname(abs_log) or os.getcwd()
    os.makedirs(state_dir, exist_ok=True)
    return os.path.join(state_dir, _STATE_FILE)

def _load_state(config: Config) -> dict:
    path = _state_path(config)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _save_state(config: Config, state: dict) -> None:
    path = _state_path(config)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception:
        # Diagnostics must never break runtime
        pass

# === Module init (no extra wiring needed) ===
config = Config()
diagnostics_logger = setup_diagnostics_logger(config)
_state = _load_state(config)

def diagnostics_self_test() -> None:
    """Writes handler info; runs automatically on import."""
    log = logging.getLogger(_LOGGER_NAME)
    log.info("DIAG_SELF_TEST: name=%s handlers=%d cwd=%s",
             _LOGGER_NAME, len(log.handlers), os.getcwd())
    for h in log.handlers:
        try:
            log.info("DIAG_SELF_TEST: handler=%s file=%s",
                     type(h).__name__, getattr(h, "baseFilename", None))
            if hasattr(h, "flush"):
                h.flush()
        except Exception:
            pass

# run once on import so you don't have to call it elsewhere
diagnostics_self_test()

def debug_r5_and_memory_state(r5_buffer: Deque, memory_tracker: MemoryTracker):
    """
    Logs:
      - R5 buffer (open/high/low/close/volume)
      - Rolling 5 most recent trades (every cycle)
      - Only NEW trades beyond last_logged_trade_id
    """
    log = diagnostics_logger

    # ----- R5 BUFFER -----
    log.info("=" * 15 + " R5 BUFFER DEBUG " + "=" * 15)
    try:
        buf_len = len(r5_buffer) if r5_buffer is not None else 0
        log.info("Total candles in buffer: %s", buf_len)

        for i, c in enumerate(r5_buffer or []):
            try:
                ts = c[0] if len(c) > 0 else "N/A"
                o  = c[1] if len(c) > 1 else "N/A"
                h  = c[2] if len(c) > 2 else "N/A"
                l  = c[3] if len(c) > 3 else "N/A"
                cl = c[4] if len(c) > 4 else "N/A"
                v  = c[5] if len(c) > 5 else "N/A"
                log.info("[%s] Timestamp(ms): %s | Open: %s | High: %s | Low: %s | Close: %s | Volume: %s",
                         i, ts, o, h, l, cl, v)
            except Exception:
                log.warning("[%s] Malformed candle data: %s", i, c)

        if buf_len != 5:
            log.warning("R5 buffer length is incorrect! Expected 5.")
    except Exception as e:
        log.error("Diagnostics: R5 buffer logging failed", extra={"error": str(e)}, exc_info=True)

    # ----- MEMORY COUNTS -----
    log.info("=" * 15 + " MEMORY TRACKER DEBUG " + "=" * 15)
    try:
        counts = memory_tracker.get_counts()
        log.info("Total trades tracked: %s", counts.get("trades_count", 0))
    except Exception as e:
        counts = {}
        log.error("Diagnostics: get_counts() failed", extra={"error": str(e)}, exc_info=True)

    # ----- ROLLING 5 (always) -----
    try:
        recent5 = memory_tracker.get_recent_trades(limit=5) or []
        if recent5:
            log.info("Most recent 5 trades (latest first):")
            for t in recent5:
                ai = t.get("ai_verdict") or {}
                verdict = ai.get("action", "N/A")
                confidence = ai.get("confidence", "N/A")
                reason = ai.get("reasoning", ai.get("reason", "N/A"))
                log.info(
                    "  [id=%s] module_ts=%s | candle_ts=%s | %s | entry=%s | verdict=%s | conf=%s | reason=%s",
                    t.get("id"), t.get("module_timestamp"), t.get("candle_timestamp"),
                    t.get("direction"), t.get("entry_price"),
                    verdict, confidence, reason
                )
        else:
            log.info("Most recent 5 trades: none recorded yet.")
    except Exception as e:
        log.error("Diagnostics: get_recent_trades(5) failed", extra={"error": str(e)}, exc_info=True)

    # ----- NEW TRADES SINCE LAST ID -----
    try:
        last_logged_id = int(_state.get("last_logged_trade_id", 0))
    except Exception:
        last_logged_id = 0

    try:
        recent20 = memory_tracker.get_recent_trades(limit=20) or []
        # recent20 is DESC by id; we want oldest-first among NEW ones
        new_trades = []
        for t in reversed(recent20):
            tid = t.get("id") or 0
            if isinstance(tid, str):
                try:
                    tid = int(tid)
                except Exception:
                    tid = 0
            if tid > last_logged_id:
                new_trades.append(t)

        if not new_trades:
            log.info("No new trades since last diagnostics cycle.")
        else:
            for t in new_trades:
                # Raw trade packet for deep debugging
                try:
                    log.info("Raw TRADE DEBUG [id=%s] %s", t.get("id"), t)
                except Exception:
                    log.info("Raw TRADE DEBUG [id=%s] <unprintable>", t.get("id"))

                ai = t.get("ai_verdict") or {}
                verdict = ai.get("action", "N/A")
                confidence = ai.get("confidence", "N/A")
                reason = ai.get("reasoning", ai.get("reason", "N/A"))

                log.info(
                    "Trade[id=%s] → module_ts: %s | candle_ts: %s | Direction: %s | Entry: %s | "
                    "Verdict: %s | Confidence: %s | Reason: %s",
                    t.get("id"),
                    t.get("module_timestamp"),
                    t.get("candle_timestamp"),
                    t.get("direction"),
                    t.get("entry_price"),
                    verdict,
                    confidence,
                    reason
                )

            # Persist highest id we saw
            try:
                _state["last_logged_trade_id"] = max(int(t.get("id") or 0) for t in new_trades)
                _save_state(config, _state)
            except Exception as e:
                log.error("Diagnostics: failed to persist state", extra={"error": str(e)}, exc_info=True)

    except Exception as e:
        log.error("Diagnostics: new-trade block failed", extra={"error": str(e)}, exc_info=True)

    # Footer + flush
    log.info("=" * 47 + "\n")
    try:
        for h in log.handlers:
            if hasattr(h, "flush"):
                h.flush()
    except Exception:
        pass