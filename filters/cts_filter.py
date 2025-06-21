def apply_cts_filter(signal_data):
    """
    Compression Trap Sensor (CTS) filter logic.
    Rejects trades if compression exceeds risk thresholds.
    """
    compression_score = signal_data.get("compression_score", 0)
    if compression_score > 0.75:
        return False  # Block entry due to compression risk
    return True