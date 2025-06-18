from signal_interface import SignalInterface

if __name__ == "__main__":
    interface = SignalInterface()
    
    while True:
        try:
            entry = float(input("Enter entry price: "))
            exit = float(input("Enter exit price: "))
            interface.process_signal(entry_price=entry, exit_price=exit)
        except Exception as e:
            print(f"Error: {e}")