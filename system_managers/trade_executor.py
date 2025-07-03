import time
import hmac
import hashlib
import json
import logging
from typing import Dict, Any, Tuple  # <-- FIXED: Added Tuple
from decimal import Decimal, ROUND_DOWN
from datetime import datetime      # <-- ADDED: Missing import for simulation

import httpx
from config.config import Config
from data_managers.market_state import MarketState

logger = logging.getLogger(__name__)

class TradeExecutor:
    def __init__(self, config: Config, market_state: MarketState, httpx_client: httpx.AsyncClient):
        self.config = config
        self.market_state = market_state
        self.client = httpx_client
        self.base_url = "https://fapi.asterdex.com"
        self.exchange_info: Dict[str, Any] = {}

    async def initialize(self):
        """Fetches and caches exchange information needed for order placement."""
        try:
            url = f"{self.base_url}/fapi/v1/exchangeInfo"
            response = await self.client.get(url)
            response.raise_for_status()
            data = response.json()
            for symbol_data in data.get('symbols', []):
                if symbol_data['symbol'] == self.config.symbol:
                    self.exchange_info = symbol_data
                    logger.info(f"Successfully fetched exchange info for {self.config.symbol}")
                    return
            logger.error(f"Could not find exchange info for symbol {self.config.symbol}")
        except Exception as e:
            logger.error(f"Failed to fetch exchange info: {e}")

    def _get_signature(self, params: Dict[str, Any]) -> str:
        """Creates the HMAC-SHA256 signature for a signed request."""
        query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
        return hmac.new(self.config.asterdex_api_secret.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()

    def _adjust_to_filters(self, qty: Decimal, price: Decimal) -> Tuple[Decimal, Decimal]:
        """Adjusts quantity and price to conform to the exchange's filters."""
        if not self.exchange_info:
            raise ValueError("Exchange info not initialized.")
        
        tick_size = Decimal("0.01") # Default
        step_size = Decimal("0.001") # Default

        for f in self.exchange_info.get('filters', []):
            if f['filterType'] == 'PRICE_FILTER':
                tick_size = Decimal(f['tickSize'])
            elif f['filterType'] == 'LOT_SIZE':
                step_size = Decimal(f['stepSize'])

        adj_price = (price // tick_size) * tick_size
        adj_qty = (qty // step_size) * step_size
        return adj_qty, adj_price

    async def _execute_live_trade(self, alert: 'TradeAlert'):
        """Builds, signs, and sends a live order to the exchange."""
        logger.info(f"Executing LIVE trade for {alert.signal} {self.config.symbol}")
        
        if self.market_state.account_balance is None or self.market_state.mark_price is None:
            logger.error("Cannot execute live trade: Missing account balance or mark price.")
            return

        # 1. Calculate position size
        risk_amount_usd = Decimal(self.market_state.account_balance) * Decimal(self.config.risk_cap_percent)
        position_size_qty = risk_amount_usd / Decimal(self.market_state.mark_price)
        
        # 2. Adjust to exchange filters
        try:
            final_qty, _ = self._adjust_to_filters(position_size_qty, Decimal(self.market_state.mark_price))
        except ValueError as e:
            logger.error(f"Could not place order: {e}")
            return
            
        # 3. Prepare order payload
        params = {
            "symbol": self.config.symbol,
            "side": alert.signal,
            "type": "MARKET",
            "quantity": f"{final_qty:.3f}",
            "timestamp": int(time.time() * 1000)
        }
        
        # 4. Generate signature and send order
        params['signature'] = self._get_signature(params)
        headers = {'X-MBX-APIKEY': self.config.asterdex_api_key}
        url = f"{self.base_url}/fapi/v1/order"

        try:
            response = await self.client.post(url, headers=headers, params=params)
            response.raise_for_status()
            logger.info(f"Successfully placed {alert.signal} order: {response.json()}")
        except httpx.HTTPStatusError as e:
            logger.error(f"Error placing order: {e.response.status_code} - {e.response.text}")

    async def _execute_simulated_trade(self, alert: 'TradeAlert'):
        """Simulates a trade and updates the simulation state file."""
        logger.info(f"Executing SIMULATED trade for {alert.signal} {self.config.symbol}")
        
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "alert": alert.dict(),
            "message": "Simulated trade executed successfully."
        }
        logger.info(f"SIMULATION: {log_entry}")

    async def execute_trade(self, alert: 'TradeAlert'):
        """Public method to execute a trade, switching between live and simulation."""
        if self.config.dry_run_mode:
            await self._execute_simulated_trade(alert)
        else:
            await self._execute_live_trade(alert)

