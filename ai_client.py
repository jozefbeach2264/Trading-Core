import logging
import json
from typing import Dict, Any

from xai_sdk import Client
from xai_sdk.chat import user

from config.config import Config

logger = logging.getLogger(__name__)

class AIClient:
    """
    Handles sending requests to the
    external AI provider (xAI Grok-3)
    and returning the adjudicated report
    using a streaming connection.
    """
    def __init__(self, config: Config):
        self.config = config

        try:
            self.client = Client(api_key=self.config.xai_api_key)
            logger.info("AIClient initialized with xAI SDK.")
        except Exception as e:
            logger.error(f"Failed to init xAI client: {e}", exc_info=True)
            self.client = None

    def get_ai_verdict(self, report: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sends the Pre-Analysis Report
        to Grok-3 via a streaming request
        and assembles the full response.
        """
        if not self.client:
            return {
                "direction": "NONE",
                "reasoning": "AI Client not initialized."
            }

        prompt = f"""
        You are a trading analysis AI.
        Your response MUST be ONLY a single, raw JSON object and nothing else.
        Do not include markdown fences like ```json or any conversational text.
        The JSON object must include keys for 'direction', 'confidence', 'entry_price', 'take_profit', 'stop_loss', and 'reasoning'.

        Analyze the following pre-analysis trade report:
        {str(report)}
        """

        try:
            logger.info("Sending report to xAI Grok-3 via stream...")

            chat = self.client.chat.create(model="grok-3")
            chat.append(user(prompt))

            full_response = ""
            for response, chunk in chat.stream():
                if chunk.content:
                    full_response += chunk.content

            logger.info("AI stream complete. Extracting JSON...")

            json_start = full_response.find('{')
            json_end = full_response.rfind('}') + 1

            if json_start == -1 or json_end == 0:
                logger.error(f"No JSON object found in AI response. Full response: {full_response}")
                return {
                    "direction": "NONE",
                    "reasoning": "No JSON from AI."
                }

            json_string = full_response[json_start:json_end]
            return json.loads(json_string)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI JSON response: {json_string}", exc_info=True)
            return {
                "direction": "NONE",
                "reasoning": "Invalid JSON from AI."
            }
        except Exception as e:
            logger.error(f"Unexpected AI stream error: {e}", exc_info=True)
            return {
                "direction": "NONE",
                "reasoning": "General AI stream error."
            }

    def close(self):
        logger.info("AIClient session complete.")