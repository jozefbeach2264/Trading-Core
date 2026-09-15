"""Perf: filter-report persistence must be batched, off the event loop, and off by default."""
import sqlite3

from conftest import run
from memory_tracker import MemoryTracker


def _count(path, table):
    with sqlite3.connect(path) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _reports(n):
    return [{"filter_name": f"F{i}", "score": 0.5, "flag": "✅ Hard Pass", "metrics": {"i": i}} for i in range(n)]


def test_filter_history_is_off_by_default(config):
    assert config.memory_filter_history is False
    tracker = MemoryTracker(config)
    before = _count(config.memory_db_path, "filters")
    run(tracker.update_filter_reports(_reports(3)))
    run(tracker.update_memory(filter_report=_reports(1)[0]))
    assert _count(config.memory_db_path, "filters") == before


def test_filter_history_enabled_writes_one_batch(config):
    config.memory_filter_history = True
    tracker = MemoryTracker(config)
    before = _count(config.memory_db_path, "filters")
    run(tracker.update_filter_reports(_reports(9)))
    assert _count(config.memory_db_path, "filters") == before + 9


def test_trade_records_always_persist(config):
    tracker = MemoryTracker(config)
    before = _count(config.memory_db_path, "trades")
    run(tracker.update_memory(trade_data={"direction": "LONG", "quantity": 1.0, "entry_price": 3000.0, "simulated": True}))
    assert _count(config.memory_db_path, "trades") == before + 1


def test_db_uses_wal_journal(config):
    MemoryTracker(config)
    with sqlite3.connect(config.memory_db_path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
