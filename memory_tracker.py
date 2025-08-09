import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from config.config import Config
from psycopg_pool import ConnectionPool
import psycopg

logger = logging.getLogger(__name__)


def _iso_or_none(raw) -> Optional[str]:
    """Normalize various timestamp inputs into ISO8601 'Z' or None."""
    if raw is None:
        return None
    try:
        if isinstance(raw, (int, float)) or (isinstance(raw, str) and raw.isdigit()):
            return datetime.fromtimestamp(int(raw) / 1000).isoformat() + "Z"
        return str(raw)
    except Exception:
        return str(raw)


def _to_ts(val: Optional[str]) -> Optional[str]:
    """Convert '...Z' ISO into RFC3339 '+00:00' so PG timestamptz accepts it."""
    if not val:
        return None
    try:
        return val[:-1] + "+00:00" if val.endswith("Z") else val
    except Exception:
        return None


def _ensure_pg_schema(conn: psycopg.Connection) -> None:
    """
    Permanent, idempotent schema guard. Safe to run on every boot.
    Creates all MemoryTracker tables and indexes if missing.
    """
    with conn.cursor() as cur:
        # mt_filters
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.mt_filters (
                id               BIGSERIAL PRIMARY KEY,
                module_timestamp TIMESTAMPTZ,
                candle_timestamp TIMESTAMPTZ,
                filter_name      TEXT NOT NULL,
                score            DOUBLE PRECISION,
                flag             TEXT,
                metrics          JSONB,
                created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_mt_filters_candle_ts
            ON public.mt_filters (candle_timestamp);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_mt_filters_filter_name
            ON public.mt_filters (filter_name);
        """)

        # mt_trades
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.mt_trades (
                id               BIGSERIAL PRIMARY KEY,
                module_timestamp TIMESTAMPTZ,
                candle_timestamp TIMESTAMPTZ,
                direction        TEXT,
                quantity         DOUBLE PRECISION,
                entry_price      DOUBLE PRECISION,
                simulated        BOOLEAN,
                failed           BOOLEAN,
                reason           TEXT,
                order_data       JSONB,
                ai_verdict       JSONB,
                created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_mt_trades_candle_ts
            ON public.mt_trades (candle_timestamp);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_mt_trades_created_at
            ON public.mt_trades (created_at);
        """)

        # mt_verdicts
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.mt_verdicts (
                id               BIGSERIAL PRIMARY KEY,
                module_timestamp TIMESTAMPTZ,
                candle_timestamp TIMESTAMPTZ,
                direction        TEXT,
                entry_price      DOUBLE PRECISION,
                verdict          TEXT,
                confidence       DOUBLE PRECISION,
                reason           TEXT,
                created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_mt_verdicts_candle_ts
            ON public.mt_verdicts (candle_timestamp);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_mt_verdicts_created_at
            ON public.mt_verdicts (created_at);
        """)

    conn.commit()


class MemoryTracker:
    """
    PostgreSQL-backed MemoryTracker using psycopg3 ConnectionPool.
    - Async update_memory(...) API preserved (awaited by callers).
    - Per-row INSERTs (simple & reliable).
    - get_counts() / get_recent_trades() read directly from PG.
    """

    def __init__(self, config: Config):
        self.config = config

        dsn = os.getenv("POSTGRES_DSN")
        if not dsn:
            raise RuntimeError("POSTGRES_DSN is not set")

        min_size = int(os.getenv("PG_POOL_MIN", "1"))
        max_size = int(os.getenv("PG_POOL_MAX", "5"))

        # autocommit=True so each execute is its own transaction (simple + safe).
        self.pool = ConnectionPool(
            conninfo=dsn,
            min_size=min_size,
            max_size=max_size,
            kwargs={"autocommit": True},
        )
        logger.info("MemoryTracker: PostgreSQL pool initialized.")

        # === Bulletproof: ensure schema exists at boot ===
        with self.pool.connection() as _conn:
            _ensure_pg_schema(_conn)

    async def update_memory(
        self,
        filter_report: Optional[Dict[str, Any]] = None,
        trade_data: Optional[Dict[str, Any]] = None,
        verdict_data: Optional[Dict[str, Any]] = None,
    ):
        """
        Async signature retained for compatibility; operations are sync via pool.
        """
        module_ts_iso = datetime.utcnow().isoformat() + "Z"

        try:
            with self.pool.connection() as conn, conn.cursor() as cur:
                if filter_report:
                    cur.execute(
                        """
                        INSERT INTO mt_filters
                        (module_timestamp, candle_timestamp, filter_name, score, flag, metrics)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            _to_ts(module_ts_iso),
                            _to_ts(_iso_or_none(filter_report.get("candle_timestamp"))),
                            filter_report.get("filter_name", "Unknown"),
                            float(filter_report.get("score", 0.0) or 0.0),
                            filter_report.get("flag", "N/A"),
                            psycopg.types.json.Json(filter_report.get("metrics", {}) or {}),
                        ),
                    )

                if trade_data:
                    cur.execute(
                        """
                        INSERT INTO mt_trades
                        (module_timestamp, candle_timestamp, direction, quantity, entry_price,
                         simulated, failed, reason, order_data, ai_verdict)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            _to_ts(module_ts_iso),
                            _to_ts(_iso_or_none(trade_data.get("candle_timestamp"))),
                            trade_data.get("direction", "N/A"),
                            float(trade_data.get("quantity", 0.0) or 0.0),
                            float(trade_data.get("entry_price", 0.0) or 0.0),
                            bool(trade_data.get("simulated", False)),
                            bool(trade_data.get("failed", False)),
                            trade_data.get("reason", ""),
                            psycopg.types.json.Json(trade_data.get("order_data", {}) or {}),
                            psycopg.types.json.Json(trade_data.get("ai_verdict", {}) or {}),
                        ),
                    )

                if verdict_data:
                    cur.execute(
                        """
                        INSERT INTO mt_verdicts
                        (module_timestamp, candle_timestamp, direction, entry_price, verdict, confidence, reason)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            _to_ts(module_ts_iso),
                            _to_ts(_iso_or_none(verdict_data.get("candle_timestamp"))),
                            verdict_data.get("direction", "N/A"),
                            float(verdict_data.get("entry_price", 0.0) or 0.0),
                            verdict_data.get("verdict", "None"),
                            float(verdict_data.get("confidence", 0.0) or 0.0),
                            verdict_data.get("reason", "N/A"),
                        ),
                    )
        except Exception as e:
            logger.error("MemoryTracker.update_memory failed", extra={"error": str(e)}, exc_info=True)

    def get_memory(self) -> Dict[str, Any]:
        """
        Compatibility method: returns full sets (use sparingly).
        """
        out = {"last_updated": datetime.utcnow().isoformat() + "Z", "filters": [], "trades": [], "verdicts": []}
        try:
            with self.pool.connection() as conn, conn.cursor() as cur:
                cur.execute("SELECT module_timestamp, candle_timestamp, filter_name, score, flag, metrics FROM mt_filters")
                for r in cur.fetchall():
                    out["filters"].append(
                        {
                            "module_timestamp": r[0].isoformat().replace("+00:00", "Z") if r[0] else None,
                            "candle_timestamp": r[1].isoformat().replace("+00:00", "Z") if r[1] else None,
                            "filter": r[2],
                            "score": r[3],
                            "flag": r[4],
                            "metrics": r[5],
                        }
                    )

                cur.execute(
                    """
                    SELECT module_timestamp, candle_timestamp, direction, quantity, entry_price,
                           simulated, failed, reason, order_data, ai_verdict
                    FROM mt_trades
                    """
                )
                for r in cur.fetchall():
                    out["trades"].append(
                        {
                            "module_timestamp": r[0].isoformat().replace("+00:00", "Z") if r[0] else None,
                            "candle_timestamp": r[1].isoformat().replace("+00:00", "Z") if r[1] else None,
                            "direction": r[2],
                            "quantity": r[3],
                            "entry_price": r[4],
                            "simulated": bool(r[5]),
                            "failed": bool(r[6]),
                            "reason": r[7],
                            "order_data": r[8],
                            "ai_verdict": r[9],
                        }
                    )

                cur.execute("SELECT module_timestamp, candle_timestamp, direction, entry_price, verdict, confidence, reason FROM mt_verdicts")
                for r in cur.fetchall():
                    out["verdicts"].append(
                        {
                            "module_timestamp": r[0].isoformat().replace("+00:00", "Z") if r[0] else None,
                            "candle_timestamp": r[1].isoformat().replace("+00:00", "Z") if r[1] else None,
                            "direction": r[2],
                            "entry_price": r[3],
                            "verdict": r[4],
                            "confidence": r[5],
                            "reason": r[6],
                        }
                    )
        except Exception as e:
            logger.error("MemoryTracker.get_memory failed", extra={"error": str(e)}, exc_info=True)
        return out

    def get_counts(self) -> Dict[str, Any]:
        try:
            with self.pool.connection() as conn, conn.cursor() as cur:
                cur.execute("SELECT COUNT(*), MAX(module_timestamp) FROM mt_filters")
                f_count, f_last = cur.fetchone()

                cur.execute("SELECT COUNT(*), MAX(module_timestamp) FROM mt_trades")
                t_count, t_last = cur.fetchone()

                cur.execute("SELECT COUNT(*), MAX(module_timestamp) FROM mt_verdicts")
                v_count, v_last = cur.fetchone()

            return {
                "filters_count": int(f_count or 0),
                "trades_count": int(t_count or 0),
                "verdicts_count": int(v_count or 0),
                "last_filter_ts": f_last.isoformat().replace("+00:00", "Z") if f_last else None,
                "last_trade_ts": t_last.isoformat().replace("+00:00", "Z") if t_last else None,
                "last_verdict_ts": v_last.isoformat().replace("+00:00", "Z") if v_last else None,
            }
        except Exception as e:
            logger.error("MemoryTracker.get_counts failed", extra={"error": str(e)}, exc_info=True)
            return {
                "filters_count": 0,
                "trades_count": 0,
                "verdicts_count": 0,
                "last_filter_ts": None,
                "last_trade_ts": None,
                "last_verdict_ts": None,
            }

    def get_recent_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        try:
            with self.pool.connection() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, module_timestamp, candle_timestamp, direction, quantity, entry_price,
                           simulated, failed, reason, order_data, ai_verdict
                    FROM mt_trades
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (int(limit),),
                )
                rows = cur.fetchall()

            trades = []
            for r in rows:
                trades.append(
                    {
                        "id": r[0],
                        "module_timestamp": r[1].isoformat().replace("+00:00", "Z") if r[1] else None,
                        "candle_timestamp": r[2].isoformat().replace("+00:00", "Z") if r[2] else None,
                        "direction": r[3],
                        "quantity": r[4],
                        "entry_price": r[5],
                        "simulated": bool(r[6]),
                        "failed": bool(r[7]),
                        "reason": r[8],
                        "order_data": r[9],
                        "ai_verdict": r[10],
                    }
                )
            return trades
        except Exception as e:
            logger.error("MemoryTracker.get_recent_trades failed", extra={"error": str(e)}, exc_info=True)
            return []

    # Placeholder to preserve your API surface; implement when needed.
    def get_similar_scenarios(self, current_state: Dict[str, Any], top_n: int = 5) -> List[Dict[str, Any]]:
        return []