import logging
import json
import os
import time
import hmac
import hashlib
from decimal import Decimal, ROUND_DOWN
from datetime import datetime
from typing import Dict, Any, Tuple

import httpx
from config.config import Config
from data_managers.market_state import MarketState
from memory_tracker import MemoryTracker

logger = logging.getLogger(__name__)

class TradeExecutor:
    def __init__(self, config: Config, market_state: MarketState, httpx_client: httpx.AsyncClient):
        self.config = config
        self.market_state = market_state
        self.client = httpx_client
        self.base_url = "https://fapi.asterdex.com"
        self.exchange_info: Dict[str, Any] = {}
        self.memory_tracker = MemoryTracker(config)
        logger.debug("TradeExecutor initialized for Asterdex.")

    async def initialize(self):
        try:
            url = f"{self.base_url}/fapi/v1/exchangeInfo"
            response = await self.client.get(url)
            response.raise_for_status()
            data = response.json()
            for symbol_data in data.get('symbols', []):
                if symbol_data['symbol'] == self.config.adex_symbol:
                    self.exchange_info = symbol_data
                    logger.debug(f"Exchange info fetched for {self.config.adex_symbol}")
                    return
            logger.error(f"Could not find exchange info for symbol {self.config.adex_symbol}")
        except Exception as e:
            logger.error(f"Failed to fetch exchange info: %s", e, exc_info=True)

    def _get_signature(self, params: Dict[str, Any]) -> str:
        query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
        return hmac.new(self.config.asterdex_api_secret.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()

    def _adjust_to_filters(self, qty: Decimal, price: Decimal) -> Tuple[Decimal, Decimal]:
        if not self.exchange_info:
            return Decimal(qty), Decimal(price)
        tick_size, step_size = Decimal("0.01"), Decimal("0.001")
        for f in self.exchange_info.get('filters', []):
            if f['filterType'] == 'PRICE_FILTER':
                tick_size = Decimal(f['tickSize'])
            elif f['filterType'] == 'LOT_SIZE':
                step_size = Decimal(f['stepSize'])
        return (qty // step_size) * step_size, (price // tick_size) * tick_size

    async def execute_trade(self, final_signal: Dict[str, Any]):
        mode = 'SIMULATION' if self.config.dry_run_mode else 'LIVE'
        direction = final_signal.get("direction", "N/A")
        logger.info(f"[AUTONOMOUS CYCLE] Trade execution requested: {direction} | Mode: {mode}")
        if self.config.dry_run_mode:
            await self._execute_simulated_trade(final_signal)
        else:
            await self._execute_live_trade(final_signal)

    async def _execute_live_trade(self, signal: Dict[str, Any]):
        direction = signal.get("direction")
        entry_price = self.market_state.mark_price
        if not all([self.market_state.account_balance, entry_price, direction]) or entry_price <= 0:
            logger.error("Live trade aborted: Missing or invalid data (balance=%s, entry_price=%s, direction=%s)",
                         self.market_state.account_balance, entry_price, direction)
            await self.memory_tracker.update_memory(trade_data={
                "direction": direction,
                "reason": "Missing or invalid data",
                "failed": True
            })
            return

        risk_amount_usd = Decimal(self.market_state.account_balance) * Decimal(self.config.risk_cap_percent)
        position_size_qty = risk_amount_usd / Decimal(entry_price)
        final_qty, _ = self._adjust_to_filters(position_size_qty, Decimal(entry_price))
            
        params = {
            "symbol": self.config.adex_symbol,
            "side": direction.upper(),
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
            trade_data = {
                "direction": direction,
                "quantity": float(final_qty),
                "entry_price": float(entry_price),
                "order": response.json()
            }
            await self.memory_tracker.update_memory(trade_data=trade_data)
            logger.info(f"Placed {direction} order: %s", response.json())
        except httpx.HTTPStatusError as e:
            logger.error(f"Order placement failed: %s - %s", e.response.status_code, e.response.text)
            await self.memory_tracker.update_memory(trade_data={
                "direction": direction,
                "reason": f"Order failed: {e.response.text}",
                "failed": True
            })

    def _get_simulation_state(self) -> Dict[str, Any]:
        path = self.config.simulation_state_file_path
        if not os.path.exists(path):
            return {"balance": self.config.simulation_initial_capital, "positions": {}, "history": []}
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading simulation state: %s", e)
            return {"balance": self.config.simulation_initial_capital, "positions": {}, "history": []}

    def _save_simulation_state(self, state: Dict[str, Any]):
        try:
            with open(self.config.simulation_state_file_path, 'w') as f:
                json.dump(state, f, indent=4)
        except IOError as e:
            logger.error(f"Could not save simulation state: %s", e)

    async def _execute_simulated_trade(self, signal: Dict[str, Any]):
        entry_price = self.market_state.mark_price
        if not entry_price or entry_price <= 0:
            logger.error("Simulation trade aborted: Invalid mark price: %s", entry_price)
            await self.memory_tracker.update_memory(trade_data={
                "direction": signal.get("direction", "N/A"),
                "reason": "Invalid mark price",
                "simulated": True,
                "failed": True
            })
            return
        state = self._get_simulation_state()
        risk_amount_usd = Decimal(state['balance']) * Decimal(self.config.risk_cap_percent)
        position_size_qty = risk_amount_usd / Decimal(entry_price)
        fee = risk_amount_usd * Decimal(self.config.leverage) * Decimal(self.config.exchange_fee_rate_taker)
        state['balance'] -= float(fee)
        trade_record = {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": self.config.adex_symbol,
            "signal_type": signal.get("trade_type", "N/A"),
            "direction": signal.get("direction"),
            "quantity": float(position_size_qty),
            "entry_price": entry_price,
            "fee": float(fee),
            "reasoning": signal.get("reason", "N/A"),
            "ai_verdict": signal.get("ai_verdict", {}),
            "simulated": True
        }
        state['history'].append(trade_record)
        state['positions'][self.config.adex_symbol] = trade_record
        self._save_simulation_state(state)
        await self.memory_tracker.update_memory(trade_data=trade_record)
        logger.debug(f"SIMULATION: {signal.get('direction')} trade recorded. Balance: {state['balance']:.2f}")