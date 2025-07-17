import logging
import json
import httpx
from typing import Dict, Any
from config.config import Config
from memory_tracker import MemoryTracker

logger = logging.getLogger(__name__)

class AIClient:
    def __init__(self, config: Config):
        self.config = config
        self.memory_tracker = MemoryTracker(config)
        self.client = httpx.AsyncClient(timeout=config.ai_client_timeout)
        logger.debug("AIClient initialized with httpx.")

    async def get_ai_verdict(self, context_packet: Dict[str, Any]) -> Dict[str, Any]:
        similar_scenarios = self.memory_tracker.get_similar_scenarios(context_packet)
        memory_summary = [
            f"Scenario {i+1}: Filter={s['filter']}, Score={s['score']}, Flag={s['flag']}, Metrics={s['metrics']}"
            for i, s in enumerate(similar_scenarios)
        ]

        prompt = f"""
        You are a trading analysis AI. Provide a final verdict on a trade signal.
        Response MUST be a JSON object with 'action', 'confidence', and 'reasoning'.
        - 'action': "✅ Execute", "⛔ Abort", or "🔁 Reanalyze".
        - 'confidence': Float between 0.0 and 1.0.
        - 'reasoning': Brief explanation.

        RULES:
        1. If any filter in 'validator_audit_log' has '❌ Block', action MUST be "⛔ Abort".
        2. Weigh '⚠️ Soft Flag' against passing filters; override if confidence > {self.config.ai_confidence_threshold}.
        3. Use 'rolling5_forecast' for risk assessment.
        4. Reference past scenarios: {memory_summary}

        Data packet:
        {json.dumps(context_packet, indent=2)}
        """

        try:
            logger.debug("Sending context packet to xAI API.")
            response = await self.client.post(
                f"{self.config.ai_provider_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.config.xai_api_key}"},
                json={
                    "model": "grok-3-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": True
                }
            )
            response.raise_for_status()

            full_response = ""
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    chunk = line[6:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        chunk_data = json.loads(chunk)
                        if chunk_data.get("choices", [{}])[0].get("delta", {}).get("content"):
                            full_response += chunk_data["choices"][0]["delta"]["content"]
                    except json.JSONDecodeError:
                        continue

            json_start = full_response.find('{')
            json_end = full_response.rfind('}') + 1
            if json_start == -1 or json_end == 0:
                logger.error("No JSON in xAI response: %s", full_response)
                return {"action": "⛔ Abort", "confidence": 0.0, "reasoning": "No JSON received."}

            json_string = full_response[json_start:json_end]
            verdict = json.loads(json_string)
            await self.memory_tracker.update_memory(trade_data={
                "direction": context_packet.get("direction", "N/A"),
                "ai_verdict": verdict,
                "order_data": context_packet.get("order_data", {})
            })
            logger.debug("xAI verdict: %s", verdict)
            return verdict

        except httpx.HTTPStatusError as e:
            logger.error("xAI API error: %s - %s", e.response.status_code, e.response.text)
            return {"action": "⛔ Abort", "confidence": 0.0, "reasoning": f"API error: {e.response.status_code}"}
        except json.JSONDecodeError:
            logger.error("Failed to parse xAI JSON: %s", json_string)
            return {"action": "⛔ Abort", "confidence": 0.0, "reasoning": "Invalid JSON from xAI."}
        except Exception as e:
            logger.error("xAI API error: %s", e, exc_info=True)
            return {"action": "⛔ Abort", "confidence": 0.0, "reasoning": "General API error."}

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
            suggestions["reasoning"] = "High success rate; loosening filter parameters."
        else:
            suggestions["reasoning"] = "Success rate too low to loosen parameters."

        logger.debug("Parameter suggestions: %s", suggestions)
        return suggestions

    async def close(self):
        await self.client.aclose()
        logger.debug("AIClient session closed.")