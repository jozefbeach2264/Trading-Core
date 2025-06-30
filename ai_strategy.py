import logging
from typing import Dict, Any

from .ai_client import send_to_ai
from .validator_stack import ValidatorStack
from .market_state import MarketState

logger = logging.getLogger(__name__)

class AIStrategy:
    """
    This class orchestrates the AI-Adjudicated Hybrid Strategy.
    It uses the ValidatorStack to compile a report, sends it to the external AI
    via the ai_client, and makes the final trade decision.
    """
    def __init__(self):
        self.validator = ValidatorStack()
        logger.info("AIStrategy orchestrator initialized.")

    async def get_trade_decision(self, market_state: MarketState) -> Dict[str, Any]:
        """
        Executes the full analysis pipeline to get a final trade decision.

        Args:
            market_state (MarketState): The current state of the market.

        Returns:
            Dict[str, Any]: The final verdict from the AI.
        """
        # 1. Get the complete data snapshot
        signal_data = market_state.get_signal_data()
        
        # 2. Generate the Pre-Analysis Report from all filters
        pre_analysis_report = await self.validator.generate_report(signal_data)
        
        # 3. Submit the report to the AI model for a final verdict
        logger.info("Submitting Pre-Analysis Report to AI...")
        ai_response = await send_to_ai(pre_analysis_report)

        # 4. Process the AI's response
        if not ai_response or 'verdict' not in ai_response:
            logger.error("AI response was missing or invalid.")
            return {
                "verdict": "NO GO",
                "confidence": 0.0,
                "reason": "AI response missing or invalid"
            }

        logger.info(f"AI Verdict Received: {ai_response.get('verdict')} with confidence {ai_response.get('confidence')}")
        
        return {
            "verdict": ai_response.get("verdict", "NO GO"),
            "confidence": ai_response.get("confidence", 0.0),
            "reasoning": ai_response.get("reasoning", "No reasoning provided.")
        }

