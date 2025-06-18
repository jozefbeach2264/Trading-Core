import time
import hashlib
import hmac
import requests
import json

with open("config.json") as f:
    CONFIG = json.load(f)

def sign_query(params):
    query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
    signature = hmac.new(
        CONFIG["SECRET_KEY"].encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return query_string + f"&signature={signature}"

def get_headers():
    return {
        "X-API-KEY": CONFIG["API_KEY"]
    }

def fetch_private(endpoint, params={}, method="GET"):
    base_url = "https://fapi.asterdex.com"
    params["timestamp"] = int(time.time() * 1000)
    params["uid"] = CONFIG["UID"]

    full_query = sign_query(params)
    url = f"{base_url}{endpoint}?{full_query}"

    try:
        if method == "GET":
            response = requests.get(url, headers=get_headers())
        else:
            response = requests.post(url, headers=get_headers())

        response.raise_for_status()
        return response.json()

    except Exception as e:
        return {"error": str(e)}