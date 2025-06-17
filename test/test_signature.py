import os
import time, hmac, hashlib

API_KEY = os.environ["API_KEY"]
API_SECRET = os.environ["API_SECRET"]
UID = os.environ["UID"]

timestamp = str(int(time.time() * 1000))
payload = f"{API_KEY}{timestamp}"

signature = hmac.new(
    API_SECRET.encode("utf-8"),
    payload.encode("utf-8"),
    hashlib.sha256
).hexdigest()

print("UID:", UID)
print("Timestamp:", timestamp)
print("Signature:", signature)