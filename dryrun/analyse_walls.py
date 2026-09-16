#!/usr/bin/env python3
"""Does a whale wall predict anything? Tests the TrapX thesis against recorded wall events.

For each wall: when it appeared, which side, how big, how far from mid, how it ended (absorbed / pulled /
faded) and where the mid went 1/5/15/30 minutes later. Reports the average move after each kind of wall
event and whether it clears the fee — the only test that matters.
"""
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

WALLS = Path.home() / "trading_core_project" / "dryrun" / "walls.jsonl"
FEE_MAKER, FEE_TAKER = 0.04, 0.16


def summarise(label, moves, sign):
    """sign: +1 if the thesis says price should RISE after this event, -1 if fall."""
    if len(moves) < 10:
        return f"  {label:<34s} n={len(moves):<4d} (too few)"
    signed = [sign * m for m in moves]
    mean = statistics.mean(signed)
    hit = 100 * sum(1 for m in signed if m > 0) / len(signed)
    verdict = "EDGE" if mean > FEE_MAKER else ("weak" if mean > 0 else "none")
    return (f"  {label:<34s} n={len(moves):<4d} mean {mean:+.4f}%  in-favour {hit:4.1f}%  "
            f"vs maker fee {FEE_MAKER}% → {verdict}")


def main():
    if not WALLS.exists():
        print("no walls recorded yet"); return 1
    rows = [json.loads(l) for l in WALLS.read_text().splitlines() if l.strip()]
    if not rows:
        print("walls.jsonl is empty"); return 1
    print(f"{len(rows)} resolved whale walls\n")
    lifetimes = [r["lifetime_s"] for r in rows]
    print(f"lifetime: median {statistics.median(lifetimes):.0f}s  max {max(lifetimes):.0f}s")
    print(f"outcomes: {dict((k, sum(1 for r in rows if r['outcome']==k)) for k in ('absorbed','pulled','faded'))}")
    print(f"sides:    bid {sum(1 for r in rows if r['side']=='bid')}  ask {sum(1 for r in rows if r['side']=='ask')}")
    print(f"size:     median share of side depth {100*statistics.median(r['peak_share'] for r in rows):.1f}%")

    for hz in (60, 300, 900, 1800):
        key = f"move_after_{hz}s_pct"
        have = [r for r in rows if r.get(key) is not None]
        if not have:
            continue
        print(f"\n=== {hz//60} minutes after the wall appeared ({len(have)} walls) ===")
        # Thesis A: a wall is support/resistance → price moves AWAY from it
        #   bid wall (below) should push price UP (+1); ask wall (above) should push price DOWN (-1)
        for side, sign, name in (("bid", +1, "bid wall → price up (support)"), ("ask", -1, "ask wall → price down (resistance)")):
            moves = [r[key] for r in have if r["side"] == side]
            print(summarise(name, moves, sign))
        # Thesis B (TrapX): a PULLED wall was a trap → price goes THROUGH where it was
        for side, sign, name in (("bid", -1, "PULLED bid wall → price falls"), ("ask", +1, "PULLED ask wall → price rises")):
            moves = [r[key] for r in have if r["side"] == side and r["outcome"] == "pulled"]
            print(summarise(name, moves, sign))
        # Thesis C: an ABSORBED wall means real demand/supply was there → continuation through it
        for side, sign, name in (("bid", -1, "ABSORBED bid wall → price falls"), ("ask", +1, "ABSORBED ask wall → price rises")):
            moves = [r[key] for r in have if r["side"] == side and r["outcome"] == "absorbed"]
            print(summarise(name, moves, sign))
    print(f"\nA result only matters if the mean move exceeds the fee it must pay: "
          f"maker {FEE_MAKER}%, taker {FEE_TAKER}%.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
