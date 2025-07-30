
import logging
from typing import Dict, Any, Tuple
from config.config import Config

logger = logging.getLogger(__name__)

class EntryRangeSimulator:
    """
    A fail-safe module that calculates realistic risk scenarios based on market volatility
    and recent price action rather than extreme forecast projections.
    """
    def __init__(self, config: Config):
        self.config = config
        self.liquidation_risk_threshold = self.config.max_liquidation_threshold
        logger.info(
            f"EntryRangeSimulator initialized with a max liquidation risk threshold of ${self.liquidation_risk_threshold:.2f}"
        )

    def calculate_market_volatility(self, klines: list) -> float:
        """
        Calculate average true range (ATR) from recent klines for realistic volatility measure.
        """
        if not klines or len(klines) < 5:
            return 20.0  # Default conservative volatility estimate
        
        true_ranges = []
        for i in range(min(5, len(klines))):  # Use last 5 candles
            kline = klines[i]
            high = float(kline[2])
            low = float(kline[3])
            prev_close = float(klines[i + 1][4]) if i + 1 < len(klines) else float(kline[4])
            
            # True Range calculation
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)
        
        atr = sum(true_ranges) / len(true_ranges)
        logger.debug(f"Calculated ATR: ${atr:.2f}")
        return atr

    def calculate_recent_move_strength(self, klines: list, current_price: float) -> float:
        """
        Analyze recent price momentum to adjust risk calculations.
        """
        if not klines or len(klines) < 3:
            return 1.0  # Neutral multiplier
        
        # Get last 3 closes
        recent_closes = [float(klines[i][4]) for i in range(min(3, len(klines)))]
        recent_closes.append(current_price)
        
        # Calculate momentum strength
        total_move = abs(recent_closes[0] - recent_closes[-1])
        avg_candle_size = sum(abs(recent_closes[i] - recent_closes[i+1]) for i in range(len(recent_closes)-1)) / (len(recent_closes)-1)
        
        # If recent move is unusually large, increase caution
        momentum_multiplier = 1.0
        if avg_candle_size > 0:
            momentum_strength = total_move / avg_candle_size
            if momentum_strength > 2.0:  # Strong momentum
                momentum_multiplier = 1.3
            elif momentum_strength < 0.5:  # Weak momentum
                momentum_multiplier = 0.8
        
        logger.debug(f"Momentum multiplier: {momentum_multiplier:.2f}")
        return momentum_multiplier

    def check_liquidation_risk(
        self,
        entry_price: float,
        trade_direction: str,
        forecast_data: Dict[str, Any],
        market_state_snapshot: Dict[str, Any] = None
    ) -> Tuple[bool, str]:
        """
        Calculate liquidation risk using realistic market-based projections instead of
        extreme forecast values. Uses ATR and recent volatility patterns.
        """
        logger.debug(f"[RISK CHECK] Entry Price: {entry_price:.2f}, Direction: {trade_direction}")
        
        if entry_price <= 0:
            return False, "Invalid entry price for risk calculation."
        
        # Get market data for realistic calculations
        klines = []
        if market_state_snapshot:
            klines = market_state_snapshot.get("klines", [])
        
        # Calculate market-based volatility
        atr = self.calculate_market_volatility(klines)
        momentum_multiplier = self.calculate_recent_move_strength(klines, entry_price)
        
        # Use ATR-based risk calculation instead of extreme forecast projections
        # Conservative estimate: 2.5x ATR as potential adverse move
        base_risk_move = atr * 2.5 * momentum_multiplier
        
        # Additional safety: check if forecast data suggests extreme conditions
        forecast_multiplier = 1.0
        forecast = forecast_data.get("forecast", {})
        if forecast and "c1" in forecast and "c2" in forecast:
            try:
                # Calculate forecast range but cap it at reasonable levels
                if trade_direction.upper() == "LONG":
                    c1_low = forecast["c1"].get("low", entry_price)
                    c2_low = forecast["c2"].get("low", entry_price)
                    forecast_pullback = entry_price - min(c1_low, c2_low)
                else:
                    c1_high = forecast["c1"].get("high", entry_price)
                    c2_high = forecast["c2"].get("high", entry_price)
                    forecast_pullback = max(c1_high, c2_high) - entry_price
                
                # If forecast suggests move larger than 5x ATR, cap it
                max_reasonable_move = atr * 5.0
                if forecast_pullback > max_reasonable_move:
                    logger.warning(f"Forecast suggests unrealistic move of ${forecast_pullback:.2f}, capping at ${max_reasonable_move:.2f}")
                    forecast_pullback = max_reasonable_move
                
                # Use the smaller of ATR-based or capped forecast-based risk
                if forecast_pullback > 0:
                    base_risk_move = min(base_risk_move, forecast_pullback)
                    
            except (KeyError, TypeError) as e:
                logger.warning(f"Error processing forecast data, using ATR-based calculation: {e}")
        
        # Final risk assessment
        risk_move = max(base_risk_move, 0.0)
        
        logger.debug(f"[RISK ANALYSIS] ATR: ${atr:.2f}, Momentum: {momentum_multiplier:.2f}, Final Risk: ${risk_move:.2f}")
        
        if risk_move >= self.liquidation_risk_threshold:
            reason = (
                f"Trade blocked. Calculated risk move of ${risk_move:.2f} "
                f"exceeds threshold of ${self.liquidation_risk_threshold:.2f}. "
                f"(ATR: ${atr:.2f}, Momentum: {momentum_multiplier:.2f}x)"
            )
            logger.warning(reason)
            return False, reason
        
        reason = (
            f"Trade passed risk check. Calculated risk: ${risk_move:.2f} "
            f"(ATR-based: ${atr * 2.5:.2f}, Momentum: {momentum_multiplier:.2f}x)"
        )
        logger.debug(reason)
        return True, reason
