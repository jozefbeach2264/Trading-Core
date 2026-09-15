"""AI verdict client.

Talks to any OpenAI-compatible chat-completions endpoint. The production target is a local
llama-server (`llm-serve <profile>`, http://127.0.0.1:8081/v1) — Grok/xAI was retired on
2026-09-15. Design points that matter for a 200x bot:

* Every failure path returns a Reanalyze verdict with confidence 0.0 (never raises).
* The system prompt is static so the server's prompt cache makes TTFT ≈ user-message only.
* Thinking/reasoning is disabled per request; the reasoning string is capped by max_tokens.
* llama.cpp's schema→grammar ignores numeric minimum/maximum, so confidence is clamped here.
"""
import asyncio
import json
import logging
import math
from typing import Any, Dict, Optional

import httpx

from ai_model_logger import get_ai_model_logger, log_ai_decision
from config.config import Config
from memory_tracker import MemoryTracker

logger = logging.getLogger(__name__)
ai_strategy_logger = logging.getLogger('AIStrategyLogger')

VALID_ACTIONS = ("Execute", "Abort", "Reanalyze")
_ACTION_BY_LOWER = {a.lower(): a for a in VALID_ACTIONS}

# Static prompt → identical prefix every call → server-side prompt cache hit.
SYSTEM_PROMPT = (
    "Analyze the provided market data for an ETH/USDT trade decision.\n"
    "- CTS Score: Compression Trap Sensor. High score (>0.8) indicates strong trend confirmation.\n"
    "- Orderbook Score: Market depth assessment. High score (>0.8) suggests strong support/resistance.\n"
    "- Reversal Likelihood Score: probability (0-1) that price reverses AGAINST the trade direction. "
    "A high value is a major red flag.\n"
    "Primary goal is capital preservation. Only 'Execute' on high-probability setups.\n"
    "Return JSON with 'action' (Execute|Abort|Reanalyze), 'confidence' (0-1) and, if the schema asks for it, "
    "'reasoning' (one short sentence, max 20 words)."
)

def build_verdict_schema(reasoning_max_chars: int) -> Dict[str, Any]:
    """JSON schema for the verdict. `reasoning` is only logged, so its length is capped in the
    grammar itself (llama.cpp honours string maxLength) — every extra token is latency.
    reasoning_max_chars <= 0 drops the field entirely (fastest: ~15 output tokens)."""
    properties: Dict[str, Any] = {
        "action": {"type": "string", "enum": list(VALID_ACTIONS)},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    }
    required = ["action", "confidence"]
    if reasoning_max_chars > 0:
        properties["reasoning"] = {"type": "string", "maxLength": reasoning_max_chars}
        required.append("reasoning")
    return {"name": "trading_decision",
            "schema": {"type": "object", "properties": properties, "required": required, "additionalProperties": False}}


VERDICT_JSON_SCHEMA = build_verdict_schema(200)

FALLBACK_EXECUTE_MIN_SCORE = 0.8      # cts + orderbook must both beat this
FALLBACK_EXECUTE_MAX_REVERSAL = 0.2   # and reversal risk must be below this
TOKEN_WARN_LIMIT = 2000


def _reanalyze(reasoning: str) -> Dict[str, Any]:
    return {"action": "Reanalyze", "confidence": 0.0, "reasoning": reasoning}


