#!/usr/bin/env python3
"""Summarise samples.jsonl: uptime, cycle rejection mix, verdict mix and latency, sim scoreboard trend."""
import json
import sys
from collections import Counter
from pathlib import Path

SAMPLES = Path.home() / "trading_core_project" / "dryrun" / "samples.jsonl"


def main() -> int:
    rows = [json.loads(l) for l in SAMPLES.read_text().splitlines() if l.strip()] if SAMPLES.exists() else []
    if not rows:
        print("no samples yet"); return 1
    rej, ver = Counter(), Counter()
    lat = []
    down = Counter()
    for r in rows:
        rej.update(r.get("rejections_since_last", {}))
        ver.update(r.get("verdicts_since_last", {}))
        l = r.get("verdict_latency_ms") or {}
        if l.get("n"):
            lat.append((l["n"], l["median"], l["p95"], l["max"]))
        for unit in ("tradingcore.service", "llama-server@trading.service"):
            if r.get(unit) != "active":
                down[unit] += 1
    first, last = rows[0], rows[-1]
    print(f"samples: {len(rows)}  from {first['ts']}  to {last['ts']}")
    print(f"unit samples not active: {dict(down) or 'none'}")
    total_rej = sum(rej.values())
    print(f"\nrejections (cycles): {total_rej}")
    for k, v in rej.most_common():
        print(f"  {v:7d}  {100*v/total_rej:5.1f}%  {k}")
    print(f"\nverdicts: {sum(ver.values())}")
    for k, v in ver.most_common():
        print(f"  {v:7d}  {k}")
    if lat:
        n = sum(x[0] for x in lat)
        med = sorted(x[1] for x in lat)[len(lat) // 2]
        print(f"\nverdict latency: n={n}  median-of-medians {med:.0f} ms  worst p95 {max(x[2] for x in lat):.0f} ms  max {max(x[3] for x in lat):.0f} ms")
    st = (last.get("stats") or {})
    print(f"\nsim: mode={st.get('mode')} balance={st.get('balance')} open={bool(st.get('open_position'))} "
          f"lifecycle={st.get('lifecycle')} mark={st.get('mark_price')} data_age={st.get('market_data_age_s')}s klines={st.get('klines')}")
    if st.get("stats"):
        print("stats:", json.dumps(st["stats"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
