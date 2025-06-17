ASTERDEX_ENDPOINTS = {
    "base_url": "https://fapi.asterdex.com",
    "order": "/fapi/v1/order",
    "klines": "/fapi/v1/indexPriceKlines",
    "ticker": "/fapi/v1/ticker/price",
    "account": "/fapi/v1/account"
}

def get_endpoint(key):
    return ASTERDEX_ENDPOINTS.get(key, "")