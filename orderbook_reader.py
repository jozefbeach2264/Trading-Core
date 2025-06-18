from secure_fetcher import fetch_private

def fetch_orderbook(pair="ETHUSDT", limit=50):
    params = {
        "symbol": pair,
        "limit": limit
    }
    data = fetch_private("/fapi/v1/depth", params)
    return data