# TradingCore/data_managers/orderbook_parser.py
from typing import Dict, List, Any

def parse_orderbook(depth_data: Dict[str, Any], level: int = 20) -> Dict[str, List]:
    """
    Parses raw depth data into a structured dictionary.
    """
    if not isinstance(depth_data, dict):
        return {"bids": [], "asks": []}
        
    # Asterdex format is typically [[price, qty], ...]
    # Ensure data is handled safely
    bids = depth_data.get('bids', [])
    asks = depth_data.get('asks', [])

    return {
        "bids": bids[:level] if isinstance(bids, list) else [],
        "asks": asks[:level] if isinstance(asks, list) else []
    }
