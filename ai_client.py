import os
import httpx
import logging
from typing import Dict, Any, Optional

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger(__name__)

# Assume the AI provider's URL and API Key are stored in secrets
AI_PROVIDER_URL = os.getenv("AI_PROVIDER_URL")
AI_PROVIDER_API_KEY = os.getenv("AI_PROVIDER_API_KEY")

async def send_to_ai(pre_analysis_report: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Sends the compiled Pre-Analysis Report to the external AI model for a final verdict.

    This function handles the secure communication, authentication, and error handling
    for the AI API call.

    Args:
        pre_analysis_report (Dict[str, Any]): The consolidated JSON report from all filters.

    Returns:
        Optional[Dict[str, Any]]: A dictionary containing the AI's verdict, confidence,
                                  and reasoning, or None if the request fails.
    """
    if not AI_PROVIDER_URL or not AI_PROVIDER_API_KEY:
        logger.error("AI_PROVIDER_URL or AI_PROVIDER_API_KEY is not set in environment secrets.")
        return None

    headers = {
        "Authorization": f"Bearer {AI_PROVIDER_API_KEY}",
        "Content-Type": "application/json"
    }

    # The prompt is structured to ask the AI to act as an expert adjudicator
    payload = {
        "model": "dan-expert-adjudicator-v1", # Example model name
        "prompt": "You are an expert trading supervisor. Based on the following pre-analysis report from your team of automated filters, provide a final verdict on whether to take this trade.",
        "report_data": pre_analysis_report,
        "response_format": {
            "verdict": "GO or NO GO",
            "confidence": "float (0.0 to 1.0)",
            "reasoning": "string"
        }
    }

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(AI_PROVIDER_URL, headers=headers, json=payload)
            response.raise_for_status()  # Raise an exception for non-2xx responses
            
            logger.info("Successfully received AI verdict.")
            return response.json()

    except httpx.RequestError as e:
        logger.error(f"AI API Request Error: Could not connect to {e.request.url}.")
        return None
    except httpx.HTTPStatusError as e:
        logger.error(f"AI API Status Error: Received status {e.response.status_code}. Response: {e.response.text}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred while communicating with the AI: {e}")
        return None

