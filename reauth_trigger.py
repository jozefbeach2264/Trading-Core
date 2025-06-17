
import time

def trigger_reauth(cooldown=30):
    print("[AUTH] Reauthentication trigger issued.")
    time.sleep(cooldown)
    print("[AUTH] Cooldown complete. Proceed with credential refresh.")