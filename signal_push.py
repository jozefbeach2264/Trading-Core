# signal_push.py (Core Side: Trading Reality Core)
import os
import logging
from aiohttp import ClientSession

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BOT_ENDPOINT = os.environ.get("BOT_ENDPOINT", "https://Telegram-Rolling5-Bot.jozefbeach2264.repl.co/signals")

async def push_signal(signal):
    """Push signal to Telegram bot."""
    auth_token = os.environ.get("HTTP_AUTH_TOKEN")
    headers = {"Authorization": f"Bearer {auth_token}"}
    async with ClientSession() as session:
        try:
            async with session.post(BOT_ENDPOINT, json=signal, headers=headers) as response:
                if response.status == 200:
                    logger.info(f"Signal {signal['signal_id']} pushed to bot")
                else:
                    logger.error(f"Failed to push signal: {response.status}")
        except Exception as e:
            logger.error(f"Error pushing signal: {e}")

async def push_alert(message):
    """Push alert to Telegram bot."""
    auth_token = os.environ.get("HTTP_AUTH_TOKEN")
    headers = {"Authorization": f"Bearer {auth_token}"}
    async with ClientSession() as session:
        try:
            async with session.post(BOT_ENDPOINT.replace("/signals", "/alerts"), json={"alerts": [message]}, headers=headers) as response:
                if response.status == 200:
                    logger.info(f"Alert pushed: {message}")
                else:
                    logger.error(f"Failed to push alert: {response.status}")
        except Exception as e:
            logger.error(f"Error pushing alert: {e}")