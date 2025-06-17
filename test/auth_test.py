import os
import requests
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from api_utils import generate_signature, get_timestamp_ms

# Load env vars
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
UID = os.getenv("UID")

# Generate auth values
timestamp = get_timestamp_ms()
signature = generate_signature(API_SECRET, timestamp)

# Prepare headers
headers = {
    "Content-Type": "application/json",
    "X-API-KEY": API_KEY,
    "X-UID": UID,
    "X-SIGNATURE": signature,
    "X-TIMESTAMP": timestamp
}

# Endpoint (e.g. indexPriceKlines - no payload required)
url = "https://fapi.asterdex.com/fapi/v1/indexPriceKlines"
params = {
    "pair": "ETHUSDT",
    "interval": "1m",
    "limit": "1"
}

# Execute GET
response = requests.get(url, headers=headers, params=params)

# Output
print("Status Code:", response.status_code)
print("Response:", response.text)