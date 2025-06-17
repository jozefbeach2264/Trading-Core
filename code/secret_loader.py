
import os
from dotenv import load_dotenv

load_dotenv()

REQUIRED_SECRETS = ["API_KEY", "SECRET_KEY", "UID"]

def validate_secrets():
    missing = [key for key in REQUIRED_SECRETS if not os.getenv(key)]
    if missing:
        raise EnvironmentError(f"Missing required secrets: {', '.join(missing)}")
    print("✅ All required secrets are present.")
