import os
import asyncio
from memory_tracker import MemoryTracker
from config.config import Config

async def main():
    mt = MemoryTracker(Config())
    await mt.update_memory(
        verdict_data={"direction": "LONG", "entry_price": 2500, "verdict": "Execute", "confidence": 0.9, "reason": "smoke"},
        trade_data={
            "direction": "LONG", "quantity": 0.01, "entry_price": 2500,
            "simulated": True, "failed": False, "reason": "smoke",
            "ai_verdict": {"action": "Execute", "confidence": 0.9}
        }
    )
    print("counts:", mt.get_counts())
    print("recent:", mt.get_recent_trades(3))

if __name__ == "__main__":
    asyncio.run(main())