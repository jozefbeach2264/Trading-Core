# TradingCore/config.py
import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    def __init__(self):
        self.api_key = os.getenv("API_KEY")
        self.secret_key = os.getenv("SECRET_KEY")
        self.uid = os.getenv("UID")
        # The WebSocket URL for NeuroSync
        self.neurosync_ws_url = os.getenv("NEUROSYNC_WS_URL")
        # The HTTP URL to send notifications to the bot
        self.bot_notify_url = os.getenv("BOT_NOTIFY_URL")
