from core_loop import run_core_cycle
from cli_display import display_status_info
from status_info import display_status_info as status_debug
from core_socket_client import start_core_socket  # NEW: socket communication

def main():
    print("[SYSTEM] Starting simulation + socket bridge...")
    start_core_socket()  # <-- Non-blocking socket listener
    display_status_info()
    status_debug()

    for _ in range(3):  # simulate 3 core loop cycles
        result = run_core_cycle()
        print(f"[RESULT] {result}")

if __name__ == "__main__":
    main()