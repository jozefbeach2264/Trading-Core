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

def log_failed_signal(report: Dict[str, Any], reason: str, config: Config):
    try:
        log_entry = {"timestamp": datetime.utcnow().isoformat() + "Z", "reason": reason, "report": report}
        with open(config.failed_signals_path, 'a') as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        logging.error(f"Failed to log rejected signal: {e}")

class Engine:
    def __init__(self, config: Config, market_state: MarketState, validator_stack: ValidatorStack, ai_strategy: AIStrategy, trade_executor: TradeExecutor):
        self.config, self.market_state, self.validator_stack, self.ai_strategy, self.trade_executor = config, market_state, validator_stack, ai_strategy, trade_executor
        self.is_running = False
        self._task: asyncio.Task = None
        logging.info("System Engine (Kernel) Initialized.")

    async def start(self):
        if not self.is_running:
            self.is_running = True
            self._task = asyncio.create_task(self.run_autonomous_cycle())
            logging.info("System Engine started.")

    async def stop(self):
        if self.is_running and self._task:
            self.is_running = False
            self._task.cancel()
            try: await self._task
            except asyncio.CancelledError: pass
            logging.info("System Engine stopped.")

    async def run_autonomous_cycle(self):
        await asyncio.sleep(10)
        while self.is_running:
            try:
                validator_report = await self.validator_stack.generate_report(self.market_state)
                final_signal = await self.ai_strategy.generate_signal(self.market_state, validator_report)
                
                if final_signal and final_signal.get("ai_verdict", {}).get("action") == "✅ Execute":
                    if self.config.autonomous_mode_enabled:
                        await self.trade_executor.execute_trade(final_signal)
                    else:
                        logging.info(f"AUTONOMOUS MODE DISABLED. Suppressing execution of signal: {final_signal.get('direction')}")
                else:
                    # --- THIS IS THE FIX ---
                    # Use the specific reason from the final_signal dictionary.
                    specific_reason = final_signal.get("reason", "UNKNOWN_REJECTION_REASON")
                    log_failed_signal(validator_report, specific_reason, self.config)
                    
                await asyncio.sleep(15)
            except asyncio.CancelledError:
                logging.info("Autonomous cycle cancelled.")
                break
            except Exception as e:
                logging.error(f"Critical error in autonomous cycle: {e}", exc_info=True)
                await asyncio.sleep(60)
