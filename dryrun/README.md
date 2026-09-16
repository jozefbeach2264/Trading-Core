# dryrun — the measurement toolkit

Everything here is analysis, not the bot. The bot runs from the repo root; these tools watch it, score it and
test ideas against real candles before they touch it.

| tool | what it does |
|---|---|
| `tradingcore-helper.sh` | copy of `~/.local/bin/tradingcore`: `start / stop / pause / resume / status / report / trades / watch / tail` |
| `dashboard.py` | live web dashboard on :8001 (cycle stream, verdicts, rejection mix, sim scoreboard). Standalone: restart it freely |
| `collect.py` | one JSON sample per run into `samples.jsonl` (scoreboard, rejection mix, verdict mix + latency, GPU, unit health). Runs on a 5-min timer |
| `report.py` | summarise `samples.jsonl` |
| `trade_review.py` | per-trade table: MFE/MAE, duration, the scores and filter flags each trade was taken on, results by exit reason / wall zone / strategy |
| `backtest_scalpel.py` | replay the Scalpel rule (and limit-order economics) over `candles_7d.json` with real fees; `--grid` sweeps band/stop/target/horizon |
| `learn.py` | labelled dataset from the bot's own setups → logistic regression → **strictly out-of-time** AUC + gate sweep |

Data files (`candles_7d.json`, `samples*.jsonl`, `learned_weights.json`) are gitignored — regenerate with the
fetch snippet in `FINDINGS_2026-09-16.md` or by letting the collector run.

**Read `FINDINGS_2026-09-16.md` first.** It is the measured state of the system: what works, what has no edge,
and what was tried and failed.
