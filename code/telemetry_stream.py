import time

def stream_telemetry(data: dict):
    timestamp = time.time()
    print(f"[TELEMETRY @ {timestamp}] :: {data}")