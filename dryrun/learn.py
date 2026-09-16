#!/usr/bin/env python3
"""Learn from the bot's own setups: build a labelled dataset of every post-signal cycle (features = what the
gates and the packet said at the time; label = did the trade win after fees, judged by what price actually did
next with the bot's exits), fit a regularised logistic regression (numpy, no sklearn), and evaluate it
STRICTLY OUT OF TIME (train on the earlier part of the data, test on the later part).

usage: learn.py [--fee 0.16] [--train-frac 0.6] [--save weights.json]
"""
import argparse
import bisect
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO = Path.home() / "trading_core_project" / "TradingCore"
DRY = Path.home() / "trading_core_project" / "dryrun"
FLAG_ORDER = {"❌": 0.0, "⚠️": 0.5, "✅": 1.0}


def flag_value(flag: str) -> float:
    for k, v in FLAG_ORDER.items():
        if str(flag).startswith(k):
            return v
    return 0.5


def load_candles():
    rows = json.load(open(DRY / "candles_7d.json"))
    return ([int(r[0]) for r in rows], [float(r[2]) for r in rows], [float(r[3]) for r in rows], [float(r[4]) for r in rows])


def outcome(candles, t_ms, direction, hz=5, sl=1.0, tp=1.5):
    ts, h, l, c = candles
    k = bisect.bisect_right(ts, t_ms) - 1
    if k < 1 or k + hz >= len(ts):
        return None
    lvl = k - 1; rng = h[lvl] - l[lvl]
    if rng <= 0:
        return None
    entry = c[k]; sign = 1 if direction == "LONG" else -1
    stop = entry - sign * rng * sl; target = entry + sign * rng * tp
    for j in range(k + 1, k + 1 + hz):
        if (l[j] <= stop if sign > 0 else h[j] >= stop): return sign * (stop - entry) / entry * 100
        if (h[j] >= target if sign > 0 else l[j] <= target): return sign * (target - entry) / entry * 100
    return sign * (c[k + hz] - entry) / entry * 100


def build_dataset(fee_pct):
    candles = load_candles()
    packets = []
    for line in open(REPO / "logs" / "ai_model.log"):
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("type") == "latency" and r.get("context"):
            packets.append(r)
    # packets carry no ts on latency records; use the api_verdict records instead (they have ts)
    packets = [json.loads(l) for l in open(REPO / "logs" / "ai_model.log") if '"api_verdict"' in l]
    packets = [p for p in packets if (p.get("ts") or 0) > 1789560000]
    packet_ts = [p["ts"] for p in packets]
    rows, times = [], []
    for line in open(REPO / "logs" / "failed_signals.json"):
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        rep = r.get("report") or {}
        if "RetestEntryLogic" not in rep:
            continue
        t = datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")).timestamp()
        i = bisect.bisect_left(packet_ts, t - 1.5)
        pkt = packets[i]["context"] if i < len(packets) and abs(packets[i]["ts"] - t) <= 1.5 else None
        direction = (pkt or {}).get("direction") or "SHORT"
        g = outcome(candles, t * 1000, direction)
        if g is None:
            continue
        f = {}
        for name in ("CtsFilter", "RetestEntryLogic", "OrderBookReversalZoneDetector", "SpoofFilter", "LowVolumeGuard",
                     "CompressionDetector", "BreakoutZoneOriginFilter", "SentimentDivergenceFilter"):
            rr = rep.get(name) or {}
            f[f"{name}.score"] = float(rr.get("score", 0.5) or 0.0)
            f[f"{name}.flag"] = flag_value(rr.get("flag", ""))
        m = (rep.get("CtsFilter") or {}).get("metrics") or {}
        f["cts.grind_ratio"] = float(m.get("grind_ratio", 1.0) or 0.0)
        f["cts.candle_age_s"] = float(m.get("candle_age_s", 30.0) or 0.0)
        f["cts.wick"] = 1.0 if m.get("wick_signal", "none") != "none" else 0.0
        rm = (rep.get("RetestEntryLogic") or {}).get("metrics") or {}
        f["retest.at_extreme"] = 1.0 if rm.get("retest_type") else 0.0
        sm = (rep.get("SpoofFilter") or {}).get("metrics") or {}
        f["spoof.thin_rate"] = float(sm.get("spoof_thin_rate", 0.0) or 0.0)
        cm = (rep.get("CompressionDetector") or {}).get("metrics") or {}
        f["compression.ratio"] = float(cm.get("compression_ratio", 1.0) or 0.0)
        sen = (rep.get("SentimentDivergenceFilter") or {}).get("metrics") or {}
        div = sen.get("divergence_type", "none")
        f["div.against"] = 1.0 if (div == "bearish" and direction == "LONG") or (div == "bullish" and direction == "SHORT") else 0.0
        f["div.with"] = 1.0 if (div == "bearish" and direction == "SHORT") or (div == "bullish" and direction == "LONG") else 0.0
        if pkt:
            f["reversal"] = float(pkt.get("reversal_likelihood_score", 0.0) or 0.0)
            zone = pkt.get("orderbook_zone", "none")
            f["zone.against"] = 1.0 if (zone == "resistance" and direction == "LONG") or (zone == "support" and direction == "SHORT") else 0.0
            f["zone.with"] = 1.0 if (zone == "resistance" and direction == "SHORT") or (zone == "support" and direction == "LONG") else 0.0
        else:
            f["reversal"] = 0.4; f["zone.against"] = 0.0; f["zone.with"] = 0.0
        f["is_long"] = 1.0 if direction == "LONG" else 0.0
        f["minute_of_hour"] = datetime.fromtimestamp(t, timezone.utc).minute / 59.0
        rows.append((f, g - fee_pct > 0, g)); times.append(t)
    return rows, times


