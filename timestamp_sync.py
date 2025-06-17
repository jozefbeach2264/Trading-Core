import time
import requests

def get_server_time(base_url):
    try:
        response = requests.get(f"{base_url}/fapi/v1/time")
        return response.json()["serverTime"]
    except:
        return int(time.time() * 1000)