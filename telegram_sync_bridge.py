import json
import os

TELEGRAM_TRIGGER_PATH = "telegram_trigger.json"

def check_for_trigger():
    if not os.path.exists(TELEGRAM_TRIGGER_PATH):
        return None
    with open(TELEGRAM_TRIGGER_PATH, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return None

def clear_trigger():
    with open(TELEGRAM_TRIGGER_PATH, 'w') as f:
        f.write('{}')