#!/usr/bin/env python3
"""Backtest of the Scalpel rule + the bot's simulated exits + the real fee, on closed 1m candles.

Replicates strategy/trade_module_scalpel.py (EMA100 trend gate, retest of the previous candle's high/low
within band × that candle's range, stop = SL_MULT × range, target = TP_MULT × range) and the
executor's exit order (stop checked before target inside a candle → conservative), a time horizon in
candles, and a round-trip taker fee. Decisions are made at candle CLOSES (the live bot decides on the
in-progress candle every 0.2 s, so this is an approximation) and the AI verdict layer is NOT modelled.

usage: backtest_scalpel.py [candles_7d.json] [--fee 0.16] [--grid]
Outputs net % of notional per trade, win rate, trades, max drawdown of a constant-fraction equity curve.
"""
import argparse
import itertools
import json
import math
import sys
from pathlib import Path


def ema(closes, n):
    k = 2 / (n + 1)
    out = [None] * len(closes)
    e = sum(closes[:n]) / n
    out[n - 1] = e
    for i in range(n, len(closes)):
        e = (closes[i] - e) * k + e
        out[i] = e
    return out


def run(rows, band=0.25, sl_mult=1.0, tp_mult=1.5, horizon=5, fee_rt_pct=0.16, one_at_a_time=True):
    o = [float(r[1]) for r in rows]; h = [float(r[2]) for r in rows]; l = [float(r[3]) for r in rows]; c = [float(r[4]) for r in rows]
    e100 = ema(c, 100)
    trades = []
    i = 100
    n = len(rows)
    while i < n - 2:
        # The bot compares the LIVE price with the PREVIOUS closed candle (level). At minute resolution:
        # level candle = i, "live" price = close of candle i+1, entry at that close, exits from candle i+2.
        lvl = i; cur = i + 1
        rng = h[lvl] - l[lvl]
        if rng <= 0 or e100[cur] is None:
            i += 1; continue
        tol = rng * band
        close = c[cur]
        direction = None
        if close > e100[cur] and abs(close - h[lvl]) <= tol:
            direction = "LONG"
        elif close < e100[cur] and abs(close - l[lvl]) <= tol:
            direction = "SHORT"
        if direction is None:
            i += 1; continue
        entry = close
        sign = 1 if direction == "LONG" else -1
        stop = entry - sign * rng * sl_mult
        target = entry + sign * rng * tp_mult
        exit_price, reason, j = None, None, cur + 1
        i = cur   # so that `i + horizon` below counts from the entry candle
        while j < n and j <= i + horizon:
            hit_stop = l[j] <= stop if sign > 0 else h[j] >= stop
            hit_tp = h[j] >= target if sign > 0 else l[j] <= target
            if hit_stop:                      # conservative: stop first when both are inside one candle
                exit_price, reason = stop, "STOP"; break
            if hit_tp:
                exit_price, reason = target, "TP"; break
            j += 1
        if exit_price is None:
            j = min(i + horizon, n - 1)
            exit_price, reason = c[j], "TIME"
        gross_pct = sign * (exit_price - entry) / entry * 100
        pnl_pct = gross_pct - fee_rt_pct
        trades.append((i, direction, pnl_pct, reason, gross_pct))
        i = j + 1 if one_at_a_time else i + 1
    if not trades:
        return None
    wins = sum(1 for t in trades if t[4] > 0)          # win = positive BEFORE fees (as the live sim reports it)
    gross = sum(t[4] for t in trades) / len(trades)
    equity, peak, dd = 1.0, 1.0, 0.0
    for _, _, pnl, _, _ in trades:
        equity *= 1 + pnl / 100 * 20      # bot sizing: 10% margin × 200x = 20× balance notional
        peak = max(peak, equity); dd = max(dd, (peak - equity) / peak)
        if equity <= 0: break
    reasons = {}
    for t in trades: reasons[t[3]] = reasons.get(t[3], 0) + 1
    longs = sum(1 for t in trades if t[1] == "LONG")
    return {"trades": len(trades), "longs": longs, "shorts": len(trades) - longs, "win_pct": 100 * wins / len(trades),
            "gross_pct_per_trade": gross,
            "net_pct_per_trade": sum(t[2] for t in trades) / len(trades), "net_pct_total": sum(t[2] for t in trades),
            "equity_x": equity, "max_dd_pct": 100 * dd, "reasons": reasons}


