import logging
import json
import os
import asyncio
from typing import Dict, Any, List, Optional
from config.config import Config
from data_managers.market_state import MarketState
from strategy.strategy_router import StrategyRouter
from rolling5_engine import Rolling5Engine
from simulators.entry_range_simulator import EntryRangeSimulator
from ai_client import AIClient
from memory_tracker import MemoryTracker
# Filter imports
from filters.low_volume_guard import LowVolumeGuard
from filters.time_of_day_filter import TimeOfDayFilter
from filters.spoof_filter import SpoofFilter
from filters.cts_filter import CtsFilter
from filters.compression_detector import CompressionDetector
from filters.breakout_zone_origin_filter import BreakoutZoneOriginFilter
from filters.retest_entry_logic import RetestEntryLogic
from filters.sentiment_divergence_filter import SentimentDivergenceFilter
from filters.order_book_reversal_zone_detector import OrderBookReversalZoneDetector

logger = logging.getLogger(__name__)

def setup_ai_strategy_logger(config: Config) -> logging.Logger:
    """Configure AIStrategyLogger with file handler."""
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
    "LowVolumeGuard": "LOW VOL", "TimeOfDayFilter": "OUT OF TIME WINDOW",
    "SpoofFilter": "SPOOFING", "CtsFilter": "CTS_BLOCK",
    "CompressionDetector": "COMPRESSION", "BreakoutZoneOriginFilter": "NO BREAKOUT",
    "RetestEntryLogic": "RETEST WEAK", "SentimentDivergenceFilter": "CVD CONFLICT",
    "OrderBookReversalZoneDetector": "OB WALL WEAK", "AI_CONFIDENCE": "AI CONFIDENCE LOW",
    "NO_SIGNAL_GENERATED": "Terminated by TrapX/Scalpel",
    "HIGH_LIQUIDATION_RISK": "HIGH LIQUIDATION RISK"
}

def format_rejection_reason(filter_reports: Dict[str, Any], prefix: str) -> Optional[str]:
    """Format rejection reasons from filter reports."""
    rejection_codes = []
    for filter_name, report in filter_reports.items():
        if isinstance(report, dict) and "❌ Block" in report.get("flag", ""):
            code = REJECTION_CODE_MAP.get(filter_name, filter_name.upper())
            rejection_codes.append(code)
    return f"Rejected - {prefix}: {', '.join(rejection_codes)}" if rejection_codes else None

