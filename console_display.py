import time
import shutil
import logging
from collections import deque
from data_managers.market_state import MarketState
from typing import List, Tuple, Optional, Dict, Deque, Any  # <- added Any

logger = logging.getLogger(__name__)

def format_market_state_for_console(market_state: MarketState) -> str:
    """
    Formats the current market state into a multi-line console dashboard,
    using the user's custom centered/indented layout.
    """
    try:
        # Get terminal width with a fallback
        try:
            terminal_width = shutil.get_terminal_size().columns
        except OSError:
            terminal_width = 80
        separator_line = "─" * terminal_width
        underscore_separator = "_" * terminal_width

        # --- Safely access all market state attributes ---
        symbol: str = getattr(market_state, 'symbol', 'N/A')
        mark_price: Optional[float] = getattr(market_state, 'mark_price', None)
        book_ticker: Dict[str, float] = getattr(market_state, 'book_ticker', {})
        recent_trades: Deque[Dict] = getattr(market_state, 'recent_trades', deque())
        open_interest: float = getattr(market_state, 'open_interest', 0.0)
        klines: Deque[List] = getattr(market_state, 'klines', deque())
        depth_20: Dict[str, Any] = getattr(market_state, 'depth_20', {})
        oi_history: Deque[Dict] = getattr(market_state, 'oi_history', deque())
        system_stats: Dict[str, Any] = getattr(market_state, 'system_stats', {})

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
                         if (now_ms - 5_000) <= int(t.get('time', 0)) and not t.get('isBuyerMaker', False))
        total_vol_5s = vol_data['5sec']
        imbalance_pct = (buy_vol_5s / total_vol_5s * 100) if total_vol_5s > 0 else 50.0

        # 4. Walls  (modified)
        # Select top 3 by qty from the first 20 levels, then display:
        # Bid 3, Bid 2, Bid 1 (where Bid 1 is closest to mark), Mark, Ask 1, Ask 2, Ask 3.
        def _top3_levels(levels):
            # take first 20, coerce to floats, pick 3 largest by qty
            lvls = []
            for x in (levels[:20] if levels else []):
                try:
                    p, q = float(x[0]), float(x[1])
                    lvls.append((p, q))
                except Exception:
                    continue
            return sorted(lvls, key=lambda t: t[1], reverse=True)[:3]

        mark = float(mark_price or 0.0)
        bids20 = depth_20.get('bids', [])
        asks20 = depth_20.get('asks', [])

        top_bids = _top3_levels(bids20)
        top_asks = _top3_levels(asks20)

        # Order for display:
        # - Bids: closest to mark should be Bid 1 (highest price), so show Bid3 (farthest), Bid2, Bid1 (closest).
        # - Asks: closest to mark should be Ask 1 (lowest price), then Ask 2, Ask 3.
        # Determine closeness by price distance to mark.
        if mark > 0.0:
            # bids: closer = higher price (assuming bids <= mark)
            top_bids_sorted_closest_first = sorted(top_bids, key=lambda x: (abs(mark - x[0]), -x[0]))
            # asks: closer = lower price (assuming asks >= mark)
            top_asks_sorted_closest_first = sorted(top_asks, key=lambda x: (abs(x[0] - mark), x[0]))
        else:
            # fallback: just sort by price appropriately if mark missing
            top_bids_sorted_closest_first = sorted(top_bids, key=lambda x: -x[0])
            top_asks_sorted_closest_first = sorted(top_asks, key=lambda x: x[0])

        # Ensure we have exactly 3 slots (pad with empties if fewer levels available)
        def _pad3(arr): 
            arr = list(arr)
            while len(arr) < 3:
                arr.append((0.0, 0.0))
            return arr

        top_bids_sorted_closest_first = _pad3(top_bids_sorted_closest_first)
        top_asks_sorted_closest_first = _pad3(top_asks_sorted_closest_first)

        # For bids: show Bid 3 (farthest), Bid 2, Bid 1 (closest)
        bid1 = top_bids_sorted_closest_first[0]
        bid2 = top_bids_sorted_closest_first[1]
        bid3 = top_bids_sorted_closest_first[2]

        # For asks: show Ask 1 (closest), Ask 2, Ask 3 (farthest)
        ask1 = top_asks_sorted_closest_first[0]
        ask2 = top_asks_sorted_closest_first[1]
        ask3 = top_asks_sorted_closest_first[2]
        
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
        if len(oi_history) > 1:
            # Use the second to last entry as the baseline for a 1-min change
            first_oi = float(oi_history[0].get('openInterest', 0.0))
            if first_oi > 0:
                oi_change_1min = ((open_interest - first_oi) / first_oi) * 100

        # 7. System Stats
        cpu_percent = system_stats.get('cpu', 0.0)
        ram_percent = system_stats.get('ram', 0.0)

        # --- DISPLAY CONSTRUCTION ---
        
        indent = " " * 5 # Set the indentation level for all metrics
        
        formatted_mark_price = f"{mark_price:.3f}" if mark_price is not None else "N/A"
        
        header = f"{separator_line}\n        {symbol}  |  {formatted_mark_price}\n{separator_line}"

        lines = [
            f"{indent}TREND: {trend_emoji} {trend_text}",
            f"{indent}OI(Total): {open_interest:.3f}",
            f"{indent}OI(1min): {oi_change_1min:+.3f}%",
            f"{underscore_separator}",
            f"{indent}SPREAD     : {spread:.3f}",
            f"{indent}IMBALANCE  : {imbalance_pct:.0f}% {'BUY' if imbalance_pct >= 50 else 'SELL'}",
            f"{indent}VOL (5sec) : {vol_data['5sec']:.3f} ETH",
            f"{indent}VOL (15sec): {vol_data['15sec']:.3f} ETH",
            f"{indent}VOL (1min) : {vol_data['1min']:.3f} ETH",
            f"{indent}DELTA(1min): {delta_data['1min']:+.3f} ETH",
            f"{indent}DELTA(5sec): {delta_data['5sec']:+.3f} ETH {trend_emoji}",
            # --- replaced wall display below ---
            f"{indent}Bid 3: {bid3[0]:.3f} ({bid3[1]:.3f} ETH)",
            f"{indent}Bid 2: {bid2[0]:.3f} ({bid2[1]:.3f} ETH)",
            f"{indent}Bid 1: {bid1[0]:.3f} ({bid1[1]:.3f} ETH)",
            f"{indent}Mark: {formatted_mark_price}",
            f"{indent}Ask 1: {ask1[0]:.3f} ({ask1[1]:.3f} ETH)",
            f"{indent}Ask 2: {ask2[0]:.3f} ({ask2[1]:.3f} ETH)",
            f"{indent}Ask 3: {ask3[0]:.3f} ({ask3[1]:.3f} ETH)",
            f"{separator_line}",
            f"{indent}CPU : {cpu_percent:03.0f}%          RAM : {ram_percent:03.0f}%",
            f"{separator_line}"
        ]
        
        # Clear the console and print the new display
        return f"\033[H\033[J{header}\n" + "\n".join(lines)

    except Exception as e:
        logger.error(f"Error in format_market_state_for_console: {e}", exc_info=True)
        return "Error generating display. Check logs."
