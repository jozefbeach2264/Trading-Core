import logging
import json
import time
from typing import Dict, Any, Optional
from typing import Protocol
from strategy.ai_strategy_protocol import AIStrategyProtocol
from config.config import Config
from log_utils import file_logger
from data_managers.market_state import MarketState
from strategy.strategy_router import StrategyRouter
from validator_stack import ValidatorStack
from rolling5_engine import Rolling5Engine
from simulators.entry_range_simulator import EntryRangeSimulator
from ai_client import AIClient
from freshness import stale_market_reason, stale_decision_reason
from position_manager import apply_fixed_stop, apply_predicted_stop
from memory_tracker import MemoryTracker

main_logger = logging.getLogger(__name__)

def setup_ai_strategy_logger(config: Config) -> logging.Logger:
    return file_logger("AIStrategyLogger", config.ai_strategy_log_path,
                       fmt="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

REJECTION_CODE_MAP = {
    "LowVolumeGuard": "LOW VOL", "TimeOfDayFilter": "OUT OF TIME WINDOW",
    "SpoofFilter": "SPOOFING", "CtsFilter": "CTS_BLOCK",
    "CompressionDetector": "COMPRESSION", "BreakoutZoneOriginFilter": "NO BREAKOUT",
    "RetestEntryLogic": "RETEST WEAK", "SentimentDivergenceFilter": "CVD CONFLICT",
    "OrderBookReversalZoneDetector": "OB WALL WEAK", "AI_CONFIDENCE": "AI CONFIDENCE LOW",
    "NO_SIGNAL_GENERATED": "Terminated by TrapX/Scalpel",
    "HIGH_LIQUIDATION_RISK": "HIGH LIQUIDATION RISK",
    "FORECAST_UNAVAILABLE": "FORECAST UNAVAILABLE",
    "REWARD_TOO_SMALL": "REWARD BELOW FEES",
    "STOP_TOO_TIGHT": "STOP TOO TIGHT FOR FEES",
    "STOP_BEYOND_LIQUIDATION": "STOP BEYOND LIQUIDATION",
    "AI_VERDICT": "AI VERDICT",
    "STALE_DATA": "STALE MARKET DATA",
    "STALE_DECISION": "STALE DECISION",
    "REVERSAL_RISK": "REVERSAL RISK",
    "NO_ENTRY_PRICE": "NO ENTRY PRICE"
}

def format_rejection_reason(filter_reports: Dict[str, Any], prefix: str) -> Optional[str]:
    rejection_codes = []
    for filter_name, report in filter_reports.items():
        if isinstance(report, dict) and "❌ Block" in report.get("flag", ""):
            code = REJECTION_CODE_MAP.get(filter_name, filter_name.upper())
            rejection_codes.append(code)
    return f"Rejected - {prefix}: {', '.join(rejection_codes)}" if rejection_codes else None

def normalize_ai_action(action: Optional[str]) -> str:
    """
    Normalizes AI verdict actions into the emoji-tagged strings the engine expects.
    Accepts plain strings (Execute/Abort/Reanalyze) and returns the emoji form.
    """
    mapping = {
        "execute": "✅ Execute",
        "abort": "⛔ Abort",
        "reanalyze": "🤔 Reanalyze"
    }
    if not action:
        return "🤔 Reanalyze"
    return mapping.get(action.lower(), action)

class AIStrategy(AIStrategyProtocol):
    def __init__(self, config: Config, strategy_router: StrategyRouter, forecaster: Rolling5Engine, ai_client: AIClient, entry_simulator: EntryRangeSimulator, memory_tracker: MemoryTracker):
        self.config = config
        self.strategy_router = strategy_router
        self.forecaster = forecaster
        self.ai_client = ai_client
        self.entry_simulator = entry_simulator
        self.memory_tracker = memory_tracker
        self.logger = setup_ai_strategy_logger(config)
        self._verdict_cache: Dict[tuple, tuple] = {}
        self.cache_hits = 0
        self.logger.info("AIStrategy initialized.")

    @staticmethod
    def _setup_key(signal_packet: Dict[str, Any], market_state: MarketState, context_packet: Dict[str, Any]) -> tuple:
        """Identity of a setup: strategy, direction, the live candle's minute, the gate scores rounded to 0.1
        and the wall zone. The same key within AI_VERDICT_CACHE_S is the same question."""
        candle = market_state.live_reconstructed_candle
        return (signal_packet.get("trade_type"), signal_packet.get("direction"), candle[0] if candle else None,
                round(float(context_packet.get("reversal_likelihood_score", 0.0)), 1),
                round(float(context_packet.get("cts_score", 0.0)), 1),
                round(float(context_packet.get("orderbook_score", 0.0)), 1),
                context_packet.get("orderbook_zone"))

    def _cached_verdict(self, key: tuple):
        ttl = self.config.ai_verdict_cache_s
        entry = self._verdict_cache.get(key) if ttl > 0 else None
        if entry and time.time() - entry[0] <= ttl:
            return entry[1]
        return None

    def _remember_verdict(self, key: tuple, verdict: Dict[str, Any]) -> None:
        if self.config.ai_verdict_cache_s <= 0:
            return
        now = time.time()
        self._verdict_cache[key] = (now, dict(verdict))
        if len(self._verdict_cache) > 256:   # drop expired entries; keys change every candle anyway
            self._verdict_cache = {k: v for k, v in self._verdict_cache.items() if now - v[0] <= self.config.ai_verdict_cache_s}

    def _reward_too_small(self, signal_packet: Dict[str, Any]) -> str:
        """'' when the target is worth taking; otherwise why it is not."""
        required = self.config.min_reward_fee_multiple
        if required <= 0:
            return ""
        entry = float(signal_packet.get("entry_price") or 0.0)
        target = signal_packet.get("take_profit")
        if entry <= 0 or target is None:
            return ""
        reward_pct = abs(float(target) - entry) / entry * 100.0
        fee_pct = self.config.round_trip_fee_percent
        if fee_pct > 0 and reward_pct < required * fee_pct:
            return f"target {reward_pct:.3f}% < {required:g}x the {fee_pct:.3f}% round-trip fee"
        return ""

    def _stop_too_tight(self, signal_packet: Dict[str, Any]) -> str:
        """'' when the stop is wide enough that fees stay a modest share of the risk; otherwise why not.

        Under risk-based sizing the position is risk / stop-distance, so a tight stop means a big position and
        the fee-to-risk ratio is simply fee% / stop%. A stop narrower than the fee means paying more in fees
        than the trade puts at risk."""
        required = self.config.min_stop_fee_multiple
        if required <= 0:
            return ""
        entry = float(signal_packet.get("entry_price") or 0.0)
        stop = signal_packet.get("stop_loss")
        if entry <= 0 or stop is None:
            return ""
        stop_pct = abs(float(stop) - entry) / entry * 100.0
        fee_pct = self.config.round_trip_fee_percent
        if fee_pct > 0 and stop_pct < required * fee_pct:
            return (f"stop {stop_pct:.3f}% < {required:g}x the {fee_pct:.3f}% fee "
                    f"(fees would be {fee_pct/stop_pct:.1f}x the risk)")
        return ""

    def _stop_beyond_liquidation(self, signal_packet: Dict[str, Any]) -> str:
        """'' when the trade is valid; otherwise why not.

        The operator's rule (2026-09-16): a trade is valid so long as a stop-out does not zero the wallet or
        exceed a set allowed capital amount. This account trades CROSS margin, where the whole wallet is
        collateral — so the old 100/LEVERAGE test was measuring isolated margin and refused stops that were
        nowhere near liquidation (57 of 60 rejections on 2026-09-16 were this).

        Two things can still make a stop invalid, and only these two:
          * it would cost more of the wallet than the allowed capital, or
          * liquidation would arrive before the stop, which makes the stop fiction.
        """
        entry = float(signal_packet.get("entry_price") or 0.0)
        stop = signal_packet.get("stop_loss")
        if entry <= 0 or stop is None:
            return ""
        stop_fraction = abs(float(stop) - entry) / entry
        if stop_fraction <= 0:
            return ""

        loss_pct = self.config.loss_fraction_at_stop(stop_fraction) * 100.0
        allowed = self.config.max_trade_loss_percent
        if loss_pct >= allowed:
            return (f"a stop-out would cost {loss_pct:.2f}% of the wallet, at or beyond the {allowed:g}% allowed")

        buffer = self.config.max_stop_liquidation_fraction
        liq_pct = self.config.liquidation_distance_fraction(stop_fraction) * 100.0
        stop_pct = stop_fraction * 100.0
        if buffer > 0 and stop_pct > buffer * liq_pct:
            return (f"stop {stop_pct:.3f}% exceeds {buffer:g}x the {liq_pct:.3f}% {self.config.margin_mode}-margin "
                    f"liquidation distance — liquidation would come first")
        return ""

    def _reject(self, code: str, detail: str, validator_report: Dict[str, Any], level: str = "warning") -> Dict[str, Any]:
        reason = f"Rejected - {REJECTION_CODE_MAP[code]}: {detail}" if detail else f"Rejected - {REJECTION_CODE_MAP[code]}"
        getattr(self.logger, level)(f"REJECTED: {reason}")
        return {"reason": reason, "validator_report": validator_report}

    async def generate_signal(self, market_state: MarketState, validator_stack: ValidatorStack) -> Dict[str, Any]:
        self.logger.info("--- New AI Strategy Cycle Started ---")

        # Never evaluate a frozen snapshot (feed outage, stalled trades channel).
        stale = stale_market_reason(market_state, self.config.max_data_staleness_s)
        if stale:
            return self._reject("STALE_DATA", stale, {})

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

        # ROLLING5 OWNS THE STOP. Scalpel and TrapX found the trade; they do not get to decide when it dies.
        # Their stops come from candle geometry (a fraction of the previous candle's range, or a fixed dollar
        # offset) and can easily sit inside the movement R5 already expects — in which case ordinary wander
        # kills the trade and the forecast is never tested. Widen to the predicted band BEFORE the guards
        # judge the stop and before sizing uses it, since the stop width sets the position size.
        # Fixed-size mode, when the operator has pinned both numbers, replaces this entirely: the stop is
        # where their dollar allowance runs out, not where any forecast says.
        stop_note = (apply_fixed_stop(signal_packet, self.config) if self.config.fixed_size_mode
                     else apply_predicted_stop(signal_packet, self.forecaster.predicted_band(market_state), self.config))
        if stop_note:
            # Debug, not info: this runs on every cycle a setup is live, so at a 0.2 s cycle an info line here
            # writes thousands of identical records per signal and buries everything else in the log. The note
            # rides along on the signal instead, so it is preserved on the trade record if the trade opens.
            signal_packet["stop_note"] = stop_note
            self.logger.debug(stop_note)

        # A target that does not clear the round-trip fee several times over cannot make money even when the
        # trade is right. Refuse it before spending a model call on it.
        reward_reason = self._reward_too_small(signal_packet)
        if reward_reason:
            return self._reject("REWARD_TOO_SMALL", reward_reason, primary_gate_report["filters"], level="info")
        stop_reason = self._stop_too_tight(signal_packet)
        if stop_reason:
            return self._reject("STOP_TOO_TIGHT", stop_reason, primary_gate_report["filters"], level="info")
        liq_reason = self._stop_beyond_liquidation(signal_packet)
        if liq_reason:
            return self._reject("STOP_BEYOND_LIQUIDATION", liq_reason, primary_gate_report["filters"], level="info")

        market_state.pending_signal_direction = str(signal_packet.get("direction") or "").upper() or None
        try:
            post_signal_report = await validator_stack.run_post_signal_validators(market_state)
        finally:
            market_state.pending_signal_direction = None
        final_validator_log = {**primary_gate_report["filters"], **post_signal_report["filters"]}
        if post_signal_report.get("hard_blocks", 0) > 0:
            reason = format_rejection_reason(post_signal_report["filters"], "Post-Signal")
            self.logger.warning(f"REJECTED: {reason}")
            return {"reason": reason, "validator_report": final_validator_log}
        self.logger.info("Post-Signal Validators passed. Proceeding to AI Core.")
        
        forecast = await self.forecaster.generate_forecast(market_state, signal_packet.get("direction"))
        if not forecast.get("forecast_generated"):
            return self._reject("FORECAST_UNAVAILABLE", "", final_validator_log)
        reversal_risk = float(forecast.get("reversal_likelihood_score", 0.0))
        if reversal_risk > self.config.ai_max_reversal_risk:
            # Deterministic backstop: do not even ask the model to trade into a forecast reversal.
            return self._reject("REVERSAL_RISK", f"{reversal_risk:.2f} > {self.config.ai_max_reversal_risk:.2f}", final_validator_log)
        
        # Create flat context_packet for AIClient
        snapshot = market_state.get_latest_data_snapshot()
        candle = snapshot.get("live_reconstructed_candle", [0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, "0"])
        if not candle or len(candle) != 9 or all(v == 0.0 for v in candle[1:6]):
            self.logger.warning(f"Invalid live_reconstructed_candle: {candle}")
            candle = [0, market_state.mark_price or 3200.0, 0.0, 0.0, market_state.mark_price or 3200.0, 0.0, 0.0, 0.0, "0"]
        
        orderbook_report = final_validator_log.get("OrderBookReversalZoneDetector", {})
        context_packet = {
            "open": candle[1],
            "close": candle[4],
            "volume": candle[5],
            "direction": signal_packet.get("direction", "N/A"),
            # Canonical key (2026-09-15): the forecaster emits exactly this name (review findings 1/9/10).
            "reversal_likelihood_score": forecast.get("reversal_likelihood_score", 0.0),
            "cts_score": final_validator_log.get("CtsFilter", {}).get("score", 0.0),
            "orderbook_score": orderbook_report.get("score", 0.0),
            # Which side the strongest wall sits on. A resistance wall opposes a LONG, a support wall a SHORT;
            # without this the model saw a wall directly against the trade as "strong confirmation".
            "orderbook_zone": (orderbook_report.get("metrics") or {}).get("detected_zone", "none"),
        }
        signal_price = float(market_state.mark_price or 0.0)
        decided_at = time.time()
        
        # Log context_packet and validator_audit_log
        self.logger.info(f"Context packet for AI: {json.dumps(context_packet, indent=2)}")
        self.logger.info(f"Validator audit log: {json.dumps(final_validator_log, indent=2)}")
        
        try:
            cache_key = self._setup_key(signal_packet, market_state, context_packet)
            cached = self._cached_verdict(cache_key)
            if cached is not None:
                ai_verdict = dict(cached)
                self.cache_hits += 1
                self.logger.info(f"AI VERDICT (cached for this setup): {ai_verdict.get('action')} {ai_verdict.get('confidence')}")
            else:
                ai_verdict = await self.ai_client.get_ai_verdict(context_packet)
                ai_verdict["action"] = normalize_ai_action(ai_verdict.get("action"))
                self._remember_verdict(cache_key, ai_verdict)
            confidence = ai_verdict.get("confidence", 0.0)
        except Exception as e:
            self.logger.error(f"Error fetching AI verdict: {e}", exc_info=True)
            ai_verdict = {"action": "🤔 Reanalyze", "confidence": 0.0, "reasoning": f"AI Client Error: {e}"}
            confidence = 0.0
        
        log_reason = ai_verdict.get('reasoning', 'No reasoning provided')
        if ai_verdict.get("action") == "🤔 Reanalyze" and confidence == 0.0:
            self.logger.error(f"AI VERDICT UNAVAILABLE: {log_reason}")
        else:
            self.logger.info(f"AI VERDICT: Action={ai_verdict.get('action')}, Confidence={confidence:.2f}, Reasoning='{log_reason}'")

        if confidence < self.config.ai_confidence_threshold:
            reason = f"Rejected - {REJECTION_CODE_MAP['AI_CONFIDENCE']} ({confidence:.2f}/{self.config.ai_confidence_threshold})"
            self.logger.warning(f"REJECTED: {reason}")
            # The returned verdict must not still say Execute: the engine keys on the action.
            rejected_verdict = {**ai_verdict, "action": "🤔 Reanalyze"}
            return {"reason": reason, "ai_verdict": rejected_verdict, "validator_report": final_validator_log}

        # The strategy's own descriptive "reason" ("Scalpel: ...") must not look like a rejection reason:
        # the engine executes only signals WITHOUT a "reason". Keep it under signal_reason.
        final_signal = {"ai_verdict": ai_verdict, **{k: v for k, v in signal_packet.items() if k != "reason"},
                        "signal_reason": signal_packet.get("reason", ""), "validator_report": final_validator_log,
                        # what the trade was taken ON — kept with the trade record so it can be judged later
                        "context_packet": dict(context_packet),
                        "filter_snapshot": {name: {"flag": r.get("flag"), "score": r.get("score"), "reason": (r.get("metrics") or {}).get("reason")}
                                            for name, r in final_validator_log.items() if isinstance(r, dict)}}

        if ai_verdict.get("action") != "✅ Execute":
            # Abort / Reanalyze with confidence above the gate: a rejection, with the model's own words.
            final_signal["reason"] = f"Rejected - {REJECTION_CODE_MAP['AI_VERDICT']}: {ai_verdict.get('action')} ({log_reason})"
            self.logger.info(f"REJECTED: {final_signal['reason']}")
            return final_signal

        if ai_verdict.get("action") == "✅ Execute":
            # The verdict was formed on a snapshot taken before the model call; re-check it is still actionable.
            entry_price = float(market_state.mark_price or 0.0)
            if entry_price <= 0:
                return self._reject("NO_ENTRY_PRICE", "", final_validator_log)
            stale = stale_market_reason(market_state, self.config.max_data_staleness_s) or stale_decision_reason(
                decided_at, signal_price, entry_price, self.config.max_decision_age_s, self.config.max_entry_drift_pct)
            if stale:
                return self._reject("STALE_DECISION", stale, final_validator_log)
            self.logger.info(f"Forecast data for risk check: {json.dumps(forecast, indent=2)}")
            is_safe, risk_reason = self.entry_simulator.check_liquidation_risk(entry_price, final_signal["direction"], forecast)
            if not is_safe:
                final_signal["ai_verdict"]["action"] = "⛔ Abort"
                reason = f"Rejected - {REJECTION_CODE_MAP['HIGH_LIQUIDATION_RISK']}: {risk_reason}"
                final_signal["reason"] = reason
                self.logger.warning(f"REJECTED: {reason}")
            else:
                self.logger.info("Liquidation risk check passed. Signal is fully approved for execution.")
        
        return final_signal
