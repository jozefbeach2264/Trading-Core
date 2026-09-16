import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

class CandleReconstructor:
    """
    Reconstructs a 1-minute OHLCV candle in real-time by aggregating
    live trade data. Now includes hard finalization logic.
    """
    def __init__(self, contract_value: float = 1.0):
        self.contract_value = contract_value   # OKX SWAP sz is in contracts; convert to the base asset
        self.current_candle: Optional[List[Any]] = None
        self.current_minute_timestamp: Optional[int] = None
        # The first candle after a (re)connect starts at the first trade SEEN, not at the minute open.
        # It must never be finalised as a closed candle (it would poison every lookback average).
        self.current_is_partial: bool = False
        logger.info("CandleReconstructor initialized.")

    def reset(self) -> None:
        """Call on websocket reconnect: whatever we were building has a gap in it."""
        self.current_candle = None
        self.current_minute_timestamp = None
        self.current_is_partial = False

    def _start_new_candle(self, trade: Dict[str, Any], partial: bool = False) -> None:
        """Initializes a new 1-minute candle based on the first trade of the minute."""
        price = float(trade['px'])
        volume = float(trade['sz']) * self.contract_value
        timestamp = int(trade['ts'])

        self.current_minute_timestamp = timestamp - (timestamp % 60000)
        self.current_is_partial = partial

        # Structure: [ts,o,h,l,c,vol,volCcy,volCcyQuote,confirm]
        # 'confirm' flag (index 8) is "0" for in-progress.
        self.current_candle = [
            self.current_minute_timestamp, price, price, price, price,
            volume, price * volume, 0.0, "0"
        ]
        logger.info(f"Started new 1m candle at {self.current_minute_timestamp}")

    def process_trade(self, trade: Dict[str, Any]) -> Optional[List[Any]]:
        """
        Processes a single trade, updating the current candle.
        Returns the completed candle only when a minute boundary is crossed.
        """
        try:
            trade_time = int(trade['ts'])
            trade_price = float(trade['px'])
            trade_volume = float(trade['sz'])
            logger.debug(f"Processing trade: time={trade_time}, price={trade_price}, volume={trade_volume}")
        except (ValueError, TypeError, KeyError) as e:
            logger.error(f"Invalid trade data: {trade}. Error: {e}")
            return None

        completed_candle = None

        trade_volume *= self.contract_value

        if self.current_candle is None:
            self._start_new_candle(trade, partial=True)
            logger.debug(f"Initial (partial) candle state: {self.current_candle}")
            return None

        # Check if the trade belongs to a new minute.
        if trade_time >= self.current_minute_timestamp + 60000:
            if self.current_is_partial:
                logger.info("Discarding partial first candle %s (started mid-minute)", self.current_minute_timestamp)
            else:
                # Finalize the old candle by setting the 'confirm' flag to "1".
                self.current_candle[8] = "1"
                completed_candle = self.current_candle.copy()
                logger.info(f"Finalized 1m candle: {completed_candle}")

            # Start the next candle with the current trade's data.
            self._start_new_candle(trade)
        else:
            # Update current candle metrics.
            self.current_candle[2] = max(self.current_candle[2], trade_price)  # High
            self.current_candle[3] = min(self.current_candle[3], trade_price)  # Low
            self.current_candle[4] = trade_price  # Close
            self.current_candle[5] += trade_volume  # Volume
            self.current_candle[6] += trade_price * trade_volume  # Quote Volume
            logger.debug(f"Updated candle: {self.current_candle}")

        return completed_candle

    def get_live_candle(self) -> Optional[List[Any]]:
        """Provides access to the current, in-progress candle."""
        candle = self.current_candle.copy() if self.current_candle else None
        logger.debug(f"Live candle requested: {candle}")
        return candle