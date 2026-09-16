import logging
import asyncio
import time
import json
from datetime import datetime, timezone
from typing import Dict, Any

from config.config import Config
from data_managers.market_state import MarketState
from validator_stack import ValidatorStack
from strategy.ai_strategy import AIStrategy
from .trade_executor import TradeExecutor 
from console_display import format_market_state_for_console
from log_utils import file_logger
from position_manager import plan_exits

logger = logging.getLogger(__name__)

def log_failed_signal(report: Dict[str, Any], reason: str, config: Config):
    """Logs a failed/rejected signal as NDJSON — through the queue-backed logger, since this is the
    hottest write path (most cycles are rejections) and used to be a synchronous open/append on the loop."""
    try:
        entry = {"timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "reason": reason, "report": report}
        file_logger("FailedSignalsLogger", config.failed_signals_path, fmt="%(message)s", level=logging.INFO).info(json.dumps(entry))
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
        self.event_queue = asyncio.Queue(maxsize=self.config.event_queue_max_size)
        self.cycles_while_open = 0
        self._last_open_candle_logged = None
        
        logger.info("System Engine (Kernel) Initialized.")

    async def _run_console_display_loop(self):
        """A separate loop to print the human-readable dashboard."""
        while self.is_running:
            try:
                display_output = format_market_state_for_console(self.market_state)
                await asyncio.to_thread(print, display_output)  # a blocked stdout must not stall the loop
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in console display loop", extra={"error": str(e)})
                await asyncio.sleep(5)

    async def resume_open_position(self) -> None:
        """Re-attach the Rolling5 lifecycle to a position that survived a restart, so it is managed and closed
        instead of being silently overwritten by the next trade."""
        try:
            position = await self.trade_executor.recover_open_position()
        except Exception as e:  # noqa: BLE001 - never block start-up on this
            logger.error("Could not check for an open position at start-up: %r", e)
            return
        if not position:
            return
        ts = self.ai_strategy.forecaster._current_candle_ts(self.market_state)
        if ts is None:
            ts = int(time.time() * 1000)
        self.ai_strategy.forecaster.lifecycle.start(ts)
        logger.warning("Rolling5 lifecycle resumed for the recovered %s position", position.get("direction"))

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
            # Stop Rolling5 lifecycle if active
            self.ai_strategy.forecaster.stop_lifecycle()
            logger.info("System Engine stopped.")

    def _lifecycle(self):
        return self.ai_strategy.forecaster.lifecycle

    def _position_is_open(self) -> bool:
        return bool(self._lifecycle().active)

    async def _settle_open_position(self) -> None:
        """Rolling5 management, every cycle while a position is open: settle stop/target/liquidation, then
        re-assess the trade against a fresh forecast and move the stop/target (position_manager.plan_exits).
        The lifecycle counts C1–C5 and REM extensions; MAX_POSITION_CANDLES is only a safety ceiling."""
        lc = self._lifecycle()
        if not lc.active:
            return
        forecaster = self.ai_strategy.forecaster
        mark = self.market_state.mark_price
        if await self.trade_executor.mark_to_market(mark):
            forecaster.stop_lifecycle()
            return
        position = await self.trade_executor.get_open_position()
        if not position:
            forecaster.stop_lifecycle()      # closed elsewhere (or never recorded): clear the guard
            return
        meta = lc.update(forecaster._current_candle_ts(self.market_state))
        if lc.candle_count > self.config.max_position_candles:
            await self.trade_executor.close_position(mark, reason="MAX_CANDLES")
            forecaster.stop_lifecycle()
            return
        if not mark or mark <= 0:
            return
        forecast = await forecaster.generate_forecast(self.market_state, position.get("direction"))
        recheck = bool(meta.get("ob_recheck_due"))
        if recheck:
            forecaster.mark_orderbook_rechecked()
            position["ob_rechecked"] = True
        new_stop, new_target, best, notes = plan_exits(position, float(mark), forecast, self.config, ob_recheck=recheck)
        changed = (new_stop != position.get("stop_loss") or new_target != position.get("take_profit")
                   or best != position.get("best_price"))
        if changed:
            await self.trade_executor.update_position_exits(new_stop, new_target, best_price=best,
                                                            note=f"C{lc.candle_count} " + "; ".join(notes))

    @staticmethod
    def _is_approved(final_signal: Dict[str, Any]) -> bool:
        """Only a fully approved signal executes: an Execute action, no rejection reason, and a direction."""
        if not final_signal or final_signal.get("reason"):
            return False
        action = (final_signal.get("ai_verdict") or {}).get("action")
        return action in ("✅ Execute", "Execute") and bool(final_signal.get("direction"))

    async def run_autonomous_cycle(self):
        await asyncio.sleep(10)
        while self.is_running:
            try:
                # Wait for either an explicit event or the periodic cycle interval
                # This allows for event-driven decisions during candle formation
                event_task = asyncio.create_task(self.event_queue.get())
                sleep_task = asyncio.create_task(asyncio.sleep(self.config.engine_cycle_interval))
                try:
                    done, pending = await asyncio.wait([event_task, sleep_task], return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for task in (event_task, sleep_task):  # asyncio.wait never cancels its children
                        if not task.done():
                            task.cancel()
                for task in done:
                    if task is event_task:
                        logger.info(f"Processing event from queue: {task.result()}")

                # One position at a time: while the Rolling5 lifecycle of the last entry is running, do not
                # re-enter. Without this the same setup re-executed every 0.2 s cycle (three stacked entries
                # 8 s apart are visible in the old simulation_state.json).
                await self._settle_open_position()
                if self._position_is_open():
                    self.cycles_while_open += 1
                    candle = self._lifecycle().candle_count
                    if candle != self._last_open_candle_logged:   # once per candle, not five times a second
                        self._last_open_candle_logged = candle
                        log_failed_signal({}, f"POSITION OPEN (Rolling5 C{candle})", self.config)
                    continue
                self._last_open_candle_logged = None

                # The AIStrategy module now handles the entire validation and signal generation flow
                final_signal = await self.ai_strategy.generate_signal(self.market_state, self.validator_stack)

                if self._is_approved(final_signal):
                    # Start Rolling5 lifecycle tracking when a trade is authorized for execution
                    self.ai_strategy.forecaster.start_lifecycle(self.market_state)
                    if self.config.autonomous_mode_enabled:
                        # Shielded: a shutdown mid-POST must not leave an order on the exchange with no record.
                        await asyncio.shield(self.trade_executor.execute_trade(final_signal))
                    else:
                        logger.info("AUTONOMOUS MODE DISABLED. Suppressing execution.", extra={"signal": final_signal})
                else:
                    reason = final_signal.get("reason", "UNKNOWN_REJECTION_REASON")
                    report = final_signal.get("validator_report", {})
                    log_failed_signal(report, reason, self.config)

            except asyncio.CancelledError:
                logger.info("Autonomous cycle cancelled.")
                break
            except Exception as e:
                logger.error("Critical error in autonomous cycle", extra={"error": str(e)}, exc_info=True)
                await asyncio.sleep(60)
