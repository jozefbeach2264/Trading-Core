import logging
import json
import httpx
from typing import Dict, Any
import asyncio
import re
import random
from config.config import Config
from memory_tracker import MemoryTracker
from ai_model_logger import get_ai_model_logger, log_ai_decision

logger = logging.getLogger(__name__)
ai_strategy_logger = logging.getLogger('AIStrategyLogger')

class AIClient:
    def __init__(self, config: Config):
        self.config = config
        self.memory_tracker = MemoryTracker(config)
        self.client = httpx.AsyncClient(timeout=config.ai_client_timeout)
        self.model_logger = get_ai_model_logger(config)
        logger.debug("AIClient initialized with httpx.")

    async def get_ai_verdict(self, context_packet: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sends a context packet to the AI using a strict JSON schema for the response.
        Returns: {"action": str, "confidence": float, "reasoning": str}
        """
        # Static prompt to maximize caching
        prompt = """
        Analyze the provided market data for an ETH/USDT trade decision.
        - CTS Score: Compression Trap Sensor. High score (>0.8) indicates strong trend confirmation.
        - Orderbook Score: Market depth assessment. High score (>0.8) suggests strong support/resistance.
        - Reversal Likelihood Score: Probability of a price reversal.
        Primary goal is capital preservation. Only 'Execute' on high-probability setups.
        Return your decision as JSON with 'action', 'confidence', and 'reasoning'.
        """

        # JSON schema (cacheable)
        json_schema = {
            "name": "trading_decision",
            "schema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["Execute", "Abort", "Reanalyze"]
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0
                    },
                    "reasoning": {
                        "type": "string"
                    }
                },
                "required": ["action", "confidence", "reasoning"],
                "additionalProperties": True
            }
        }

        try:
            logger.debug("Requesting one-shot verdict from AI with JSON schema.")
            start_time = asyncio.get_event_loop().time()
            response = await self.client.post(
                f"{self.config.ai_provider_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.config.xai_api_key}"},
                json={
                    "model": "grok-4-fast-reasoning",
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": f"Market Data: {json.dumps(context_packet)}"}
                    ],
                    "max_completion_tokens": 600,  # Set to current value
                    "temperature": 0.2,
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": json_schema
                    },
                    "stream": False
                }
            )
            elapsed_ms = (asyncio.get_event_loop().time() - start_time) * 1000.0
            response.raise_for_status()

            # Log full raw response and token usage
            raw_response = response.text
            ai_strategy_logger.info(f"FULL RAW API RESPONSE: ---{raw_response}---")
            try:
                log_ai_decision(
                    self.model_logger,
                    {
                        "type": "latency",
                        "latency_ms": round(elapsed_ms, 2),
                        "context": context_packet,
                    }
                )
            except Exception:
                pass

            response_data = response.json()
            # Log token usage with caching
            token_usage = response_data.get("usage", {})
            cached_tokens = token_usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
            total_tokens = token_usage.get("total_tokens", 0)
            ai_strategy_logger.info(
                f"TOKEN USAGE: Prompt={token_usage.get('prompt_tokens', 0)}, "
                f"Completion={token_usage.get('completion_tokens', 0)}, "
                f"Total={total_tokens}, Cached={cached_tokens}"
            )

            # Warn if exceeding token limit
            if total_tokens > 2000:
                ai_strategy_logger.warning(f"Total tokens ({total_tokens}) exceeding target limit of 2000.")

            # Validate response structure
            if not response_data.get("choices") or not isinstance(response_data["choices"], list) or not response_data["choices"]:
                ai_strategy_logger.error("Invalid API response structure: No choices found.")
                return {
                    "action": "Reanalyze",
                    "confidence": 0.0,
                    "reasoning": "Invalid API response: No choices provided."
                }

            choice = response_data["choices"][0]
            finish_reason = choice.get("finish_reason")
            ai_strategy_logger.info(f"FINISH REASON: {finish_reason}")

            full_response_text = choice.get("message", {}).get("content", "")
            ai_strategy_logger.info(f"RAW AI RESPONSE RECEIVED: ---{full_response_text}---")

            if not full_response_text:
                # Fallback to context_packet-based heuristic
                verdict = self._fallback_from_context(context_packet)
                ai_strategy_logger.info("Fallback verdict from context_packet.")
                await self.memory_tracker.update_memory(
                    trade_data={"direction": context_packet.get("direction", "N/A"), "ai_verdict": verdict}
                )
                logger.debug("xAI verdict received via context fallback", extra=verdict)
                return verdict

            # Attempt to parse response
            verdict = json.loads(full_response_text)

            # Validate response structure
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
                try:
                    log_ai_decision(
                        self.model_logger,
                        {
                            "ts": response_data.get("created"),
                            "type": "api_verdict",
                            "context": context_packet,
                            "verdict": verdict,
                            "finish_reason": finish_reason,
                            "latency_ms": round(elapsed_ms, 2)
                        }
                    )
                except Exception:
                    pass
                logger.debug("xAI verdict received", extra=verdict)
                return verdict
            else:
                raise ValueError("Invalid response structure")

        except httpx.HTTPStatusError as e:
            ai_strategy_logger.error(f"AI API HTTP ERROR: Status {e.response.status_code} - Response: {e.response.text}")
            verdict = {
                "action": "Reanalyze",
                "confidence": 0.0,
                "reasoning": f"API HTTP error: {e.response.status_code} - {e.response.text}"
            }
            log_ai_decision(self.model_logger, {"type": "api_error", "context": context_packet, "verdict": verdict, "latency_ms": round(elapsed_ms, 2)})
            return verdict
        except (json.JSONDecodeError, KeyError, IndexError, ValueError) as e:
            ai_strategy_logger.error(f"AI VERDICT FAILED: {str(e)}. Full Response: {raw_response}")
            # Fallback to context_packet-based heuristic
            verdict = self._fallback_from_context(context_packet)
            ai_strategy_logger.info("Fallback verdict from context_packet.")
            await self.memory_tracker.update_memory(
                trade_data={"direction": context_packet.get("direction", "N/A"), "ai_verdict": verdict}
            )
            log_ai_decision(self.model_logger, {"type": "fallback", "context": context_packet, "verdict": verdict, "error": str(e), "latency_ms": round(elapsed_ms, 2)})
            logger.debug("xAI verdict received via context fallback", extra=verdict)
            return verdict
        except httpx.TimeoutException:
            ai_strategy_logger.error("AI VERDICT FAILED: Request Timed Out.")
            verdict = {
                "action": "Reanalyze",
                "confidence": 0.0,
                "reasoning": "AI request timed out."
            }
            log_ai_decision(self.model_logger, {"type": "timeout", "context": context_packet, "verdict": verdict, "latency_ms": round(elapsed_ms, 2)})
            return verdict
        except Exception as e:
            ai_strategy_logger.error(f"An unexpected error occurred in AIClient: {e}", exc_info=True)
            verdict = {
                "action": "Reanalyze",
                "confidence": 0.0,
                "reasoning": f"A general error occurred: {str(e)}"
            }
            log_ai_decision(self.model_logger, {"type": "error", "context": context_packet, "verdict": verdict, "latency_ms": round(elapsed_ms, 2)})
            return verdict

    def _fallback_from_context(self, context_packet: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a fallback verdict based on context_packet if API response is empty or invalid.
        """
        direction = context_packet.get("direction", "N/A").lower()
        open_price = context_packet.get("open", 0.0)
        close_price = context_packet.get("close", 0.0)
        volume = context_packet.get("volume", 0.0)
        reversal_likelihood_score = context_packet.get("reversal_likelihood_score", 0.0)
        cts_score = context_packet.get("cts_score", 0.0)
        orderbook_score = context_packet.get("orderbook_score", 0.0)

        # Heuristic with filter scores
        confidence = min(reversal_likelihood_score + cts_score + orderbook_score, 1.0) / 3.0
        if direction == "short":
            if close_price < open_price and volume > 0 and reversal_likelihood_score > 0.8 and cts_score > 0.8 and orderbook_score > 0.8:
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
        else:  # Long or unspecified
            if close_price > open_price and volume > 0 and reversal_likelihood_score > 0.8 and cts_score > 0.8 and orderbook_score > 0.8:
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
