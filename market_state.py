# TradingCore/market_state.py
import asyncio
from dataclasses import dataclass, field
from typing import List, Tuple

@dataclass
class MarketState:
    """A thread-safe, centralized container for all live market data."""
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # Ticker/Kline Data
    price: float = 0.0
    index_price: float = 0.0
    mark_price: float = 0.0
    funding_rate: float = 0.0
    open_interest: float = 0.0
    volume: float = 0.0
    high: float = 0.0
    low: float = 0.0
    open: float = 0.0
    close: float = 0.0

    # Order Book Data
    bids: List[Tuple[float, float]] = field(default_factory=list)  # List of (price, qty)
    asks: List[Tuple[float, float]] = field(default_factory=list)  # List of (price, qty)
    
    # Derived/Other Data
    long_short_ratio: float = 0.0
    oi_change_rate: float = 0.0 # Will need to be calculated
    liquidation_map: dict = field(default_factory=dict)

    def __str__(self):
        # A simple representation for printing.
        # The lock is removed as this is a non-critical debug view.
        return (f"Price: {self.price}, Mark: {self.mark_price}, OI: {self.open_interest}, "
                f"Bids[0]: {self.bids[0] if self.bids else None}, Asks[0]: {self.asks[0] if self.asks else None}")

