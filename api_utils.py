
import time
import hmac
import hashlib

def generate_signature(api_secret, timestamp, payload=""):
    message = f"{timestamp}{payload}".encode()
    return hmac.new(api_secret.encode(), message, hashlib.sha256).hexdigest()

def get_timestamp_ms():
    return str(int(time.time() * 1000))