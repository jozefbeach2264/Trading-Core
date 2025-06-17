
def check_loop_integrity(cycle_time: float, drift_threshold: float = 0.1):
    from time import time, sleep
    last = time()
    while True:
        now = time()
        drift = abs(now - last - cycle_time)
        if drift > drift_threshold:
            print(f"[WARNING] Loop drift: {drift:.4f}s")
        last = now
        sleep(cycle_time)