import json

LOG_FILE = "execution_log.json"

def append_log(entry):
    with open(LOG_FILE, "r+") as f:
        data = json.load(f)
        data.append(entry)
        f.seek(0)
        json.dump(data, f, indent=2)

def read_log():
    try:
        with open(LOG_FILE, "r") as f:
            return json.load(f)
    except:
        return []