import logging
import psutil
import asyncio
from typing import Dict, Any, Optional

from config.config import Config
from data_managers.market_state import MarketState
from validator_stack import ValidatorStack
from strategy.ai_strategy import AIStrategy
from .trade_executor import TradeExecutor
from console_display import format_market_state_for_console
from .diagnostics import debug_r5_and_memory_state

logger = logging.getLogger(__name__)

class Engine:
    def __init__(
        self,
        config: Config,
        market_state: MarketState,
        validator_stack: ValidatorStack,
        ai_strategy: AIStrategy,
        trade_executor: TradeExecutor
    ):
        self.config = config
        self.market_state = market_state
        self.validator_stack = validator_stack
        self.ai_strategy = ai_strategy
        self.trade_executor = trade_executor

        self.is_running = False
        self._main_task: asyncio.Task = None
        self._display_task: asyncio.Task = None
        self._monitor_task: asyncio.Task = None

        self.last_candle_close_time = None

        logger.info("System Engine (Kernel) Initialized.")

    async def _run_console_display_loop(self):
        """A separate loop to print the human-readable dashboard."""
        while self.is_running:
            try:
                display_output = format_market_state_for_console(self.market_state)
                print(display_output)
                await asyncio.sleep(self.config.console_display_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in console display loop", extra={"error": str(e)})
                await asyncio.sleep(5)

    async def _run_system_monitor_loop(self):
        """A dedicated loop to update system stats at its own interval."""
        while self.is_running:
            try:
                cpu_percent = psutil.cpu_percent()
                ram_percent = psutil.virtual_memory().percent
                await self.market_state.update_system_stats({
                    "cpu": cpu_percent,
                    "ram": ram_percent
                })
                await asyncio.sleep(self.config.system_monitor_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in system monitor loop", extra={"error": str(e)})
                await asyncio.sleep(5)

    async def start(self):
        if not self.is_running:
            self.is_running = True
            self._main_task = asyncio.create_task(self.run_autonomous_cycle())
            if self.config.live_print_headers:
                self._display_task = asyncio.create_task(self._run_console_display_loop())

            if getattr(self.config, 'enable_system_monitoring', True):
                self._monitor_task = asyncio.create_task(self._run_system_monitor_loop())

            logger.info("System Engine started.")

    async def stop(self):
        if self.is_running:
            self.is_running = False
            if self._main_task:
                self._main_task.cancel()
                try:
                    await self._main_task
                except asyncio.CancelledError:
                    pass
            if self._display_task:
                self._display_task.cancel()
                try:
                    await self._display_task
                except asyncio.CancelledError:
                    pass
            if self._monitor_task:
                self._monitor_task.cancel()
                try:
                    await self._monitor_task
                except asyncio.CancelledError:
                    pass
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

                # === AI decision path ===
                # Only if AI is actually called and returns a signal with 'ai_verdict'
                final_signal: Optional[Dict[str, Any]] = await self.ai_strategy.generate_signal(
                    self.market_state,
                    self.validator_stack
                )

                # Diagnostics snapshot (unchanged)
                if self.market_state.klines and len(self.market_state.klines) >= 5:
                    r5_buffer = list(self.market_state.klines)[:5]
                    debug_r5_and_memory_state(r5_buffer, self.ai_strategy.memory_tracker)
                else:
                    logger.warning("Diagnostic check skipped: Not enough klines in market state for R5 buffer.")

                # === Persist verdict ONLY if AI returned one ===
                try:
                    mt = getattr(self.ai_strategy, "memory_tracker", None)
                    if mt and final_signal and isinstance(final_signal, dict):
                        ai_v = final_signal.get("ai_verdict", None)
                        if isinstance(ai_v, dict) and "action" in ai_v:
                            verdict_action = ai_v.get("action", "HOLD")
                            verdict_conf   = float(ai_v.get("confidence", 0.0) or 0.0)
                            verdict_reason = ai_v.get("reasoning", "N/A")
                            direction = final_signal.get("direction") or ai_v.get("direction") or "N/A"
                            entry_price = float(final_signal.get("entry_price", 0.0) or 0.0)

                            await mt.update_memory(
                                verdict_data={
                                    "candle_timestamp": current_candle_time,
                                    "direction": direction,
                                    "entry_price": entry_price,
                                    "verdict": verdict_action,
                                    "confidence": verdict_conf,
                                    "reason": verdict_reason,
                                }
                            )
                        # If ai_verdict is missing, do not write anything (pre-AI denials won't reach here)
                except Exception as e:
                    logger.error("Failed to persist verdict", extra={"error": str(e)}, exc_info=True)

                # === Execution flow (unchanged) ===
                if final_signal:
                    verdict = (final_signal.get("ai_verdict") or {}).get("action", "")

                    if verdict == "Execute":
                        if self.config.autonomous_mode_enabled:
                            await self.trade_executor.execute_trade(final_signal)
                        else:
                            logger.info(
                                "AUTONOMOUS MODE DISABLED. Suppressing execution.",
                                extra={"signal": final_signal}
                            )

                    elif verdict == "Abort":
                        exit_price = self.market_state.mark_price or 0.0
                        trade_id = final_signal.get("trade_id", "UNKNOWN_ID")
                        reason = final_signal.get("ai_verdict", {}).get("reasoning", "No reason given.")
                        await self.trade_executor.exit_trade(trade_id, exit_price, exit_reason=reason)
                        logger.info(f"EXIT SIGNAL: Closed trade {trade_id} at price {exit_price} due to: {reason}")

                    elif verdict in ("Reanalyze", "HOLD"):
                        logger.info(f"AI Verdict: {verdict}. Continuing without action.")

                    else:
                        # Only log failed signals separately; NOT to trades/verdicts tables
                        try:
                            reason = final_signal.get("reason", "UNKNOWN_REJECTION_REASON")
                            report = final_signal.get("validator_report", {})
                            # If you have a helper for failed signals, call it; else ignore silently
                            from .engine import log_failed_signal as _lfs  # self-import safe if exists
                            _lfs(report, reason, self.config)
                        except Exception:
                            pass

                await asyncio.sleep(self.config.engine_cycle_interval)

            except asyncio.CancelledError:
                logger.info("Autonomous cycle cancelled.")
                break
            except Exception as e:
                logger.error("Critical error in autonomous cycle", extra={"error": str(e)}, exc_info=True)
                await asyncio.sleep(60)