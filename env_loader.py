
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
UID = os.getenv("UID")
BASE_URL = os.getenv("BASE_URL", "https://fapi.asterdex.com")

def validate_secrets ():
    if not all([API_KEY, SECRET_KEY, UID]):
        raise
EnvironmentError("Missing one or more environment variables.")
def get_env():
    if not all([API_KEY, SECRET_KEY, UID]):
        raise EnvironmentError("Missing one or more environment variables.")
    return {
        "api_key": API_KEY,
        "secret_key": SECRET_KEY,
        "uid": UID,
        "base_url": BASE_URL
    }

def load_env():
    from dotenv import load_dotenv
    load_dotenv()