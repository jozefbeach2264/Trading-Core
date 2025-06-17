# main.py

import sys
from env_loader import load_env # Ensure environment variables are loaded

from secret_loader import validate_secrets # Ensure secrets are loaded and validated

from connection_validator import validate_connection
from status_monitor import start_status_monitor
from receiver_module import start_receiver
from orderbook_reader import start_feed
from core_loop import run_core_cycle
from cli_display import display_status_info
from log_writer import init_logging
from trade_executor import prepare_trade_executor
from scheduler import start_scheduler
from network_bridge import initialize_network_bridge

BASE_URL = "https://fapi.asterdex.com"

def boot_sequence():
    print("Initializing Trading Reality Core...")
    
    load_env()
    validate_secrets()
    
    print("Validating Asterdex connection...")
    if not validate_connection(BASE_URL):
        print("❌ Asterdex connection failed. Aborting launch.")
        sys.exit(1)

    print("✅ Asterdex connection confirmed. Booting subsystems...\n")
    init_logging()
    start_status_monitor()
    start_receiver()
    start_feed()
    prepare_trade_executor()
    start_scheduler()
    initialize_network_bridge()
    display_status()
    run_core_logic()

if __name__ == "__main__":
    boot_sequence()