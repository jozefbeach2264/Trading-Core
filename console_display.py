# TradingCore/console_display.py
import time
import shutil
from market_state import MarketState

def format_market_state_for_console(market_state: MarketState) -> str:
    """Takes the current market state and formats it into a rich, multi-line dashboard."""
    try:
        terminal_width = shutil.get_terminal_size().columns
        separator_line = "─" * terminal_width

        # Safely get all required data with defaults
        symbol = getattr(market_state, 'symbol', 'N/A')
        mark_price = getattr(market_state, 'mark_price', 0.0)
        book_ticker = getattr(market_state, 'book_ticker', {})
        klines = getattr(market_state, 'klines', [])
        recent_trades = getattr(market_state, 'recent_trades', [])
        depth_20 = getattr(market_state, 'depth_20', {})
        open_interest = getattr(market_state, 'open_interest', 0.0)
        previous_open_interest = getattr(market_state, 'previous_open_interest', 0.0)

        # --- Calculations (with updated logic) ---
        bid_price = float(book_ticker.get('bidPrice', 0.0))
        ask_price = float(book_ticker.get('askPrice', 0.0))
        spread = ask_price - bid_price if bid_price and ask_price else 0.0

        # --- NEW: Calculate volume and delta from the entire fetched trade batch ---
        batch_vol, buy_vol, sell_vol = 0.0, 0.0, 0.0
        for trade in recent_trades:
            qty = float(trade.get('qty', 0))
            batch_vol += qty
            if not trade.get('isBuyerMaker'):
                buy_vol += qty
            else:
                sell_vol += qty
        
        delta = buy_vol - sell_vol
        imbalance_pct = (buy_vol / batch_vol * 100) if batch_vol > 0 else 50
        
        ask_wall_price, ask_wall_qty = max(depth_20.get('asks', []), key=lambda x: float(x[1]), default=(0, 0))
        bid_wall_price, bid_wall_qty = max(depth_20.get('bids', []), key=lambda x: float(x[1]), default=(0, 0))
        
        change_1m = 0.0
        if klines:
            k_open = float(klines[-1][1])
            k_close = float(klines[-1][4])
            if k_open > 0: change_1m = ((k_close - k_open) / k_open) * 100
        trend_emoji = "🔼" if change_1m >= 0 else "🔽"
        trend_text = "MICRO-UP" if change_1m >= 0 else "MICRO-DOWN"
        
        oi_text = "OI: N/A"
        if previous_open_interest > 0 and open_interest > 0:
            oi_change = (open_interest - previous_open_interest) / previous_open_interest * 100
            oi_text = f"OI: {oi_change:+.3f}%"

        # --- Formatting (label changed from VOL (1s) to VOL (BATCH)) ---
        header = f"{separator_line}\n        {symbol}  |  {mark_price:.3f}\n{separator_line}"
        lines = [
            f" SPREAD     : {spread:.3f}",
            f" VOL (BATCH): {batch_vol / 1000:.2f}K", # Changed label for clarity
            f" DELTA      : {delta / 1000:+.2f}K {trend_emoji}",
            f" IMBALANCE  : {imbalance_pct:.0f}% {'BUY' if imbalance_pct >= 50 else 'SELL'}",
            f" WALL (ASK) : {float(ask_wall_price):.3f} ({float(ask_wall_qty):.1f} ETH)",
            f" WALL (BID) : {float(bid_wall_price):.3f} ({float(bid_wall_qty):.1f} ETH)",
            f"{separator_line}",
            f"TREND: {trend_emoji} {trend_text}     {oi_text}",
            f"{separator_line}"
        ]
        return f"\033[H\033[J{header}\n" + "\n".join(lines)
    except Exception as e:
        return f"Error generating display: {e}"
