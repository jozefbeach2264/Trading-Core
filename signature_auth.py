import hmac
import hashlib
import base64
import os

def generate_signature(secret_key, message):
    signature = hmac.new(secret_key.encode(), message.encode(), hashlib.sha256).hexdigest()
    return signature

def verify_signature(secret_key, message, client_sig):
    server_sig = generate_signature(secret_key, message)
    return hmac.compare_digest(server_sig, client_sig)