def fit_logreg(X, y, l2=1.0, iters=3000, lr=0.05):
    n, d = X.shape
    w = np.zeros(d); b = 0.0
    for _ in range(iters):
        z = X @ w + b; p = 1 / (1 + np.exp(-z))
        gw = X.T @ (p - y) / n + l2 * w / n; gb = float(np.mean(p - y))
        w -= lr * gw; b -= lr * gb
    return w, b


def auc(scores, labels):
    order = np.argsort(scores); ranks = np.empty(len(scores)); ranks[order] = np.arange(1, len(scores) + 1)
    pos = labels == 1; n_pos, n_neg = pos.sum(), (~pos).sum()
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    return float((ranks[pos].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fee", type=float, default=0.16)
    ap.add_argument("--train-frac", type=float, default=0.6)
    ap.add_argument("--save", default=None)
    a = ap.parse_args()
    rows, times = build_dataset(a.fee)
    if len(rows) < 100:
        print(f"only {len(rows)} labelled setups — not enough to learn from yet"); return 1
    order = np.argsort(times); rows = [rows[i] for i in order]
    names = sorted(rows[0][0])
    X = np.array([[r[0].get(k, 0.0) for k in names] for r in rows]); y = np.array([1.0 if r[1] else 0.0 for r in rows]); g = np.array([r[2] for r in rows])
    n_train = int(len(rows) * a.train_frac)
    mu, sd = X[:n_train].mean(0), X[:n_train].std(0) + 1e-9
    Xs = (X - mu) / sd
    w, b = fit_logreg(Xs[:n_train], y[:n_train])
    p_test = 1 / (1 + np.exp(-(Xs[n_train:] @ w + b))); y_test = y[n_train:]; g_test = g[n_train:]
    t0, t1, t2 = (datetime.fromtimestamp(times[i], timezone.utc).strftime("%H:%M") for i in (order[0], order[n_train], order[-1]))
    print(f"{len(rows)} labelled setups; train {n_train} ({t0}–{t1} UTC), test {len(rows) - n_train} ({t1}–{t2} UTC); fee {a.fee}%")
    print(f"base rate (wins after fee): train {y[:n_train].mean():.1%}, test {y_test.mean():.1%}; take-everything mean net on test {np.mean(g_test) - a.fee:+.4f}%")
    print(f"out-of-time AUC: {auc(p_test, y_test):.3f}  (0.5 = no skill)")
    for thr in (0.3, 0.4, 0.5, 0.6):
        take = p_test >= thr
        if take.sum():
            print(f"  gate p≥{thr}: takes {take.sum():4d}/{len(take)} ({take.mean():.0%})  win {y_test[take].mean():.1%}  mean net {np.mean(g_test[take]) - a.fee:+.4f}%  vs skipped net {(np.mean(g_test[~take]) - a.fee) if (~take).sum() else float('nan'):+.4f}%")
    imp = sorted(zip(names, w), key=lambda kv: -abs(kv[1]))[:10]
    print("strongest features (standardised weight; + = more likely to win):")
    for k, v in imp:
        print(f"  {v:+.3f}  {k}")
    if a.save:
        json.dump({"names": names, "mu": mu.tolist(), "sd": sd.tolist(), "w": w.tolist(), "b": b, "trained_on": len(rows)}, open(a.save, "w"))
        print("saved", a.save)
    return 0


if __name__ == "__main__":
    sys.exit(main())
