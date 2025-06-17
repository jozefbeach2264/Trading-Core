from request_wrapper import send_request
from secret_loader import get_keys
from signature_auth import generate_signature
from timestamp_sync import get_current_timestamp

def relay_packet(endpoint: str, payload: dict):
    keys = get_keys()
    ts = get_current_timestamp()
    sig = generate_signature(keys['SECRET_KEY'], ts)
    return send_request("post", endpoint, keys['API_KEY'], sig, ts, payload)