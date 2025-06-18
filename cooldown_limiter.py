import time

class CooldownLimiter:
    def __init__(self, cooldown_secs=300):
        self.cooldown_secs = cooldown_secs
        self.last_exit_time = 0

    def start_cooldown(self):
        self.last_exit_time = time.time()

    def is_ready(self):
        return (time.time() - self.last_exit_time) >= self.cooldown_secs