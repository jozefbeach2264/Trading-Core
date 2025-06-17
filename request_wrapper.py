
import requests
from headers_builder import build_headers

def send_request(method: str, url: str, api_key: str, signature: str, timestamp: str, payload=None):
    headers = build_headers(api_key, signature, timestamp)
    if method.lower() == "get":
        return requests.get(url, headers=headers, params=payload)
    elif method.lower() == "post":
        return requests.post(url, headers=headers, json=payload)
    else:
        raise ValueError("Unsupported HTTP method")