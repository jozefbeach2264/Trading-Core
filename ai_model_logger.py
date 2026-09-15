import json
import logging
import os
from typing import Any, Dict

from config.config import Config
from log_utils import file_logger


def get_ai_model_logger(config: Config) -> logging.Logger:
    """Dedicated NDJSON logger for AI model decisions (queue-backed, never blocks the loop).
    Path defaults to <ai_strategy_log dir>/ai_model.log unless AI_MODEL_LOG_PATH is set."""
    log_path = os.getenv("AI_MODEL_LOG_PATH", os.path.join(os.path.dirname(config.ai_strategy_log_path), "ai_model.log"))
    return file_logger("AIModelLogger", log_path, fmt="%(message)s", level=logging.INFO)


def log_ai_decision(logger: logging.Logger, decision: Dict[str, Any]):
    """Write a single AI decision as NDJSON."""
    try:
        logger.info(json.dumps(decision))
    except Exception as exc:
        logging.getLogger(__name__).warning("Failed to log AI decision", extra={"error": str(exc)})
