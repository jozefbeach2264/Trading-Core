import os
import json
from decimal import Decimal

class CoreSystemConfig:
    def __init__(self):
        self.balance = Decimal("10.00")
        self.initial_balance = Decimal("10.00")
        self.reinvest = True
        self.leverage = Decimal("250")
        self.liquidation_threshold = Decimal("10.00")
        self.trade_fee_percent = Decimal("0.34")
        self.trade_log_path = "logs/trade_log.json"
        self.ensure_log_directory()

    def ensure_log_directory(self):
        os.makedirs(os.path.dirname(self.trade_log_path), exist_ok=True)

    def save_trade_log(self, log):
        with open(self.trade_log_path, 'w') as file:
            json.dump(log, file, indent=4)