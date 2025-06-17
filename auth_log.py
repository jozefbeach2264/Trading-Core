
import datetime

def log_auth_attempt(success: bool):
    timestamp = datetime.datetime.utcnow().isoformat()
    status = "SUCCESS" if success else "FAILURE"
    with open("auth_log.txt", "a") as f:
        f.write(f"[{timestamp}] Authentication {status}\n")