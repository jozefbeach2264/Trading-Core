import logging
import json
import os
import httpx
from typing import Dict, Any
from config.config import Config
from memory_tracker import MemoryTracker

logger = logging.getLogger(__name__)
ai_strategy_logger = logging.getLogger('AIStrategyLogger')

# ---------- CACHING-FRIENDLY STATIC PROMPT (updated for new reversal fields) ----------
STATIC_ENTRY_PROMPT = """
You are a high-frequency quant trading analysis AI for ETH/USDT futures markets.
Your sole purpose is to execute, maintain, and exit trades for maximum profitability by capturing as much favorable market movement as possible.
Your sole function is to return a valid JSON object.

You are being fed live ETH/USDT 1-minute candle data along with pre-processed filter signals and orderbook reversal metrics. Analyze them to make a directional decision.

Key terms:
- 'cts_score': Confirms compression + expansion structure. Non-directional, not a LONG or SHORT bias.
- 'orderbook_score': Measures orderbook wall strength. A high score (>= 0.8) supports the direction selected.
- 'reversal_likelihood_score': Probability of a price reversal. Higher score = more likely to move against the current candle.
- 'reversal_detected_zone': Indicates 'support' or 'resistance' zone, or None if not detected.
- 'reversal_direction_hint': Suggests 'long' or 'short' bias from orderbook, or None if neutral.
- 'reversal_wall_price': Price level of the detected orderbook wall, or None if not applicable.
- 'reversal_wall_qty': Quantity at the wall, indicating strength, or None if not applicable.
- 'reversal_delta_pct': Percentage change in orderbook pressure, if available.
- 'reversal_delta_dir': Direction of orderbook pressure change ('thin' or 'build'), or None.
- 'reversal_directional_score': Additional score supporting the direction hint, if available.
- 'reversal_flag': Optional flag indicating specific reversal conditions, if present.

Warning: Filter scores (cts_score, orderbook_score, reversal_likelihood_score) take priority over raw candle data. Candle direction should only influence when filter scores are weak.
New reversal metrics (reversal_detected_zone, reversal_direction_hint, etc.) provide strong directional signals when present and should be weighted heavily.
Override conditions for bull/bear traps:
- If direction = 'SHORT', close > open, and (cts + orderbook + reversal_likelihood) >= 2.9 -> short trap -> EXECUTE.
- If direction = 'LONG', close < open, and (cts + orderbook + reversal_likelihood) >= 2.9 -> long trap -> EXECUTE.
- If reversal_direction_hint aligns with direction and reversal_detected_zone is 'support' (for LONG) or 'resistance' (for SHORT), strongly favor EXECUTE.
- Abort only if filter confidence is weak (< 2.4) and price contradicts direction without strong reversal metrics.

TASK: Analyze the following live market data for a potential NEW TRADE ENTRY.
RULES: High scores for cts_score, orderbook_score, or reversal_likelihood_score are strong signals. Reversal metrics (reversal_direction_hint, reversal_detected_zone) take precedence when available.

Historical Context:
"""

STATIC_EXIT_PROMPT = """
You are a high-frequency quant trading analysis AI for ETH/USDT futures markets.
Your sole purpose is to execute, maintain, and exit trades for maximum profitability by capturing as much favorable market movement as possible.
Your sole function is to return a valid JSON object.

TASK: Analyze the following OPEN TRADE and determine the optimal exit strategy.
RULES: The primary goal is to secure profit or minimize loss. A high 'reversal_likelihood_score' is a strong signal to exit.

Open Trade Context:
"""

# ---------- ENTRY JSON SCHEMA ----------
ENTRY_JSON_SCHEMA = {
    "name": "trading_decision",
    "schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["Execute", "Abort", "Reanalyze"]},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "reasoning": {"type": "string"}
        },
        "required": ["action", "confidence", "reasoning"],
        "additionalProperties": False
    }
}

# ---------- EXIT JSON SCHEMA ----------
EXIT_JSON_SCHEMA = {
    "name": "exit_decision",
    "schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["HOLD", "EXIT_PROFIT", "EXIT_LOSS"]},
            "reasoning": {"type": "string"}
        },
        "required": ["action", "reasoning"],
        "additionalProperties": False
    }
}

