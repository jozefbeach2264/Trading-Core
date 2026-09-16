#!/usr/bin/env python3
"""Record whale-wall events and what price did afterwards, so the TrapX thesis can be MEASURED.

Runs its own OKX websocket (independent of the bot — it cannot disturb it, and touches no GPU). For every
wall that appears in the 50-level book it logs: when it appeared, its side, price, size, share of visible
depth, the mid at that moment, then what happened to it (absorbed / pulled / still there) and where the mid
went 1, 5, 15 and 30 minutes later. One JSON line per resolved wall into walls.jsonl.

  python3 record_walls.py [--minutes 0]      (0 = run until killed)
"""
import argparse
import asyncio
import json
import sys
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path.home() / "trading_core_project" / "TradingCore"))
import websockets                                   # noqa: E402
from data_managers.orderbook_l2 import L2Book       # noqa: E402
from data_managers.orderbook_parser import WallTracker  # noqa: E402

OUT = Path.home() / "trading_core_project" / "dryrun" / "walls.jsonl"
HORIZONS = (60, 300, 900, 1800)          # seconds after the wall first appears
PULLED_FRACTION = 0.5                     # size below this share of its peak counts as pulled


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=0)
    ap.add_argument("--inst", default="ETH-USDT-SWAP")
    a = ap.parse_args()
    book = L2Book()
    tracker = WallTracker(size_multiple=8.0, skip_levels=3, min_age_s=10.0, max_distance_pct=0.15)
    live = {}                 # (side, price) -> record being built
    mids = deque()            # (ts, mid) for looking forward
    pending = []              # records waiting for their horizons to elapse
    written = 0
    deadline = time.time() + a.minutes * 60 if a.minutes else None

    async with websockets.connect("wss://ws.okx.com:8443/ws/v5/public") as ws:
        await ws.send(json.dumps({"op": "subscribe", "args": [{"channel": "books", "instId": a.inst}]}))
        print(f"recording whale walls on {a.inst} → {OUT}", flush=True)
        while deadline is None or time.time() < deadline:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
            if "data" not in msg:
                continue
            try:
                book.apply(msg.get("action", "update"), msg["data"][0])
            except Exception:
                book.reset(); live.clear()
                await ws.send(json.dumps({"op": "unsubscribe", "args": [{"channel": "books", "instId": a.inst}]}))
                await ws.send(json.dumps({"op": "subscribe", "args": [{"channel": "books", "instId": a.inst}]}))
                continue
            now = time.time()
            depth = book.top(50)
            if not depth["bids"] or not depth["asks"]:
                continue
            mid = (depth["bids"][0][0] + depth["asks"][0][0]) / 2
            mids.append((now, mid))
            while mids and now - mids[0][0] > max(HORIZONS) + 60:
                mids.popleft()

            depth_full = book.top(400)
            walls = tracker.update(depth_full, now, mid=mid)
            # the tracker now reports each wall's ENDING itself, with how it ended
            for e in walls.get("events", []):
                pending.append({"side": e["side"], "price": e["price"], "first_seen": now - e["lifetime_s"],
                                "mid_at_appear": mid, "peak_qty": e["peak_qty"], "last_qty": e["last_qty"],
                                "distance_pct": e.get("distance_pct"), "lifetime_s": e["lifetime_s"],
                                "outcome": e["outcome"], "mid_at_end": mid, "ended": now})
            # write out records whose longest horizon has elapsed
            ready = [r for r in pending if now - r["first_seen"] >= max(HORIZONS)]
            for r in ready:
                pending.remove(r)
                for hz in HORIZONS:
                    target_ts = r["first_seen"] + hz
                    later = next((m for t, m in mids if t >= target_ts), None)
                    r[f"mid_after_{hz}s"] = later
                    if later:
                        r[f"move_after_{hz}s_pct"] = round((later - r["mid_at_appear"]) / r["mid_at_appear"] * 100, 4)
                with OUT.open("a") as f:
                    f.write(json.dumps(r) + "\n")
                written += 1
                if written % 10 == 0:
                    print(f"  {written} walls resolved and written", flush=True)
    print(f"done: {written} walls written to {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(0)
