from typing import Protocol, Dict, Any

class AIStrategyProtocol(Protocol):
    async def generate_signal(self, market_state: Any, validator_stack: Any) -> Dict[str, Any]:
        """
        Generates a trading signal based on market state and validator reports.
        """
        ...
