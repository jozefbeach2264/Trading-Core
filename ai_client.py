import logging
import json
import os
import httpx
from typing import Dict, Any
import asyncio
from config.config import Config
from services.memory_tracker import MemoryTracker

logger = logging.getLogger(__name__)
ai_strategy_logger = logging.getLogger('AIStrategyLogger')

# Static prompt for maximum caching (using plain ASCII)
STATIC_PROMPT = """
You are a high-frequency quant trading algorithm specializing in crypto futures markets.
You are being fed live ETH/USDT 1-minute candle data along with pre-processed filter signals. Analyze them to make a directional decision.

Key terms:
- 'cts_score': Confirms compression + expansion structure. It is non-directional and should not be interpreted as LONG or SHORT bias.
- 'orderbook_score': Measures orderbook wall strength. A high score (>= 0.8) supports the direction selected.
- 'reversal_likelihood_score': Measures probability of a price reversal. The higher the score, the more likely a move against the current candle.

Warning: Filter scores take priority over raw candle data. Candle direction should only influence decision when filter scores are weak.
Override conditions exist to handle bull/bear trap scenarios — they apply when candle direction conflicts with strong signal data.

Decision Logic:
- If direction = 'SHORT' and close > open and (cts + orderbook + reversal) >= 2.9 -> short trap -> EXECUTE.
- If direction = 'LONG' and close < open and (cts + orderbook + reversal) >= 2.9 -> long trap -> EXECUTE.
- In all other cases, base your answer on filter strength, not just price movement.
- Abort only if filter confidence is weak or price directly contradicts direction and signal scores are < 2.4.

Return JSON: {'action': 'Execute'|'Abort'|'Reanalyze', 'confidence': float (0.0-1.0), 'reasoning': 'One sentence'}.
"""

