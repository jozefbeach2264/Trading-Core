import time
import hmac
import hashlib
import json
import logging
from typing import Dict, Any, Tuple
from decimal import Decimal, ROUND_DOWN
from datetime import datetime
import os

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
        
        tick_size = Decimal("0.01")
        step_size = Decimal("0.001")

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

        risk_amount_usd = Decimal(self.market_state.account_balance) * Decimal(self.config.risk_cap_percent)
        position_size_qty = risk_amount_usd / Decimal(self.market_state.mark_price)
        
        try:
            final_qty, _ = self._adjust_to_filters(position_size_qty, Decimal(self.market_state.mark_price))
        except ValueError as e:
            logger.error(f"Could not place order: {e}")
            return
            
        params = {
            "symbol": self.config.symbol,
            "side": alert.signal,
            "type": "MARKET",
            "quantity": f"{final_qty}",
            "timestamp": int(time.time() * 1000)
        }
        
        params['signature'] = self._get_signature(params)
        headers = {'X-MBX-APIKEY': self.config.asterdex_api_key}
        url = f"{self.base_url}/fapi/v1/order"

        try:
            response = await self.client.post(url, headers=headers, params=params)
            response.raise_for_status()
            logger.info(f"Successfully placed {alert.signal} order: {response.json()}")
        except httpx.HTTPStatusError as e:
            logger.error(f"Error placing order: {e.response.status_code} - {e.response.text}")

    def _get_simulation_state(self) -> Dict[str, Any]:
        """Loads the simulation state from file, or creates it if it doesn't exist."""
        path = self.config.simulation_state_file_path
        if not os.path.exists(path):
            logger.info(f"Simulation state file not found. Creating at {path}")
            state = {
                "balance": self.config.simulation_initial_capital,
                "positions": {},
                "history": []
            }
            return state
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error reading simulation state file: {e}. Starting fresh.")
            return {"balance": self.config.simulation_initial_capital, "positions": {}, "history": []}

    def _save_simulation_state(self, state: Dict[str, Any]):
        """Saves the updated simulation state to file."""
        path = self.config.simulation_state_file_path
        try:
            with open(path, 'w') as f:
                json.dump(state, f, indent=4)
        except IOError as e:
            logger.error(f"Could not save simulation state to file: {e}")

    async def _execute_simulated_trade(self, alert: 'TradeAlert'):
        """Simulates a trade and updates the simulation state file."""
        logger.info(f"Executing SIMULATED trade for {alert.signal} {self.config.symbol}")
        
        if self.market_state.mark_price is None:
            logger.error("Cannot simulate trade: Mark price is not available.")
            return

        state = self._get_simulation_state()
        entry_price = self.market_state.mark_price
        
        risk_amount_usd = Decimal(state['balance']) * Decimal(self.config.risk_cap_percent)
        position_size_qty = risk_amount_usd / Decimal(entry_price)

        fee = risk_amount_usd * Decimal(self.config.leverage) * Decimal(self.config.exchange_fee_rate_taker)
        
        state['balance'] -= float(fee)

        trade_record = {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": alert.symbol,
            "signal": alert.signal,
            "quantity": float(position_size_qty),
            "entry_price": entry_price,
            "fee": float(fee)
        }
        
        state['history'].append(trade_record)
        state['positions'][alert.symbol] = trade_record

        self._save_simulation_state(state)
        logger.info(f"SIMULATION: Trade recorded. New balance: {state['balance']:.2f}")

    async def execute_trade(self, alert: 'TradeAlert'):
        """Public method to execute a trade, switching between live and simulation."""
        logger.info(f"[AUTONOMOUS CYCLE] Trade execution requested: {alert.signal} | Mode: {'SIM' if self.config.dry_run_mode else 'LIVE'}")
        
        if self.config.dry_run_mode:
            await self._execute_simulated_trade(alert)
        else:
            await self._execute_live_trade(alert)