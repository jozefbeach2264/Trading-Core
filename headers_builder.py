def build_headers(api_key: str, signature: str, timestamp: str) -> dict:
    return {
        "X-ASTER-APIKEY": api_key,
        "X-ASTER-SIGN": signature,
        "X-ASTER-TIMESTAMP": timestamp,
        "Content-Type": "application/json"
    }