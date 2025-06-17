def simulate_trade(entry_price, exit_price, direction="LONG", size=1.0, leverage=200):
    global capital

    if capital <= 0:
        print("[SIMULATOR] Capital depleted. Reinitializing with $10.")
        capital = starting_capital

    position_value = capital * leverage * size

    if direction == "LONG":
        pnl = (exit_price - entry_price) * (position_value / entry_price)
    elif direction == "SHORT":
        pnl = (entry_price - exit_price) * (position_value / entry_price)
    else:
        raise ValueError(f"Unknown trade direction: {direction}")

    gross_roi = pnl / capital
    gross_profit = capital * gross_roi

    fee = capital * FEE_RATE
    slip = capital * SLIPPAGE
    net_profit = gross_profit - fee - slip
    capital += net_profit

    trade_record = {
        "entry": entry_price,
        "exit": exit_price,
        "direction": direction,
        "size": size,
        "gross_roi": round(gross_roi * 100, 2),
        "net_profit": round(net_profit, 4),
        "capital_after": round(capital, 4)
    }
    trade_log.append(trade_record)

    print(f"[TRADE] {direction} Entry: {entry_price} Exit: {exit_price} ROI: {trade_record['gross_roi']}% "
          f"Net: {trade_record['net_profit']} Capital: {trade_record['capital_after']}")