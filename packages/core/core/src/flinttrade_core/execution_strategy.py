"""Bind the existing StrategyRunner to an exact Paper run and canonical adapter.

Factories are trusted backend registrations, not uploaded HTTP code or strategy
names looked up in an active scheduler. No strategy gains Live qualification.
"""
from __future__ import annotations

import asyncio
import threading
from dataclasses import asdict
from typing import Any

from flinttrade_engine.scheduler import StrategyRunner
from flinttrade_engine.strategy import BaseStrategy
from flinttrade_engine.strategy_execution import StrategyExecutionMode

from .models import Order, Quote
from .practice_agent_adapter import PracticeAgentAdapter
from .practice_agent_runtime import _Run, _sandbox_flat


class _BoundStrategyRunner(StrategyRunner):
    """Keep the real lifecycle and callback leases; submit only via canonical ingress."""

    def __init__(self, owner: ExecutionStrategyOwner, strategy: BaseStrategy) -> None:
        self.owner = owner
        super().__init__(strategy, owner.run.adapter, scheduler=owner.app.config["TIME_SCHEDULER"],
                         symbol=owner.run.config["symbols"][0], tick_interval_seconds=owner.run.config["cycle_interval_sec"])

    async def _tick(self) -> None:
        owner, run = self.owner, self.owner.run
        try:
            if type(run.adapter) is not PracticeAgentAdapter:
                raise ValueError("canonical strategy adapter required")
            run.adapter.validate_session()
            if not self.scheduler.is_market_open(self.strategy.exchange, symbol=self.symbol):
                return
            data = await run.adapter.quotes(symbol=self.symbol, exchange=self.strategy.exchange)
            quote = Quote.model_validate({**data["data"], "symbol": self.symbol, "exchange": self.strategy.exchange})
            await self._invoke_strategy_callback(lambda: self.strategy.on_tick(quote))
            orders = await self._invoke_strategy_callback(self.strategy.generate_orders)
            if type(orders) is not list:
                raise ValueError("strategy intents unavailable")
            for order in orders:
                if (not isinstance(order, Order) or order.symbol != self.symbol
                        or str(order.exchange) != run.config["exchange"] or str(order.product) != run.config["product"]):
                    raise ValueError("strategy execution scope mismatch")
                quantity = int(order.quantity)
                with owner.execution_binding.fence():
                    positions = owner.sandbox.get_positions()
                    net = sum(row["net_qty"] for row in positions if row["symbol"] == order.symbol
                              and row["exchange"] == str(order.exchange) and row["product"] == str(order.product))
                    after = net + (quantity if str(order.action) == "BUY" else -quantity)
                    if abs(after) > abs(net) and abs(after) > run.config["max_position_size"]:
                        raise ValueError("strategy position limit")
                result = await run.adapter.route_order(order)
                if not result.passed:
                    owner.execution_binding.registry.retire_entries(owner.execution_binding.scope)
                    break
            self._tick_count += 1
        except Exception:
            owner.execution_binding.registry.retire_entries(owner.execution_binding.scope)


