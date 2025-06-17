def detect_apex(candles):
    if len(candles) < 3:
        return False

    prev = float(candles[-2][4])
    curr = float(candles[-1][4])
    earlier = float(candles[-3][4])

    if curr < prev > earlier:
        return "top"
    elif curr > prev < earlier:
        return "bottom"
    else:
        return False