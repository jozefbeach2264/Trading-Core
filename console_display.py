import time
import shutil
import logging
from collections import deque
from data_managers.market_state import MarketState
from typing import List, Tuple, Optional, Dict, Deque

logger = logging.getLogger(__name__)

def format_market_state_for_console(market_state: MarketState) -> str:
    """
    Formats the current market state into a multi-line console dashboard,
    using the user's original formatting and metrics.
    """
    try:
        # Get terminal width with a fallback
        try:
            terminal_width = shutil.get_terminal_size().columns
        except OSError:
            terminal_width = 80
        separator_line = "─" * terminal_width

        # Safely access market state attributes
        symbol: str = getattr(market_state, 'symbol', 'N/A')
        mark_price: Optional[float] = getattr(market_state, 'mark_price', None)
        book_ticker: Dict[str, float] = getattr(market_state, 'book_ticker', {})
        recent_trades: Deque[Dict] = getattr(market_state, 'recent_trades', deque())
        open_interest: float = getattr(market_state, 'open_interest', 0.0)
        klines: Deque[List] = getattr(market_state, 'klines', deque())
        depth_20: Dict[str, Any] = getattr(market_state, 'depth_20', {})
        oi_history: Deque[List] = getattr(market_state, 'oi_history', deque())

        # --- METRIC CALCULATIONS ---

        # 1. Spread
        bid_price = book_ticker.get('bidPrice', 0.0)
        ask_price = book_ticker.get('askPrice', 0.0)
        spread = ask_price - bid_price if bid_price and ask_price else 0.0

        # 2. Volume and Delta
        timeframes = {'1min': 60_000, '15sec': 15_000, '5sec': 5_000}
        vol_data = {k: 0.0 for k in timeframes}
        delta_data = {k: 0.0 for k in ['1min', '5sec']}
        now_ms = int(time.time() * 1000)

        for trade in recent_trades:
            trade_time = int(trade.get('time', 0))
            qty = float(trade.get('qty', 0.0))
            is_buy = not trade.get('isBuyerMaker', False)
            
            for tf_name, tf_ms in timeframes.items():
                if (now_ms - tf_ms) <= trade_time:
                    vol_data[tf_name] += qty
                    if tf_name in delta_data:
                        delta_data[tf_name] += qty if is_buy else -qty
        
        # 3. Imbalance
        buy_vol_5s = sum(float(t.get('qty', 0)) for t in recent_trades
                         if (now_ms - 5_000) <= int(t.get('time', 0)) and not t.get('isBuyerMaker'))
        sell_vol_5s = vol_data['5sec'] - buy_vol_5s
        total_vol_5s = buy_vol_5s + sell_vol_5s
        imbalance_pct = (buy_vol_5s / total_vol_5s * 100) if total_vol_5s > 0 else 50.0

        # 4. Walls
        ask_wall_price, ask_wall_qty = max(depth_20.get('asks', []), key=lambda x: float(x[1]), default=(0.0, 0.0))
        bid_wall_price, bid_wall_qty = max(depth_20.get('bids', []), key=lambda x: float(x[1]), default=(0.0, 0.0))
        
        # 5. Trend
        change_1m = 0.0
        if klines:
            last_kline = klines[-1]
            k_open = float(last_kline[1])
            k_close = float(last_kline[4])
            if k_open > 0:
                change_1m = ((k_close - k_open) / k_open) * 100
        trend_emoji = "🔼" if change_1m >= 0 else "🔽"
        trend_text = "MICRO-UP" if change_1m >= 0 else "MICRO-DOWN"

        # 6. OI Change
        oi_change_1min = 0.0
        if oi_history:
            first_oi = float(oi_history[0].get('openInterest', 0.0))
            if first_oi > 0:
                oi_change_1min = ((open_interest - first_oi) / first_oi) * 100

        # --- DISPLAY CONSTRUCTION (WITH ORIGINAL FORMATTING RESTORED) ---
        
        formatted_mark_price = f"{mark_price:.3f}" if mark_price is not None else "N/A"
        
        header = f"{separator_line}\n        {symbol}  |  {formatted_mark_price}\n{separator_line}"

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
            f"TREND: {trend_emoji} {trend_text}     OI(Total): {open_interest:.3f} OI(1min): {oi_change_1min:+.3f}%",
            f"{separator_line}"
        ]
        
        return f"\033[H\033[J{header}\n" + "\n".join(lines)

    except Exception as e:
        logger.error(f"Error in format_market_state_for_console: {e}", exc_info=True)
        return "Error generating display. Check logs."

