
import requests
from timestamp_sync import get_server_timestamp
from auth_handler import get_auth_headers

def validate_connection(base_url):
    test_endpoint = "/fapi/v1/ping"
    timestamp = get_server_timestamp()
    headers = get_auth_headers(test_endpoint, timestamp)

    try:
        response = requests.get(f"{base_url}{test_endpoint}", headers=headers)
        return response.status_code == 200
    except requests.exceptions.RequestException as e:
        print("Connection error:", e)
        return False