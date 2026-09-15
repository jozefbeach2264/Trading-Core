"""Perf: file logging goes through a queue so the event loop never blocks on disk."""
import logging
import os

from log_utils import file_logger, flush_all


def test_file_logger_writes_through_queue(tmp_path):
    path = tmp_path / "sub" / "x.log"
    logger = file_logger("TestQueueLogger", str(path), fmt="%(message)s", level=logging.DEBUG)
    logger.debug("hello-queue")
    flush_all()
    assert os.path.exists(path)
    assert "hello-queue" in path.read_text()
    assert logger.propagate is False


def test_file_logger_is_idempotent(tmp_path):
    a = file_logger("TestIdem", str(tmp_path / "a.log"))
    b = file_logger("TestIdem", str(tmp_path / "b.log"))
    assert a is b and len(a.handlers) == 1
