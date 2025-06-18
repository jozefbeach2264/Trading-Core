class RiskAssessor:
    def __init__(self, capital, leverage, liquidation_threshold=10.0):
        self.capital = capital
        self.leverage = leverage
        self.liquidation_threshold = liquidation_threshold

    def assess_risk(self, entry_price, current_price, sl_price):
        buffer = abs(entry_price - sl_price)
        if buffer < self._liquidation_margin():
            return {
                "approved": False,
                "reason": "Stop loss too close. Breach risk.",
                "buffer": round(buffer, 4)
            }

        max_loss = self._project_loss(entry_price, sl_price)
        if max_loss > self.capital * 0.5:
            return {
                "approved": False,
                "reason": "Max loss exceeds 50% capital",
                "max_loss": round(max_loss, 4)
            }

        return {
            "approved": True,
            "buffer": round(buffer, 4),
            "max_loss": round(max_loss, 4)
        }

    def _project_loss(self, entry, stop):
        distance = abs(entry - stop)
        return distance * self.leverage

    def _liquidation_margin(self):
        return self.liquidation_threshold