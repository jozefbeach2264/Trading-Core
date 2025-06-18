import json
import os

NEUROSYNC_DATA_PATH = "neurosync_relay.json"

def load_neurosync_signal():
    if not os.path.exists(NEUROSYNC_DATA_PATH):
        return None
    with open(NEUROSYNC_DATA_PATH, 'r') as f:
        try:
            data = json.load(f)
            return data
        except json.JSONDecodeError:
            return None

def clear_neurosync_signal():
    with open(NEUROSYNC_DATA_PATH, 'w') as f:
        f.write('{}')