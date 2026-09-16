"""Local L2 order book for OKX's `books` channel (400 levels, snapshot + incremental updates).

The `books5` channel the bot used before is a full 5-level snapshot every 100 ms — TrapX, the wall detector
and the spoof metric were designed for 50 levels and were starved. `books` delivers one snapshot and then
deltas: [price, size, liquidated_orders, order_count]; size "0" deletes the level. Integrity is checked with
the seqId chain (every update's prevSeqId must equal the last seqId; a gap means resubscribe) and, when OKX
sends a non-zero checksum, with the CRC32 of the top-25 interleaved "bidPx:bidSz:askPx:askSz…" string.
"""
import struct
import zlib
from typing import Any, Dict, List, Optional, Tuple


class SequenceGap(Exception):
    """An update did not chain to the previous one; the local book can no longer be trusted."""


class L2Book:
    def __init__(self):
        self.bids: Dict[str, str] = {}      # price string → size string (strings preserved for the checksum)
        self.asks: Dict[str, str] = {}
        self.seq_id: Optional[int] = None
        self.ts_ms: Optional[int] = None
        self.ready: bool = False
        self.updates: int = 0

    def reset(self) -> None:
        self.__init__()

    def apply(self, action: str, data: Dict[str, Any]) -> None:
        """Apply one `books` message payload (data[0]). Raises SequenceGap when the chain breaks."""
        seq = _int(data.get("seqId"))
        prev = _int(data.get("prevSeqId"))
        if action == "snapshot":
            self.bids.clear(); self.asks.clear()
            self.ready = True
        else:
            if not self.ready:
                raise SequenceGap("update before snapshot")
            if prev is not None and self.seq_id is not None and prev != self.seq_id:
                raise SequenceGap(f"prevSeqId {prev} != last seqId {self.seq_id}")
        for side, store in (("bids", self.bids), ("asks", self.asks)):
            for level in data.get(side, []):
                if len(level) < 2:
                    continue
                price, size = str(level[0]), str(level[1])
                if float(size) == 0.0:
                    store.pop(price, None)
                else:
                    store[price] = size
        if seq is not None:
            self.seq_id = seq
        self.ts_ms = _int(data.get("ts")) or self.ts_ms
        self.updates += 1
        claimed = _int(data.get("checksum"))
        if claimed:                                   # OKX currently sends 0 on `books`; verify only when given
            actual = self.checksum()
            if actual != claimed:
                raise SequenceGap(f"checksum mismatch {actual} != {claimed}")

    def sorted_bids(self) -> List[Tuple[str, str]]:
        return sorted(self.bids.items(), key=lambda kv: -float(kv[0]))

    def sorted_asks(self) -> List[Tuple[str, str]]:
        return sorted(self.asks.items(), key=lambda kv: float(kv[0]))

    def top(self, n: int) -> Dict[str, List[Tuple[float, float]]]:
        """Best-first float levels for both sides (the structure MarketState.depth_20 publishes)."""
        return {"bids": [(float(p), float(s)) for p, s in self.sorted_bids()[:n]],
                "asks": [(float(p), float(s)) for p, s in self.sorted_asks()[:n]]}

    def checksum(self) -> int:
        bids, asks = self.sorted_bids()[:25], self.sorted_asks()[:25]
        parts: List[str] = []
        for i in range(25):
            if i < len(bids):
                parts += [bids[i][0], bids[i][1]]
            if i < len(asks):
                parts += [asks[i][0], asks[i][1]]
        crc = zlib.crc32(":".join(parts).encode())
        return struct.unpack("i", struct.pack("I", crc))[0]     # OKX compares against a signed 32-bit value

    def depth(self) -> Tuple[int, int]:
        return len(self.bids), len(self.asks)


def _int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None
