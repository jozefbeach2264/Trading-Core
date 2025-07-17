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
        self.base_path = "logs/filters/"
        self.db_file = os.path.join("logs", "memory_tracker.db")
        self.filter_logs = [
            config.cts_filter_log_path,
            config.retest_logic_log_path,
            config.breakout_filter_log_path,
            config.orderbook_reversal_log_path
        ]
        self.trade_logs = [
            config.log_file_path,
            config.simulation_state_file_path,
            config.failed_signals_path
        ]
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
            cursor.execute("DELETE FROM filters WHERE timestamp < datetime('now', '-30 days')")
            cursor.execute("DELETE FROM trades WHERE timestamp < datetime('now', '-30 days')")
            conn.commit()

    def _parse_filter_log(self, log_path: str) -> List[Dict[str, Any]]:
        entries = []
        if not os.path.exists(log_path):
            logger.debug("Filter log not found: %s", log_path)
            return entries
        try:
            with open(log_path, "r") as f:
                for line in f:
                    if "report generated: score=" in line or "report: score=" in line:
                        try:
                            metrics_start = line.find("metrics=") + 8
                            metrics_end = line.rfind("}")
                            metrics = json.loads(line[metrics_start:metrics_end + 1])
                            timestamp = line[:19]
                            score = float(line[line.find("score=") + 6:line.find(",", line.find("score="))])
                            flag = line[line.find("flag=") + 5:line.find(",", line.find("flag="))].strip("'")
                            filter_name = line[line.find(" - ") + 3:line.find(" - ", line.find(" - ") + 1)]
                            entries.append({
                                "timestamp": timestamp,
                                "filter": filter_name,
                                "score": score,
                                "flag": flag,
                                "metrics": metrics
                            })
                        except (json.JSONDecodeError, ValueError) as e:
                            logger.error("Error parsing filter log %s: %s", log_path, e)
        except Exception as e:
            logger.error("Failed to read filter log %s: %s", log_path, e)
        return entries

    def _parse_trade_logs(self) -> List[Dict[str, Any]]:
        trades = []
        if os.path.exists(self.config.log_file_path):
            try:
                with open(self.config.log_file_path, "r") as f:
                    for line in f:
                        if "Successfully placed" in line or "SIMULATION: " in line:
                            try:
                                timestamp = line[:19]
                                direction = line[line.find("direction: ") + 11:line.find(" ", line.find("direction: ") + 11)] if "direction: " in line else line[line.find("placed ") + 7:line.find(" order:")]
                                trade_data = {"timestamp": timestamp, "direction": direction}
                                if "order: {" in line:
                                    json_start = line.find("order: {") + 7
                                    json_end = line.rfind("}")
                                    trade_json = json.loads(line[json_start:json_end + 1])
                                    trade_data.update({"order_data": trade_json})
                                trades.append(trade_data)
                            except (json.JSONDecodeError, ValueError) as e:
                                logger.error("Error parsing system log trade: %s", e)
            except Exception as e:
                logger.error("Failed to read system log %s: %s", self.config.log_file_path, e)

        if os.path.exists(self.config.simulation_state_file_path):
            try:
                with open(self.config.simulation_state_file_path, "r") as f:
                    sim_data = json.load(f)
                    for trade in sim_data.get("history", []):
                        trades.append({
                            "timestamp": trade["timestamp"],
                            "direction": trade["direction"],
                            "quantity": trade["quantity"],
                            "entry_price": trade["entry_price"],
                            "simulated": True
                        })
            except (json.JSONDecodeError, IOError) as e:
                logger.error("Error parsing simulation state %s: %s", self.config.simulation_state_file_path, e)

        if os.path.exists(self.config.failed_signals_path):
            try:
                with open(self.config.failed_signals_path, "r") as f:
                    failed_signals = json.load(f)
                    for signal in failed_signals:
                        trades.append({
                            "timestamp": signal.get("timestamp", datetime.utcnow().isoformat() + "Z"),
                            "direction": signal.get("direction", "N/A"),
                            "reason": signal.get("reason", "Unknown"),
                            "failed": True
                        })
            except (json.JSONDecodeError, IOError) as e:
                logger.error("Error parsing failed signals %s: %s", self.config.failed_signals_path, e)

        return trades

    async def update_memory(self, filter_report: Dict[str, Any] = None, trade_data: Dict[str, Any] = None):
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            if filter_report:
                cursor.execute('''
                    INSERT INTO filters (timestamp, filter_name, score, flag, metrics)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    datetime.utcnow().isoformat() + "Z",
                    filter_report.get("filter_name", "Unknown"),
                    filter_report.get("score", 0.0),
                    filter_report.get("flag", "❌ Block"),
                    json.dumps(filter_report.get("metrics", {}))
                ))
            if trade_data:
                cursor.execute('''
                    INSERT INTO trades (timestamp, direction, quantity, entry_price, simulated, failed, reason, order_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    datetime.utcnow().isoformat() + "Z",
                    trade_data.get("direction", "N/A"),
                    trade_data.get("quantity", 0.0),
                    trade_data.get("entry_price", 0.0),
                    trade_data.get("simulated", False),
                    trade_data.get("failed", False),
                    trade_data.get("reason", ""),
                    json.dumps(trade_data.get("order_data", {}))
                ))
            cursor.execute("DELETE FROM filters WHERE timestamp < datetime('now', '-30 days')")
            cursor.execute("DELETE FROM trades WHERE timestamp < datetime('now', '-30 days')")
            conn.commit()
        logger.debug("Memory updated in DB: %s", self.db_file)

    def get_memory(self) -> Dict[str, Any]:
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT timestamp, filter_name, score, flag, metrics FROM filters")
            filters = [{"timestamp": r[0], "filter": r[1], "score": r[2], "flag": r[3], "metrics": json.loads(r[4])} for r in cursor.fetchall()]
            cursor.execute("SELECT timestamp, direction, quantity, entry_price, simulated, failed, reason, order_data FROM trades")
            trades = [{"timestamp": r[0], "direction": r[1], "quantity": r[2], "entry_price": r[3], "simulated": bool(r[4]), "failed": bool(r[5]), "reason": r[6], "order_data": json.loads(r[7])} for r in cursor.fetchall()]
        return {"last_updated": datetime.utcnow().isoformat() + "Z", "filters": filters, "trades": trades}

    def get_similar_scenarios(self, current_state: Dict[str, Any], top_n: int = 5) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT metrics FROM filters")
            past_metrics = [json.loads(row[0]) for row in cursor.fetchall()]
        
        current_metrics = current_state.get("metrics", {})
        current_vector = [
            current_metrics.get("mark_price", 0.0),
            current_metrics.get("grind_ratio", 0.0),
            current_metrics.get("wick_strength_ratio", 0.0),
            current_metrics.get("bid_pressure", 0.0),
            current_metrics.get("ask_pressure", 0.0)
        ]
        similarities = []
        for i, past in enumerate(past_metrics):
            past_vector = [
                past.get("mark_price", 0.0),
                past.get("grind_ratio", 0.0),
                past.get("wick_strength_ratio", 0.0),
                past.get("bid_pressure", 0.0),
                past.get("ask_pressure", 0.0)
            ]
            try:
                current_norm = np.linalg.norm(current_vector)
                past_norm = np.linalg.norm(past_vector)
                if current_norm > 0 and past_norm > 0:
                    similarity = np.dot(current_vector, past_vector) / (current_norm * past_norm)
                    similarities.append((i, similarity))
            except Exception as e:
                logger.error("Error calculating similarity: %s", e)
        
        similarities.sort(key=lambda x: x[1], reverse=True)
        top_indices = [i for i, _ in similarities[:top_n]]
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT timestamp, filter_name, score, flag, metrics FROM filters")
            rows = cursor.fetchall()
            return [{"timestamp": r[0], "filter": r[1], "score": r[2], "flag": r[3], "metrics": json.loads(r[4])} for i, r in enumerate(rows) if i in top_indices]