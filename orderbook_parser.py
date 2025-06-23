# TradingCore/orderbook_parser.py
from typing import List, Tuple, Dict, Any

def parse_orderbook(data: Dict[str, Any]) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]:
    """
    Parses the raw order book data from the exchange API.

    Args:
        data (Dict[str, Any]): The raw JSON response from the /fapi/v1/depth endpoint.

    Returns:
        A tuple containing two lists: one for bids and one for asks.
        Each list contains tuples of (price, quantity).
    """
    # Use .get() to safely access keys, providing an empty list as a default
    bids = [(float(price), float(qty)) for price, qty in data.get('bids', [])]
    asks = [(float(price), float(qty)) for price, qty in data.get('asks', [])]
    
    return bids, asks
