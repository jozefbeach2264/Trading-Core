import logging
import asyncio
import json
from datetime import datetime
from typing import Dict, Any

from config.config import Config
from data_managers.market_state import MarketState
from validator_stack import ValidatorStack
from strategy.ai_strategy import AIStrategy
from .trade_executor import TradeExecutor
from console_display import format_market_state_for_console
from .diagnostics import debug_r5_and_memory_state

logger = logging.getLogger(__name__)

def log_failed_signal(report: Dict[str, Any], reason: str, config: Config):
    """Logs a failed/rejected signal to a dedicated JSON file for later analysis."""
    try:
        with open(config.failed_signals_path, 'a') as f:
            log_entry = {"timestamp": datetime.utcnow().isoformat() + "Z", "reason": reason, "report": report}
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        logger.error("Failed to log rejected signal", extra={"error": str(e)}, exc_info=True)

class Engine:
    def __init__(self, config: Config, market_state: MarketState, validator_stack: ValidatorStack, ai_strategy: AIStrategy, trade_executor: TradeExecutor):
        self.config = config
        self.market_state = market_state
        self.validator_stack = validator_stack
        self.ai_strategy = ai_strategy
        self.trade_executor = trade_executor
        
        self.is_running = False
        self._main_task: asyncio.Task = None
        self._display_task: asyncio.Task = None
        
        self.last_candle_close_time = None
        
        logger.info("System Engine (Kernel) Initialized.")

    async def _run_console_display_loop(self):
        """A separate loop to print the human-readable dashboard."""
        while self.is_running:
            try:
                display_output = format_market_state_for_console(self.market_state)
                print(display_output)
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in console display loop", extra={"error": str(e)})
                await asyncio.sleep(5)

    async def start(self):
        if not self.is_running:
            self.is_running = True
            self._main_task = asyncio.create_task(self.run_autonomous_cycle())
            if self.config.live_print_headers:
                self._display_task = asyncio.create_task(self._run_console_display_loop())
            logger.info("System Engine started.")

    async def stop(self):
        if self.is_running:
            self.is_running = False
            if self._main_task:
                self._main_task.cancel()
                try: await self._main_task
                except asyncio.CancelledError: pass
            if self._display_task:
                self._display_task.cancel()
                try: await self._display_task
                except asyncio.CancelledError: pass
            logger.info("System Engine stopped.")

    async def run_autonomous_cycle(self):
        await asyncio.sleep(10)
        while self.is_running:
            try:
                if not self.market_state.klines:
                    await asyncio.sleep(1)
                    continue

                latest_candle = self.market_state.klines[0]
                current_candle_time = latest_candle[0]

                if self.last_candle_close_time == current_candle_time:
                    logger.debug("Duplicate candle — skipping verdict cycle.")
                    await asyncio.sleep(self.config.engine_cycle_interval)
                    continue

                logger.info(f"New candle detected. Proceeding with R5 verdict cycle @ {current_candle_time}.")
                self.last_candle_close_time = current_candle_time

                final_signal = await self.ai_strategy.generate_signal(self.market_state, self.validator_stack)

                if self.market_state.klines and len(self.market_state.klines) >= 5:
                    r5_buffer = list(self.market_state.klines)[:5]
                    debug_r5_and_memory_state(r5_buffer, self.ai_strategy.memory_tracker)
                else:
                    logger.warning("Diagnostic check skipped: Not enough klines in market state for R5 buffer.")

                if final_signal and final_signal.get("ai_verdict", {}).get("action") == "Execute":
                    if self.config.autonomous_mode_enabled:
                        await self.trade_executor.execute_trade(final_signal)
                    else:
                        logger.info("AUTONOMOUS MODE DISABLED. Suppressing execution.", extra={"signal": final_signal})
                else:
                    reason = final_signal.get("reason", "UNKNOWN_REJECTION_REASON")
                    report = final_signal.get("validator_report", {})
                    log_failed_signal(report, reason, self.config)

                await asyncio.sleep(self.config.engine_cycle_interval)

            except asyncio.CancelledError:
                logger.info("Autonomous cycle cancelled.")
                break
            except Exception as e:
                logger.error("Critical error in autonomous cycle", extra={"error": str(e)}, exc_info=True)
                await asyncio.sleep(60)