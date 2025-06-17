
import os

def confirm_uid():
    uid = os.getenv("UID")
    if not uid:
        raise EnvironmentError("UID not found in secrets.")
    return uid