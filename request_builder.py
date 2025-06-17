import requests
from signature_auth import create_signature, get_timestamp
from env_loader import get_env

def build_signed_request(endpoint, params):
    env = get_env()
    timestamp = get_timestamp()
    payload = f"{params}&timestamp={timestamp}"
    signature = create_signature(env['secret_key'], payload)
    headers = {
        "X-API-KEY": env['api_key']
    }
    url = f"{env['base_url']}{endpoint}?{payload}&signature={signature}"
    return url, headers