"""Bounded decision workers owned by the existing execution-session registry.

Strategies emit proposals; only NativeAutonomy can reserve and dispatch them.
A server registration is not qualification, permission, or a running worker.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from flinttrade_engine.strategy import BaseStrategy
from flinttrade_engine.strategy_execution import StrategyExecutionContract, StrategyExecutionMode

from .models import Order, Quote
from .native_autonomy_contracts_v2 import ProducerPinV2
from .native_financial_v2 import primitive_copy, reference


class ThresholdEntryStrategy(BaseStrategy):
    """Emit one fixed limit proposal when a fresh mark reaches its threshold.

    This is a read-only strategy at the engine seam. Its order is a proposal,
    never a broker capability; the native command owner performs all admission.
    """

    supported_execution_modes = frozenset({StrategyExecutionMode.READ_ONLY})

    def __init__(self, order: dict[str, Any], threshold: str) -> None:
        self.order = Order.model_validate(order)
        self.threshold = Fraction(threshold)
        if self.threshold <= 0 or self.order.pricetype != "LIMIT":
            raise ValueError("positive threshold and limit order required")
        self._quote: Quote | None = None
        self._emitted = False
        super().__init__("bounded-threshold", exchange=str(self.order.exchange), product=str(self.order.product),
                         execution_contract=StrategyExecutionContract.read_only())
        self.require_execution_contract()

    def on_tick(self, quote: Quote) -> None:
        """Accept only the registered instrument's current observed mark."""
        if quote.symbol != self.order.symbol or str(quote.exchange) != str(self.order.exchange):
            raise ValueError("strategy quote scope changed")
        self._quote = quote

    def on_bar(self, bar: Any) -> None:
        """Refuse bars because this producer requires an explicit quote observation.

        Args:
            bar: Bar observation that is deliberately unsupported by this quote-only producer.

        Raises:
            ValueError: Always: bars cannot drive this threshold producer.
        """
        raise ValueError("threshold producer requires a quote, not a bar")

    def on_signal(self, signal: dict[str, Any]) -> None:
        """Refuse external signals as a source of producer authority.

        Args:
            signal: External signal that must not authorise this producer.

        Raises:
            ValueError: Always: external signals cannot authorise this producer.
        """
        raise ValueError("external signals cannot authorise this producer")

    def generate_orders(self) -> list[Order]:
        """Generate at most one proposal; no replay on subsequent observations."""
        if self._emitted or self._quote is None:
            return []
        mark = Fraction(str(self._quote.ltp))
        eligible = mark <= self.threshold if self.order.action == "BUY" else mark >= self.threshold
        if not eligible:
            return []
        self._emitted = True
        return [self.order]


