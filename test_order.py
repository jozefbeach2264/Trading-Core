
from request_builder import build_signed_request
from env_loader import get_env
import requests

def test_order():
    env = get_env()
    endpoint = "/fapi/v1/order"
    params = f"symbol=ETHUSDT&side=BUY&type=MARKET&quantity=0.001&timestamp={get_synchronized_timestamp()}"
    url, headers = build_signed_request(endpoint, params)
    response = requests.post(url, headers=headers)
    return response.json()