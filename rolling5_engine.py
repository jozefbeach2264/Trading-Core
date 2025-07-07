import logging
import asyncio
from typing import Dict, Any

from config.config import Config
from data_managers.market_state import (
    MarketState
)
from validator_stack import ValidatorStack
from system_managers.trade_executor import (
    TradeExecutor
)
from ai_client import AIClient

logger = logging.getLogger(__name__)

class Rolling5Engine:
    """
    The central engine that orchestrates
    the autonomous trading loop.
    """
    def __init__(
        self,
        config: Config,
        market_state: MarketState,
        validator_stack: ValidatorStack,
        trade_executor: TradeExecutor,
        ai_client: AIClient
    ):
        self.config = config
        self.market_state = market_state
        self.validator_stack = (
            validator_stack
        )
        self.trade_executor = trade_executor
        self.ai_client = ai_client
        self.is_running = False
        self._task: asyncio.Task = None
        
        logger.info(
            "Rolling5Engine Initialized."
        )

    async def start(self):
        """Starts the autonomous loop."""
        if not self.is_running:
            self.is_running = True
            self._task = asyncio.create_task(
                self.run_autonomous_cycle()
            )
            logger.info("Rolling5Engine started.")

    async def stop(self):
        """Stops the autonomous loop."""
        if self.is_running and self._task:
            self.is_running = False
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                logger.info(
                    "Cycle task was cancelled."
                )
            logger.info("Rolling5Engine stopped.")

    async def run_autonomous_cycle(self):
        """The main autonomous loop."""
        logger.info(
            "--- Starting Autonomous Cycle ---"
        )
        while self.is_running:
            try:
                if not self.config.autonomous_mode_enabled:
                    logger.info(
                        "Autonomous mode is "
                        "disabled. Engine idle."
                    )
                    await asyncio.sleep(300)
                    continue

                report = (
                    await self.validator_stack
                    .generate_report(
                        self.market_state
                    )
                )
                
                if not report or not report.get("filters"):
                    await asyncio.sleep(10)
                    continue

                ai_report = (
                    await self.ai_client
                    .get_ai_verdict(report)
                )

                trade_direction = ai_report.get(
                    "direction", "NONE"
                )
                if ai_report and trade_direction in [
                    "LONG", "SHORT"
                ]:
                    logger.info(
                        "AI returned an actionable "
                        "report. Passing to executor."
                    )
                    await self.trade_executor.execute_trade(
                        ai_report
                    )
                else:
                    reason = ai_report.get(
                        'reasoning',
                        'No actionable trade.'
                    )
                    logger.info(
                        "AI report not actionable. "
                        f"Reason: {reason}"
                    )
                
                await asyncio.sleep(60)

            except asyncio.CancelledError:
                logger.info(
                    "Autonomous cycle cancelled."
                )
                break
            except Exception as e:
                logger.error(
                    "Error in autonomous cycle: "
                    f"{e}", exc_info=True
                )
                await asyncio.sleep(60)

    def generate_predictions(
        self, klines: list
    ) -> Dict[str, Any]:
        """
        Generates a 5-candle forecast
        using linear regression on recent
        closing prices.
        """
        num_klines = len(klines)
        if num_klines < 10:
            return {
                "error": "Not enough data."
            }

        # Use last 10 candles for trend
        recent_klines = klines[-10:]
        
        # Simple linear regression
        x = list(range(10))
        y = [float(k[4]) for k in recent_klines]
        
        n = 10
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(
            xi * yi for xi, yi in zip(x, y)
        )
        sum_x2 = sum(xi**2 for xi in x)

        try:
            slope = (
                (n * sum_xy - sum_x * sum_y) /
                (n * sum_x2 - sum_x**2)
            )
            intercept = (
                (sum_y - slope * sum_x) / n
            )
        except ZeroDivisionError:
            return {"error": "Calc failed."}

        # Generate 5 future predictions
        predictions = {}
        last_close = y[-1]
        
        for i in range(1, 6):
            pred_price = intercept + slope * (9+i)
            direction = (
                "up" if pred_price > last_close
                else "down"
            )
            # Simple confidence based on slope
            confidence = min(
                abs(slope) / last_close * 100,
                1.0
            ) * 100
            
            predictions[f"c{i}"] = {
                "direction": direction,
                "confidence": round(confidence, 2)
            }
            last_close = pred_price

        return {
            "prediction_type": "5_candle_forecast",
            **predictions
        }
