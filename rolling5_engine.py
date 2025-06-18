import time import random from decimal import Decimal from core_initializer import CoreSystemConfig

class Rolling5: def init(self): self.config = CoreSystemConfig() self.balance = self.config.balance self.trade_log = []

def calculate_fee(self, amount):
    return (self.config.trade_fee_percent / Decimal("100")) * amount

def simulate_trade(self, entry_price: float, exit_price: float):
    if self.balance <= 0:
        print("[Rolling5] Balance hit 0. nitializing to $10.00")
        self.balance = self.config.initial_balance

    capital = self.balance
    position_size = capital * self.config.leverage
    price_move = Decimal(exit_price) - Decimal(entry_price)
    roi_decimal = (price_move / Decimal(entry_price)) * self.config.leverage

    gross_profit = capital * roi_decimal
    fee = self.calculate_fee(capital + gross_profit)
    net_profit = gross_profit - fee
    final_balance = capital + net_profit

    if final_balance < 0:
        print("[Rolling5] Liquidated. Resetting balance.")
        final_balance = self.config.initial_balance

    self.balance = final_balance if self.config.reinvest else self.balance

    trade_record = {
        "entry": entry_price,
        "exit": exit_price,
        "roi": round(roi_decimal * 100, 2),
        "fee": round(fee, 4),
        "net_profit": round(net_profit, 4),
        "final_balance": round(self.balance, 4),
    }
    self.trade_log.append(trade_record)
    self.config.save_trade_log(self.trade_log)

    print(f"[Rolling5] Entry: {entry_price}, Exit: {exit_price}, ROI: {roi_decimal * 100:.2f}%, Fee: {fee:.4f}, Balance: {self.balance:.4f}")
    return trade_record

def get_balance(self):
    return round(self.balance, 4)

def get_trade_log(self):
    return self.trade_log