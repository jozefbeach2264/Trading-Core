import os
import json
import logging
import sqlite3
from datetime import datetime
from typing import Dict, Any, List
import numpy as np
from config.config import Config

logger = logging.getLogger(__name__)

class MemoryTracker:
    def __init__(self, config: Config):
        self.config = config
        self.db_file = os.path.join("logs", "memory_tracker.db")
        os.makedirs(os.path.dirname(self.db_file), exist_ok=True)
        self._init_db()
        logger.debug("MemoryTracker initialized with DB: %s", self.db_file)

    def _init_db(self):
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS filters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    filter_name TEXT,
                    score REAL,
                    flag TEXT,
                    metrics TEXT
                )
            ''')
            cursor.execute('''
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
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS verdicts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    direction TEXT,
                    entry_price REAL,
                    verdict TEXT,
                    confidence REAL,
                    reason TEXT
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_filters_timestamp ON filters (timestamp);')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades (timestamp);')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_verdicts_timestamp ON verdicts (timestamp);')
            cursor.execute("DELETE FROM filters WHERE timestamp < datetime('now', '-30 days')")
            cursor.execute("DELETE FROM trades WHERE timestamp < datetime('now', '-30 days')")
            cursor.execute("DELETE FROM verdicts WHERE timestamp < datetime('now', '-30 days')")
            conn.commit()

    async def update_memory(self, filter_report: Dict[str, Any] = None, trade_data: Dict[str, Any] = None, verdict_data: Dict[str, Any] = None):
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            if filter_report:
                # Always generate a fresh timestamp with microsecond precision for database uniqueness
                timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f') + "Z"
                cursor.execute('''
                    INSERT INTO filters (timestamp, filter_name, score, flag, metrics)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    timestamp,
                    filter_report.get("filter_name", "Unknown"),
                    filter_report.get("score", 0.0),
                    filter_report.get("flag", "N/A"),
                    json.dumps(filter_report.get("metrics", {}))
                ))
            if trade_data:
                # Always generate a fresh timestamp with microsecond precision for database uniqueness
                timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f') + "Z"
                cursor.execute('''
                    INSERT INTO trades (timestamp, direction, quantity, entry_price, simulated, failed, reason, order_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    timestamp,
                    trade_data.get("direction", "N/A"),
                    trade_data.get("quantity", 0.0),
                    trade_data.get("entry_price", 0.0),
                    trade_data.get("simulated", False),
                    trade_data.get("failed", False),
                    trade_data.get("reason", ""),
                    json.dumps(trade_data.get("order_data", {}))
                ))
            if verdict_data:
                # Always generate a fresh timestamp with microsecond precision for database uniqueness
                timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f') + "Z"
                cursor.execute('''
                    INSERT INTO verdicts (timestamp, direction, entry_price, verdict, confidence, reason)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    timestamp,
                    verdict_data.get("direction", "N/A"),
                    verdict_data.get("entry_price", 0.0),
                    verdict_data.get("verdict", "None"),
                    float(verdict_data.get("confidence", 0.0)),
                    verdict_data.get("reason", "N/A")
                ))
            conn.commit()
        logger.debug("Memory database updated.")

    def get_memory(self) -> Dict[str, Any]:
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT timestamp, filter_name, score, flag, metrics FROM filters")
            filters = [{"timestamp": r[0], "filter": r[1], "score": r[2], "flag": r[3], "metrics": json.loads(r[4])} for r in cursor.fetchall()]
            cursor.execute("SELECT timestamp, direction, quantity, entry_price, simulated, failed, reason, order_data FROM trades")
            trades = [{"timestamp": r[0], "direction": r[1], "quantity": r[2], "entry_price": r[3], "simulated": bool(r[4]), "failed": bool(r[5]), "reason": r[6], "order_data": json.loads(r[7])} for r in cursor.fetchall()]
            cursor.execute("SELECT timestamp, direction, entry_price, verdict, confidence, reason FROM verdicts")
            verdicts = [{"timestamp": r[0], "direction": r[1], "entry_price": r[2], "verdict": r[3], "confidence": r[4], "reason": r[5]} for r in cursor.fetchall()]
        return {
            "last_updated": datetime.utcnow().isoformat() + "Z",
            "filters": filters,
            "trades": trades,
            "verdicts": verdicts
        }

    def get_similar_scenarios(self, current_state: Dict[str, Any], top_n: int = 5) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, metrics FROM filters")
            past_scenarios = [{"id": row[0], "metrics": json.loads(row[1])} for row in cursor.fetchall()]

        current_metrics = current_state.get("validator_audit_log", {}).get("CtsFilter", {}).get("metrics", {})
        current_vector = np.array([
            current_metrics.get("grind_ratio", 0.0),
            current_metrics.get("wick_strength_ratio", 0.0)
        ])

        if np.linalg.norm(current_vector) == 0:
            return []

        similarities = []
        for scenario in past_scenarios:
            past_metrics = scenario.get("metrics", {})
            past_vector = np.array([
                past_metrics.get("grind_ratio", 0.0),
                past_metrics.get("wick_strength_ratio", 0.0)
            ])
            if np.linalg.norm(past_vector) > 0:
                similarity = np.dot(current_vector, past_vector) / (np.linalg.norm(current_vector) * np.linalg.norm(past_vector))
                similarities.append((scenario["id"], similarity))

        similarities.sort(key=lambda x: x[1], reverse=True)
        top_ids = [id for id, _ in similarities[:top_n]]

        if not top_ids:
            return []

        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            placeholders = ','.join('?' for _ in top_ids)
            cursor.execute(f"SELECT timestamp, filter_name, score, flag, metrics FROM filters WHERE id IN ({placeholders})", top_ids)
            rows = cursor.fetchall()
            return [{"timestamp": r[0], "filter": r[1], "score": r[2], "flag": r[3], "metrics": json.loads(r[4])} for r in rows]