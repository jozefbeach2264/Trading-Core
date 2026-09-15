import asyncio
import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
from config.config import Config

logger = logging.getLogger(__name__)

RETENTION_DAYS = 30
SQLITE_BUSY_TIMEOUT_S = 5.0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class _SqliteStore:
    """One connection + lock per database file, shared by every MemoryTracker instance
    (the bot creates four). WAL + synchronous=NORMAL so a commit no longer fsyncs twice."""

    def __init__(self, path: str):
        self.path = path
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(path, timeout=SQLITE_BUSY_TIMEOUT_S, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self.lock, self.conn:
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS filters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    filter_name TEXT,
                    score REAL,
                    flag TEXT,
                    metrics TEXT
                )
            ''')
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    direction TEXT,
                    quantity REAL,
                    entry_price REAL,
                    simulated BOOLEAN,
                    failed BOOLEAN,
                    reason TEXT,
                    order_data TEXT
                )
            ''')
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_filters_timestamp ON filters (timestamp);')
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades (timestamp);')
            self.conn.execute(f"DELETE FROM filters WHERE timestamp < datetime('now', '-{RETENTION_DAYS} days')")
            self.conn.execute(f"DELETE FROM trades WHERE timestamp < datetime('now', '-{RETENTION_DAYS} days')")

    def write(self, filter_rows: List[tuple], trade_rows: List[tuple]) -> None:
        """One transaction for everything passed in. Runs on a worker thread."""
        if not filter_rows and not trade_rows:
            return
        with self.lock, self.conn:
            if filter_rows:
                self.conn.executemany(
                    "INSERT INTO filters (timestamp, filter_name, score, flag, metrics) VALUES (?, ?, ?, ?, ?)",
                    filter_rows)
            if trade_rows:
                self.conn.executemany(
                    "INSERT INTO trades (timestamp, direction, quantity, entry_price, simulated, failed, reason, order_data) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", trade_rows)

    def query(self, sql: str, params: tuple = ()) -> List[tuple]:
        with self.lock:
            return self.conn.execute(sql, params).fetchall()


_stores: Dict[str, _SqliteStore] = {}
_stores_lock = threading.Lock()


def _store_for(path: str) -> _SqliteStore:
    abs_path = os.path.abspath(path)
    with _stores_lock:
        store = _stores.get(abs_path)
        if store is None:
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            store = _SqliteStore(abs_path)
            _stores[abs_path] = store
        return store


def _filter_row(report: Dict[str, Any]) -> tuple:
    return (_utc_now_iso(), report.get("filter_name", "Unknown"), report.get("score", 0.0),
            report.get("flag", "N/A"), json.dumps(report.get("metrics", {})))


def _trade_row(trade: Dict[str, Any]) -> tuple:
    return (_utc_now_iso(), trade.get("direction", "N/A"), trade.get("quantity", 0.0), trade.get("entry_price", 0.0),
            trade.get("simulated", False), trade.get("failed", False), trade.get("reason", ""),
            json.dumps(trade.get("order_data", {})))


class MemoryTracker:
    """Persists filter reports and trade records to SQLite without blocking the event loop.

    Filter-report history is OFF unless MEMORY_FILTER_HISTORY=true: at a 0.2 s cycle it is
    ~45 rows/s of write-only data (nothing in the bot reads it back), and each row used to be
    its own fsync'd commit on the event loop."""

    def __init__(self, config: Config):
        self.config = config
        self.db_file = config.memory_db_path
        self._store = _store_for(self.db_file)
        logger.debug("MemoryTracker initialized with DB: %s", self.db_file)

    @property
    def filter_history_enabled(self) -> bool:
        return bool(getattr(self.config, "memory_filter_history", False))

    async def _write(self, filter_rows: List[tuple], trade_rows: List[tuple]) -> None:
        """Off-loop write. A storage failure is logged, never raised: a history write must
        not stall the trading cycle (the engine sleeps 60 s on an escaped exception)."""
        try:
            await asyncio.to_thread(self._store.write, filter_rows, trade_rows)
        except sqlite3.Error as e:
            logger.error("MemoryTracker write failed (%d filter rows, %d trade rows): %r",
                         len(filter_rows), len(trade_rows), e)

    async def update_filter_reports(self, reports: List[Dict[str, Any]]) -> None:
        """Persist a whole cycle's filter reports in ONE transaction, off-loop."""
        if not self.filter_history_enabled or not reports:
            return
        await self._write([_filter_row(r) for r in reports if isinstance(r, dict)], [])

    async def update_memory(self, filter_report: Optional[Dict[str, Any]] = None,
                            trade_data: Optional[Dict[str, Any]] = None) -> None:
        """Updates the database with real-time filter or trade data (off-loop)."""
        filter_rows = [_filter_row(filter_report)] if filter_report and self.filter_history_enabled else []
        trade_rows = [_trade_row(trade_data)] if trade_data else []
        if not filter_rows and not trade_rows:
            return
        await self._write(filter_rows, trade_rows)
        logger.debug("Memory database updated.")

    def get_memory(self) -> Dict[str, Any]:
        """Retrieves all filter and trade history from the database."""
        filters = [{"timestamp": r[0], "filter": r[1], "score": r[2], "flag": r[3], "metrics": json.loads(r[4])}
                   for r in self._store.query("SELECT timestamp, filter_name, score, flag, metrics FROM filters")]
        trades = [{"timestamp": r[0], "direction": r[1], "quantity": r[2], "entry_price": r[3], "simulated": bool(r[4]),
                   "failed": bool(r[5]), "reason": r[6], "order_data": json.loads(r[7])}
                  for r in self._store.query(
                      "SELECT timestamp, direction, quantity, entry_price, simulated, failed, reason, order_data FROM trades")]
        return {"last_updated": _utc_now_iso(), "filters": filters, "trades": trades}

    def get_similar_scenarios(self, current_state: Dict[str, Any], top_n: int = 5) -> List[Dict[str, Any]]:
        """Finds scenarios in memory that are similar to the current market state using vector similarity."""
        past_scenarios = [{"id": row[0], "metrics": json.loads(row[1])}
                          for row in self._store.query("SELECT id, metrics FROM filters")]

        current_metrics = current_state.get("validator_audit_log", {}).get("CtsFilter", {}).get("metrics", {})
        current_vector = np.array([current_metrics.get("grind_ratio", 0.0), current_metrics.get("wick_strength_ratio", 0.0)])
        if np.linalg.norm(current_vector) == 0:
            return []

        similarities = []
        for scenario in past_scenarios:
            past_metrics = scenario.get("metrics", {})
            past_vector = np.array([past_metrics.get("grind_ratio", 0.0), past_metrics.get("wick_strength_ratio", 0.0)])
            if np.linalg.norm(past_vector) > 0:
                similarity = np.dot(current_vector, past_vector) / (np.linalg.norm(current_vector) * np.linalg.norm(past_vector))
                similarities.append((scenario["id"], similarity))

        similarities.sort(key=lambda x: x[1], reverse=True)
        top_ids = [scenario_id for scenario_id, _ in similarities[:top_n]]
        if not top_ids:
            return []
        placeholders = ",".join("?" for _ in top_ids)
        rows = self._store.query(
            f"SELECT timestamp, filter_name, score, flag, metrics FROM filters WHERE id IN ({placeholders})", tuple(top_ids))
        return [{"timestamp": r[0], "filter": r[1], "score": r[2], "flag": r[3], "metrics": json.loads(r[4])} for r in rows]
