#!/usr/bin/env python3
"""Live test of the TrapX thesis: does a wall ending predict the next few minutes?

Tracks walls at several size/distance settings at once, records every wall ENDING with how it ended
(pulled = size vanished before price reached it; absorbed = price ate through it), then measures where mid
went 1 / 3 / 5 minutes later. Writes one JSON line per resolved event to live_wall_test.jsonl.

  python3 live_wall_test.py --minutes 30
"""
import argparse
import asyncio
import json
import sys
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path.home() / "trading_core_project" / "TradingCore"))
import websockets                                        # noqa: E402
from data_managers.orderbook_l2 import L2Book            # noqa: E402
from data_managers.orderbook_parser import WallTracker   # noqa: E402

OUT = Path(__file__).with_name("live_wall_test.jsonl")
HORIZONS = (60, 300, 600, 1200)
# Stricter = stronger, in the first run (8x -> noise, 20x -> +0.030%, 50x -> +0.057%). Push further.
SETTINGS = [(50.0, 0.10, 20.0), (100.0, 0.10, 30.0), (100.0, 0.05, 30.0), (200.0, 0.10, 45.0)]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=30)
    ap.add_argument("--inst", default="ETH-USDT-SWAP")
    a = ap.parse_args()
    book = L2Book()
    trackers = {s: WallTracker(size_multiple=s[0], skip_levels=3, min_age_s=s[2], max_distance_pct=s[1]) for s in SETTINGS}
    mids = deque()
    pending = []
    written = 0
    deadline = time.time() + a.minutes * 60
    print(f"live wall test on {a.inst} for {a.minutes:.0f} min → {OUT}", flush=True)
    async with websockets.connect("wss://ws.okx.com:8443/ws/v5/public") as ws:
        await ws.send(json.dumps({"op": "subscribe", "args": [{"channel": "books", "instId": a.inst}]}))
        while time.time() < deadline + max(HORIZONS) + 10:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=45))
            except asyncio.TimeoutError:
                continue
            if "data" not in msg:
                continue
            try:
                book.apply(msg.get("action", "update"), msg["data"][0])
            except Exception:
                book.reset()
                await ws.send(json.dumps({"op": "unsubscribe", "args": [{"channel": "books", "instId": a.inst}]}))
                await ws.send(json.dumps({"op": "subscribe", "args": [{"channel": "books", "instId": a.inst}]}))
                continue
            now = time.time()
            depth = book.top(400)
            if not depth["bids"] or not depth["asks"]:
                continue
            mid = (depth["bids"][0][0] + depth["asks"][0][0]) / 2
            mids.append((now, mid))
            while mids and now - mids[0][0] > max(HORIZONS) + 30:
                mids.popleft()
            if now < deadline:
                for setting, tr in trackers.items():
                    for e in tr.update(depth, now, mid=mid).get("events", []):
                        e["setting"] = f"{setting[0]:g}x/{setting[1]:g}%/{setting[2]:g}s"
                        e["at"] = now
                        e["mid_at_end"] = mid
                        pending.append(e)
            ready = [e for e in pending if now - e["at"] >= max(HORIZONS)]
            for e in ready:
                pending.remove(e)
                for hz in HORIZONS:
                    later = next((m for t, m in mids if t >= e["at"] + hz), None)
                    if later:
                        e[f"move_{hz}s_pct"] = round((later - e["mid_at_end"]) / e["mid_at_end"] * 100, 4)
                with OUT.open("a") as f:
                    f.write(json.dumps(e) + "\n")
                written += 1
                if written % 200 == 0:
                    print(f"  {written} events written", flush=True)
    print(f"done: {written} events", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(0)
