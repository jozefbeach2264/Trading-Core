# okx_hist_eth_swap_1m_10080_from_2025_08_02.py
import requests, csv, time
from datetime import datetime, timezone

BASE = "https://www.okx.com"
HEADERS = {"User-Agent": "tradingcore-okx/1.0", "Accept": "application/json"}
INST_ID = "ETH-USDT-SWAP"   # OKX Perpetual Swap
BAR = "1m"
LIMIT = 300                 # OKX max per page

# START settings
START_DATE = datetime(2025, 8, 2, 0, 0, tzinfo=timezone.utc)
MAX_CANDLES = 10080         # 7 days of 1-minute candles

def okx_get(path, **params):
    r = requests.get(f"{BASE}{path}", params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    j = r.json()
    if j.get("code") != "0":
        raise RuntimeError(f"OKX error: {j}")
    return j.get("data", [])

def fetch_history(before_ms=None):
    params = {"instId": INST_ID, "bar": BAR, "limit": str(LIMIT)}
    if before_ms is not None:
        params["before"] = str(before_ms)  # ms open time
    return okx_get("/api/v5/market/history-candles", **params)

def main():
    start_ms = int(START_DATE.timestamp() * 1000)
    rows = []
    cursor = None  # start from latest and paginate back
    pages = 0

    while len(rows) < MAX_CANDLES:
        batch = fetch_history(cursor)
        pages += 1
        if not batch:
            raise RuntimeError("No data returned from OKX history endpoint.")
        rows.extend(batch)
        oldest = min(int(r[0]) for r in batch)
        cursor = oldest
        if oldest <= start_ms:
            break
        time.sleep(0.12)

    # Normalize and slice
    rows = sorted(rows, key=lambda r: int(r[0]))
    norm = []
    for r in rows:
        ts = int(r[0])
        if ts < start_ms:
            continue
        o, h, l, c = map(float, r[1:5])
        vol = float(r[5]) if len(r) > 5 and r[5] is not None else float("nan")
        norm.append((ts, o, h, l, c, vol))
        if len(norm) >= MAX_CANDLES:
            break

    out = "okx_ethusdt_swap_1m_from2025_08_02.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["open_time_ms", "open", "high", "low", "close", "volume", "open_time_iso"])
        for ts, o, h, l, c, v in norm:
            iso = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat()
            w.writerow([ts, o, h, l, c, v, iso])

    print(f"{INST_ID} {BAR}: rows={len(norm)}, pages={pages}")
    print(f"saved: {out}")

if __name__ == "__main__":
    main()