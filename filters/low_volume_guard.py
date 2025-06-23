# TradingCore/filters/low_volume_guard.py
import logging
import os
from typing import Dict, Any, List

# Configure logging
logger = logging.getLogger(__name__)

class LowVolumeGuard:
    """
    This filter rejects trades during low-volume periods to prevent slippage
    and entries in illiquid market conditions. The threshold is based on the
    base asset volume (e.g., ETH) and is configurable via Replit Secrets.
    """
    KLINE_BASE_VOLUME_INDEX = 5
    
    def __init__(self):
        """
        Initializes the LowVolumeGuard filter and loads its threshold from secrets.
        """
        # A sensible default for base asset volume (e.g., 100 ETH)
        default_threshold = 100.0
        
        # --- UPDATED: Using the new secret key name "LOW_ETH_VOL" ---
        secret_key_name = "LOW_ETH_VOL"
        
        try:
            threshold_from_secret = float(os.getenv(secret_key_name))
            self.volume_threshold = threshold_from_secret if threshold_from_secret is not None else default_threshold
        except (ValueError, TypeError):
            self.volume_threshold = default_threshold

        logger.info(
            "LowVolumeGuard initialized with a base asset volume threshold of: %s ETH",
            self.volume_threshold
        )

    async def validate(self, signal_data: Dict[str, Any]) -> bool:
        """
        Validates the signal based on the base asset volume of the last 1-minute kline.
        """
        klines: List[List[Any]] = signal_data.get("klines", [])
        symbol = signal_data.get("symbol", "unknown")

        if not klines:
            logger.warning("Signal REJECTED by LowVolumeGuard: No kline data available.")
            return False

        try:
            last_kline = klines[-1]
            base_asset_volume = float(last_kline[self.KLINE_BASE_VOLUME_INDEX])
            
            if base_asset_volume < self.volume_threshold:
                logger.warning(
                    "Signal REJECTED for %s by LowVolumeGuard: Last 1m volume %s ETH is below threshold of %s ETH",
                    symbol,
                    f"{base_asset_volume:,.2f}",
                    f"{self.volume_threshold:,.2f}"
                )
                return False

            logger.info(
                "Signal PASSED LowVolumeGuard: Last 1m volume %s ETH is sufficient.",
                f"{base_asset_volume:,.2f}"
            )
            return True

        except (IndexError, TypeError, ValueError) as e:
            logger.error(
                "Signal REJECTED by LowVolumeGuard due to data error: %s. Kline data: %s",
                e, klines
            )
            return False