class ExecutionStrategyOwner:
    """Own one actual scheduled strategy, persisted run ledger and worker thread."""

    def __init__(self, app: Any, store: Any, *, execution_binding: Any) -> None:
        self.app, self.store, self.execution_binding = app, store, execution_binding
        self.sandbox = execution_binding.sandbox
        self.run: _Run | None = None
        self.runner: _BoundStrategyRunner | None = None
        self.strategy: BaseStrategy | None = None
        self._closed = False

    def start(self, token: str, owner: str, config: dict[str, Any], *, rearm: bool = False) -> None:
        scope = self.execution_binding.scope
        if owner != scope.actor or len(config["symbols"]) != 1:
            raise ValueError("exact single-instrument strategy scope required")
        factory = self.app.config.get("EXECUTION_STRATEGY_FACTORIES", {}).get(config["strategy"])
        if not callable(factory):
            raise ValueError("registered Paper strategy factory unavailable")
        strategy = factory(scope, dict(config))
        if not isinstance(strategy, BaseStrategy) or strategy.require_execution_contract().mode != StrategyExecutionMode.PRACTICE:
            raise ValueError("explicit Paper strategy execution contract required")
        if str(strategy.exchange) != config["exchange"] or str(strategy.product) != config["product"]:
            raise ValueError("strategy scope mismatch")
        with self.execution_binding.registry.lock:
            if any(getattr(other, "strategy", None) is strategy for other in self.execution_binding.registry.owners.values()):
                raise ValueError("strategy instance already owned by another run")
            strategy._strategy_id = scope.run_id
            strategy._injected_state_root = self.execution_binding.registry.path / scope.run_id / "strategy"
            self.strategy = strategy
        persisted = {**config, "owner": owner, "execution_session": asdict(scope)}
        if rearm:
            if self.store.get_run(scope.run_id)["config"] != persisted:
                raise ValueError("strategy configuration changed")
            row = self.store.rearm_execution(asdict(scope))
        else:
            row = self.store.create_run(run_id=scope.run_id, mode="practice", config=persisted)
        run = _Run(scope.run_id, owner, config, row["created_at"])
        self.run = run
        run.adapter = PracticeAgentAdapter(self.app, token, execution_binding=self.execution_binding,
            stop_check=lambda: not self.execution_binding.registry.status(scope)["entries_armed"],
            event_sink=lambda kind, data: self.store.append_event(scope.run_id, kind=kind, data=data))
        protection = self.app.config.get("PROTECTION_SERVICES")
        if protection is not None:
            run.adapter._protection_supervisor = self
            protection.attach(scope, self.store, run.adapter)
        self.runner = _BoundStrategyRunner(self, strategy)
        run.thread = threading.Thread(target=self._worker, name="paper-strategy-" + scope.run_id, daemon=True)
        run.thread.start()

    async def _close_positions(self) -> None:
        if self.run is None or type(self.run.adapter) is not PracticeAgentAdapter:
            raise ValueError("canonical strategy adapter required")
        # Explicit Close is a fixed reduction, never a fallback opening order.
        for position in self.sandbox.get_positions():
            quantity = position["net_qty"]
            if not quantity:
                continue
            order = Order(symbol=position["symbol"], exchange=position["exchange"], product=position["product"],
                          action="SELL" if quantity > 0 else "BUY", quantity=str(abs(quantity)), pricetype="MARKET")
            with self.run.adapter.protective_action():
                result = await self.run.adapter.route_order(order)
            if not result.passed:
                raise ValueError("strategy Close unresolved")
        if not _sandbox_flat(self.app, sandbox=self.sandbox):
            raise ValueError("strategy working orders or exposure remain")

    async def _loop(self) -> None:
        await self.runner.start()
        self.store.transition_run(self.run.run_id, status="running")
        try:
            while not self.run.stop.is_set():
                if self.run.close_requested.is_set():
                    await self._close_positions()
                    break
                await asyncio.to_thread(self.run.stop.wait, 0.25)
        finally:
            await self.runner.stop()

    def _worker(self) -> None:
        state = "stopped"
        with self.app.app_context():
            try:
                asyncio.run(self._loop())
            except BaseException:
                state = "reconciliation_required"
            finally:
                if not _sandbox_flat(self.app, sandbox=self.sandbox) or self.run.adapter.reconciliation_required:
                    state = "reconciliation_required"
                self.run.adapter.close()
                self.run.status = state
                try:
                    self.store.transition_run(self.run.run_id, status=state)
                    self.execution_binding.registry.observe(self.execution_binding.scope, state,
                        uncertain=self.run.adapter.reconciliation_required)
                    self.run.cleanup_complete = True
                except Exception:
                    self.run.evidence_failed = True

    def shutdown(self, timeout: float) -> bool:
        if self._closed:
            return True
        if self.run is not None:
            self.run.stop.set()
            if self.run.thread is not None:
                self.run.thread.join(max(0, timeout))
                if self.run.thread.is_alive():
                    return False
            if self.run.evidence_failed or self.run.status == "reconciliation_required":
                return False
        return True
