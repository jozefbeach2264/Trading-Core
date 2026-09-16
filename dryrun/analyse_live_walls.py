#!/usr/bin/env python3
"""Does a wall ending predict the next few minutes, ONCE MARKET DRIFT IS REMOVED?

The naive test is worthless: if the market rose during the sample, every "N minutes later" number looks
bullish whatever the wall did. The only wall-specific information is the DIFFERENCE between what follows a
bid-wall ending and what follows an ask-wall ending. Half that difference is what one side of a trade could
earn, and it must beat the fee to be worth anything.
"""
import json
import statistics
import sys
from pathlib import Path

SRC = Path(__file__).with_name("live_wall_test.jsonl")
FEE_MAKER, FEE_TAKER = 0.04, 0.16


def main():
    if not SRC.exists():
        print("no data yet"); return 1
    rows = [json.loads(l) for l in SRC.read_text().splitlines() if l.strip()]
    if not rows:
        print("empty"); return 1
    horizons = sorted({int(k.split("_")[1][:-1]) for r in rows for k in r if k.startswith("move_")})
    print(f"{len(rows):,} wall endings\n")
    print(f"{'setting':18s} {'horizon':>8s} {'n':>6s} {'drift':>9s} {'after bid':>10s} {'after ask':>10s} "
          f"{'wall signal':>12s} {'t':>6s} {'per side':>9s} {'vs maker':>9s}")
    for setting in sorted({r["setting"] for r in rows}):
        sub = [r for r in rows if r["setting"] == setting]
        for hz in horizons:
            key = f"move_{hz}s_pct"
            have = [r for r in sub if r.get(key) is not None]
            bid = [r[key] for r in have if r["side"] == "bid"]
            ask = [r[key] for r in have if r["side"] == "ask"]
            if len(bid) < 25 or len(ask) < 25:
                continue
            allm = [r[key] for r in have]
            drift = statistics.mean(allm)
            bm, am = statistics.mean(bid), statistics.mean(ask)
            diff = bm - am
            pooled = statistics.pstdev(allm)
            se = pooled * ((1 / len(bid) + 1 / len(ask)) ** 0.5)
            t = diff / se if se else 0.0
            per_side = abs(diff) / 2
            verdict = "CLEARS" if per_side > FEE_MAKER and abs(t) >= 2 else ("short" if abs(t) >= 2 else "noise")
            print(f"{setting:18s} {hz//60:6d}min {len(have):6d} {drift:+9.4f} {bm:+10.4f} {am:+10.4f} "
                  f"{diff:+12.4f} {t:+6.1f} {per_side:+9.4f} {verdict:>9s}")
    print(f"\n  'wall signal' = (move after a bid wall) - (move after an ask wall): the only drift-free measure.")
    print(f"  'per side' = half of it, what one leg of a trade could earn. It must beat maker {FEE_MAKER}% / taker {FEE_TAKER}%.")
    print(f"  t >= 2 or it is indistinguishable from chance.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
