import logging
import json
import asyncio
from typing import Dict, Any

from openai import AsyncOpenAI, APIError

from config.config import Config

logger = logging.getLogger(__name__)

class AIClient:
    """
    Handles sending requests to the
    external AI provider and returning
    the adjudicated report using a
    streaming connection.
    """
    def __init__(self, config: Config):
        self.config = config
        
        try:
            self.client = AsyncOpenAI(
                api_key=self.config.ai_provider_api_key,
                base_url=self.config.ai_provider_url
            )
            logger.info(
                f"AIClient initialized for URL: {self.config.ai_provider_url}"
            )
        except Exception as e:
            logger.error(
                f"Failed to init OpenAI client: {e}",
                exc_info=True
            )
            self.client = None

    async def get_ai_verdict(
        self, report: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Sends the Pre-Analysis Report
        to the AI via a streaming request
        and assembles the full response.
        """
        if not self.client:
            return {
                "direction": "NONE",
                "reasoning": "AI Client not initialized."
            }
        
        # --- NEW: Explicit Prompt Engineering ---
        # This prompt gives the AI clear, non-negotiable instructions.
        prompt = f"""
        You are a trading analysis AI.
        Your response MUST be ONLY a single, raw JSON object and nothing else.
        Do not include markdown fences like ```json or any conversational text.
        The JSON object must include keys for 'direction', 'confidence', 'entry_price', 'take_profit', 'stop_loss', and 'reasoning'.

        Analyze the following pre-analysis trade report:
        {str(report)}
        """
            
        try:
            logger.info(
                "Sending report to AI via stream..."
            )

            stream = await self.client.chat.completions.create(
                model="grok-3",
                messages=[
                    {
                        "role": "user",
                        "content": prompt # Use the new, explicit prompt
                    }
                ],
                stream=True
            )

            full_response = ""
            async for chunk in stream:
                content = (
                    chunk.choices[0]
                    .delta.content
                )
                if content is not None:
                    full_response += content
            
            logger.info(
                "AI stream complete. Extracting JSON..."
            )
            
            json_start = full_response.find('{')
            json_end = full_response.rfind('}') + 1
            
            if json_start == -1 or json_end == 0:
                logger.error(
                    f"No JSON object found in AI response. Full response: {full_response}"
                )
                return {
                    "direction": "NONE",
                    "reasoning": "No JSON from AI."
                }
            
            json_string = full_response[json_start:json_end]
            return json.loads(json_string)
            
        except APIError as e:
            logger.error(f"OpenAI API Error: {e}")
            return {
                "direction": "NONE",
                "reasoning": "AI provider API error."
            }
        except json.JSONDecodeError as e:
            logger.error(
                f"Failed to parse AI JSON response: {json_string}",
                exc_info=True
            )
            return {
                "direction": "NONE",
                "reasoning": "Invalid JSON from AI."
            }
        except Exception as e:
            logger.error(
                f"Unexpected AI stream error: {e}",
                exc_info=True
            )
            return {
                "direction": "NONE",
                "reasoning": "General AI stream error."
            }

    async def close(self):
        """Closes the HTTP client."""
        if self.client:
            await self.client.close()
            logger.info(
                "AIClient session closed."
            )
