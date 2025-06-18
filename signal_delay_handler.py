import time

class SignalDelayHandler:
    def __init__(self, delay_seconds=5):
        self.delay = delay_seconds
        self.last_trigger_time = None

    def confirm_after_delay(self, trigger_timestamp, current_timestamp, volume_confirmed):
        elapsed = current_timestamp - trigger_timestamp
        if elapsed >= self.delay:
            if volume_confirmed:
                return {
                    "confirmed": True,
                    "reason": "Delay complete, volume confirmed"
                }
            else:
                return {
                    "confirmed": False,
                    "reason": "Volume not confirmed after delay"
                }
        else:
            return {
                "confirmed": False,
                "reason": f"Waiting for delay window: {elapsed:.2f}/{self.delay}s"
            }

    def set_trigger(self):
        self.last_trigger_time = time.time()