import logging
import json
import re
import httpx
from typing import Dict, Any
from config.config import Config
from memory_tracker import MemoryTracker

logger = logging.getLogger(__name__)

class AIClient:
    def __init__(self, config: Config):
        self.config = config
        self.memory_tracker = MemoryTracker(config)
        self.client = httpx.AsyncClient(timeout=self.config.ai_client_timeout)
        logger.debug("AIClient initialized with httpx.")

    async def get_ai_verdict(self, context_packet: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sends a context packet to the AI and gets a final verdict.
        Now features a robust regex-based JSON extraction method.
        """
        similar_scenarios = self.memory_tracker.get_similar_scenarios(context_packet)
        memory_summary = [
            f"Scenario {i+1}: Filter={s['filter']}, Score={s['score']}, Flag={s['flag']}, Metrics={s['metrics']}"
            for i, s in enumerate(similar_scenarios)
        ]

        prompt = f"""
        You are an automated trading analysis bot. Your sole function is to return a valid JSON object.
        Do not provide any conversational text, markdown, or any characters outside of the JSON structure.

        Your response MUST be a single, raw JSON object with the following structure:
        - "action": A string, either "✅ Execute", "⛔ Abort", or "🔁 Reanalyze".
        - "confidence": A float between 0.0 and 1.0.
        - "reasoning": A brief, clear explanation for your decision.

        RULES:
        1. If any filter in the 'validator_audit_log' has a '❌ Block' flag, the action MUST be "⛔ Abort".
        2. Weigh '⚠️ Soft Flag's against passing filters. Override soft flags only if your confidence is high (e.g., > {self.config.ai_confidence_threshold}).
        3. Use the 'rolling5_forecast' to assess forward-looking risk. A high 'reversal_likelihood_score' is a major red flag.
        4. Reference past scenarios for context: {memory_summary}

        DATA PACKET:
        {json.dumps(context_packet, indent=2)}

        Your response must be ONLY the raw JSON object and nothing else.
        """

        full_response_text = ""
        try:
            logger.debug("Sending context packet to xAI API.")
            response = await self.client.post(
                f"{self.config.ai_provider_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.config.xai_api_key}"},
                json={
                    "model": "grok-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": True,
                    "max_tokens": 512,
                    "response_format": {"type": "json_object"}
                }
            )
            response.raise_for_status()

            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    chunk = line[6:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        chunk_data = json.loads(chunk)
                        if chunk_data.get("choices", [{}])[0].get("delta", {}).get("content"):
                            full_response_text += chunk_data["choices"][0]["delta"]["content"]
                    except json.JSONDecodeError:
                        continue
            
            # --- Robust JSON Extraction using Regex ---
            # This pattern finds a JSON object even if it's embedded in other text.
            match = re.search(r'\{.*\}', full_response_text, re.DOTALL)
            if not match:
                logger.error("No JSON object found in xAI response: %s", full_response_text)
                return {"action": "⛔ Abort", "confidence": 0.0, "reasoning": "No JSON object received from AI."}

            json_string = match.group(0)
            verdict = json.loads(json_string)
            
            await self.memory_tracker.update_memory(trade_data={
                "direction": context_packet.get("direction", "N/A"),
                "ai_verdict": verdict,
                "order_data": context_packet.get("order_data", {})
            })
            logger.debug("xAI verdict received", extra=verdict)
            return verdict

        except httpx.HTTPStatusError as e:
            logger.error("xAI API HTTP error: %s - %s", e.response.status_code, e.response.text)
            return {"action": "⛔ Abort", "confidence": 0.0, "reasoning": f"API HTTP error: {e.response.status_code}"}
        except json.JSONDecodeError:
            logger.error("Failed to parse JSON from xAI response: %s", full_response_text)
            return {"action": "⛔ Abort", "confidence": 0.0, "reasoning": "Invalid JSON format received from AI."}
        except Exception as e:
            logger.error("An unexpected error occurred in AIClient: %s", e, exc_info=True)
            return {"action": "⛔ Abort", "confidence": 0.0, "reasoning": "A general error occurred while contacting AI."}

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
