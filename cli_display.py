from core_loop import run_core_logic

def launch_cli():
    print("Starting core system loop...\n")
    while True:
        result = run_core_cycle()
        print(f"[{result['direction']}] Entry: {result['entry']} | Fill: {result['fill']} | Status: {result['status']}")