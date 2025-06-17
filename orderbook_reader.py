

import requests
from env_loader import get_env

def start_feed():
    env = get_env()
    url = f"{env['base_url']}/fapi/v1/depth?symbol=ETHUSDT&limit=5"
    try:
        response = requests.get(url)
        print("[ORDERBOOK] Snapshot:", response.json())
    except Exception as e:
        print("[ORDERBOOK] Error:", str(e))

def fetch_orderbook(pair="ETHUSDT", limit=50):
    env = get_env()
    url = f"{env['base_url']}/fapi/v1/depth?symbol={pair}&limit={limit}"
    response = requests.get(url)
    return response.json()