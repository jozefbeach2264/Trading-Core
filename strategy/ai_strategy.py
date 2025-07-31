import logging
import json
import os
import uuid
from typing import Dict, Any, Optional

from config.config import Config
from data_managers.market_state import MarketState
from strategy.strategy_router import StrategyRouter
from validator_stack import ValidatorStack
from rolling5_engine import Rolling5Engine
from simulators.entry_range_simulator import EntryRangeSimulator
from ai_client import AIClient
from memory_tracker import MemoryTracker
from system_managers.trade_executor import TradeExecutor

def setup_ai_strategy_logger(config: Config) -> logging.Logger:
    log_path = config.ai_strategy_log_path
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    logger = logging.getLogger('AIStrategyLogger')
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        logger.handlers.clear()
    handler = logging.FileHandler(log_path, mode='a')
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger

REJECTION_CODE_MAP = {
    "LowVolumeGuard": "LOW VOL", "TimeOfDayFilter": "OUT OF TIME WINDOW", "SpoofFilter": "SPOOFING",
    "CtsFilter": "CTS_BLOCK", "CompressionDetector": "COMPRESSION", "BreakoutZoneOriginFilter": "NO BREAKOUT",
    "RetestEntryLogic": "RETEST WEAK", "SentimentDivergenceFilter": "CVD CONFLICT",
    "OrderBookReversalZoneDetector": "OB WALL WEAK", "AI_CONFIDENCE": "AI CONFIDENCE LOW",
    "NO_SIGNAL_GENERATED": "Terminated by TrapX/Scalpel", "HIGH_LIQUIDATION_RISK": "HIGH LIQUIDATION RISK"
}

def format_rejection_reason(filter_reports: Dict[str, Any], prefix: str) -> Optional[str]:
    rejection_codes = []
    for filter_name, report in filter_reports.items():
        if isinstance(report, dict) and "❌ Block" in report.get("flag", ""):
            code = REJECTION_CODE_MAP.get(filter_name, filter_name.upper())
            rejection_codes.append(code)
    if rejection_codes:
        return f"Rejected - {prefix}: {', '.join(rejection_codes)}"
    return None

class AIStrategy:
    def __init__(self,
                 config: Config,
                 strategy_router: StrategyRouter,
                 forecaster: Rolling5Engine,
                 ai_client: AIClient,
                 entry_simulator: EntryRangeSimulator,
                 memory_tracker: MemoryTracker,
                 trade_executor: TradeExecutor):
        self.config = config
        self.strategy_router = strategy_router
        self.forecaster = forecaster
        self.ai_client = ai_client
        self.entry_simulator = entry_simulator
        self.memory_tracker = memory_tracker
        self.trade_executor = trade_executor
        self.logger = setup_ai_strategy_logger(config)
        self.logger.info("AIStrategy initialized and linked with TradeExecutor.")

    async def generate_signal(self, market_state: MarketState, validator_stack: ValidatorStack) -> Dict[str, Any]:
        self.logger.info("--- New AI Strategy Cycle Started ---")

        primary_gate_report = await validator_stack.run_primary_gate(market_state)
        if primary_gate_report.get("hard_blocks", 0) > 0:
            reason = format_rejection_reason(primary_gate_report["filters"], "Primary Gate")
            self.logger.warning(f"REJECTED: {reason}")
            return {"reason": reason, "validator_report": primary_gate_report["filters"]}

        signal_packet = await self.strategy_router.route_and_generate_signal(market_state, primary_gate_report)
        if not signal_packet:
            reason = REJECTION_CODE_MAP['NO_SIGNAL_GENERATED']
            self.logger.info(f"HALTED: {reason}")
            return {"reason": reason, "validator_report": primary_gate_report["filters"]}

        self.logger.info(f"Signal Packet Generated: Type={signal_packet.get('trade_type')}, Direction={signal_packet.get('direction')}")

        post_signal_report = await validator_stack.run_post_signal_validators(market_state)
        final_validator_log = {**primary_gate_report["filters"], **post_signal_report["filters"]}
        if post_signal_report.get("hard_blocks", 0) > 0:
            reason = format_rejection_reason(post_signal_report["filters"], "Post-Signal")
            self.logger.warning(f"REJECTED: {reason}")
            return {"reason": reason, "validator_report": final_validator_log}

        self.logger.info("Post-Signal Validators passed. Proceeding to AI Core.")

        forecast = await self.forecaster.generate_forecast(market_state)
        snapshot = market_state.get_latest_data_snapshot()
        candle = snapshot.get("live_reconstructed_candle", [0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, "0"])
        if not candle or len(candle) != 9 or all(v == 0.0 for v in candle[1:6]):
            self.logger.warning(f"Invalid live_reconstructed_candle: {candle}")
            candle = [0, market_state.mark_price or 3200.0, 0.0, 0.0, market_state.mark_price or 3200.0, 0.0, 0.0, 0.0, "0"]

        context_packet = {
            "open": candle[1], "close": candle[4], "volume": candle[5],
            "direction": signal_packet.get("direction", "N/A"),
            "reversal_likelihood_score": forecast.get("reversal_likelihood_score", 0.0),
            "cts_score": final_validator_log.get("CtsFilter", {}).get("score", 0.0),
            "orderbook_score": final_validator_log.get("OrderBookReversalZoneDetector", {}).get("score", 0.0)
        }

        ai_verdict = await self.ai_client.get_ai_verdict(context_packet)
        final_signal = {"ai_verdict": ai_verdict, **signal_packet, "validator_report": final_validator_log}

        entry_price = 0.0
        quantity = 0.0

        if ai_verdict.get("action") == "✅ Execute":
            entry_price_for_risk_check = market_state.mark_price or 0.0
            is_safe, risk_reason = self.entry_simulator.check_liquidation_risk(entry_price_for_risk_check, final_signal["direction"], forecast)

            if not is_safe:
                final_signal["ai_verdict"]["action"] = "⛔ Abort"
                final_signal["reason"] = f"Rejected - {REJECTION_CODE_MAP['HIGH_LIQUIDATION_RISK']}: {risk_reason}"
                self.logger.warning(f"REJECTED: {final_signal['reason']}")
            else:
                self.logger.info("Liquidation risk check passed. Delegating to TradeExecutor.")
                entry_price = market_state.mark_price
                if entry_price and entry_price > 0:
                    quantity = self.config.trade_size_usd / entry_price

                    trade_details = {
                        "trade_id": str(uuid.uuid4()),
                        "symbol": self.config.symbol,
                        "direction": final_signal.get("direction"),
                        "size": quantity,
                        "entry_price": entry_price
                    }

                    await self.trade_executor.execute_trade(trade_details)
                else:
                    final_signal["ai_verdict"]["action"] = "⛔ Abort"
                    final_signal["reason"] = "Invalid mark price at execution time."
                    self.logger.error(f"Execution HALTED: {final_signal['reason']}")

        # Your original memory tracker logic is preserved, but now it's fed the correct data.
        await self.memory_tracker.update_memory(
            verdict_data={
                "direction": final_signal.get("direction", "N/A"),
                "entry_price": entry_price, # This now uses the calculated price
                "quantity": quantity, # This now includes the calculated quantity
                "verdict": ai_verdict.get("action", "None"),
                "confidence": ai_verdict.get("confidence", 0.0),
                "reason": ai_verdict.get("reasoning", "N/A")
            }
        )

        return final_signal
