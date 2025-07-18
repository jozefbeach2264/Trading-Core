import logging
import json
from typing import Dict, Any, List, Optional

from config.config import Config
from data_managers.market_state import MarketState
from strategy.strategy_router import StrategyRouter
# Assuming other imports are correct
# from strategy.trade_module_trapx import TradeModuleTrapX
# from strategy.trade_module_scalpel import TradeModuleScalpel
# from rolling5_engine import Rolling5Engine
# from simulators.entry_range_simulator import EntryRangeSimulator
# from ai_client import AIClient
# from memory_tracker import MemoryTracker

logger = logging.getLogger(__name__)

# --- Helper Logic Integration ---

REJECTION_CODE_MAP = {
    "LowVolumeGuard": "LOW VOL",
    "TimeOfDayFilter": "OUT OF TIME WINDOW",
    "SpoofFilter": "SPOOFING",
    "CtsFilter": "NO TRAP SIGNAL",
    "CompressionDetector": "COMPRESSION",
    "BreakoutZoneOriginFilter": "NO BREAKOUT",
    "RetestEntryLogic": "RETEST WEAK",
    "SentimentDivergenceFilter": "BEAR/BULL CVD CONFLICT",
    "OrderBookReversalZoneDetector": "OB WALL WEAK/MISSING",
    "AI_STRATEGY_CONFIDENCE": "AI CONFIDENCE TOO LOW",
    "STACK_SUPPRESSION": "SUPPRESSED BY STRATEGY STACK",
    "NO_RETEST_CONFIRMATION": "NO RETEST BOUNCE",
    "NO_RESISTANCE_ZONE": "NO OB RESISTANCE",
    "NO_SUPPORT_ZONE": "NO OB SUPPORT",
    "NOT_IN_RANGE": "OUT OF TRADE RANGE",
    "INVALID_CANDLE": "CANDLE INVALID SHAPE",
    "NO_SIGNAL_PACKET": "NO SIGNAL GENERATED",
}

def format_rejection_reason(filter_reports: List[Any]) -> Optional[str]:
    """
    Checks a list of filter reports for hard blocks and formats a specific
    rejection reason string.
    """
    rejection_codes = []
    for report in filter_reports:
        # --- THIS IS THE FIX ---
        # It ensures we only process dictionary reports and skip any other data types.
        if not isinstance(report, dict):
            continue
        
        if report.get("flag") == "❌ Block":
            filter_name = report.get("filter_name")
            code = REJECTION_CODE_MAP.get(filter_name, filter_name.upper())
            rejection_codes.append(code)
    if rejection_codes:
        return f"Rejected - {', '.join(rejection_codes)}"
    
    return None

class AIStrategy:
    def __init__(self, config: Config, strategy_router: StrategyRouter, forecaster: Any, ai_client: Any, entry_simulator: Any, memory_tracker: Any):
        self.config = config
        self.strategy_router = strategy_router
        self.forecaster = forecaster
        self.ai_client = ai_client
        self.entry_simulator = entry_simulator
        self.memory_tracker = memory_tracker
        logger.debug("AIStrategy initialized.")

    async def generate_signal(self, market_state: MarketState, validator_audit_log: Dict[str, Any]) -> Dict[str, Any]:
        logger.debug("Generating AI signal with validator audit log: %s", validator_audit_log)

        # --- Stage 1: Check for Hard Blocks from Upstream Filters First ---
        upstream_rejection_reason = format_rejection_reason(list(validator_audit_log.values()))
        if upstream_rejection_reason:
            logger.warning(f"Upstream filter rejection: {upstream_rejection_reason}")
            return {
                "direction": "N/A", "trade_type": "N/A", "confidence": 0.0,
                "reason": upstream_rejection_reason,
                "ai_verdict": {"action": "⛔ Abort", "reasoning": "Rejected by upstream filters."}
            }
        
        forecast = await self.forecaster.generate_forecast(market_state)
        logger.debug("Rolling5 forecast: %s", forecast)
        
        signal_packet = await self.strategy_router.route_and_generate_signal(market_state, validator_audit_log)
        logger.debug("Signal packet from strategy router: %s", signal_packet)
        
        if signal_packet is None:
            rejection_reason = f"Rejected - {REJECTION_CODE_MAP.get('NO_SIGNAL_PACKET', 'NO_SIGNAL_PACKET')}"
            logger.warning(rejection_reason)
            return {
                "direction": "N/A", "trade_type": "N/A", "confidence": 0.0,
                "reason": rejection_reason,
                "ai_verdict": {"action": "⛔ Abort", "reasoning": "No valid trade module signal."}
            }
        
        # --- Stage 2: All filters passed, proceed to AI Strategy ---
        context_packet = {
            "market_state_snapshot": market_state.get_latest_data_snapshot(),
            "validator_audit_log": validator_audit_log,
            "rolling5_forecast": forecast,
            "direction": signal_packet.get("direction", "N/A"),
            "trade_type": signal_packet.get("trade_type", "N/A")
        }
        
        similar_scenarios = self.memory_tracker.get_similar_scenarios(context_packet)
        context_packet["similar_scenarios"] = similar_scenarios
        
        ai_verdict = await self.ai_client.get_ai_verdict(context_packet)
        logger.debug("AI verdict received: %s", ai_verdict)

        # --- Stage 3: Check AI Confidence Threshold ---
        confidence_score = ai_verdict.get("confidence", 0.0)
        ai_confidence_threshold = self.config.ai_confidence_threshold
        if confidence_score < ai_confidence_threshold:
            rejection_reason = (
                f"Rejected - {REJECTION_CODE_MAP.get('AI_STRATEGY_CONFIDENCE', 'AI CONFIDENCE TOO LOW')} "
                f"({confidence_score:.2f}/{ai_confidence_threshold})"
            )
            logger.warning(rejection_reason)
            return {
                "direction": signal_packet.get("direction", "N/A"),
                "trade_type": signal_packet.get("trade_type", "N/A"),
                "confidence": confidence_score,
                "reason": rejection_reason,
                "ai_verdict": ai_verdict
            }
            
        final_signal = {
            "direction": signal_packet.get("direction", "N/A"),
            "trade_type": signal_packet.get("trade_type", "N/A"),
            "ai_verdict": ai_verdict,
            "reason": ai_verdict.get("reasoning", "No reasoning provided"),
            "confidence": confidence_score
        }
        
        if ai_verdict.get("action") == "✅ Execute":
            entry_price = market_state.mark_price or 0.0
            is_safe, risk_reason = self.entry_simulator.check_liquidation_risk(
                entry_price=entry_price,
                trade_direction=signal_packet.get("direction", "N/A"),
                forecast_data=forecast
            )
            final_signal.update({"risk_check": {"is_safe": is_safe, "reason": risk_reason}})
            if not is_safe:
                final_signal["ai_verdict"]["action"] = "⛔ Abort"
                final_signal["reason"] = f"Rejected - HIGH LIQUIDATION RISK: {risk_reason}"

        await self.memory_tracker.update_memory(filter_report=validator_audit_log, trade_data={
            "direction": final_signal["direction"],
            "ai_verdict": final_signal["ai_verdict"],
        })
        logger.debug("Final signal generated: %s", final_signal)
        return final_signal
