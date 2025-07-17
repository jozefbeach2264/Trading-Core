import logging
import os
from typing import Dict, Any, Optional

from config.config import Config
from data_managers.market_state import MarketState
from strategy.trade_module_trapx import TradeModuleTrapX
from strategy.trade_module_scalpel import TradeModuleScalpel

logger = logging.getLogger(__name__)

class StrategyRouter:
    def __init__(self, config: Config):
        self.config = config
        self.trapx_module = TradeModuleTrapX(config)
        self.scalpel_module = TradeModuleScalpel(config)
        self.force_module = os.getenv('FORCE_MODULE', 'NONE').upper()
        self.default_strategy = os.getenv('DEFAULT_STRATEGY', 'TRAPX').upper()
        logger.info(f"StrategyRouter initialized. Default: {self.default_strategy}, Force: {self.force_module}")

    async def route_and_generate_signal(self, market_state: MarketState, validator_report: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if self.force_module == 'TRAPX': return await self.trapx_module.generate_signal(market_state)
        if self.force_module == 'SCALPEL': return await self.scalpel_module.generate_signal(market_state)
        retest_report = validator_report.get("filters", {}).get("RetestEntryLogic", {})
        if retest_report.get("flag") == "fallback_strategy: Scalpel": return await self.scalpel_module.generate_signal(market_state)
        cts_report = validator_report.get("filters", {}).get("CtsFilter", {})
        if cts_report.get("score", 1.0) < 0.75: return await self.trapx_module.generate_signal(market_state)
        breakout_report = validator_report.get("filters", {}).get("BreakoutZoneOriginFilter", {})
        if breakout_report.get("score", 0.0) >= 0.75: return await self.scalpel_module.generate_signal(market_state)
        if self.default_strategy == 'SCALPEL': return await self.scalpel_module.generate_signal(market_state)
        else: return await self.trapx_module.generate_signal(market_state)
