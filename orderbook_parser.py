from typing import List, Tuple, Dict, Any

def parse_orderbook(data: Dict[str, Any]) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]:
    """
    Parses the raw order book data from the exchange API into a clean format.

    Args:
        data (Dict[str, Any]): The raw JSON response from a depth endpoint.

    Returns:
        A tuple containing two lists: one for bids and one for asks.
        Each list contains tuples of (price, quantity), both as floats.
    """
    # Use .get() to safely access keys, providing an empty list as a default.
    # This prevents KeyErrors if the 'bids' or 'asks' key is missing.
    try:
        bids = [(float(price), float(qty)) for price, qty in data.get('bids', [])]
        asks = [(float(price), float(qty)) for price, qty in data.get('asks', [])]
    except (ValueError, TypeError) as e:
        # If any value cannot be converted to float, return empty lists.
        # This handles malformed data gracefully.
        print(f"Error parsing order book data: {e}. Data: {data}")
        return [], []
    
    return bids, asks
