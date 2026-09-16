#!/usr/bin/env python3
"""Per-trade review of the simulation: was each trade a good one, and what do the losers have in common?
usage: trade_review.py [simulation_state.json]"""
import json
import os
import statistics
import sys
from collections import defaultdict


def main(argv):
    path = argv[1] if len(argv) > 1 else os.path.expanduser("~/trading_core_project/TradingCore/logs/simulation_state.json")
    state = json.load(open(path))
    closes = [h for h in state.get("history", []) if h.get("event") == "close"]
    if not closes:
        print("no closed trades yet"); return 0
    print(f"{'time':8s} {'dir':5s} {'entry':>9s} {'exit':>9s} {'why':13s} {'pnl':>8s} {'fee':>7s} {'mfe%':>7s} {'mae%':>7s} {'dur s':>6s} {'conf':>5s} {'rev':>5s} {'cts':>5s} {'ob':>5s} zone")
    for c in closes:
        cp = c.get("context_packet") or {}
        print(f"{c['timestamp'][11:19]} {str(c.get('direction')):5s} {c['entry_price']:9.2f} {c['exit_price']:9.2f} {c['reason']:13s} "
              f"{c['pnl']:8.4f} {c['fee']:7.4f} {c.get('mfe_pct', 0) or 0:7.3f} {c.get('mae_pct', 0) or 0:7.3f} {str(c.get('duration_s') or ''):>6s} "
              f"{str(c.get('ai_confidence') or ''):>5s} {cp.get('reversal_likelihood_score', ''):>5} {cp.get('cts_score', ''):>5} {cp.get('orderbook_score', ''):>5} {cp.get('orderbook_zone', '')}")
    wins = [c for c in closes if c["pnl"] > 0]; losses = [c for c in closes if c["pnl"] <= 0]
    print(f"\n{len(closes)} closed: {len(wins)} wins / {len(losses)} losses | gross {sum(c['pnl'] for c in closes):+.4f} | fees {sum(c['fee'] for c in closes) * 2:.4f} (open+close)")
    if losses and any(c.get("mfe_pct") is not None for c in losses):
        gave_back = [c for c in losses if (c.get("mfe_pct") or 0) > 0.05]
        print(f"losers that were up ≥0.05% at some point (profit given back): {len(gave_back)}/{len(losses)}; "
              f"avg MFE of losers {statistics.mean(c.get('mfe_pct') or 0 for c in losses):+.3f}%")
    if wins and any(c.get("mae_pct") is not None for c in wins):
        print(f"avg MAE of winners (how close they came to the stop): {statistics.mean(c.get('mae_pct') or 0 for c in wins):+.3f}%")
    by = defaultdict(list)
    for c in closes:
        by[c["reason"]].append(c["pnl"])
    print("by exit reason: " + ", ".join(f"{k} n={len(v)} avg {statistics.mean(v):+.4f}" for k, v in by.items()))
    for key in ("orderbook_zone", "signal_type"):
        groups = defaultdict(list)
        for c in closes:
            groups[str((c.get("context_packet") or {}).get(key) or c.get(key))].append(c["pnl"])
        print(f"by {key}: " + ", ".join(f"{k} n={len(v)} avg {statistics.mean(v):+.4f}" for k, v in groups.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