# Static JSON schema for caching
JSON_SCHEMA = {
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

class AIClient:
    def __init__(self, config: Config):
        self.config = config
        self.memory_tracker = MemoryTracker(config)
        self.client = httpx.AsyncClient(timeout=config.ai_client_timeout)

        # --- AI Interaction Logger Setup ---
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
        Sends a context packet to the AI using a strict JSON schema for the response.
        Returns: {"action": str, "confidence": float, "reasoning": str}
        """
        prompt = f"{STATIC_PROMPT}\nData:\n{json.dumps(context_packet, indent=2)}."

        try:
            logger.debug("Requesting one-shot verdict from AI with JSON schema.")
            response = await self.client.post(
                getattr(self.config, "ai_provider_url", "https://api.x.ai/v1"),
                headers={"Authorization": f"Bearer {self.config.xai_api_key}"},
                json={
                    "model": "grok-3-mini",
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": "Analyze the provided data and return a trading decision."}
                    ],
                    "max_completion_tokens": 1200,
                    "temperature": 0.2,
                    "response_format": {"type": "json_schema", "json_schema": JSON_SCHEMA},
                    "stream": False
                }
            )
            response.raise_for_status()

            raw_response = response.text
            ai_strategy_logger.info(f"FULL RAW API RESPONSE: ---{raw_response}---")

            response_data = response.json()
            token_usage = response_data.get("usage", {})
            cached_tokens = token_usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
            total_tokens = token_usage.get("total_tokens", 0)
            ai_strategy_logger.info(
                f"TOKEN USAGE: Prompt={token_usage.get('prompt_tokens', 0)}, "
                f"Completion={token_usage.get('completion_tokens', 0)}, "
                f"Total={total_tokens}, Cached={cached_tokens}"
            )

            if total_tokens > 2000:
                ai_strategy_logger.warning(f"Total tokens ({total_tokens}) exceeding target limit of 2000.")

            choice = response_data.get("choices", [{}])[0]
            finish_reason = choice.get("finish_reason")
            ai_strategy_logger.info(f"FINISH REASON: {finish_reason}")

            full_response_text = choice.get("message", {}).get("content", "")
            ai_strategy_logger.info(f"RAW AI RESPONSE RECEIVED: ---{full_response_text}---")

            if not full_response_text:
                ai_strategy_logger.info("Fallback verdict from context_packet.")
                return self._fallback_from_context(context_packet)

            verdict = json.loads(full_response_text)
            if (
                isinstance(verdict, dict) and
                verdict.get("action") in ["Execute", "Abort", "Reanalyze"] and
                isinstance(verdict.get("confidence"), (int, float)) and
                0.0 <= verdict.get("confidence") <= 1.0 and
                isinstance(verdict.get("reasoning"), str)
            ):
                await self.memory_tracker.update_memory(
                    trade_data={"direction": context_packet.get("direction", "N/A"), "ai_verdict": verdict}
                )
                logger.debug("xAI verdict received", extra=verdict)
                return verdict

            ai_strategy_logger.error("Invalid response structure.")
            return self._fallback_from_context(context_packet)

        except httpx.HTTPStatusError as e:
            ai_strategy_logger.error(f"AI API HTTP ERROR: Status {e.response.status_code} - Response: {e.response.text}")
            return self._fallback_from_context(context_packet)
        except (json.JSONDecodeError, KeyError, IndexError, ValueError) as e:
            ai_strategy_logger.error(f"AI VERDICT FAILED: {str(e)}. Full Response: {raw_response}")
            return self._fallback_from_context(context_packet)
        except httpx.TimeoutException:
            ai_strategy_logger.error("AI VERDICT FAILED: Request Timed Out.")
            return self._fallback_from_context(context_packet)
        except Exception as e:
            ai_strategy_logger.error(f"Unexpected error in AIClient: {e}", exc_info=True)
            return self._fallback_from_context(context_packet)

    def _fallback_from_context(self, context_packet: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a fallback verdict based on context_packet if API response is empty or invalid.
        """
        direction = context_packet.get("direction", "N/A").lower()
        open_price = context_packet.get("open", 0.0)
        close_price = context_packet.get("close", 0.0)
        volume = context_packet.get("volume", 0.0)
        reversal = context_packet.get("reversal_likelihood_score", 0.0)
        cts = context_packet.get("cts_score", 0.0)
        orderbook = context_packet.get("orderbook_score", 0.0)
        total_score = cts + orderbook + reversal
        confidence = min(total_score, 1.0) / 3.0

        if direction == "short" and close_price > open_price and total_score >= 2.9:
            return {
                "action": "Execute",
                "confidence": confidence,
                "reasoning": "High filter scores override bullish price movement for short trade."
            }
        if direction == "long" and close_price < open_price and total_score >= 2.9:
            return {
                "action": "Execute",
                "confidence": confidence,
                "reasoning": "High filter scores override bearish price movement for long trade."
            }

        if direction == "short":
            if close_price < open_price and volume > 0 and total_score >= 2.4:
                return {
                    "action": "Execute",
                    "confidence": confidence,
                    "reasoning": "Bearish price movement and strong filter scores support short trade."
                }
            elif close_price > open_price:
                return {
                    "action": "Abort",
                    "confidence": 0.8,
                    "reasoning": "Bullish price movement conflicts with short direction."
                }
            else:
                return {
                    "action": "Reanalyze",
                    "confidence": confidence,
                    "reasoning": "Unclear price movement or weak filter scores for short trade."
                }
        else:
            if close_price > open_price and volume > 0 and total_score >= 2.4:
                return {
                    "action": "Execute",
                    "confidence": confidence,
                    "reasoning": "Bullish price movement and strong filter scores support long trade."
                }
            elif close_price < open_price:
                return {
                    "action": "Abort",
                    "confidence": 0.8,
                    "reasoning": "Bearish price movement conflicts with long direction."
                }
            else:
                return {
                    "action": "Reanalyze",
                    "confidence": confidence,
                    "reasoning": "Unclear price movement or weak filter scores for long trade."
                }

    async def suggest_parameter_adjustments(self) -> Dict[str, Any]:
        """
        Suggest parameter adjustments based on trade success rate.
        """
        memory = self.memory_tracker.get_memory()
        success_rate = 0.0
        total_trades = len([t for t in memory["trades"] if not t["failed"]])
        successful_trades = len([t for t in memory["trades"] if not t["failed"] and t["order_data"]])
        if total_trades > 0:
            success_rate = successful_trades / total_trades

        suggestions = {}
        if success_rate > 0.8:
            suggestions["cts_narrow_range_ratio"] = self.config.cts_narrow_range_ratio * 0.9
            suggestions["retest_proximity_percent"] = self.config.retest_proximity_percent * 0.9
            suggestions["reasoning"] = "High success rate; proposing to loosen filter parameters."
        else:
            suggestions["reasoning"] = "Success rate is not high enough to recommend loosening parameters."

        logger.debug("Parameter adjustment suggestions generated.", extra=suggestions)
        return suggestions

    async def close(self):
        await self.client.aclose()
        logger.debug("AIClient httpx session closed.")