class AIClient:
    def __init__(self, config: Config):
        self.config = config
        self.memory_tracker = MemoryTracker(config)
        self.client = httpx.AsyncClient(timeout=config.ai_client_timeout)

        # --- AI Interaction Logger ---
        self.ai_interaction_logger = logging.getLogger("AIInteractionLogger")
        self.ai_interaction_logger.setLevel(logging.INFO)
        self.ai_interaction_logger.propagate = False
        if not self.ai_interaction_logger.handlers:
            log_path = self.config.ai_interaction_log_path
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            handler = logging.FileHandler(log_path, mode='a')
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.ai_interaction_logger.addHandler(handler)

        logger.debug("AIClient initialized with httpx.")

    async def get_ai_verdict(self, context_packet: Dict[str, Any]) -> Dict[str, Any]:
        """
        ENTRY verdict. Uses static prefix for caching, appends dynamic historical context and current data (including new reversal fields).
        """
        # --- Inject reversal metrics into context_packet (no structure changes) ---
        _rev = context_packet.get("reversal_report") or context_packet.get("orderbook_reversal") or {}
        if isinstance(_rev, dict):
            _m = _rev.get("metrics") or {}
            context_packet.setdefault("reversal_likelihood_score", float(_rev.get("score", 0.0) or 0.0))
            context_packet.setdefault("reversal_detected_zone", _m.get("detected_zone"))
            context_packet.setdefault("reversal_direction_hint", _m.get("direction_hint"))
            context_packet.setdefault("reversal_human_reason", _m.get("human_reason") or _m.get("reason"))
            context_packet.setdefault("reversal_wall_price", _m.get("wall_price"))
            context_packet.setdefault("reversal_wall_qty", _m.get("wall_qty"))
            context_packet.setdefault("reversal_delta_pct", _m.get("delta_pct"))
            context_packet.setdefault("reversal_delta_dir", _m.get("delta_dir"))
            context_packet.setdefault("reversal_directional_score", _m.get("directional_score"))
            context_packet.setdefault("reversal_flag", _rev.get("flag"))

        similar_scenarios = self.memory_tracker.get_similar_scenarios(context_packet)
        dynamic_entry_prompt = (
            f"{json.dumps(similar_scenarios, indent=2)}\n\n"
            f"Current Live Data:\n{json.dumps(context_packet, indent=2)}\n"
        )

        try:
            self.ai_interaction_logger.info("ENTRY REQUEST START")
            response = await self.client.post(
                getattr(self.config, "ai_provider_url", "https://api.x.ai/v1") + "/chat/completions",
                headers={"Authorization": f"Bearer {self.config.xai_api_key}"},
                json={
                    "model": "grok-3-mini",
                    "messages": [
                        {"role": "system", "content": STATIC_ENTRY_PROMPT},
                        {"role": "user", "content": dynamic_entry_prompt}
                    ],
                    "max_completion_tokens": 1600,
                    "temperature": 0.1,
                    "response_format": {"type": "json_schema", "json_schema": ENTRY_JSON_SCHEMA},
                    "stream": False
                }
            )
            response.raise_for_status()

            raw_response = response.text
            self.ai_interaction_logger.info(f"ENTRY RAW RESPONSE: ---{raw_response}---")

            data = response.json()
            usage = data.get("usage", {})
            cached = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
            self.ai_interaction_logger.info(
                f"ENTRY TOKENS: prompt={usage.get('prompt_tokens', 0)}, "
                f"completion={usage.get('completion_tokens', 0)}, total={usage.get('total_tokens', 0)}, cached={cached}"
            )

            choice = data.get("choices", [{}])[0]
            self.ai_interaction_logger.info(f"ENTRY FINISH: {choice.get('finish_reason')}")

            content = choice.get("message", {}).get("content", "")
            self.ai_interaction_logger.info(f"ENTRY CONTENT: ---{content}---")

            if not content:
                self.ai_interaction_logger.info("ENTRY FALLBACK: empty content")
                return self._fallback_from_context(context_packet)

            verdict = json.loads(content)
            await self.memory_tracker.update_memory(
                trade_data={"direction": context_packet.get("direction", "N/A"), "ai_verdict": verdict}
            )
            logger.debug("xAI entry verdict received", extra=verdict)
            return verdict

        except httpx.HTTPStatusError as e:
            self.ai_interaction_logger.error(
                f"ENTRY HTTP ERROR: {e.response.status_code} - {e.response.text}"
            )
            return self._fallback_from_context(context_packet)
        except (json.JSONDecodeError, KeyError, IndexError, ValueError) as e:
            try:
                raw_response
            except NameError:
                raw_response = "<unavailable>"
            self.ai_interaction_logger.error(f"ENTRY PARSE ERROR: {e}. RESP: {raw_response}")
            return self._fallback_from_context(context_packet)
        except httpx.TimeoutException:
            self.ai_interaction_logger.error("ENTRY TIMEOUT")
            return self._fallback_from_context(context_packet)
        except Exception as e:
            self.ai_interaction_logger.error(f"ENTRY UNEXPECTED: {e}", exc_info=True)
            ai_strategy_logger.error(f"ENTRY UNEXPECTED: {e}", exc_info=True)
            return self._fallback_from_context(context_packet)

    async def get_dynamic_exit_verdict(self, open_trade_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        EXIT verdict. Includes reversal injection and configurable kill-switch threshold.
        """
        # --- Inject reversal metrics into open_trade_context (no structure changes) ---
        _rev = open_trade_context.get("reversal_report") or open_trade_context.get("orderbook_reversal") or {}
        if isinstance(_rev, dict):
            _m = _rev.get("metrics") or {}
            open_trade_context.setdefault("reversal_likelihood_score", float(_rev.get("score", 0.0) or 0.0))
            open_trade_context.setdefault("reversal_detected_zone", _m.get("detected_zone"))
            open_trade_context.setdefault("reversal_direction_hint", _m.get("direction_hint"))
            open_trade_context.setdefault("reversal_human_reason", _m.get("human_reason") or _m.get("reason"))
            open_trade_context.setdefault("reversal_wall_price", _m.get("wall_price"))
            open_trade_context.setdefault("reversal_wall_qty", _m.get("wall_qty"))
            open_trade_context.setdefault("reversal_delta_pct", _m.get("delta_pct"))
            open_trade_context.setdefault("reversal_delta_dir", _m.get("delta_dir"))
            open_trade_context.setdefault("reversal_directional_score", _m.get("directional_score"))
            open_trade_context.setdefault("reversal_flag", _rev.get("flag"))

        # --- R5 EXIT KILL-SWITCH: reversal against position (threshold from Config) ---
        pos  = (open_trade_context.get("direction") or "").lower()
        revp = float(open_trade_context.get("reversal_likelihood_score") or 0.0)
        zone = open_trade_context.get("reversal_detected_zone")
        hint = open_trade_context.get("reversal_direction_hint")

        # Sensible default if Config lacks the attribute
        thr = float(getattr(self.config, "exit_reversal_threshold", 0.80))
        if thr < 0.0: thr = 0.0
        if thr > 1.0: thr = 1.0

        if revp >= thr and (
            (pos == "long"  and (hint == "short" or zone == "resistance")) or
            (pos == "short" and (hint == "long"  or zone == "support"))
        ):
            pnl = open_trade_context.get("unrealized_pnl")
            return {
                "action": "EXIT_PROFIT" if isinstance(pnl, (int, float)) and pnl >= 0 else "EXIT_LOSS",
                "reasoning": f"Reversal {revp:.2f} >= {thr:.2f} against {pos} (zone={zone}, hint={hint}). Exiting now."
            }

        dynamic_exit_prompt = f"{json.dumps(open_trade_context, indent=2)}\n"

        try:
            self.ai_interaction_logger.info("EXIT REQUEST START")
            response = await self.client.post(
                getattr(self.config, "ai_provider_url", "https://api.x.ai/v1") + "/chat/completions",
                headers={"Authorization": f"Bearer {self.config.xai_api_key}"},
                json={
                    "model": "grok-3-mini",
                    "messages": [
                        {"role": "system", "content": STATIC_EXIT_PROMPT},
                        {"role": "user", "content": dynamic_exit_prompt}
                    ],
                    "max_completion_tokens": 1000,
                    "temperature": 0.05,
                    "response_format": {"type": "json_schema", "json_schema": EXIT_JSON_SCHEMA},
                    "stream": False
                }
            )
            response.raise_for_status()

            raw_response = response.text
            self.ai_interaction_logger.info(f"EXIT RAW RESPONSE: ---{raw_response}---")

            data = response.json()
            usage = data.get("usage", {})
            cached = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
            self.ai_interaction_logger.info(
                f"EXIT TOKENS: prompt={usage.get('prompt_tokens', 0)}, "
                f"completion={usage.get('completion_tokens', 0)}, total={usage.get('total_tokens', 0)}, cached={cached}"
            )

            choice = data.get("choices", [{}])[0]
            self.ai_interaction_logger.info(f"EXIT FINISH: {choice.get('finish_reason')}")

            content = choice.get("message", {}).get("content", "")
            self.ai_interaction_logger.info(f"EXIT CONTENT: ---{content}---")

            if not content:
                self.ai_interaction_logger.info("EXIT FALLBACK: empty content")
                return {"action": "HOLD", "reasoning": "Error during exit analysis."}

            verdict = json.loads(content)
            logger.debug("xAI exit verdict received", extra=verdict)
            return verdict

        except httpx.HTTPStatusError as e:
            self.ai_interaction_logger.error(
                f"EXIT HTTP ERROR: {e.response.status_code} - {e.response.text}"
            )
            return {"action": "HOLD", "reasoning": "HTTP error contacting AI."}
        except (json.JSONDecodeError, KeyError, IndexError, ValueError) as e:
            try:
                raw_response
            except NameError:
                raw_response = "<unavailable>"
            self.ai_interaction_logger.error(f"EXIT PARSE ERROR: {e}. RESP: {raw_response}")
            return {"action": "HOLD", "reasoning": "Parse error during exit analysis."}
        except httpx.TimeoutException:
            self.ai_interaction_logger.error("EXIT TIMEOUT")
            return {"action": "HOLD", "reasoning": "Timeout during exit analysis."}
        except Exception as e:
            self.ai_interaction_logger.error(f"EXIT UNEXPECTED: {e}", exc_info=True)
            ai_strategy_logger.error(f"EXIT UNEXPECTED: {e}", exc_info=True)
            return {"action": "HOLD", "reasoning": "Unexpected error during exit analysis."}

    def _fallback_from_context(self, context_packet: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fallback verdict updated to use new reversal fields.
        """
        direction = context_packet.get("direction", "N/A").lower()
        open_price = context_packet.get("open", 0.0)
        close_price = context_packet.get("close", 0.0)
        volume = context_packet.get("volume", 0.0)
        reversal = context_packet.get("reversal_likelihood_score", 0.0)
        cts = context_packet.get("cts_score", 0.0)
        orderbook = context_packet.get("orderbook_score", 0.0)
        reversal_direction_hint = context_packet.get("reversal_direction_hint")
        reversal_detected_zone = context_packet.get("reversal_detected_zone")
        reversal_wall_qty = context_packet.get("reversal_wall_qty", 0.0)
        reversal_directional_score = context_packet.get("reversal_directional_score", 0.0)
        total_score = cts + orderbook + reversal
        confidence = min(total_score / 3.0 + (reversal_directional_score or 0.0) / 3.0, 1.0)

        if (reversal_direction_hint == direction and
                ((direction == "long" and reversal_detected_zone == "support") or
                 (direction == "short" and reversal_detected_zone == "resistance")) and
                reversal_wall_qty is not None and reversal_wall_qty > 0):
            return {
                "action": "Execute",
                "confidence": min(confidence + 0.2, 1.0),
                "reasoning": f"Strong reversal metrics ({reversal_detected_zone} zone, {reversal_direction_hint} hint) support {direction} trade."
            }

        if direction == "short" and close_price > open_price and total_score >= 2.9:
            return {"action": "Execute", "confidence": confidence,
                    "reasoning": "High filter scores override bullish price movement for short trade."}
        if direction == "long" and close_price < open_price and total_score >= 2.9:
            return {"action": "Execute", "confidence": confidence,
                    "reasoning": "High filter scores override bearish price movement for long trade."}

        if direction == "short":
            if (close_price < open_price and volume > 0 and total_score >= 2.4) or \
               (reversal_direction_hint == "short" and reversal_detected_zone == "resistance"):
                return {"action": "Execute", "confidence": confidence,
                        "reasoning": "Bearish move or strong reversal metrics support short trade."}
            elif close_price > open_price and total_score < 2.4:
                return {"action": "Abort", "confidence": 0.8,
                        "reasoning": "Bullish move conflicts with short direction and weak filters."}
            else:
                return {"action": "Reanalyze", "confidence": confidence,
                        "reasoning": "Unclear move or weak filters for short trade."}
        else:
            if (close_price > open_price and volume > 0 and total_score >= 2.4) or \
               (reversal_direction_hint == "long" and reversal_detected_zone == "support"):
                return {"action": "Execute", "confidence": confidence,
                        "reasoning": "Bullish move or strong reversal metrics support long trade."}
            elif close_price < open_price and total_score < 2.4:
                return {"action": "Abort", "confidence": 0.8,
                        "reasoning": "Bearish move conflicts with long direction and weak filters."}
            else:
                return {"action": "Reanalyze", "confidence": confidence,
                        "reasoning": "Unclear move or weak filters for long trade."}

    async def close(self):
        await self.client.aclose()
        logger.debug("AIClient httpx session closed.")