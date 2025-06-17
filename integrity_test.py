def integrity_check(files: list):
    missing = [f for f in files if not f.exists()]
    if missing:
        raise FileNotFoundError(f"Missing files: {[f.name for f in missing]}")
    print("[INTEGRITY] All critical files are present.")