
import logging

def handle_failure(error_msg):
    logging.basicConfig(level=logging.ERROR)
    logging.error(f"FAILOVER TRIGGERED: {error_msg}")