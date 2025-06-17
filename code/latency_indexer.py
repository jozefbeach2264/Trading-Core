import time
import requests

def measure_latency(url: str):
    start = time.time()
    try:
        requests.get(url)
        end = time.time()
        return round((end - start) * 1000, 2)
    except Exception:
        return -1