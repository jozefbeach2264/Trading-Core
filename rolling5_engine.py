import logging
import asyncio
from typing import Dict, Any

from config.config import Config
from data_managers.market_state import MarketState
from validator_stack import ValidatorStack
from system_managers.trade_executor import TradeExecutor
from ai_client import AIClient

logger = logging.getLogger(__name__)

class Rolling5Engine:
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
        self.validator_stack = validator_stack
        self.trade_executor = trade_executor
        self.ai_client = ai_client
        self.is_running = False
        self._task: asyncio.Task = None

        logger.info("Rolling5Engine Initialized.")

    async def start(self):
        if not self.is_running:
            self.is_running = True
            self._task = asyncio.create_task(self.run_autonomous_cycle())
            logger.info("Rolling5Engine started.")

    async def stop(self):
        if self.is_running and self._task:
            self.is_running = False
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                logger.info("Cycle task was cancelled.")
            logger.info("Rolling5Engine stopped.")

    async def _wait_for_initial_data(self):
        min_klines_needed = 50  # Changed from 4 to 50
        logger.info("Rolling5Engine is waiting for initial market data to load...")

        while not self.is_running:
            await asyncio.sleep(1)

        while self.is_running:
            klines_len = len(self.market_state.klines)
            has_orderbook = bool(self.market_state.depth_20.get("bids"))
            has_live_candle = self.market_state.live_reconstructed_candle is not None

            if (klines_len >= min_klines_needed and has_orderbook and has_live_candle):
                logger.info("--- Initial market data loaded. Starting autonomous analysis. ---")
                return

            log_msg = f"Waiting for data... Klines: {klines_len}/{min_klines_needed}, " \
                      f"Orderbook: {'YES' if has_orderbook else 'NO'}, " \
                      f"Live Candle: {'YES' if has_live_candle else 'NO'}"
            logger.info(log_msg)
            await asyncio.sleep(2)

    async def preload_modules_from_historical_klines(self):
        required = 50  # Changed from 10 to 50
        historical = list(self.market_state.klines)[-required:]

        if not historical:
            logger.warning("No historical klines found for preload.")
            return

        logger.info(f"Preloading {len(historical)} historical candles into ValidatorStack...")

        for candle in historical:
            await self.validator_stack.process_backfill_candle(candle)

    async def run_autonomous_cycle(self):
        await self._wait_for_initial_data()
        await self.preload_modules_from_historical_klines()

        logger.info("--- Starting Autonomous Cycle ---")
        while self.is_running:
            try:
                if not self.config.autonomous_mode_enabled:
                    logger.info("Autonomous mode is disabled. Engine idle.")
                    await asyncio.sleep(300)
                    continue

                report = await self.validator_stack.generate_report(self.market_state)

                if not report or not report.get("filters"):
                    await asyncio.sleep(10)
                    continue

                ai_report = self.ai_client.get_ai_verdict(report)
                trade_direction = ai_report.get("direction", "NONE")

                if ai_report and trade_direction in ["LONG", "SHORT"]:
                    logger.info("AI returned an actionable report. Passing to executor.")
                    await self.trade_executor.execute_trade(ai_report)
                else:
                    reason = ai_report.get("reasoning", "No actionable trade.")
                    logger.info(f"AI report not actionable. Reason: {reason}")

                await asyncio.sleep(60)

            except asyncio.CancelledError:
                logger.info("Autonomous cycle cancelled.")
                break
            except Exception as e:
                logger.error(f"Error in autonomous cycle: {e}", exc_info=True)
                await asyncio.sleep(60)

    def generate_predictions(self, klines: list) -> Dict[str, Any]:
        num_klines = len(klines)
        if num_klines < 10:
            return {"error": "Not enough data."}
        recent_klines = klines[-10:]
        x = list(range(10))
        y = [float(k[4]) for k in recent_klines]
        n = 10
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(xi * yi for xi, yi in zip(x, y))
        sum_x2 = sum(xi**2 for xi in x)
        try:
            slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x**2)
            intercept = (sum_y - slope * sum_x) / n
        except ZeroDivisionError:
            return {"error": "Calc failed."}
        predictions = {}
        last_close = y[-1]
        for i in range(1, 6):
            pred_price = intercept + slope * (9 + i)
            direction = "up" if pred_price > last_close else "down"
            confidence = min(abs(slope) / last_close * 100, 1.0) * 100
            predictions[f"c{i}"] = {
                "direction": direction,
                "confidence": round(confidence, 2)
            }
            last_close = pred_price
        return {"prediction_type": "5_candle_forecast", **predictions}