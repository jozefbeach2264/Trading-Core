from request_wrapper import send_request
from secret_loader import get_keys
from signature_auth import generate_signature
from timestamp_sync import get_current_timestamp

def ping():
    keys = get_keys()
    ts = get_current_timestamp()
    sig = generate_signature(keys['SECRET_KEY'], ts)
    url = "https://fapi.asterdex.com/fapi/v1/ping"
    response = send_request("get", url, keys['API_KEY'], sig, ts)
    return response.status_code == 200