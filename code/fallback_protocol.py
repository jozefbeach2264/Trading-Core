def fallback_action(reason: str):
    from auth_log import log_auth_attempt
    log_auth_attempt(success=False)
    print(f"[FALLBACK TRIGGERED] :: {reason}")