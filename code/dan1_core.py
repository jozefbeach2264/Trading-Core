def core_logic_dan1(signal):
    """
    DAN1 logic layer — handles Scalpel triggers and fast entries.
    """
    if signal.get("strategy") == "scalpel":
        if signal.get("volume") > 25000 and signal.get("speed") > 30:
            return True
    return False