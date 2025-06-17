def core_logic_dan2(signal):
    """
    DAN2 override layer — TrapX and cascade detection.
    """
    if signal.get("strategy") == "trapx" and signal.get("spoof_shift") >= 12:
        return True
    if signal.get("cascade") and signal.get("momentum") > 85:
        return True
    return False