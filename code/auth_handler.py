import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
UID = os.getenv("UID")

def get_auth_headers(endpoint, timestamp):
    message = f"{UID}{endpoint}{timestamp}"
    from signature_auth import generate_signature
    signature = generate_signature(SECRET_KEY, message)
    return {
        "X-API-KEY": API_KEY,
        "X-SIGNATURE": signature,
        "X-TIMESTAMP": str(timestamp),
        "X-UID": UID
    }