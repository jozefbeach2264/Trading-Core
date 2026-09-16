#!/usr/bin/env python3
"""Profitability AND accuracy of a dry run, separated — because they are different questions.

  PROFITABILITY  what the account actually did, and where the money went.
  ACCURACY       was each component RIGHT, judged against what price did next:
                   * the signal      — did price go the signal's way at all?
                   * the model       — did its Execute calls beat its Abort calls?
                   * the exits       — did winners run and losers get cut, or the reverse?
                   * the filters     — did a veto correctly avoid a bad trade?

usage: accuracy.py [--state logs/simulation_state.json]
"""
import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path.home() / "trading_core_project" / "TradingCore"


def pct(part, whole):
    return f"{100*part/whole:.1f}%" if whole else "n/a"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default=str(REPO / "logs" / "simulation_state.json"))
    a = ap.parse_args()
    state = json.load(open(a.state))
    hist = state.get("history", [])
    closes = [h for h in hist if h.get("event") == "close"]
    opens = [h for h in hist if h.get("event", "open") == "open"]
    start = float(state.get("initial_capital") or 100)
    bal = float(state.get("balance", start))

    print("=" * 68)
    print("PROFITABILITY")
    print("=" * 68)
    if not closes:
        print("  no closed trades yet"); return 0
    gross = sum(c["pnl"] for c in closes)
    fees = sum(c.get("fee", 0) for c in closes) * 2
    wins = [c for c in closes if c["pnl"] > 0]
    losses = [c for c in closes if c["pnl"] <= 0]
    print(f"  balance          {bal:8.2f}  of {start:.2f}   ({100*(bal-start)/start:+.1f}%)")
    print(f"  closed trades    {len(closes):8d}   ({len(opens)-len(closes)} still open)")
    print(f"  gross P&L        {gross:+8.2f}")
    print(f"  fees             {-fees:+8.2f}   ({abs(fees/gross):.1f}x the gross)" if gross else f"  fees {-fees:+8.2f}")
    print(f"  net              {gross-fees:+8.2f}")
    if wins:
        print(f"  average win      {statistics.mean(c['pnl'] for c in wins):+8.2f}  ({len(wins)} trades)")
    if losses:
        print(f"  average loss     {statistics.mean(c['pnl'] for c in losses):+8.2f}  ({len(losses)} trades)")
    if wins and losses:
        rr = abs(statistics.mean(c['pnl'] for c in wins) / statistics.mean(c['pnl'] for c in losses))
        need = 100 / (1 + rr)
        print(f"  reward:risk      {rr:8.2f}   → break-even win rate {need:.0f}%, actual {100*len(wins)/len(closes):.0f}%")
    print(f"  exits            {dict(Counter(c['reason'] for c in closes))}")

    print()
    print("=" * 68)
    print("ACCURACY — was each part RIGHT?")
    print("=" * 68)
    # 1. the signal: did price move the trade's way at all (before exits interfered)?
    mfe = [c["mfe_pct"] for c in closes if c.get("mfe_pct") is not None]
    mae = [c["mae_pct"] for c in closes if c.get("mae_pct") is not None]
    if mfe and mae:
        went_right = sum(1 for c in closes if (c.get("mfe_pct") or 0) > abs(c.get("mae_pct") or 0))
        print(f"  SIGNAL   price favoured the trade more than it hurt it: {pct(went_right, len(closes))}")
        print(f"           median best-case move  {statistics.median(mfe):+.3f}%")
        print(f"           median worst-case move {statistics.median(mae):+.3f}%")
    # 2. direction accuracy by side
    by_dir = defaultdict(list)
    for c in closes:
        by_dir[c.get("direction")].append(c["pnl"])
    for d, g in sorted(by_dir.items()):
        print(f"  DIRECTION {str(d):6s} {len(g):3d} trades, {pct(sum(1 for x in g if x>0), len(g))} won, total {sum(g):+.2f}")
    # 3. the model: Execute calls vs its own confidence
    conf = [(c.get("ai_confidence"), c["pnl"]) for c in closes if c.get("ai_confidence") is not None]
    if len(conf) >= 4:
        hi = [p for cf, p in conf if cf >= 0.9]
        lo = [p for cf, p in conf if cf < 0.9]
        print(f"  MODEL    confidence >= 0.90: {len(hi):3d} trades, {pct(sum(1 for x in hi if x>0), len(hi))} won, avg {statistics.mean(hi):+.3f}" if hi else "  MODEL    no high-confidence trades")
        if lo:
            print(f"           confidence <  0.90: {len(lo):3d} trades, {pct(sum(1 for x in lo if x>0), len(lo))} won, avg {statistics.mean(lo):+.3f}")
        print(f"           → the model adds value only if the first line beats the second")
    # 4. carry: how much of the move available to it did Rolling5 actually take home?
    #    This is the question "can R5 carry a trade into profit" reduced to one number. A trade that ran
    #    +0.20% in its favour and closed at +0.02% captured 10% of what the market offered it.
    capture = []
    for c in closes:
        best = c.get("mfe_pct")
        got = c.get("realised_pct")
        if got is None and c.get("entry_price") and c.get("exit_price") and c.get("direction"):
            sign = 1.0 if str(c["direction"]).upper() == "LONG" else -1.0
            got = 100.0 * sign * (float(c["exit_price"]) - float(c["entry_price"])) / float(c["entry_price"])
        if best and best > 0 and got is not None:
            capture.append(100.0 * got / best)
    if capture:
        print(f"  CARRY    median capture of the best available move: {statistics.median(capture):.0f}%"
              f"  (mean {statistics.mean(capture):.0f}%, n={len(capture)})")
        print(f"           gave back everything or worse: {pct(sum(1 for x in capture if x <= 0), len(capture))}")

    # 5. exits: did winners run?
    for reason in sorted({c["reason"] for c in closes}):
        g = [c["pnl"] for c in closes if c["reason"] == reason]
        flag = ""
        if reason == "TAKE_PROFIT" and statistics.mean(g) <= 0:
            flag = "   <-- REGRESSION: a take-profit that loses money means a target was moved to a losing price"
        print(f"  EXIT     {reason:16s} {len(g):3d}  avg {statistics.mean(g):+.3f}  total {sum(g):+.2f}{flag}")
    losing_tps = [c for c in closes if c["reason"] == "TAKE_PROFIT" and c["pnl"] <= 0]
    if losing_tps:
        print(f"           {len(losing_tps)} of {sum(1 for c in closes if c['reason'] == 'TAKE_PROFIT')} "
              f"take-profits LOST money — see position_manager.plan_exits (fixed 2026-09-16, 1c93711)")
    # 5. context at entry
    for field in ("orderbook_zone",):
        groups = defaultdict(list)
        for c in closes:
            groups[str((c.get("context_packet") or {}).get(field))].append(c["pnl"])
        if len(groups) > 1:
            print(f"  CONTEXT  by {field}:")
            for k, g in sorted(groups.items()):
                print(f"             {k:12s} {len(g):3d} trades, {pct(sum(1 for x in g if x>0), len(g))} won, avg {statistics.mean(g):+.3f}")
    durs = [c["duration_s"] for c in closes if c.get("duration_s")]
    if durs:
        print(f"  HOLDING  median {statistics.median(durs)/60:.1f} min, max {max(durs)/60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