@dataclass(frozen=True)
class ProducerRegistration:
    """Exact server-owned source/config selection, not an authority DTO."""

    pin: dict[str, Any]
    order: dict[str, Any]
    threshold: str
    interval_ms: int
    max_decisions: int
    model_binding: dict[str, Any] | None = None

    @classmethod
    def model_entry(cls, *, name: str, order: dict[str, Any], threshold: str,
                    interval_ms: int, max_decisions: int, binding: dict[str, Any],
                    model_pin: dict[str, Any]) -> ProducerRegistration:
        """Bind the existing model task dispatcher, not a callback or client DTO."""
        base = cls.threshold_entry(name=name, order=order, threshold=threshold,
                                   interval_ms=interval_ms, max_decisions=max_decisions)
        configuration = {"strategy": base.pin["config_revision"], "binding": binding, "model": model_pin}
        pin = ProducerPinV2.model_validate({
            "kind": "model", "producer_ref": reference(name, [base.pin["source_revision"], configuration]),
            "source_revision": base.pin["source_revision"],
            "config_revision": reference("config", configuration)["revision"], "model": model_pin,
        }).model_dump(mode="json")
        return cls(pin, base.order, threshold, interval_ms, max_decisions, primitive_copy(binding))

    @classmethod
    def threshold_entry(cls, *, name: str, order: dict[str, Any], threshold: str,
                        interval_ms: int, max_decisions: int) -> ProducerRegistration:
        """Register a real finite deterministic strategy without starting it."""
        from hashlib import sha256
        from pathlib import Path

        if (type(interval_ms) is not int or interval_ms <= 0
                or type(max_decisions) is not int or not 0 < max_decisions <= 1000):
            raise ValueError("explicit finite decision schedule required")
        typed = Order.model_validate(order)
        canonical = typed.model_dump(mode="json")
        ThresholdEntryStrategy(canonical, threshold)
        source = sha256(Path(__file__).read_bytes()).hexdigest()
        configuration = {"order": canonical, "threshold": threshold, "interval_ms": interval_ms,
                         "max_decisions": max_decisions}
        pin = ProducerPinV2.model_validate({
            "kind": "deterministic", "producer_ref": reference(name, [source, configuration]),
            "source_revision": source, "config_revision": reference("config", configuration)["revision"],
            "model": None,
        }).model_dump(mode="json")
        return cls(pin, canonical, threshold, interval_ms, max_decisions)

    def require_current(self) -> None:
        """Recheck the actual implementation and immutable registration content."""
        if self.model_binding is None:
            expected = self.threshold_entry(name=self.pin["producer_ref"]["id"], order=self.order,
                                            threshold=self.threshold, interval_ms=self.interval_ms,
                                            max_decisions=self.max_decisions)
        else:
            expected = self.model_entry(name=self.pin["producer_ref"]["id"], order=self.order,
                                        threshold=self.threshold, interval_ms=self.interval_ms,
                                        max_decisions=self.max_decisions, binding=self.model_binding,
                                        model_pin=self.pin["model"])
        if expected != self:
            raise ValueError("registered producer source or configuration changed")


class NativeProducerOwner:
    """One retained thread; stopping admission never discards an in-flight call."""

    def __init__(self, workflow: Any, row: dict[str, Any], registration: ProducerRegistration) -> None:
        self.workflow = workflow
        self.scope = workflow.registry.scope(row["binding"]["run_id"], row["operator"])
        self.registration = registration
        self.strategy = ThresholdEntryStrategy(registration.order, registration.threshold)
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None
        self.completed = threading.Event()
        self.failed = False
        self.decisions = 0
        remaining = row["grant_v2"]["expires_at_ms"] - int(time.time() * 1000)
        self.deadline = time.monotonic() + max(0, min(remaining, row["grant_v2"]["limits"]["max_duration_ms"])) / 1000

    def start(self) -> None:
        """Start the acquired exact worker once, with no automatic rearm."""
        if self.thread is not None:
            raise ValueError("producer already started")
        self.thread = threading.Thread(target=self._worker, name="native-producer-" + self.scope.run_id, daemon=True)
        self.thread.start()

    def _worker(self) -> None:
        with self.workflow.app.app_context():
            self._decide()

    def _decide(self) -> None:
        try:
            self.strategy.start()
            for index in range(self.registration.max_decisions):
                if self.stop.is_set():
                    break
                self.registration.require_current()
                quote = self.workflow.producer_observation(self)
                self.strategy.on_tick(quote)
                proposed = (self.registration.model_binding is None
                            or self.workflow.model_decision(self, index, quote))
                orders = self.strategy.generate_orders() if proposed else []
                self.decisions += 1
                self.workflow.record_decision(self, index, len(orders))
                for order in orders:
                    self.workflow.submit_proposal(self, index, order)
                pause = min(self.registration.interval_ms / 1000, max(0, self.deadline - time.monotonic()))
                if orders or self.stop.wait(pause):
                    break
        except Exception:
            self.failed = True
        finally:
            self.strategy.stop()
            try:
                self.workflow.producer_finished(self)
            finally:
                self.completed.set()

    def shutdown(self, timeout: float) -> bool:
        """Retry only this owner; an external call remains owned until it returns."""
        self.stop.set()
        if self.thread is not None:
            self.thread.join(max(0, timeout))
            return not self.thread.is_alive() and self.completed.is_set()
        return True

    def snapshot(self) -> dict[str, Any]:
        """Read actual worker activity, independently of persistent entry state."""
        return {"decisions": self.decisions, "alive": bool(self.thread and self.thread.is_alive()),
                "completed": self.completed.is_set(), "failed": self.failed,
                "pin": primitive_copy(self.registration.pin)}
