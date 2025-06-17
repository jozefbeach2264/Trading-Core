
from core_loop import run_core_cycle
from status_info import display_status_info  # now from new file

def launch_cli():
    print("Starting core system loop...\n")
    display_status_info()
    while True:
        result = run_core_cycle()
        print(f"[{result['direction']}] Entry: {result['entry']}")