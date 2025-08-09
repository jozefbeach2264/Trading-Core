# migrate_sqlite_to_pg.py
import sqlite3, os
from psycopg_pool import ConnectionPool
import psycopg
from datetime import datetime

SQLITE = "logs/memory_tracker.db"
PG_DSN = os.getenv("POSTGRES_DSN")

def iso(ts):
    if not ts or ts == "N/A": return None
    if ts.endswith("Z"): return ts[:-1] + "+00:00"
    return ts

pool = ConnectionPool(PG_DSN, min_size=1, max_size=2, kwargs={"autocommit": True})

with sqlite3.connect(SQLITE) as sconn, pool.connection() as pconn, pconn.cursor() as cur:
    scur = sconn.cursor()

    # filters
    for (m_ts, c_ts, name, score, flag, metrics) in scur.execute(
        "SELECT module_timestamp, candle_timestamp, filter_name, score, flag, metrics FROM filters"):
        cur.execute(
            "INSERT INTO mt_filters (module_timestamp, candle_timestamp, filter_name, score, flag, metrics) VALUES (%s,%s,%s,%s,%s,%s)",
            (iso(m_ts), iso(c_ts), name, float(score or 0), flag, psycopg.types.json.Json(json.loads(metrics or "{}")))
        )

    # trades
    for (m_ts, c_ts, direction, qty, entry_price, simulated, failed, reason, order_data, ai_verdict) in scur.execute(
        "SELECT module_timestamp, candle_timestamp, direction, quantity, entry_price, simulated, failed, reason, order_data, ai_verdict FROM trades"):
        cur.execute(
            "INSERT INTO mt_trades (module_timestamp, candle_timestamp, direction, quantity, entry_price, simulated, failed, reason, order_data, ai_verdict) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (iso(m_ts), iso(c_ts), direction, float(qty or 0), float(entry_price or 0),
             bool(simulated), bool(failed), reason or "",
             psycopg.types.json.Json(json.loads(order_data or "{}")),
             psycopg.types.json.Json(json.loads(ai_verdict or "{}")))
        )

    # verdicts
    for (m_ts, c_ts, direction, entry_price, verdict, confidence, reason) in scur.execute(
        "SELECT module_timestamp, candle_timestamp, direction, entry_price, verdict, confidence, reason FROM verdicts"):
        cur.execute(
            "INSERT INTO mt_verdicts (module_timestamp, candle_timestamp, direction, entry_price, verdict, confidence, reason) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (iso(m_ts), iso(c_ts), direction, float(entry_price or 0), verdict or "None", float(confidence or 0), reason or "N/A")
        )
print("Migration complete.")