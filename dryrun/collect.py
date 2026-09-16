#!/usr/bin/env python3
"""Dry-run data collector for TradingCore. Every run appends ONE JSON line to
~/trading_core_project/dryrun/samples.jsonl with: the bot's /stats, the model server's health,
counts of new rejection reasons since the last sample, AI verdict latency/actions since the last
sample, and GPU memory. Designed for a systemd timer; safe to run by hand."""
import json
import os
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path.home() / "trading_core_project" / "TradingCore"
OUT_DIR = Path.home() / "trading_core_project" / "dryrun"
SAMPLES = OUT_DIR / "samples.jsonl"
CURSOR = OUT_DIR / ".cursor.json"          # byte offsets into the two logs we tail
FAILED = REPO / "logs" / "failed_signals.json"
AI_LOG = REPO / "logs" / "ai_model.log"


def http_json(url, timeout=5.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:  # noqa: BLE001
        return {"error": repr(e)}


def read_new_lines(path: Path, key: str, cursor: dict):
    if not path.exists():
        return []
    size = path.stat().st_size
    start = cursor.get(key, 0)
    if start > size:      # rotated / truncated
        start = 0
    with path.open("rb") as f:
        f.seek(start)
        data = f.read()
    cursor[key] = start + len(data)
    return [line for line in data.decode("utf-8", "replace").splitlines() if line.strip()]


def reason_bucket(reason: str) -> str:
    """Collapse free text so counts aggregate: 'Rejected - AI CONFIDENCE LOW (0.40/0.7)' → 'AI CONFIDENCE LOW';
    'Primary Gate: CTS_BLOCK' is kept whole; STALE… / REVERSAL RISK are cut at the colon (numbers vary)."""
    r = reason.replace("Rejected - ", "").split(" (", 1)[0].strip()
    if r.startswith(("STALE", "REVERSAL RISK", "NO ENTRY PRICE", "POSITION OPEN")):
        r = r.split(":", 1)[0].split(" (", 1)[0].strip()
    return r


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cursor = json.loads(CURSOR.read_text()) if CURSOR.exists() else {}
    sample = {"ts": datetime.now(timezone.utc).isoformat(), "stats": http_json("http://127.0.0.1:8000/stats"),
              "model_health": http_json("http://127.0.0.1:8081/health")}
    rejections = Counter()
    for line in read_new_lines(FAILED, "failed", cursor):
        try:
            rejections[reason_bucket(json.loads(line).get("reason", "?"))] += 1
        except json.JSONDecodeError:
            rejections["<unparsable>"] += 1
    sample["rejections_since_last"] = dict(rejections)
    verdicts, latencies = Counter(), []
    for line in read_new_lines(AI_LOG, "ai", cursor):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("type") == "latency":
            latencies.append(float(rec.get("latency_ms", 0)))
        elif rec.get("type") in ("api_verdict", "fallback", "timeout", "api_error", "error"):
            verdicts[f"{rec['type']}:{(rec.get('verdict') or {}).get('action', '?')}"] += 1
    latencies.sort()
    sample["verdicts_since_last"] = dict(verdicts)
    sample["verdict_latency_ms"] = ({"n": len(latencies), "median": latencies[len(latencies) // 2],
                                     "p95": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))], "max": latencies[-1]}
                                    if latencies else {"n": 0})
    try:
        gpu = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        used, util = gpu.split(",")
        sample["gpu"] = {"mem_mib": int(used), "util_pct": int(util)}
    except Exception:  # noqa: BLE001
        sample["gpu"] = None
    for unit in ("tradingcore.service", "llama-server@trading.service"):
        sample[unit] = subprocess.run(["systemctl", "--user", "is-active", unit], capture_output=True, text=True).stdout.strip()
    with SAMPLES.open("a") as f:
        f.write(json.dumps(sample) + "\n")
    CURSOR.write_text(json.dumps(cursor))
    print(json.dumps({k: sample[k] for k in ("ts", "rejections_since_last", "verdicts_since_last", "verdict_latency_ms", "gpu")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
