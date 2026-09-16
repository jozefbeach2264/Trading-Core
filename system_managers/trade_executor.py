import asyncio
import logging
import json
import os
import time
import hmac
import hashlib
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple

import httpx
from config.config import Config
from data_managers.market_state import MarketState
from memory_tracker import MemoryTracker
from sim_stats import compute_stats, summary_line

logger = logging.getLogger(__name__)

def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


ORDER_TIMEOUT_S = 5.0  # a market order that has not answered in 5 s is not going to get faster
ORDER_SIDE = {"LONG": "BUY", "SHORT": "SELL"}       # Binance-style /fapi order side enum
CLOSE_SIDE = {"LONG": "SELL", "SHORT": "BUY"}
BALANCE_REFRESH_EVERY_PINGS = 1                    # refresh the balance on every keep-alive tick

class TradeExecutor:
    def __init__(self, config: Config, market_state: MarketState, httpx_client: httpx.AsyncClient):
        self.config = config
        self.market_state = market_state
        self.client = httpx_client
        self.base_url = self.config.asterdex_base_url
        self.exchange_info: Dict[str, Any] = {}
        self.memory_tracker = MemoryTracker(config)
        self._keepalive_task = None
        self.open_position: Optional[Dict[str, Any]] = None
        logger.debug("TradeExecutor initialized for Asterdex.")

    async def initialize(self):
        if self.config.dry_run_mode:
            logger.info("Dry run mode enabled. Skipping Asterdex exchange info initialization.")
            return
        await self._fetch_exchange_info()
        await self._fetch_balance()
        await self._set_leverage()
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())

    async def _keepalive_loop(self):
        """Keep the exchange TLS session warm so a live order reuses the pooled connection
        instead of paying connect + handshake (~100-300 ms) at the moment it matters, and
        refresh the account balance the sizing depends on."""
        url = f"{self.base_url}/fapi/v1/ping"
        while True:
            await asyncio.sleep(self.config.exchange_keepalive_seconds)
            try:
                await self.client.get(url, timeout=5.0)
            except Exception as e:
                logger.debug("Exchange keep-alive ping failed: %r", e)
            await self._fetch_balance()

    def _signed_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        signed = {**params, "timestamp": int(time.time() * 1000)}
        signed["signature"] = self._get_signature(signed)
        return signed

    def _auth_headers(self) -> Dict[str, str]:
        return {'X-MBX-APIKEY': self.config.asterdex_api_key}

    async def _fetch_balance(self) -> None:
        """GET /fapi/v2/balance → available USDT. Never populated before 2026-09-16: every live order
        aborted at the 'Missing or invalid data' guard, so live trading had never actually worked."""
        url = f"{self.base_url}/fapi/v2/balance"
        try:
            response = await self.client.get(url, headers=self._auth_headers(), params=self._signed_params({}), timeout=5.0)
            response.raise_for_status()
            rows = response.json()
            quote = self.config.adex_symbol[-4:] if self.config.adex_symbol.endswith("USDT") else "USDT"
            for row in rows if isinstance(rows, list) else []:
                if row.get("asset") == quote:
                    self.market_state.account_balance = float(row.get("availableBalance", row.get("balance", 0.0)))
                    logger.debug("Account balance: %s %s", self.market_state.account_balance, quote)
                    return
            logger.error("Balance response had no %s row: %s", quote, str(rows)[:300])
        except Exception as e:
            logger.error("Balance fetch failed (sizing will refuse to trade until it succeeds): %r", e)

    async def _set_leverage(self) -> None:
        """Opt-in (EXCHANGE_SET_LEVERAGE): push config LEVERAGE to the exchange, otherwise the account's
        stored leverage governs liquidation distance while the config number is decorative."""
        if not self.config.exchange_set_leverage:
            logger.warning("EXCHANGE_SET_LEVERAGE is off: the leverage stored on the exchange account governs risk, "
                           "not LEVERAGE=%s.", self.config.leverage)
            return
        url = f"{self.base_url}/fapi/v1/leverage"
        try:
            params = self._signed_params({"symbol": self.config.adex_symbol, "leverage": self.config.leverage})
            response = await self.client.post(url, headers=self._auth_headers(), params=params, timeout=5.0)
            response.raise_for_status()
            logger.info("Exchange leverage set: %s", response.text[:200])
        except Exception as e:
            logger.error("Setting leverage failed: %r", e)

    async def close(self):
        task = getattr(self, "_keepalive_task", None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            self._keepalive_task = None

    async def _fetch_exchange_info(self):
        try:
            url = f"{self.base_url}/fapi/v1/exchangeInfo"
            response = await self.client.get(url, timeout=15.0)
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

    def position_size(self, balance: float, entry_price: float, stop_loss: Optional[float]) -> Dict[str, Any]:
        """Size by RISK: the position is chosen so that hitting the stop costs RISK_PER_TRADE_PERCENT of the
        account, then the margin is capped at RISK_CAP_PERCENT (the operator's 10% rule) — so a wide stop means
        a smaller position rather than a bigger loss. Falls back to the cap when no stop is known."""
        cap_margin = balance * self.config.risk_cap_percent
        risk_pct = self.config.risk_per_trade_percent
        stop_distance = abs(entry_price - float(stop_loss)) if stop_loss else 0.0
        if risk_pct <= 0 or stop_distance <= 0 or entry_price <= 0:
            margin, mode = cap_margin, "margin_cap"
        else:
            risk_amount = balance * risk_pct / 100.0
            notional = risk_amount * entry_price / stop_distance     # loss at the stop == risk_amount
            margin = notional / self.config.leverage
            mode = "risk_based"
            if margin > cap_margin:
                margin, mode = cap_margin, "risk_based_capped"
        notional = margin * self.config.leverage
        return {"margin": margin, "notional": notional, "quantity": notional / entry_price if entry_price > 0 else 0.0,
                "sizing_mode": mode,
                "risk_at_stop": notional * stop_distance / entry_price if entry_price > 0 else 0.0}

    async def _record_failure(self, direction: Any, reason: str) -> None:
        logger.error("Live trade aborted: %s", reason)
        await self.memory_tracker.update_memory(trade_data={"direction": direction, "reason": reason, "failed": True})

    def _check_order_filters(self, qty: Decimal, price: Decimal) -> str:
        """'' when the order passes LOT_SIZE / MIN_NOTIONAL, else the reason it would be rejected."""
        if qty <= 0:
            return f"Quantity {qty} is below the step size (balance too small for RISK_CAP_PERCENT at this price)"
        for f in self.exchange_info.get('filters', []):
            if f.get('filterType') == 'LOT_SIZE' and Decimal(str(f.get('minQty', '0'))) > qty:
                return f"Quantity {qty} below minQty {f['minQty']}"
            if f.get('filterType') == 'MIN_NOTIONAL' and Decimal(str(f.get('notional', '0'))) > qty * price:
                return f"Notional {qty * price:.2f} below MIN_NOTIONAL {f['notional']}"
        return ""

    async def close_position(self, mark_price: Any, reason: str) -> None:
        """Close the tracked position. Simulation realises PnL at the mark price. Live mode sends a
        reduce-only MARKET order on the opposite side; if that fails the guard is still cleared and the
        operator is told loudly, because a position with no exit is worse than a duplicate close."""
        if self.config.dry_run_mode:
            await asyncio.to_thread(self._close_simulated_position, mark_price, reason)
            return
        position = self.open_position
        self.open_position = None
        if not position:
            return
        params = self._signed_params({
            "symbol": self.config.adex_symbol,
            "side": CLOSE_SIDE[position["direction"].upper()],
            "type": "MARKET",
            "quantity": f"{Decimal(str(position['quantity'])).normalize():f}",
            "reduceOnly": "true",
        })
        try:
            response = await self.client.post(f"{self.base_url}/fapi/v1/order", headers=self._auth_headers(),
                                              params=params, timeout=ORDER_TIMEOUT_S)
            response.raise_for_status()
            logger.info("Closed %s position (%s): %s", position["direction"], reason, response.text[:200])
        except Exception as e:
            logger.critical("CLOSE ORDER FAILED for %s position (%s): %r — CHECK THE EXCHANGE MANUALLY",
                            position["direction"], reason, e)

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

        side = ORDER_SIDE.get(str(direction).upper())
        if side is None:
            await self._record_failure(direction, f"Unknown direction {direction!r}")
            return
        if not self.exchange_info:
            # Without LOT_SIZE/PRICE_FILTER the quantity cannot be rounded; an unrounded Decimal is rejected
            # by the exchange on every cycle (-1111 precision).
            await self._record_failure(direction, "Exchange filters unknown (exchangeInfo fetch failed)")
            return

        # Same math as the simulation: risk-based, capped at RISK_CAP_PERCENT of the account.
        sizing = self.position_size(float(self.market_state.account_balance), float(entry_price), _as_float(signal.get("stop_loss")))
        position_size_qty = Decimal(str(sizing["quantity"]))
        logger.info("Sizing (%s): balance=%s margin=%.2f notional=%.2f at %sx, loss at stop %.2f",
                    sizing["sizing_mode"], self.market_state.account_balance, sizing["margin"], sizing["notional"],
                    self.config.leverage, sizing["risk_at_stop"])
        final_qty, _ = self._adjust_to_filters(position_size_qty, Decimal(str(entry_price)))
        rejection = self._check_order_filters(final_qty, Decimal(str(entry_price)))
        if rejection:
            await self._record_failure(direction, rejection)
            return

        params = self._signed_params({
            "symbol": self.config.adex_symbol,
            "side": side,
            "type": "MARKET",
            "quantity": f"{final_qty.normalize():f}",
        })
        headers = self._auth_headers()
        url = f"{self.base_url}/fapi/v1/order"

        try:
            response = await self.client.post(url, headers=headers, params=params, timeout=ORDER_TIMEOUT_S)
            response.raise_for_status()
            try:
                order = response.json()
            except ValueError:
                order = {"raw": response.text[:500], "note": "non-JSON 2xx body"}
            trade_data = {
                "direction": direction,
                "quantity": float(final_qty),
                "entry_price": float(entry_price),
                "order_data": order,   # key must match memory_tracker._trade_row
            }
            self.open_position = {"direction": direction, "quantity": float(final_qty), "entry_price": float(entry_price),
                                  "opened_at": time.time(), "order_data": order}
            await self.memory_tracker.update_memory(trade_data=trade_data)
            logger.info(f"Placed {direction} ({side}) order: %s", order)
        except httpx.HTTPStatusError as e:
            logger.error(f"Order placement failed: %s - %s", e.response.status_code, e.response.text)
            await self.memory_tracker.update_memory(trade_data={
                "direction": direction,
                "reason": f"Order failed: {e.response.text}",
                "failed": True
            })
        except httpx.HTTPError as e:
            # Timeout / connect / protocol error. The order MAY have reached the exchange: log loudly and
            # record it as failed rather than letting the exception stall the engine for 60 s.
            logger.error("Order request errored (fill state UNKNOWN — check the exchange): %r", e)
            await self.memory_tracker.update_memory(trade_data={
                "direction": direction,
                "reason": f"Order transport error: {e!r}",
                "failed": True
            })

    def _get_simulation_state(self) -> Dict[str, Any]:
        path = self.config.simulation_state_file_path
        if not os.path.exists(path):
            return {"balance": self.config.simulation_initial_capital, "initial_capital": self.config.simulation_initial_capital,
                    "positions": {}, "history": []}
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
                "direction": signal.get("direction", "N/A"), "reason": "Invalid mark price", "simulated": True, "failed": True})
            return
        record = await asyncio.to_thread(self._open_simulated_position, signal, float(entry_price))
        if record is None:
            await self.memory_tracker.update_memory(trade_data={
                "direction": signal.get("direction", "N/A"), "reason": "Simulated balance exhausted", "simulated": True, "failed": True})
            return
        await self.memory_tracker.update_memory(trade_data=record)
        logger.debug("SIMULATION: %s trade recorded at %.2f", signal.get("direction"), entry_price)

    def _open_simulated_position(self, signal: Dict[str, Any], entry_price: float) -> Optional[Dict[str, Any]]:
        """Margin = balance × RISK_CAP_PERCENT; notional = margin × LEVERAGE; fee = notional × taker % / 100.
        (The old fee used 0.08 as a fraction — 8% — which sent a $10 account to -$30 on its first trade.)
        The strategy's stop_loss / take_profit and the liquidation price are stored so mark_to_market can
        close the position the way an exchange would."""
        state = self._get_simulation_state()
        balance = float(state["balance"])
        if balance <= 0:
            logger.error("SIMULATION: balance %.2f exhausted; refusing to open a position", balance)
            return None
        existing = (state.get("positions") or {}).get(self.config.adex_symbol)
        if existing:
            # Never silently overwrite: the old record's fee was already charged and its outcome would be lost.
            logger.error("SIMULATION: a %s position from %s is still open; refusing to open another",
                         existing.get("direction"), existing.get("timestamp"))
            return None
        direction = str(signal.get("direction", "")).upper()
        sign = 1.0 if direction == "LONG" else -1.0
        sizing = self.position_size(balance, entry_price, _as_float(signal.get("stop_loss")))
        margin, notional, quantity = sizing["margin"], sizing["notional"], sizing["quantity"]
        if quantity <= 0:
            logger.error("SIMULATION: computed a zero position size; refusing to open")
            return None
        fee = notional * self.config.exchange_fee_rate_taker / 100.0
        state["balance"] = balance - fee
        # Liquidation ≈ the move that consumes the whole margin (maintenance margin ignored → slightly optimistic).
        liquidation_price = entry_price * (1.0 - sign / self.config.leverage)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "open",
            "symbol": self.config.adex_symbol,
            "signal_type": signal.get("trade_type", "N/A"),
            "direction": direction,
            "quantity": quantity,
            "entry_price": entry_price,
            "margin": margin,
            "notional": notional,
            "sizing_mode": sizing["sizing_mode"],
            "risk_at_stop": sizing["risk_at_stop"],
            "fee": fee,
            "stop_loss": _as_float(signal.get("stop_loss")),
            "take_profit": _as_float(signal.get("take_profit")),
            "initial_risk": abs(entry_price - _as_float(signal.get("stop_loss"))) if _as_float(signal.get("stop_loss")) else None,
            "best_price": entry_price,
            "worst_price": entry_price,
            "opened_at": datetime.now(timezone.utc).timestamp(),
            "liquidation_price": liquidation_price,
            "reasoning": signal.get("signal_reason") or signal.get("reason", "N/A"),
            "ai_verdict": signal.get("ai_verdict", {}),
            "context_packet": signal.get("context_packet", {}),
            "filter_snapshot": signal.get("filter_snapshot", {}),
            "simulated": True,
        }
        state["history"].append(record)
        state["positions"][self.config.adex_symbol] = record
        self._save_simulation_state(state)
        return record

    @staticmethod
    def _exit_trigger(position: Dict[str, Any], mark_price: float) -> Optional[Tuple[float, str]]:
        """(fill price, reason) if the mark has crossed liquidation, stop-loss or take-profit; else None.
        Liquidation is checked first (worst case wins), then the stop, then the target."""
        sign = 1.0 if str(position.get("direction", "")).upper() == "LONG" else -1.0
        adverse = lambda level: level is not None and sign * (mark_price - level) <= 0   # mark at/beyond the level, against us
        favourable = lambda level: level is not None and sign * (mark_price - level) >= 0
        if adverse(position.get("liquidation_price")):
            return float(position["liquidation_price"]), "LIQUIDATION"
        if adverse(position.get("stop_loss")):
            return float(position["stop_loss"]), "STOP_LOSS"
        if favourable(position.get("take_profit")):
            return float(position["take_profit"]), "TAKE_PROFIT"
        return None

    async def recover_open_position(self) -> Optional[Dict[str, Any]]:
        """Called at start-up. A position survives a restart in the simulation state file, but the Rolling5
        lifecycle that manages it lives only in memory — so without this the engine believes it is flat and the
        next trade overwrites the record, losing an already-charged fee and an unrealised outcome (observed
        2026-09-16: the 11:25:49 SHORT was orphaned by the 11:30 restart)."""
        position = await self.get_open_position()
        if position:
            logger.warning("Recovered an open %s position from %s at %s — resuming management of it",
                           position.get("direction"), position.get("timestamp"), position.get("entry_price"))
        return position

    async def get_open_position(self) -> Optional[Dict[str, Any]]:
        """The open position record (simulation: from the state file; live: in memory), or None."""
        if self.config.dry_run_mode:
            state = await asyncio.to_thread(self._get_simulation_state)
            return (state.get("positions") or {}).get(self.config.adex_symbol)
        return self.open_position

    async def update_position_exits(self, stop_loss: Optional[float], take_profit: Optional[float],
                                    best_price: Optional[float] = None, note: str = "") -> None:
        """Rolling5 management writes the new levels. Simulation: into the state file (mark_to_market honours
        them next cycle). Live: in memory + a log line — amending exchange-side orders is not wired yet."""
        if self.config.dry_run_mode:
            await asyncio.to_thread(self._update_sim_exits, stop_loss, take_profit, best_price, note)
            return
        if self.open_position is not None:
            self.open_position.update({"stop_loss": stop_loss, "take_profit": take_profit, "best_price": best_price})
            logger.info("Position exits updated (live, in memory only): stop=%s target=%s %s", stop_loss, take_profit, note)

    def _update_sim_exits(self, stop_loss, take_profit, best_price, note: str) -> None:
        state = self._get_simulation_state()
        position = (state.get("positions") or {}).get(self.config.adex_symbol)
        if not position:
            return
        position["stop_loss"], position["take_profit"] = stop_loss, take_profit
        if best_price is not None:
            position["best_price"] = best_price
        position.setdefault("adjustments", []).append({"ts": datetime.now(timezone.utc).isoformat(), "stop": stop_loss,
                                                        "target": take_profit, "note": note})
        self._save_simulation_state(state)
        logger.info("SIMULATION: exits updated stop=%s target=%s (%s)", stop_loss, take_profit, note)

    async def mark_to_market(self, mark_price: Any) -> bool:
        """Simulation: close the open position if the mark crossed its liquidation / stop / target level.
        Returns True when a position was closed. Live mode returns False (exchange-side SL/TP orders are an
        operator decision not yet wired)."""
        if not self.config.dry_run_mode or not mark_price or float(mark_price) <= 0:
            return False
        return await asyncio.to_thread(self._mark_to_market_sim, float(mark_price))

    def _mark_to_market_sim(self, mark_price: float) -> bool:
        state = self._get_simulation_state()
        position = state["positions"].get(self.config.adex_symbol)
        if not position:
            return False
        # Excursion tracking: how far price went FOR (best) and AGAINST (worst) the trade while it was open.
        sign = 1.0 if str(position.get("direction", "")).upper() == "LONG" else -1.0
        best, worst = position.get("best_price", mark_price), position.get("worst_price", mark_price)
        position["best_price"] = max(best, mark_price) if sign > 0 else min(best, mark_price)
        position["worst_price"] = min(worst, mark_price) if sign > 0 else max(worst, mark_price)
        trigger = self._exit_trigger(position, mark_price)
        if trigger is None:
            if (position["best_price"], position["worst_price"]) != (best, worst):
                self._save_simulation_state(state)
            return False
        fill_price, reason = trigger
        self._close_simulated_position(fill_price, reason, state=state)
        return True

    def _close_simulated_position(self, mark_price: Any, reason: str, state: Optional[Dict[str, Any]] = None) -> None:
        state = state if state is not None else self._get_simulation_state()
        position = state["positions"].pop(self.config.adex_symbol, None)
        if not position or not mark_price or float(mark_price) <= 0:
            return
        exit_price = float(mark_price)
        sign = 1.0 if str(position.get("direction", "")).upper() == "LONG" else -1.0
        pnl = (exit_price - float(position["entry_price"])) * float(position["quantity"]) * sign
        if reason == "LIQUIDATION":
            pnl = -float(position.get("margin", abs(pnl)))   # the whole margin is gone, never more
        fee = float(position.get("notional", 0.0)) * self.config.exchange_fee_rate_taker / 100.0
        state["balance"] = float(state["balance"]) + pnl - fee
        entry = float(position["entry_price"])
        best = float(position.get("best_price", entry)); worst = float(position.get("worst_price", entry))
        opened_at = float(position.get("opened_at") or 0.0)
        state["history"].append({
            "timestamp": datetime.now(timezone.utc).isoformat(), "symbol": self.config.adex_symbol, "event": "close",
            "direction": position.get("direction"), "entry_price": entry, "exit_price": exit_price,
            "quantity": position["quantity"], "pnl": pnl, "fee": fee, "reason": reason, "simulated": True,
            # trade-quality fields: excursions in % of entry, duration, and what the trade was taken on
            "mfe_pct": round(sign * (best - entry) / entry * 100, 4),
            "mae_pct": round(sign * (worst - entry) / entry * 100, 4),
            "duration_s": round(datetime.now(timezone.utc).timestamp() - opened_at, 1) if opened_at else None,
            "signal_type": position.get("signal_type"),
            "ai_confidence": (position.get("ai_verdict") or {}).get("confidence"),
            "context_packet": position.get("context_packet", {}),
            "filter_snapshot": position.get("filter_snapshot", {}),
            "adjustments": len(position.get("adjustments") or []),
        })
        state.setdefault("initial_capital", self.config.simulation_initial_capital)
        stats = compute_stats(state["history"], float(state["initial_capital"]))
        state["stats"] = stats
        self._save_simulation_state(state)
        logger.info("SIMULATION: closed %s at %.2f (%s) pnl=%.4f fee=%.4f balance=%.4f | %s",
                    position.get("direction"), exit_price, reason, pnl, fee, state["balance"], summary_line(stats))
