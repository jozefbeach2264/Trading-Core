import logging
import asyncio
import json
from datetime import datetime
from typing import Dict, Any

from config.config import Config
from data_managers.market_state import MarketState
from validator_stack import ValidatorStack
from strategy.ai_strategy import AIStrategy
from system_managers.trade_executor import TradeExecutor
from console_display import format_market_state_for_console

logger = logging.getLogger(__name__)

def log_failed_signal(report: Dict[str, Any], reason: str, config: Config):
    """Logs a failed/rejected signal to a dedicated JSON file for later analysis."""
    try:
        # Use 'a' mode to append to the file
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
        self._display_task: asyncio.Task = None # Task for the console display
        
        logger.info("System Engine (Kernel) Initialized.")

    async def _run_console_display_loop(self):
        """A separate loop to print the human-readable dashboard."""
        while self.is_running:
            try:
                display_output = format_market_state_for_console(self.market_state)
                print(display_output)
                await asyncio.sleep(1)  # Refresh rate of 1 second
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in console display loop", extra={"error": str(e)})
                await asyncio.sleep(5)

    async def start(self):
        if not self.is_running:
            self.is_running = True
            self._main_task = asyncio.create_task(self.run_autonomous_cycle())
            
            # Start the console display loop only if it's enabled in the config
            if self.config.live_print_headers:
                self._display_task = asyncio.create_task(self._run_console_display_loop())
                
            logger.info("System Engine started.")

    async def stop(self):
        if self.is_running:
            self.is_running = False
            
            # Cancel both the main task and the display task
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
                    
            logger.info("System Engine stopped.")

    async def run_autonomous_cycle(self):
        """The main operational loop for the trading bot."""
        # Initial delay to allow connections to stabilize fully
        await asyncio.sleep(10)
        
        while self.is_running:
            try:
                # 1. Generate a comprehensive report from all validation filters
                validator_report = await self.validator_stack.generate_report(self.market_state)
                
                # 2. Generate a final signal using the AI strategy
                final_signal = await self.ai_strategy.generate_signal(self.market_state, validator_report['filters'])
                
                # 3. Check the AI's final verdict for execution
                if final_signal and final_signal.get("ai_verdict", {}).get("action") == "✅ Execute":
                    if self.config.autonomous_mode_enabled:
                        await self.trade_executor.execute_trade(final_signal)
                    else:
                        logger.info("AUTONOMOUS MODE DISABLED. Suppressing execution of signal.", extra={"signal": final_signal})
                else:
                    # Log the specific reason for rejection
                    specific_reason = final_signal.get("reason", "UNKNOWN_REJECTION_REASON")
                    log_failed_signal(validator_report, specific_reason, self.config)
                
                # Wait for the next cycle
                await asyncio.sleep(15)

            except asyncio.CancelledError:
                logger.info("Autonomous cycle cancelled.")
                break
            except Exception as e:
                logger.error("Critical error in autonomous cycle", extra={"error": str(e)}, exc_info=True)
                await asyncio.sleep(60) # Wait longer after a critical error
