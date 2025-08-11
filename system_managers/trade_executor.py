import logging
from typing import Any, Dict, Optional

from config.config import Config
from data_managers.market_state import MarketState
from execution.simulation_account import SimulationAccount
from data_managers.trade_lifecycle_manager import TradeLifecycleManager
from memory_tracker import MemoryTracker

# PerformanceTracker is optional; don't crash if path changes
try:
    from tracking.performance_tracker import PerformanceTracker  # type: ignore
except Exception:  # pragma: no cover
    PerformanceTracker = Any  # type: ignore

logger = logging.getLogger(__name__)

class TradeExecutor:
    """
    Backward/forward compatible TradeExecutor.

    - Accepts both the old 2-arg signature (config, market_state) and the newer
      expanded dependency set used by main.py (http_client, TLM, memory_tracker,
      simulation_account, performance_tracker).
    - Does NOT remove any features you already rely on.
    - Writes trade entries/exits to MemoryTracker when they occur (AI-driven only).
    """

    def __init__(
        self,
        config: Config,
        market_state: MarketState,
        http_client: Any = None,
        trade_lifecycle_manager: Optional[TradeLifecycleManager] = None,
        memory_tracker: Optional[MemoryTracker] = None,
        simulation_account: Optional[SimulationAccount] = None,
        performance_tracker: Optional[PerformanceTracker] = None,
        ai_strategy: Any = None,  # optional pass-through if your engine provides it
    ):
        self.config = config
        self.market_state = market_state

        # Optional deps (preserve everything that might already be wired)
        self.http_client = http_client
        self.trade_lifecycle_manager = trade_lifecycle_manager
        self.memory_tracker = memory_tracker
        self.sim_account = simulation_account
        self.performance_tracker = performance_tracker
        self.ai_strategy = ai_strategy

        logger.info(
            "TradeExecutor ready. dry_run=%s, deps: http=%s, TLM=%s, MT=%s, SIM=%s, PERF=%s",
            getattr(self.config, "dry_run_mode", None),
            bool(self.http_client),
            bool(self.trade_lifecycle_manager),
            bool(self.memory_tracker),
            bool(self.sim_account),
            bool(self.performance_tracker),
        )

    async def initialize(self):
        logger.info("TradeExecutor initialized.")
        # no-op for now (kept for compatibility)

    async def execute_trade(self, trade_details: Dict[str, Any]) -> bool:
        """
        Executes/starts a trade (live or sim). Logs an entry to MemoryTracker.
        Called only after AI verdict == 'Execute' (so pre-AI denials never log).
        """
        if self.config.dry_run_mode:
            if not self.trade_lifecycle_manager:
                logger.warning("TLM missing; cannot start simulated trade.")
                return False

            logger.info(
                "Routing new simulated trade %s to TLM.",
                trade_details.get("trade_id")
            )
            await self.trade_lifecycle_manager.start_new_trade(
                trade_details.get("trade_id"),
                trade_details
            )

            # MEMORY LOG — entry
            mt = self._resolve_memory_tracker()
            if mt:
                try:
                    candle_ts = trade_details.get("candle_timestamp") or (
                        self.market_state.klines[0][0] if getattr(self.market_state, "klines", None) else None
                    )
                    ai_verdict = trade_details.get("ai_verdict", {}) or {}
                    await mt.update_memory(
                        trade_data={
                            "candle_timestamp": candle_ts,
                            "direction": trade_details.get("direction", "N/A"),
                            "quantity": float(trade_details.get("size") or trade_details.get("quantity") or 0.0),
                            "entry_price": float(trade_details.get("entry_price") or self.market_state.mark_price or 0.0),
                            "simulated": True,
                            "failed": False,
                            "reason": trade_details.get("reason", ""),
                            "order_data": trade_details.get("order_data", {}) or {},
                            "ai_verdict": ai_verdict,
                        }
                    )
                except Exception as e:
                    logger.error("TradeExecutor: failed to log entry to MemoryTracker", extra={"error": str(e)}, exc_info=True)
        else:
            logger.info("LIVE EXECUTION: Would place new trade %s.", trade_details.get("trade_id"))
            # If you log live entries too, call MT here in the same way.

        return True

    async def exit_trade(self, trade_id: str, exit_price: float, exit_reason: str = "") -> bool:
        """
        Closes a trade. Logs an exit event to MemoryTracker and pushes a summary
        to PerformanceTracker (if present).
        """
        if self.config.dry_run_mode:
            if not self.trade_lifecycle_manager or not self.sim_account:
                logger.warning("Missing TLM or SimulationAccount; cannot exit simulated trade.")
                return False

            trade = self.trade_lifecycle_manager.active_trades.get(trade_id)
            if not trade:
                logger.warning("Attempted to exit trade %s, but not found in TLM.", trade_id)
                return False

            pnl = self.sim_account.close_trade(trade_id, exit_price, trade.leverage)

            # ROI relative to margin used
            entry_value = trade.entry_price * trade.size
            roi_percent = (pnl / (entry_value / max(trade.leverage, 1))) * 100 if entry_value > 0 else 0.0

            # Performance tracker (optional)
            if self.performance_tracker:
                try:
                    self.performance_tracker.log_trade({
                        "trade_id": trade.trade_id,
                        "symbol": trade.symbol,
                        "direction": trade.direction,
                        "pnl": pnl,
                        "roi_percent": roi_percent,
                        "exit_reason": exit_reason,
                    })
                except Exception as e:
                    logger.error("PerformanceTracker log failed", extra={"error": str(e)}, exc_info=True)

            # Memory tracker — exit record
            mt = self._resolve_memory_tracker()
            if mt:
                try:
                    candle_ts = self.market_state.klines[0][0] if getattr(self.market_state, "klines", None) else None
                    await mt.update_memory(
                        trade_data={
                            "candle_timestamp": candle_ts,
                            "direction": "EXIT",
                            "quantity": 0.0,
                            "entry_price": float(exit_price or 0.0),
                            "simulated": True,
                            "failed": False,
                            "reason": exit_reason or "",
                            "order_data": {
                                "trade_id": trade.trade_id,
                                "exit": True,
                                "exit_reason": exit_reason,
                            },
                            "ai_verdict": {},
                        }
                    )
                except Exception as e:
                    logger.error("TradeExecutor: failed to log exit to MemoryTracker", extra={"error": str(e)}, exc_info=True)
        else:
            logger.info("LIVE EXECUTION: Would close trade %s.", trade_id)
            # Mirror the MemoryTracker insert here if you log live exits.

        return True

    # -------- helpers --------
    def _resolve_memory_tracker(self) -> Optional[MemoryTracker]:
        """
        Resolve a MemoryTracker instance from (priority):
          1) self.memory_tracker (explicitly injected)
          2) self.ai_strategy.memory_tracker (if executor was given ai_strategy)
          3) self.market_state.memory_tracker (if you stash it there)
        """
        if isinstance(self.memory_tracker, MemoryTracker):
            return self.memory_tracker
        try:
            mt = getattr(self.ai_strategy, "memory_tracker", None)
            if isinstance(mt, MemoryTracker):
                return mt
        except Exception:
            pass
        try:
            mt = getattr(self.market_state, "memory_tracker", None)
            if isinstance(mt, MemoryTracker):
                return mt
        except Exception:
            pass
        return None