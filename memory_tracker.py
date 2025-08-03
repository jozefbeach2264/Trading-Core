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
                    module_timestamp TEXT,
                    candle_timestamp TEXT,
                    filter_name TEXT,
                    score REAL,
                    flag TEXT,
                    metrics TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    module_timestamp TEXT,
                    candle_timestamp TEXT,
                    direction TEXT,
                    quantity REAL,
                    entry_price REAL,
                    simulated BOOLEAN,
                    failed BOOLEAN,
                    reason TEXT,
                    order_data TEXT,
                    ai_verdict TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS verdicts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    module_timestamp TEXT,
                    candle_timestamp TEXT,
                    direction TEXT,
                    entry_price REAL,
                    verdict TEXT,
                    confidence REAL,
                    reason TEXT
                )
            ''')

            # Patch: Ensure ai_verdict column exists (backward compatibility)
            try:
                cursor.execute("SELECT ai_verdict FROM trades LIMIT 1")
            except sqlite3.OperationalError:
                cursor.execute("ALTER TABLE trades ADD COLUMN ai_verdict TEXT")

            cursor.execute('CREATE INDEX IF NOT EXISTS idx_filters_module_ts ON filters (module_timestamp);')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_filters_candle_ts ON filters (candle_timestamp);')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_module_ts ON trades (module_timestamp);')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_candle_ts ON trades (candle_timestamp);')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_verdicts_module_ts ON verdicts (module_timestamp);')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_verdicts_candle_ts ON verdicts (candle_timestamp);')

            cursor.execute("DELETE FROM filters WHERE module_timestamp < datetime('now', '-30 days')")
            cursor.execute("DELETE FROM trades WHERE module_timestamp < datetime('now', '-30 days')")
            cursor.execute("DELETE FROM verdicts WHERE module_timestamp < datetime('now', '-30 days')")
            conn.commit()

    async def update_memory(self, filter_report: Dict[str, Any] = None, trade_data: Dict[str, Any] = None, verdict_data: Dict[str, Any] = None):
        module_ts = datetime.utcnow().isoformat() + "Z"

        def resolve_cts(obj: Dict[str, Any]) -> str:
            raw = obj.get("candle_timestamp")
            if raw is None:
                return "N/A"
            try:
                return datetime.fromtimestamp(int(raw) / 1000).isoformat() + "Z"
            except:
                return str(raw)

        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()

            if filter_report:
                cursor.execute('''
                    INSERT INTO filters (module_timestamp, candle_timestamp, filter_name, score, flag, metrics)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    module_ts,
                    resolve_cts(filter_report),
                    filter_report.get("filter_name", "Unknown"),
                    filter_report.get("score", 0.0),
                    filter_report.get("flag", "N/A"),
                    json.dumps(filter_report.get("metrics", {}))
                ))

            if trade_data:
                cursor.execute('''
                    INSERT INTO trades (
                        module_timestamp, candle_timestamp, direction, quantity,
                        entry_price, simulated, failed, reason, order_data, ai_verdict
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    module_ts,
                    resolve_cts(trade_data),
                    trade_data.get("direction", "N/A"),
                    trade_data.get("quantity", 0.0),
                    trade_data.get("entry_price", 0.0),
                    trade_data.get("simulated", False),
                    trade_data.get("failed", False),
                    trade_data.get("reason", ""),
                    json.dumps(trade_data.get("order_data", {})),
                    json.dumps(trade_data.get("ai_verdict", {}))
                ))

            if verdict_data:
                cursor.execute('''
                    INSERT INTO verdicts (module_timestamp, candle_timestamp, direction, entry_price, verdict, confidence, reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    module_ts,
                    resolve_cts(verdict_data),
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
            cursor.execute("SELECT module_timestamp, candle_timestamp, filter_name, score, flag, metrics FROM filters")
            filters = [{
                "module_timestamp": r[0], "candle_timestamp": r[1],
                "filter": r[2], "score": r[3], "flag": r[4],
                "metrics": json.loads(r[5]) if r[5] else {}
            } for r in cursor.fetchall()]

            cursor.execute("SELECT module_timestamp, candle_timestamp, direction, quantity, entry_price, simulated, failed, reason, order_data, ai_verdict FROM trades")
            trades = [{
                "module_timestamp": r[0], "candle_timestamp": r[1], "direction": r[2],
                "quantity": r[3], "entry_price": r[4], "simulated": bool(r[5]),
                "failed": bool(r[6]), "reason": r[7],
                "order_data": json.loads(r[8]) if r[8] else {},
                "ai_verdict": json.loads(r[9]) if r[9] else {}
            } for r in cursor.fetchall()]

            cursor.execute("SELECT module_timestamp, candle_timestamp, direction, entry_price, verdict, confidence, reason FROM verdicts")
            verdicts = [{
                "module_timestamp": r[0], "candle_timestamp": r[1], "direction": r[2],
                "entry_price": r[3], "verdict": r[4], "confidence": r[5], "reason": r[6]
            } for r in cursor.fetchall()]

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
            past_scenarios = [{"id": row[0], "metrics": json.loads(row[1]) if row[1] else {}} for row in cursor.fetchall()]

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
            cursor.execute(f"SELECT module_timestamp, candle_timestamp, filter_name, score, flag, metrics FROM filters WHERE id IN ({placeholders})", top_ids)
            rows = cursor.fetchall()
            return [{
                "module_timestamp": r[0], "candle_timestamp": r[1], "filter": r[2],
                "score": r[3], "flag": r[4], "metrics": json.loads(r[5]) if r[5] else {}
            } for r in rows]