def run_limit(rows, band=0.25, sl_mult=1.0, tp_mult=1.5, horizon=5, maker_pct=0.02, taker_pct=0.08, wait=3,
              one_at_a_time=True):
    """Same rule, but the entry is a resting LIMIT at the level price (maker fee) that must be touched within
    `wait` candles, the take-profit is a resting limit (maker), the stop and the time-out are taker exits.
    A limit that would already be marketable at signal time fills at the close as a taker."""
    h = [float(r[2]) for r in rows]; l = [float(r[3]) for r in rows]; c = [float(r[4]) for r in rows]
    e100 = ema(c, 100)
    trades = []; unfilled = 0
    i = 100; n = len(rows)
    while i < n - 2:
        lvl, cur = i, i + 1
        rng = h[lvl] - l[lvl]
        if rng <= 0 or e100[cur] is None:
            i += 1; continue
        tol = rng * band; close = c[cur]
        direction = level = None
        if close > e100[cur] and abs(close - h[lvl]) <= tol:
            direction, level = "LONG", h[lvl]
        elif close < e100[cur] and abs(close - l[lvl]) <= tol:
            direction, level = "SHORT", l[lvl]
        if direction is None:
            i += 1; continue
        sign = 1 if direction == "LONG" else -1
        # fill: a buy limit at `level` fills when price trades at/below it; a sell limit when at/above it
        marketable = (close <= level) if sign > 0 else (close >= level)
        if marketable:
            entry, fee_in, k = close, taker_pct, cur
        else:
            entry, fee_in, k = None, maker_pct, None
            for j in range(cur + 1, min(cur + 1 + wait, n)):
                if (l[j] <= level if sign > 0 else h[j] >= level):
                    entry, k = level, j; break
            if entry is None:
                unfilled += 1; i = cur + wait; continue
        stop = entry - sign * rng * sl_mult
        target = entry + sign * rng * tp_mult
        exit_price = reason = None; j = k + 1
        while j < n and j <= k + horizon:
            hit_stop = l[j] <= stop if sign > 0 else h[j] >= stop
            hit_tp = h[j] >= target if sign > 0 else l[j] <= target
            if hit_stop:
                exit_price, reason, fee_out = stop, "STOP", taker_pct; break
            if hit_tp:
                exit_price, reason, fee_out = target, "TP", maker_pct; break
            j += 1
        if exit_price is None:
            j = min(k + horizon, n - 1); exit_price, reason, fee_out = c[j], "TIME", taker_pct
        gross_pct = sign * (exit_price - entry) / entry * 100
        trades.append((k, direction, gross_pct - fee_in - fee_out, reason, gross_pct))
        i = j + 1 if one_at_a_time else i + 1
    if not trades:
        return None
    wins = sum(1 for t in trades if t[4] > 0)
    reasons = {}
    for t in trades: reasons[t[3]] = reasons.get(t[3], 0) + 1
    return {"trades": len(trades), "unfilled": unfilled, "win_pct": 100 * wins / len(trades),
            "gross_pct_per_trade": sum(t[4] for t in trades) / len(trades),
            "net_pct_per_trade": sum(t[2] for t in trades) / len(trades), "net_pct_total": sum(t[2] for t in trades),
            "avg_fee_pct": sum(t[4] - t[2] for t in trades) / len(trades), "reasons": reasons}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=str(Path(__file__).with_name("candles_7d.json")))
    ap.add_argument("--fee", type=float, default=0.16, help="round-trip fee, percent of notional")
    ap.add_argument("--grid", action="store_true")
    a = ap.parse_args()
    rows = json.load(open(a.path))
    print(f"{len(rows)} candles, fee {a.fee}% round trip\n")
    base = run(rows, fee_rt_pct=a.fee)
    print("LIVE SETTINGS (band 0.25, SL 1x, TP 1.5x, horizon 5):", json.dumps(base))
    print("OLD SETTINGS  (band ~0.5% price ≈ 5x range, SL 1x, TP 1.5x, horizon 5):", json.dumps(run(rows, band=5.0, fee_rt_pct=a.fee)))
    print("\nLIMIT-ORDER ECONOMICS (maker entry + maker TP, taker stop/time-out), live settings:")
    for mk in (0.02, 0.0):
        r = run_limit(rows, maker_pct=mk, taker_pct=0.08)
        print(f"  maker {mk:.2f}% / taker 0.08%: {json.dumps(r)}")
    if not a.grid:
        return 0
    print("\nLIMIT GRID, maker 0.02% / taker 0.08% (top 10 by net %/trade, ≥ 30 trades):")
    lim = []
    for band, sl, tp, hz in itertools.product((0.1, 0.25, 0.5), (1, 2, 3, 4), (1.5, 3, 4.5, 6, 8), (5, 10, 15, 30, 60)):
        r = run_limit(rows, band=band, sl_mult=sl, tp_mult=tp, horizon=hz)
        if r and r["trades"] >= 30:
            lim.append(((band, sl, tp, hz), r))
    lim.sort(key=lambda x: -x[1]["net_pct_per_trade"])
    for (band, sl, tp, hz), r in lim[:10]:
        print(f"  band {band:4} SL {sl} TP {tp:3} hz {hz:3}: trades {r['trades']:5d} (unfilled {r['unfilled']:4d}) win {r['win_pct']:5.1f}% "
              f"gross {r['gross_pct_per_trade']:+.3f} fee {r['avg_fee_pct']:.3f} net {r['net_pct_per_trade']:+.3f}%  {r['reasons']}")
    print(f"  limit variants net-positive: {sum(1 for _, r in lim if r['net_pct_per_trade'] > 0)} of {len(lim)}")
    print("\nGRID (sorted by net % per trade; only variants with ≥ 30 trades):")
    results = []
    for band, sl, tp, hz in itertools.product((0.1, 0.25, 0.5), (1, 2, 3, 4), (1.5, 3, 4.5, 6, 8), (5, 10, 15, 30, 60)):
        r = run(rows, band=band, sl_mult=sl, tp_mult=tp, horizon=hz, fee_rt_pct=a.fee)
        if r and r["trades"] >= 30:
            results.append(((band, sl, tp, hz), r))
    results.sort(key=lambda x: -x[1]["net_pct_per_trade"])
    print(f"{'band':>5} {'SL':>4} {'TP':>4} {'hz':>3} {'trades':>6} {'L/S':>7} {'win%':>5} {'gross/tr%':>9} {'net/tr%':>8} {'total%':>8} {'maxDD%':>6}  exits")
    for (band, sl, tp, hz), r in results[:15]:
        print(f"{band:5} {sl:4} {tp:4} {hz:3} {r['trades']:6d} {r['longs']:3d}/{r['shorts']:<3d} {r['win_pct']:5.1f} {r['gross_pct_per_trade']:9.3f} {r['net_pct_per_trade']:8.3f} {r['net_pct_total']:8.1f} {r['max_dd_pct']:6.1f}  {r['reasons']}")
    positive = sum(1 for _, r in results if r["net_pct_per_trade"] > 0)
    print(f"\nvariants tested: {len(results)}, net-positive after fees: {positive}")
    print("... worst 3:")
    for (band, sl, tp, hz), r in results[-3:]:
        print(f"{band:5} {sl:4} {tp:4} {hz:3} {r['trades']:6d} {r['win_pct']:5.1f}% {r['net_pct_per_trade']:8.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
