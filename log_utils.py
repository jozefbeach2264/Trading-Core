"""Non-blocking file loggers.

Every filter used to attach a plain FileHandler to its own logger, so each DEBUG record
was a synchronous write on the asyncio event loop that also services the OKX websocket.
`file_logger` puts a QueueHandler in front of the FileHandler and drains the queue on a
background thread (QueueListener), so the hot loop only pays for a queue.put().
"""
import atexit
import logging
import logging.handlers
import os
import queue
from typing import Dict, List

_listeners: Dict[str, logging.handlers.QueueListener] = {}

DEFAULT_FORMAT = "%(asctime)s - %(message)s"
ROTATE_BYTES = 50 * 1024 * 1024   # per-file cap; the filters wrote ~1 GB/day unrotated
ROTATE_BACKUPS = 3
# Filter loggers default to DEBUG because their per-cycle JSON reports are the training data the
# log parser consumes; FILTER_LOG_LEVEL=INFO silences them.
DEFAULT_LEVEL = getattr(logging, os.getenv("FILTER_LOG_LEVEL", "DEBUG").upper(), logging.DEBUG)


def file_logger(name: str, path: str, fmt: str = DEFAULT_FORMAT, level: int = None) -> logging.Logger:
    """Return the named logger wired to `path` through a queue. Idempotent per logger name."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(path, mode="a", maxBytes=ROTATE_BYTES, backupCount=ROTATE_BACKUPS)
    file_handler.setFormatter(logging.Formatter(fmt))
    log_queue: "queue.Queue[logging.LogRecord]" = queue.Queue()
    listener = logging.handlers.QueueListener(log_queue, file_handler, respect_handler_level=True)
    listener.start()
    _listeners[name] = listener
    logger.addHandler(logging.handlers.QueueHandler(log_queue))
    logger.setLevel(DEFAULT_LEVEL if level is None else level)
    logger.propagate = False
    return logger


def make_async(logger: logging.Logger, handlers: List[logging.Handler]) -> None:
    """Attach `handlers` to `logger` behind one shared queue (used for the root logger)."""
    log_queue: "queue.Queue[logging.LogRecord]" = queue.Queue()
    listener = logging.handlers.QueueListener(log_queue, *handlers, respect_handler_level=True)
    listener.start()
    _listeners[f"__root__:{id(logger)}"] = listener
    logger.addHandler(logging.handlers.QueueHandler(log_queue))


def flush_all() -> None:
    """Block until every queued record has been written (tests, shutdown)."""
    for listener in _listeners.values():
        listener.queue.join()  # QueueListener calls task_done() per record
        for handler in listener.handlers:
            handler.flush()


def shutdown() -> None:
    for name, listener in list(_listeners.items()):
        listener.stop()
        for handler in listener.handlers:
            handler.close()
        _listeners.pop(name, None)


atexit.register(shutdown)
