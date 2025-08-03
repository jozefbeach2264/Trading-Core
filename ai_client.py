import logging
import json
import os
import httpx
from typing import Dict, Any
from config.config import Config
from memory_tracker import MemoryTracker

logger = logging.getLogger(__name__)
ai_strategy_logger = logging.getLogger('AIStrategyLogger')

# --- STATIC BASE PROMPT (Cacheable) ---
STATIC_BASE_PROMPT = """{
  "role": "system",
  "content": "You are a high-frequency quant trading AI for ETH/USDT. Analyze market data and return a JSON object with decisions: EXECUTE (initiate/continue trade), HOLD (wait/continue holding), EXIT (abandon/close trade)."
}"""

# --- ENTRY PROMPT TEMPLATE (Dynamic Part) ---
ENTRY_PROMPT_TEMPLATE = """{
  "role": "user",
  "content": "Analyze live market data for NEW TRADE ENTRY. Rules: High CtsFilter or OrderBookReversalZoneDetector scores favor EXECUTE. Low scores favor HOLD or EXIT. Historical Context: {historical_context}. Current Data: {current_data}",
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "trading_decision",
      "schema": {
        "type": "object",
        "properties": {
          "action": {"type": "string", "enum": ["EXECUTE", "HOLD", "EXIT"]},
          "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
          "reasoning": {"type": "string"}
        },
        "required": ["action", "confidence", "reasoning"]
      }
    }
  }
}"""

# --- EXIT PROMPT TEMPLATE (Dynamic Part) ---
EXIT_PROMPT_TEMPLATE = """{
  "role": "user",
  "content": "Analyze open trade for EXIT STRATEGY. Rules: Secure profit or minimize loss. High reversal_likelihood_score favors EXIT. Stable conditions favor HOLD. Strong continuation signals favor EXECUTE. Open Trade Context: {open_trade_context}",
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "exit_decision",
      "schema": {
        "type": "object",
        "properties": {
          "action": {"type": "string", "enum": ["EXECUTE", "HOLD", "EXIT"]},
          "reasoning": {"type": "string"}
        },
        "required": ["action", "reasoning"]
      }
    }
  }
}"""

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
        similar_scenarios = self.memory_tracker.get_similar_scenarios(context_packet)
        historical_context = json.dumps(similar_scenarios, separators=(',', ':'))
        current_data = json.dumps(context_packet, separators=(',', ':'))

        messages = [
            json.loads(STATIC_BASE_PROMPT),
            json.loads(ENTRY_PROMPT_TEMPLATE.format(
                historical_context=historical_context,
                current_data=current_data
            ))
        ]

        try:
            logger.debug("Requesting ENTRY verdict from AI.")
            response = await self.client.post(
                getattr(self.config, "ai_provider_url", "https://api.x.ai/v1"),
                headers={"Authorization": f"Bearer {self.config.xai_api_key}"},
                json={
                    "model": "grok-3-mini",
                    "messages": messages,
                    "max_tokens": 1536,
                    "temperature": 0.2
                }
            )
            response.raise_for_status()
            response_data = response.json()

            choice = response_data.get("choices", [{}])[0]
            verdict_str = choice.get("message", {}).get("content", "{}")
            usage = response_data.get("usage", {})

            self.ai_interaction_logger.info("[ENTRY RAW VERDICT] %s", verdict_str)
            self.ai_interaction_logger.info("[TOKENS USED] prompt=%s, completion=%s, total=%s",
                                           usage.get("prompt_tokens", "N/A"),
                                           usage.get("completion_tokens", "N/A"),
                                           usage.get("total_tokens", "N/A"))

            verdict = json.loads(verdict_str)
            verdict["token_usage"] = {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0)
            }
            return verdict
        except Exception as e:
            logger.error("An error occurred in get_ai_verdict: %s", e, exc_info=True)
            return {
                "action": "HOLD",
                "confidence": 0.0,
                "reasoning": "A general error occurred while contacting AI.",
                "token_usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0
                }
            }

    async def get_dynamic_exit_verdict(self, open_trade_context: Dict[str, Any]) -> Dict[str, Any]:
        open_trade_context_json = json.dumps(open_trade_context, separators=(',', ':'))
        messages = [
            json.loads(STATIC_BASE_PROMPT),
            json.loads(EXIT_PROMPT_TEMPLATE.format(
                open_trade_context=open_trade_context_json
            ))
        ]

        try:
            logger.debug("Requesting EXIT verdict from AI.")
            response = await self.client.post(
                getattr(self.config, "ai_provider_url", "https://api.x.ai/v1"),
                headers={"Authorization": f"Bearer {self.config.xai_api_key}"},
                json={
                    "model": "grok-3-mini",
                    "messages": messages,
                    "max_tokens": 256,
                    "temperature": 0.1
                }
            )
            response.raise_for_status()
            response_data = response.json()

            choice = response_data.get("choices", [{}])[0]
            verdict_str = choice.get("message", {}).get("content", "{}")
            usage = response_data.get("usage", {})

            self.ai_interaction_logger.info("[EXIT RAW VERDICT] %s", verdict_str)
            self.ai_interaction_logger.info("[TOKENS USED] prompt=%s, completion=%s, total=%s",
                                           usage.get("prompt_tokens", "N/A"),
                                           usage.get("completion_tokens", "N/A"),
                                           usage.get("total_tokens", "N/A"))

            verdict = json.loads(verdict_str)
            verdict["token_usage"] = {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0)
            }
            return verdict
        except Exception as e:
            logger.error("An error occurred in get_dynamic_exit_verdict: %s", e, exc_info=True)
            return {
                "action": "HOLD",
                "reasoning": "Error during exit analysis.",
                "token_usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0
                }
            }

    async def close(self):
        await self.client.aclose()
        logger.debug("AIClient httpx session closed.")