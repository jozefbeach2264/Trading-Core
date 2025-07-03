import logging
from typing import Dict, Any

from ai_client import AIClient
from validator_stack import ValidatorStack
from managers.market_state import MarketState

logger = logging.getLogger(__name__)

class AIStrategy:
    """
    Orchestrates the AI-Adjudicated Hybrid Strategy.
    This module's workflow is based directly on your Proprietary_Logic.docx.
    """
    def __init__(self, validator_stack: ValidatorStack, ai_client: AIClient):
        self.validator_stack = validator_stack
        self.ai_client = ai_client
        logger.info("AIStrategy initialized.")

    async def get_trade_decision(self, market_state: MarketState) -> Dict[str, Any]:
        """
        Submits the pre-analysis report to the AI model and returns the final trade decision.
        
        As per Proprietary_Logic.docx:
        - It does not contain its own analysis logic.
        - It calls the ValidatorStack to compile the report.
        - It communicates with AIClient to get the verdict.
        - It returns a standardized dictionary with "verdict", "confidence", and "reasoning".
        """
        
        # 1. Generate the comprehensive Pre-Analysis Report using ValidatorStack
        logger.info("Generating Pre-Analysis Report for AI...")
        pre_analysis_report = await self.validator_stack.generate_report(market_state)
        
        # 2. Send the report to the AI for a verdict using AIClient
        logger.info("Submitting report to AI for adjudication...")
        ai_response = await self.ai_client.get_ai_verdict(pre_analysis_report)
        
        # 3. Handle the response and return it in the specified format
        if not ai_response:
            logger.error("AI response was missing or invalid.")
            return {
                "verdict": "NO GO",
                "confidence": 0.0,
                "reasoning": "AI response missing or invalid"
            }

        # Your logic specified returning a dictionary with these keys.
        final_decision = {
            "verdict": ai_response.get("verdict", "NO GO"),
            "confidence": ai_response.get("confidence", 0.0),
            "reasoning": ai_response.get("reasoning", "No reasoning provided.")
        }
        
        logger.info(f"AI decision received: {final_decision['verdict']} (Confidence: {final_decision['confidence']})")
        return final_decision