class ValidatorStack:
    def __init__(self, config: Config):
        self.config = config
        self.memory_tracker = MemoryTracker(config)
        self.ai_client = AIClient(config)
        self.strategy_router = StrategyRouter(config)
        self.forecaster = Rolling5Engine(config)
        self.entry_simulator = EntryRangeSimulator(config)
        self.logger = setup_ai_strategy_logger(config)
        self.primary_gate_filters = [
            CtsFilter(config),
            TimeOfDayFilter(config)
        ]
        self.post_signal_filters = [
            RetestEntryLogic(config),
            OrderBookReversalZoneDetector(config),
            SpoofFilter(config),
            LowVolumeGuard(config),
            CompressionDetector(config),
            BreakoutZoneOriginFilter(config),
            SentimentDivergenceFilter(config)
        ]
        self.logger.debug(f"ValidatorStack initialized with {len(self.primary_gate_filters)} primary gates and {len(self.post_signal_filters)} post-signal validators.")

    async def _run_filter_group(self, market_state: MarketState, filters: List[Any], group_name: str) -> Dict[str, Any]:
        """Generic function to run a group of filters and report results."""
        tasks = [f.generate_report(market_state) for f in filters]
        filter_results = await asyncio.gather(*tasks, return_exceptions=True)
        report = {"filters": {}, "hard_blocks": 0}
        self.logger.info(f"--- Validator {group_name} Report ---")
        for result in filter_results:
            if isinstance(result, Exception):
                self.logger.error(f"A {group_name} filter failed", extra={"error": str(result)}, exc_info=True)
                continue
            filter_name = result.get("filter_name", "UnknownFilter")
            flag = result.get("flag", "N/A")
            score = result.get("score", 0.0)
            self.logger.info(f"{filter_name:<35} | Flag: {flag:<18} | Score: {score:.4f}")
            report["filters"][filter_name] = result
            await market_state.update_filter_audit_report(filter_name, result)
            await self.memory_tracker.update_memory(filter_report=result)
            if "❌ Block" in flag:
                report["hard_blocks"] += 1
        return report

    async def run_primary_gate(self, market_state: MarketState) -> Dict[str, Any]:
        """Runs the initial, primary gate filters."""
        return await self._run_filter_group(market_state, self.primary_gate_filters, "Primary Gate")

    async def run_post_signal_validators(self, market_state: MarketState) -> Dict[str, Any]:
        """Runs the secondary stack of filters after a signal is generated."""
        return await self._run_filter_group(market_state, self.post_signal_filters, "Post-Signal")

    async def generate_signal_and_verdict(self, market_state: MarketState) -> Dict[str, Any]:
        """
        Generate a signal, run validators, and get AI verdict.
        Returns: {"ai_verdict": Dict, "trade_type": str, "direction": str, "validator_report": Dict, "reason": str (if rejected)}
        """
        self.logger.info("--- New AI Strategy Cycle Started ---")
        # Run primary gate filters
        primary_gate_report = await self.run_primary_gate(market_state)
        if primary_gate_report.get("hard_blocks", 0) > 0:
            reason = format_rejection_reason(primary_gate_report["filters"], "Primary Gate")
            self.logger.warning(f"REJECTED: {reason}")
            return {"reason": reason, "validator_report": primary_gate_report["filters"]}
        # Generate signal
        signal_packet = await self.strategy_router.route_and_generate_signal(market_state, primary_gate_report)
        if not signal_packet:
            reason = REJECTION_CODE_MAP['NO_SIGNAL_GENERATED']
            self.logger.info(f"HALTED: {reason}")
            return {"reason": reason, "validator_report": primary_gate_report["filters"]}
        self.logger.info(f"Signal Packet Generated: Type={signal_packet.get('trade_type')}, Direction={signal_packet.get('direction')}")
        # Run post-signal validators
        post_signal_report = await self.run_post_signal_validators(market_state)
        final_validator_log = {**primary_gate_report["filters"], **post_signal_report["filters"]}
        if post_signal_report.get("hard_blocks", 0) > 0:
            reason = format_rejection_reason(post_signal_report["filters"], "Post-Signal")
            self.logger.warning(f"REJECTED: {reason}")
            return {"reason": reason, "validator_report": final_validator_log}
        self.logger.info("Post-Signal Validators passed. Proceeding to AI Core.")
        # Generate forecast
        forecast = await self.forecaster.generate_forecast(market_state)
        # Create context_packet
        snapshot = market_state.get_latest_data_snapshot()
        candle = snapshot.get("live_reconstructed_candle", [0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, "0"])
        if not candle or len(candle) != 9 or all(v == 0.0 for v in candle[1:6]):
            self.logger.warning(f"Invalid live_reconstructed_candle: {candle}")
            candle = [0, market_state.mark_price or 3200.0, 0.0, 0.0, market_state.mark_price or 3200.0, 0.0, 0.0, 0.0, "0"]
        context_packet = {
            "open": candle[1],
            "close": candle[4],
            "volume": candle[5],
            "direction": signal_packet.get("direction", "N/A"),
            "reversal_likelihood_score": forecast.get("reversal_likelihood_score", 0.0),
            "cts_score": final_validator_log.get("CtsFilter", {}).get("score", 0.0),
            "orderbook_score": final_validator_log.get("OrderBookReversalZoneDetector", {}).get("score", 0.0)
        }
        self.logger.info(f"Context packet for AI: {json.dumps(context_packet, indent=2)}")
        self.logger.info(f"Validator audit log: {json.dumps(final_validator_log, indent=2)}")
        # Get AI verdict
        ai_verdict = await self.ai_client.get_ai_verdict(context_packet)
        confidence = ai_verdict.get("confidence", 0.0)
        log_reason = ai_verdict.get('reasoning', 'No reasoning provided')
        if ai_verdict.get("action") == "⛔ Abort" and "AI request timed out" in log_reason:
            self.logger.error(f"AI VERDICT FAILED: Request Timed Out.")
        elif ai_verdict.get("action") == "⛔ Abort" and "Invalid JSON" in log_reason:
            self.logger.error(f"AI VERDICT FAILED: Unreadable Response. Reason: {log_reason}")
        else:
            self.logger.info(f"AI VERDICT: Action={ai_verdict.get('action')}, Confidence={confidence:.2f}, Reasoning='{log_reason}'")
        if confidence < self.config.ai_confidence_threshold:
            reason = f"Rejected - {REJECTION_CODE_MAP['AI_CONFIDENCE']} ({confidence:.2f}/{self.config.ai_confidence_threshold})"
            self.logger.warning(f"REJECTED: {reason}")
            await self.memory_tracker.update_memory(trade={"ai_verdict": ai_verdict, **signal_packet, "validator_report": final_validator_log})
            return {"reason": reason, "ai_verdict": ai_verdict, "validator_report": final_validator_log}
        final_signal = {"ai_verdict": ai_verdict, **signal_packet, "validator_report": final_validator_log}
        if ai_verdict.get("action") == "✅ Execute":
            entry_price = market_state.mark_price or 0.0
            is_safe, risk_reason = self.entry_simulator.check_liquidation_risk(entry_price, final_signal["direction"], forecast)
            if not is_safe:
                final_signal["ai_verdict"]["action"] = "⛔ Abort"
                reason = f"Rejected - {REJECTION_CODE_MAP['HIGH_LIQUIDATION_RISK']}: {risk_reason}"
                final_signal["reason"] = reason
                self.logger.warning(f"REJECTED: {reason}")
            else:
                self.logger.info("Liquidation risk check passed. Signal is fully approved for execution.")
        await self.memory_tracker.update_memory(trade=final_signal)
        return final_signal

    async def close(self):
        """Close the AIClient session."""
        await self.ai_client.close()
        self.logger.debug("ValidatorStack closed AIClient session.")