def _clamp01(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


def parse_verdict(content: str) -> Optional[Dict[str, Any]]:
    """Strict parse of the model's JSON. Returns None for anything not usable."""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    action = _ACTION_BY_LOWER.get(str(data.get("action", "")).strip().lower())
    confidence = data.get("confidence")
    if action is None or isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return None
    if math.isnan(confidence) or math.isinf(confidence):
        return None
    reasoning = data.get("reasoning", "")
    return {"action": action, "confidence": _clamp01(confidence),
            "reasoning": reasoning if isinstance(reasoning, str) else str(reasoning)}


class AIClient:
    def __init__(self, config: Config):
        self.config = config
        self.memory_tracker = MemoryTracker(config)
        timeout = httpx.Timeout(config.ai_client_timeout, connect=min(3.0, config.ai_client_timeout))
        self.client = httpx.AsyncClient(timeout=timeout, limits=httpx.Limits(max_keepalive_connections=2, keepalive_expiry=300.0))
        self.model_logger = get_ai_model_logger(config)
        self._verdict_url = f"{config.ai_provider_url}/chat/completions"
        self._schema = build_verdict_schema(config.ai_reasoning_max_chars)
        logger.debug("AIClient initialized → %s (model=%s)", self._verdict_url, config.ai_model)

    # ------------------------------------------------------------------ request
    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.ai_api_key:
            headers["Authorization"] = f"Bearer {self.config.ai_api_key}"
        return headers

    def _build_request(self, context_packet: Dict[str, Any]) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "model": self.config.ai_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Market Data: {json.dumps(context_packet)}"},
            ],
            "max_tokens": self.config.ai_max_tokens,
            "temperature": self.config.ai_temperature,
            "response_format": {"type": "json_schema", "json_schema": self._schema},
            "stream": False,
        }
        if self.config.ai_disable_thinking:
            # Qwen/Gemma templates read enable_thinking; gpt-oss reads reasoning_effort;
            # llama-server honours reasoning_budget. Unknown keys are ignored by every provider.
            body["chat_template_kwargs"] = {"enable_thinking": False, "reasoning_effort": "low"}
            body["reasoning_budget"] = 0
        return body

    def _record(self, entry: Dict[str, Any]) -> None:
        try:
            log_ai_decision(self.model_logger, entry)
        except Exception:  # logging must never break a verdict
            logger.debug("AI decision log write failed", exc_info=True)

    async def _remember(self, context_packet: Dict[str, Any], verdict: Dict[str, Any]) -> None:
        try:
            await self.memory_tracker.update_memory(
                trade_data={"direction": context_packet.get("direction", "N/A"), "ai_verdict": verdict})
        except Exception:
            logger.debug("MemoryTracker update failed", exc_info=True)

    # ------------------------------------------------------------------ verdict
    async def get_ai_verdict(self, context_packet: Dict[str, Any]) -> Dict[str, Any]:
        """Return {"action": Execute|Abort|Reanalyze, "confidence": 0..1, "reasoning": str}. Never raises."""
        loop = asyncio.get_running_loop()
        start_time = loop.time()

        def elapsed_ms() -> float:
            return round((loop.time() - start_time) * 1000.0, 2)

        try:
            response = await self.client.post(self._verdict_url, headers=self._headers(), json=self._build_request(context_packet))
            response.raise_for_status()
        except httpx.TimeoutException:
            ai_strategy_logger.error("AI VERDICT FAILED: Request Timed Out after %.0f ms.", elapsed_ms())
            verdict = _reanalyze("AI request timed out.")
            self._record({"type": "timeout", "context": context_packet, "verdict": verdict, "latency_ms": elapsed_ms()})
            return verdict
        except httpx.HTTPStatusError as e:
            body = e.response.text[:500]
            ai_strategy_logger.error(f"AI API HTTP ERROR: Status {e.response.status_code} - Response: {body}")
            verdict = _reanalyze(f"API HTTP error: {e.response.status_code} - {body}")
            self._record({"type": "api_error", "context": context_packet, "verdict": verdict, "latency_ms": elapsed_ms()})
            return verdict
        except httpx.HTTPError as e:  # connect/DNS/protocol errors
            ai_strategy_logger.error(f"AI API TRANSPORT ERROR: {e!r}")
            verdict = _reanalyze(f"AI transport error: {e!r}")
            self._record({"type": "api_error", "context": context_packet, "verdict": verdict, "latency_ms": elapsed_ms()})
            return verdict
        except Exception as e:  # pragma: no cover - last line of defence
            ai_strategy_logger.error(f"An unexpected error occurred in AIClient: {e}", exc_info=True)
            verdict = _reanalyze(f"A general error occurred: {e}")
            self._record({"type": "error", "context": context_packet, "verdict": verdict, "latency_ms": elapsed_ms()})
            return verdict

        latency_ms = elapsed_ms()
        raw_response = response.text
        ai_strategy_logger.info(f"FULL RAW API RESPONSE: ---{raw_response}---")
        self._record({"type": "latency", "latency_ms": latency_ms, "context": context_packet})

        try:
            response_data = response.json()
            choice = response_data["choices"][0]
            message = choice.get("message") or {}
            content = message.get("content") or ""
            finish_reason = choice.get("finish_reason")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
            ai_strategy_logger.error(f"AI VERDICT FAILED: unusable response structure ({e!r}). Full Response: {raw_response[:500]}")
            return await self._fallback(context_packet, error=f"bad response structure: {e!r}", latency_ms=latency_ms)

        self._log_token_usage(response_data.get("usage") or {})
        ai_strategy_logger.info(f"FINISH REASON: {finish_reason}")
        ai_strategy_logger.info(f"RAW AI RESPONSE RECEIVED: ---{content}---")

        verdict = parse_verdict(content) if content else None
        if verdict is None:
            ai_strategy_logger.error(f"AI VERDICT FAILED: invalid or empty verdict content: {content[:300]!r}")
            return await self._fallback(context_packet, error="invalid verdict content", latency_ms=latency_ms)

        await self._remember(context_packet, verdict)
        self._record({"ts": response_data.get("created"), "type": "api_verdict", "context": context_packet,
                      "verdict": verdict, "finish_reason": finish_reason, "latency_ms": latency_ms})
        logger.debug("AI verdict received in %.0f ms: %s", latency_ms, verdict)
        return verdict

    def _log_token_usage(self, usage: Dict[str, Any]) -> None:
        cached_tokens = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        total_tokens = usage.get("total_tokens", 0)
        ai_strategy_logger.info(
            f"TOKEN USAGE: Prompt={usage.get('prompt_tokens', 0)}, Completion={usage.get('completion_tokens', 0)}, "
            f"Total={total_tokens}, Cached={cached_tokens}")
        if total_tokens > TOKEN_WARN_LIMIT:
            ai_strategy_logger.warning(f"Total tokens ({total_tokens}) exceeding target limit of {TOKEN_WARN_LIMIT}.")

    async def _fallback(self, context_packet: Dict[str, Any], error: str, latency_ms: float) -> Dict[str, Any]:
        verdict = self._fallback_from_context(context_packet)
        ai_strategy_logger.info("Fallback verdict from context_packet.")
        await self._remember(context_packet, verdict)
        self._record({"type": "fallback", "context": context_packet, "verdict": verdict, "error": error, "latency_ms": latency_ms})
        logger.debug("AI verdict produced via context fallback: %s", verdict)
        return verdict

    def _fallback_from_context(self, context_packet: Dict[str, Any]) -> Dict[str, Any]:
        """Heuristic verdict when the model returns nothing usable.

        Confidence is the mean of the three gate scores (reversal risk inverted). Execute needs
        price moving with the trade, strong CTS + orderbook scores AND low reversal risk."""
        direction = str(context_packet.get("direction", "N/A")).lower()
        open_price = float(context_packet.get("open", 0.0) or 0.0)
        close_price = float(context_packet.get("close", 0.0) or 0.0)
        volume = float(context_packet.get("volume", 0.0) or 0.0)
        reversal_risk = _clamp01(context_packet.get("reversal_likelihood_score", 0.0) or 0.0)
        cts_score = _clamp01(context_packet.get("cts_score", 0.0) or 0.0)
        orderbook_score = _clamp01(context_packet.get("orderbook_score", 0.0) or 0.0)

        confidence = round(((1.0 - reversal_risk) + cts_score + orderbook_score) / 3.0, 4)
        gates_strong = (cts_score > FALLBACK_EXECUTE_MIN_SCORE and orderbook_score > FALLBACK_EXECUTE_MIN_SCORE
                        and reversal_risk < FALLBACK_EXECUTE_MAX_REVERSAL and volume > 0)
        is_short = direction == "short"
        price_with_trade = close_price < open_price if is_short else close_price > open_price
        price_against_trade = close_price > open_price if is_short else close_price < open_price
        label = "short" if is_short else "long"

        if price_with_trade and gates_strong:
            return {"action": "Execute", "confidence": confidence,
                    "reasoning": f"Price moving with the {label} and strong filter scores support the trade."}
        if price_against_trade:
            return {"action": "Abort", "confidence": 0.8,
                    "reasoning": f"Price movement conflicts with {label} direction."}
        return {"action": "Reanalyze", "confidence": confidence,
                "reasoning": f"Unclear price movement or weak filter scores for {label} trade."}

    # ------------------------------------------------------------------ health
    async def check_provider(self) -> bool:
        """Log which model the provider is serving. Non-fatal: a down provider just yields Reanalyze verdicts."""
        try:
            response = await self.client.get(f"{self.config.ai_provider_url}/models", headers=self._headers(), timeout=5.0)
            response.raise_for_status()
            models = [m.get("id") for m in (response.json().get("data") or [])]
            logger.info("AI provider reachable at %s; models: %s", self.config.ai_provider_url, models or "unknown")
            return True
        except Exception as e:
            logger.error("AI provider NOT reachable at %s (%r). Verdicts will be Reanalyze until it is up.",
                         self.config.ai_provider_url, e)
            return False

    async def suggest_parameter_adjustments(self) -> Dict[str, Any]:
        memory = self.memory_tracker.get_memory()
        total_trades = len([t for t in memory["trades"] if not t["failed"]])
        successful_trades = len([t for t in memory["trades"] if not t["failed"] and t["order_data"]])
        success_rate = successful_trades / total_trades if total_trades > 0 else 0.0

        suggestions: Dict[str, Any] = {}
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
