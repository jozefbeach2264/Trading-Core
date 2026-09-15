import logging
import os
import json
from typing import Dict, Any
from config.config import Config


def get_ai_model_logger(config: Config) -> logging.Logger:
    """
    Returns a dedicated logger for AI model decisions (structured NDJSON).
    Path defaults to logs/ai_model.log unless AI_MODEL_LOG_PATH is set.
    """
    log_path = os.getenv("AI_MODEL_LOG_PATH", os.path.join(os.path.dirname(config.ai_strategy_log_path), "ai_model.log"))
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    logger = logging.getLogger("AIModelLogger")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if logger.handlers:
        return logger

    handler = logging.FileHandler(log_path, mode='a')
    formatter = logging.Formatter('%(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


def log_ai_decision(logger: logging.Logger, decision: Dict[str, Any]):
    """Write a single AI decision as NDJSON."""
    try:
        logger.info(json.dumps(decision))
    except Exception as exc:
        logging.getLogger(__name__).warning("Failed to log AI decision", extra={"error": str(exc)})
