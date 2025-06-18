from rolling5_engine import Rolling5

class SignalInterface:
    def __init__(self):
        self.trader = Rolling5()

    def process_signal(self, entry_price, exit_price):
        result = self.trader.simulate_trade(entry_price=entry_price, exit_price=exit_price)
        self.display_result(result)

    def display_result(self, result):
        print(f"\n--- Trade Summary ---")
        print(f"Entry Price: {result['entry']}")
        print(f"Exit Price: {result['exit']}")
        print(f"ROI: {result['roi']}%")
        print(f"Net Profit: ${result['net_profit']}")
        print(f"Fee Paid: ${result['fee']}")
        print(f"New Balance: ${result['final_balance']}")
        print(f"----------------------\n")