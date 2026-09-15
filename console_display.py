import time
import shutil
import logging
import sys
from collections import deque
from data_managers.market_state import MarketState
from typing import List, Tuple, Optional, Dict, Deque, Any

logger = logging.getLogger(__name__)

# HUD configuration
HUD_SEPARATOR_CHAR = "─"
HUD_HEADER_TEMPLATE = "{symbol}  |  {mark_price}"
# Tune which metrics to show
SHOW_WALLS = True
SHOW_OI = True
SHOW_DELTA = True
SHOW_IMBALANCE = True
SHOW_VOLUME = True
SHOW_TREND = True
SHOW_CVD = True
SHOW_RSI = True
RSI_PERIOD = 14

ASCII_FALLBACK_MAP = str.maketrans({
    "─": "-",
    "🔼": "^",
    "🔽": "v",
})


def _calculate_rsi(closes: List[float], period: int = 14) -> Optional[float]:
    if len(closes) <= period:
        return None

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    
    # Calculate initial average gain and loss from the first 'period' deltas
    initial_gains = [d for d in deltas[:period] if d > 0]
    initial_losses = [-d for d in deltas[:period] if d < 0]
    
    avg_gain = sum(initial_gains) / period
    avg_loss = sum(initial_losses) / period

    # Apply Wilder's smoothing for the rest of the data
    for i in range(period, len(deltas)):
        delta = deltas[i]
        gain = delta if delta > 0 else 0
        loss = -delta if delta < 0 else 0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def format_market_state_for_console(market_state: MarketState) -> str:
    """
    Formats a focused HUD: spread, volumes/deltas, imbalance, walls, trend, and OI.
    Keeps output concise for console readability.
    """
    try:
        # Get terminal width with a fallback
        try:
            terminal_width = shutil.get_terminal_size().columns
        except OSError:
            terminal_width = 80
        separator_line = HUD_SEPARATOR_CHAR * terminal_width

        # Safely access market state attributes
        symbol: str = getattr(market_state, 'symbol', 'N/A')
        mark_price: Optional[float] = getattr(market_state, 'mark_price', None)
        book_ticker: Dict[str, float] = getattr(market_state, 'book_ticker', {})
        recent_trades: Deque[Dict] = getattr(market_state, 'recent_trades', deque())
        open_interest: float = getattr(market_state, 'open_interest', 0.0)
        klines: Deque[List] = getattr(market_state, 'klines', deque())
        depth_20: Dict[str, Any] = getattr(market_state, 'depth_20', {})
        oi_history: Deque[Dict] = getattr(market_state, 'oi_history', deque())
        running_cvd: float = getattr(market_state, 'running_cvd', 0.0)

        # --- METRIC CALCULATIONS ---

        # 1. Spread
        bid_price = book_ticker.get('bidPrice', 0.0)
        ask_price = book_ticker.get('askPrice', 0.0)
        if (not bid_price or not ask_price) and depth_20.get("bids") and depth_20.get("asks"):
            # Fallback to top of book if ticker missing
            bid_price = depth_20["bids"][0][0]
            ask_price = depth_20["asks"][-1][0] if depth_20["asks"] else 0.0
        spread = ask_price - bid_price if bid_price and ask_price else 0.0
        # For display: show more precision to surface small changes
        spread = round(spread, 5)

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
        buy_vol_5s = sum(float(t.get('qty', 0.0)) for t in recent_trades
                         if (now_ms - 5_000) <= int(t.get('time', 0)) and t.get('side', '').lower() == 'buy')
        sell_vol_5s = sum(float(t.get('qty', 0.0)) for t in recent_trades
                          if (now_ms - 5_000) <= int(t.get('time', 0)) and t.get('side', '').lower() == 'sell')
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

        # 6. OI Change (1 minute window)
        oi_change_1min = 0.0
        now_ms = int(time.time() * 1000)
        if oi_history:
            # assume oi_history stores dicts with 'ts' and 'oi'
            recent = [float(item.get('oi', 0.0)) for item in oi_history if (now_ms - 60_000) <= int(item.get('ts', 0))]
            if recent:
                first_oi = recent[0]
                last_oi = recent[-1]
                if first_oi > 0:
                    oi_change_1min = ((last_oi - first_oi) / first_oi) * 100

        # 7. RSI (using latest closes, include live mark price for responsiveness)
        rsi_value = None
        if len(klines) > RSI_PERIOD:
            # klines stored newest-first (index 0 = newest), so reverse to get oldest->newest
            # Then cap to most recent 200 for responsiveness
            all_closes = [float(k[4]) for k in reversed(klines)]
            closes = all_closes[-min(200, len(all_closes)):]  # take most recent 200 or fewer

            # Use live reconstructed close if available to boost responsiveness
            live_close = None
            if market_state.live_reconstructed_candle and len(market_state.live_reconstructed_candle) > 4:
                try:
                    live_close = float(market_state.live_reconstructed_candle[4])
                except (TypeError, ValueError):
                    live_close = None

            # Inject live price as the most recent close for intra-candle responsiveness
            live_price = live_close or mark_price
            if live_price and live_price > 0:
                closes[-1] = live_price

            rsi_value = _calculate_rsi(closes, RSI_PERIOD)

        # --- DISPLAY CONSTRUCTION (WITH ORIGINAL FORMATTING RESTORED) ---
        
        formatted_mark_price = f"{mark_price:.3f}" if mark_price is not None else "N/A"
        
        header = f"{separator_line}\n        {HUD_HEADER_TEMPLATE.format(symbol=symbol, mark_price=formatted_mark_price)}\n{separator_line}"

        lines = [
            f" SPREAD     : {spread:.3f}",
        ]
        if SHOW_VOLUME:
            lines.append(f" VOL (1min) : {vol_data['1min']:.3f} ETH")
            lines.append(f" VOL (15sec): {vol_data['15sec']:.3f} ETH")
            lines.append(f" VOL (5sec) : {vol_data['5sec']:.3f} ETH")
        if SHOW_DELTA:
            lines.append(f" DELTA(1min): {delta_data['1min']:+.3f} ETH")
            lines.append(f" DELTA(5sec): {delta_data['5sec']:+.3f} ETH {trend_emoji}")
        if SHOW_IMBALANCE:
            lines.append(f" IMBALANCE  : {imbalance_pct:.0f}% {'BUY' if imbalance_pct >= 50 else 'SELL'}")
        if SHOW_WALLS:
            lines.append(f" WALL (ASK) : {float(ask_wall_price):.3f} ({float(ask_wall_qty):.3f} ETH)")
            lines.append(f" WALL (BID) : {float(bid_wall_price):.3f} ({float(bid_wall_qty):.3f} ETH)")
        if SHOW_CVD:
            lines.append(f" CVD        : {running_cvd:.2f}")
        if SHOW_RSI and rsi_value is not None:
            lines.append(f" RSI({RSI_PERIOD}) : {rsi_value:5.2f}")
        lines.append(f"{separator_line}")
        if SHOW_TREND or SHOW_OI:
            trend_part = f"{trend_emoji} {trend_text}" if SHOW_TREND else ""
            oi_part = f"OI(Total): {open_interest:.3f} OI(1min): {oi_change_1min:+.3f}%" if SHOW_OI else ""
            lines.append(f"TREND: {trend_part}     {oi_part}".strip())
        lines.append(f"{separator_line}")
        
        display_output = f"\033[H\033[J{header}\n" + "\n".join(lines)
        stdout_encoding = (getattr(sys.stdout, "encoding", None) or "").lower()
        if "ascii" in stdout_encoding:
            display_output = display_output.translate(ASCII_FALLBACK_MAP)
        return display_output

    except Exception as e:
        logger.error(f"Error in format_market_state_for_console: {e}", exc_info=True)
        return "Error generating display. Check logs."
