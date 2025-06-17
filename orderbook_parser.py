def parse_orderbook(data):
    bids = [(float(price), float(qty)) for price, qty in data.get('bids', [])]
    asks = [(float(price), float(qty)) for price, qty in data.get('asks', [])]
    return bids, asks