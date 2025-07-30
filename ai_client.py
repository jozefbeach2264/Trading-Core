import logging
import json
import httpx
from typing import Dict, Any
from config.config import Config
from memory_tracker import MemoryTracker

logger = logging.getLogger(__name__)
ai_strategy_logger = logging.getLogger('AIStrategyLogger')

# Static prompt to maximize caching, strictly numerical, and probability-based
UNIFIED_BASE_PROMPT = """You are a high-frequency quant trading AI for ETH/USDT, returning a JSON object with numerical decisions based on statistical probabilities. For ENTRY: Evaluate provided live data and predict a 5-minute price forecast within ±$20 of the current price; return {'action': '✅ Execute'|'⛔ Abort'|'🔁 Reanalyze', 'confidence': float (0.0-1.0), 'forecast_price': float, 'reasoning': 'One-sentence statistical justification.'}. For EXIT: Assess open trade context; return {'action': 'HOLD'|'EXIT_PROFIT'|'EXIT_LOSS', 'reasoning': 'One-sentence statistical justification.'}. Use provided scores, avoid speculative outputs, and keep reasoning concise."""

class AIClient:
    def __init__(self, config: Config):
        self.config = config
        self.memory_tracker = MemoryTracker(config)
        self.client = httpx.AsyncClient(timeout=config.ai_client_timeout)
        logger.debug("AIClient initialized with httpx.")

    async def get_ai_verdict(self, context_packet: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handles ENTRY decision with numerical, constrained price forecast.
        """
        similar_scenarios = self.memory_tracker.get_similar_scenarios(context_packet)

        # Separate dynamic data to maximize caching
        data_payload = {
            "task": "ENTRY",
            "rules": "Use cts_score and orderbook_score as primary signals. Ensure forecast_price is within ±$20 of current close.",
            "historical_context": similar_scenarios,
            "live_data": context_packet
        }

        prompt = f"{UNIFIED_BASE_PROMPT}\n\nInput Data:\n{json.dumps(data_payload, indent=2)}"

        json_schema = {
            "name": "trading_decision",
            "schema": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["✅ Execute", "⛔ Abort", "🔁 Reanalyze"]},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "forecast_price": {"type": "number"},
                    "reasoning": {"type": "string"}
                },
                "required": ["action", "confidence", "forecast_price", "reasoning"]
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
                    "max_tokens": 1150,  # Reduced from 1536 to lower costs
                    "temperature": 0.2,
                    "response_format": {"type": "json_schema", "json_schema": json_schema}
                }
            )
            response.raise_for_status()
            response_data = response.json()
            verdict_str = response_data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
            verdict = json.loads(verdict_str)
            # Validate forecast_price within ±$20
            current_close = context_packet.get("close", 0.0)
            forecast_price = verdict.get("forecast_price", current_close)
            if abs(forecast_price - current_close) > 20:
                logger.warning(f"Invalid forecast_price {forecast_price}, adjusting to {current_close}.")
                verdict["forecast_price"] = current_close
            return verdict
        except Exception as e:
            logger.error(f"An error occurred in get_ai_verdict: {e}", exc_info=True)
            return {"action": "⛔ Abort", "confidence": 0.0, "forecast_price": context_packet.get("close", 0.0), "reasoning": "Error in AI verdict processing."}

    async def get_dynamic_exit_verdict(self, open_trade_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handles EXIT decision with numerical analysis.
        """
        data_payload = {
            "task": "EXIT",
            "rules": "Prioritize reversal_likelihood_score for exit decisions. Secure profit or minimize loss.",
            "open_trade_context": open_trade_context
        }

        prompt = f"{UNIFIED_BASE_PROMPT}\n\nInput Data:\n{json.dumps(data_payload, indent=2)}"

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