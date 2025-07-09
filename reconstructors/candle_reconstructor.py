import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

class CandleReconstructor:
    """
    Reconstructs a 1-minute OHLCV candle in real-time by aggregating
    live trade data from a WebSocket stream. This simulates the data structure
    of an official kline/candle feed.
    """
    def __init__(self):
        self.current_candle: Optional[List[Any]] = None
        self.current_minute_timestamp: Optional[int] = None
        logger.info("CandleReconstructor initialized.")

    def _start_new_candle(self, trade: Dict[str, Any]) -> None:
        """Initializes a new 1-minute candle based on the first trade of the minute."""
        price = float(trade['px'])
        volume = float(trade['sz'])
        timestamp = int(trade['ts'])
        
        # Calculate the starting timestamp for the current minute (e.g., 17:45:33 -> 17:45:00)
        self.current_minute_timestamp = timestamp - (timestamp % 60000)

        # This structure mimics the official OKX kline format:
        # [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
        self.current_candle = [
            self.current_minute_timestamp, # 0: Timestamp (start of the minute)
            price,                        # 1: Open
            price,                        # 2: High
            price,                        # 3: Low
            price,                        # 4: Close
            volume,                       # 5: Volume (in base currency, e.g., ETH)
            price * volume,               # 6: Volume (in quote currency, e.g., USDT)
            0.0,                          # 7: volCcyQuote (unused, kept for structure)
            "0"                           # 8: Confirmation flag (0 = in-progress)
        ]
        logger.debug(f"Started new 1m candle at {self.current_minute_timestamp} with trade: {trade}")

    def process_trade(self, trade: Dict[str, Any]) -> Optional[List[Any]]:
        """
        Processes a single trade from the WebSocket feed, updating the current candle.
        
        Returns:
            A list representing the completed candle if a minute has just ended, 
            otherwise returns None.
        """
        try:
            trade_time = int(trade['ts'])
            trade_price = float(trade['px'])
            trade_volume = float(trade['sz'])
        except (ValueError, TypeError, KeyError) as e:
            logger.error(f"Could not parse trade data: {trade}. Error: {e}")
            return None

        completed_candle = None

        # If this is the very first trade we've seen, start the first candle.
        if self.current_candle is None:
            self._start_new_candle(trade)
            return None

        # Check if the trade belongs to a new minute.
        if trade_time >= self.current_minute_timestamp + 60000:
            # 1. Finalize the old candle by setting its confirmation flag.
            self.current_candle[8] = "1" 
            completed_candle = self.current_candle.copy()
            logger.info(f"Finalized 1m candle: {completed_candle}")
            
            # 2. Start a new candle with the current trade's data.
            self._start_new_candle(trade)
        else:
            # This trade is part of the current minute, so update the candle.
            # High price
            if trade_price > self.current_candle[2]:
                self.current_candle[2] = trade_price
            # Low price
            if trade_price < self.current_candle[3]:
                self.current_candle[3] = trade_price
            # Close price is always the last trade's price
            self.current_candle[4] = trade_price
            # Accumulate volume
            self.current_candle[5] += trade_volume
            self.current_candle[6] += trade_price * trade_volume

        return completed_candle

    def get_live_candle(self) -> Optional[List[Any]]:
        """
        Provides access to the current, in-progress candle for intra-candle analysis.
        This is the method the filters will call to get the latest data.
        """
        return self.current_candle.copy() if self.current_candle else None
