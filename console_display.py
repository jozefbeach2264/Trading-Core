# TradingCore/console_display.py
import time
import shutil
import logging
from market_state import MarketState
from typing import List, Tuple

logger = logging.getLogger(__name__)

def format_market_state_for_console(market_state: MarketState) -> str:
    """
    Formats the current market state into a multi-line console dashboard.
    Includes Volume (1min, 15sec, 5sec), Delta (1min, 5sec), OI (Total, 5min, 1min).
    All data up to current moment, values formatted to 0.000 precision.
    """
    try:
        # Get terminal width with fallback
        try:
            terminal_width = shutil.get_terminal_size().columns
        except OSError:
            terminal_width = 80
        separator_line = "─" * terminal_width

        # Safely access market state attributes
        symbol = getattr(market_state, 'symbol', 'N/A')
        mark_price = getattr(market_state, 'mark_price', 0.0)
        book_ticker = getattr(market_state, 'book_ticker', {})
        klines = getattr(market_state, 'klines', [])
        recent_trades = getattr(market_state, 'recent_trades', [])
        depth_20 = getattr(market_state, 'depth_20', {})
        open_interest = getattr(market_state, 'open_interest', 0.0)
        oi_history = getattr(market_state, 'oi_history', [])

        # Log if mark_price is stuck at 0.0
        if mark_price == 0.0:
            logger.warning("mark_price is 0.0; check book_ticker or premium_index data.")

        # Calculate spread
        bid_price = float(book_ticker.get('bidPrice', 0.0))
        ask_price = float(book_ticker.get('askPrice', 0.0))
        spread = ask_price - bid_price if bid_price and ask_price else 0.0

        # Calculate volume and delta for specified timeframes
        timeframes = {
            '1min': 60_000,  # 1 minute in ms
            '15sec': 15_000,
            '5sec': 5_000
        }
        vol_data = {k: 0.0 for k in timeframes}
        delta_data = {k: 0.0 for k in ['1min', '5sec']}
        now_ms = int(time.time() * 1000)

        for trade in recent_trades:
            trade_time = int(trade.get('time', 0))
            qty = float(trade.get('qty', 0.0))
            is_buy = not trade.get('isBuyerMaker', False)
            for tf_name, tf_ms in timeframes.items():
                cutoff_ms = now_ms - tf_ms
                if cutoff_ms <= trade_time:
                    vol_data[tf_name] += qty
                    if tf_name in ['1min', '5sec']:
                        delta_data[tf_name] += qty if is_buy else -qty

        # Calculate imbalance (using 5sec for consistency)
        buy_vol_5s = sum(float(t.get('qty', 0)) for t in recent_trades
                         if now_ms - 5_000 <= int(t.get('time', 0)) and not t.get('isBuyerMaker'))
        sell_vol_5s = vol_data['5sec'] - buy_vol_5s
        total_vol_5s = buy_vol_5s + sell_vol_5s
        imbalance_pct = (buy_vol_5s / total_vol_5s * 100) if total_vol_5s > 0 else 50.0

        # Calculate order book walls
        ask_wall_price, ask_wall_qty = max(depth_20.get('asks', []), key=lambda x: float(x[1]), default=(0.0, 0.0))
        bid_wall_price, bid_wall_qty = max(depth_20.get('bids', []), key=lambda x: float(x[1]), default=(0.0, 0.0))

        # Calculate trend
        change_1m = 0.0
        if klines:
            k_open = float(klines[-1][1])
            k_close = float(klines[-1][4])
            if k_open > 0:
                change_1m = ((k_close - k_open) / k_open) * 100
        trend_emoji = "🔼" if change_1m >= 0 else "🔽"
        trend_text = "MICRO-UP" if change_1m >= 0 else "MICRO-DOWN"

        # Calculate OI metrics
        oi_total = open_interest
        oi_change_5min = 0.0
        oi_change_1min = 0.0
        if oi_history:
            cutoff_5min = now_ms - 300_000
            cutoff_1min = now_ms - 60_000
            for oi_entry in reversed(oi_history):
                oi_time = oi_entry.get('time', 0)
                oi_value = float(oi_entry.get('openInterest', 0.0))
                if oi_time <= now_ms:
                    if oi_time <= cutoff_5min and oi_change_5min == 0.0:
                        oi_change_5min = ((oi_total - oi_value) / oi_value * 100) if oi_value > 0 else 0.0
                    if oi_time <= cutoff_1min and oi_change_1min == 0.0:
                        oi_change_1min = ((oi_total - oi_value) / oi_value * 100) if oi_value > 0 else 0.0
                    if oi_change_5min != 0.0 and oi_change_1min != 0.0:
                        break

        # Format display
        header = f"{separator_line}\n        {symbol}  |  {mark_price:.3f}\n{separator_line}"
        lines = [
            f" SPREAD     : {spread:.3f}",
            f" VOL (1min) : {vol_data['1min']:.3f} ETH",
            f" VOL (15sec): {vol_data['15sec']:.3f} ETH",
 f" VOL (5sec) : {vol_data['5sec']:.3f} ETH",
            f" DELTA(1min): {delta_data['1min']:+.3f} ETH",
            f" DELTA(5sec): {delta_data['5sec']:+.3f} ETH {trend_emoji}",
            f" IMBALANCE  : {imbalance_pct:.0f}% {'BUY' if imbalance_pct >= 50 else 'SELL'}",
            f" WALL (ASK) : {float(ask_wall_price):.3f} ({float(ask_wall_qty):.3f} ETH)",
            f" WALL (BID) : {float(bid_wall_price):.3f} ({float(bid_wall_qty):.3f} ETH)",
            f"{separator_line}",
            f"TREND: {trend_emoji} {trend_text}     OI(Total): {oi_total:.3f} OI(5min): {oi_change_5min:+.3f}% OI(1min): {oi_change_1min:+.3f}%",
            f"{separator_line}"
        ]
        return f"\033[H\033[J{header}\n" + "\n".join(lines)

    except Exception as e:
        logger.error(f"Error in format_market_state_for_console: {e}", exc_info=True)
        return "Error generating display. Check logs."