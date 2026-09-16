"""Run statistics for the dry-run simulation, computed from simulation_state.json history.

Pure functions over the history list so they are testable and usable both from the executor
(after every close) and from the command line: `python sim_stats.py [path/to/simulation_state.json]`.
"""
import json
import os
import sys
from typing import Any, Dict, List


def compute_stats(history: List[Dict[str, Any]], initial_capital: float) -> Dict[str, Any]:
    closes = [h for h in history if h.get("event") == "close"]
    opens = [h for h in history if h.get("event", "open") == "open"]
    wins = [c for c in closes if c.get("pnl", 0.0) > 0]
    losses = [c for c in closes if c.get("pnl", 0.0) <= 0]
    gross = sum(c.get("pnl", 0.0) for c in closes)
    fees = sum(h.get("fee", 0.0) for h in history)
    equity, peak, max_drawdown_pct = initial_capital, initial_capital, 0.0
    for h in history:                      # equity after every fee/pnl event, for drawdown
        equity += h.get("pnl", 0.0) - h.get("fee", 0.0)
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown_pct = max(max_drawdown_pct, (peak - equity) / peak * 100.0)
    # An "open" with a later "open" before any "close" was orphaned (a restart lost the lifecycle).
    orphans, depth = 0, 0
    for h in history:
        if h.get("event", "open") == "open":
            if depth:
                orphans += 1
            depth += 1
        elif depth:
            depth -= 1
    by_reason: Dict[str, int] = {}
    for c in closes:
        by_reason[c.get("reason", "?")] = by_reason.get(c.get("reason", "?"), 0) + 1
    return {
        "trades_opened": len(opens),
        "trades_closed": len(closes),
        "open_now": max(len(opens) - len(closes) - orphans, 0),
        "orphaned_opens": orphans,
        "win_rate_pct": round(100.0 * len(wins) / len(closes), 2) if closes else None,
        "gross_pnl": round(gross, 6),
        "fees": round(fees, 6),
        "net_pnl": round(gross - fees, 6),
        "avg_win": round(sum(c["pnl"] for c in wins) / len(wins), 6) if wins else None,
        "avg_loss": round(sum(c["pnl"] for c in losses) / len(losses), 6) if losses else None,
        "max_drawdown_pct": round(max_drawdown_pct, 3),
        "final_equity": round(equity, 6),
        "return_pct": round((equity - initial_capital) / initial_capital * 100.0, 3) if initial_capital else None,
        "closes_by_reason": by_reason,
    }


def summary_line(stats: Dict[str, Any]) -> str:
    return (f"SIM {stats['trades_closed']} closed ({stats['open_now']} open) | win {stats['win_rate_pct']}% | "
            f"net {stats['net_pnl']:+.4f} (fees {stats['fees']:.4f}) | equity {stats['final_equity']:.4f} "
            f"({stats['return_pct']:+.2f}%) | maxDD {stats['max_drawdown_pct']:.2f}% | {stats['closes_by_reason']}")


def main(argv: List[str]) -> int:
    path = argv[1] if len(argv) > 1 else os.path.join("logs", "simulation_state.json")
    with open(path) as f:
        state = json.load(f)
    initial = float(state.get("initial_capital") or os.getenv("SIMULATION_INITIAL_CAPITAL", "10"))
    stats = compute_stats(state.get("history", []), initial)
    print(json.dumps(stats, indent=2))
    print(summary_line(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
