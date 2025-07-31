import logging
import json
import re
import httpx
from typing import Dict, Any
from config.config import Config
from memory_tracker import MemoryTracker

logger = logging.getLogger(__name__)
ai_strategy_logger = logging.getLogger('AIStrategyLogger')

# --- NEW UNIFIED BASE PROMPT ---
# This single, static prompt defines the AI's core mission to maximize caching.
UNIFIED_BASE_PROMPT = """You are a high-frequency quant trading analysis AI for ETH/USDT. Your sole purpose is to execute, maintain, and exit trades for maximum profitability by capturing as much favorable market movement as possible. Your sole function is to return a valid JSON object."""

class AIClient:
    def __init__(self, config: Config):
        self.config = config
        self.memory_tracker = MemoryTracker(config)
        self.client = httpx.AsyncClient(timeout=config.ai_client_timeout)
        logger.debug("AIClient initialized with httpx.")

    async def get_ai_verdict(self, context_packet: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handles the ENTRY decision by appending task-specific instructions to the unified prompt.
        """
        similar_scenarios = self.memory_tracker.get_similar_scenarios(context_packet)

        # --- FIX: Appends specific task and data to the unified base prompt ---
        prompt = f"""
        {UNIFIED_BASE_PROMPT}

        TASK: Analyze the following live market data for a potential NEW TRADE ENTRY.
        RULES: A high score for CtsFilter or OrderBookReversalZoneDetector is a strong signal.

        Historical Context:
        {json.dumps(similar_scenarios, indent=2)}

        Current Live Data:
        {json.dumps(context_packet, indent=2)}
        """

        json_schema = {
            "name": "trading_decision",
            "schema": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["✅ Execute", "⛔ Abort", "🔁 Reanalyze"]},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "reasoning": {"type": "string"}
                },
                "required": ["action", "confidence", "reasoning"]
            }
        }

        try:
            logger.debug("Requesting ENTRY verdict from AI.")
            response = await self.client.post(
                f"{self.config.ai_provider_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.config.xai_api_key}"},
                json={
                    "model": "grok-3-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 1536,
                    "temperature": 0.2,
                    "response_format": {"type": "json_schema", "json_schema": json_schema}
                }
            )
            response.raise_for_status()
            response_data = response.json()
            verdict_str = response_data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
            return json.loads(verdict_str)
        except Exception as e:
            logger.error(f"An error occurred in get_ai_verdict: {e}", exc_info=True)
            return {"action": "⛔ Abort", "confidence": 0.0, "reasoning": "A general error occurred while contacting AI."}

    async def get_dynamic_exit_verdict(self, open_trade_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handles the EXIT decision by appending task-specific instructions to the unified prompt.
        """
        # --- FIX: Appends specific task and data to the unified base prompt ---
        prompt = f"""
        {UNIFIED_BASE_PROMPT}

        TASK: Analyze the following OPEN TRADE and determine the optimal exit strategy.
        RULES: The primary goal is to secure profit or minimize loss. A high 'reversal_likelihood_score' is a strong signal to exit.

        Open Trade Context:
        {json.dumps(open_trade_context, indent=2)}
        """

        json_schema = {
            "name": "exit_decision",
            "schema": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["HOLD", "EXIT_PROFIT", "EXIT_LOSS"]},
                    "reasoning": {"type": "string"}
                },
                "required": ["action", "reasoning"]
            }
        }

        try:
            logger.debug("Requesting EXIT verdict from AI.")
            response = await self.client.post(
                f"{self.config.ai_provider_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.config.xai_api_key}"},
                json={
                    "model": "grok-3-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 256,
                    "temperature": 0.1,
                    "response_format": {"type": "json_schema", "json_schema": json_schema}
                }
            )
            response.raise_for_status()
            response_data = response.json()
            verdict_str = response_data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
            return json.loads(verdict_str)
        except Exception as e:
            logger.error(f"An error occurred in get_dynamic_exit_verdict: {e}", exc_info=True)
            return {"action": "HOLD", "reasoning": "Error during exit analysis."}

    async def close(self):
        await self.client.aclose()
        logger.debug("AIClient httpx session closed.")
