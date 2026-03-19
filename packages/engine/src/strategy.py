"""Base strategy interface and strategy registry.

All user strategies inherit from BaseStrategy. The StrategyRegistry manages
discovery, enabling/disabling, and lifecycle.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote

logger = logging.getLogger("flinttrade.engine.strategy")


# ---------------------------------------------------------------------------
# Strategy state machine
# ---------------------------------------------------------------------------


class StrategyState(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


# ---------------------------------------------------------------------------
# BaseStrategy — abstract class all strategies inherit from
# ---------------------------------------------------------------------------


class BaseStrategy(ABC):
    """Abstract base for all FlintTrade strategies.

    Subclasses must implement:
    - on_tick(quote)  — called on every LTP/quote update
    - on_bar(bar)     — called on every OHLCV bar close
    - on_signal(signal) — called when an external signal arrives (webhook, etc.)
    - generate_orders() — returns list of Order objects to submit

    Lifecycle: STOPPED → ACTIVE ↔ PAUSED → STOPPED
                                  ↘ ERROR
    """

    def __init__(self, name: str, exchange: str = "NSE", product: str = "MIS") -> None:
        self.name = name
        self.exchange = exchange
        self.product = product
        self._state = StrategyState.STOPPED
        self._error_message: str = ""

    # -- State properties --

    @property
    def state(self) -> StrategyState:
        return self._state

    @property
    def error_message(self) -> str:
        return self._error_message

    @property
    def is_active(self) -> bool:
        return self._state == StrategyState.ACTIVE

    # -- State transitions --

    def start(self) -> None:
        if self._state in (StrategyState.STOPPED, StrategyState.ERROR):
            self._state = StrategyState.ACTIVE
            self._error_message = ""
            logger.info("Strategy '%s' started", self.name)

    def pause(self) -> None:
        if self._state == StrategyState.ACTIVE:
            self._state = StrategyState.PAUSED
            logger.info("Strategy '%s' paused", self.name)

    def resume(self) -> None:
        if self._state == StrategyState.PAUSED:
            self._state = StrategyState.ACTIVE
            logger.info("Strategy '%s' resumed", self.name)

    def stop(self) -> None:
        if self._state in (StrategyState.ACTIVE, StrategyState.PAUSED, StrategyState.ERROR):
            self._state = StrategyState.STOPPED
            logger.info("Strategy '%s' stopped", self.name)

    def set_error(self, message: str) -> None:
        self._state = StrategyState.ERROR
        self._error_message = message
        logger.error("Strategy '%s' errored: %s", self.name, message)

    # -- Abstract hooks --

    @abstractmethod
    def on_tick(self, quote: Quote) -> None:
        """Called on every LTP / quote update from WebSocket."""

    @abstractmethod
    def on_bar(self, bar: OHLCV) -> None:
        """Called on every completed OHLCV bar."""

    @abstractmethod
    def on_signal(self, signal: dict[str, Any]) -> None:
        """Called when an external signal arrives (webhook, TradingView alert, etc.)."""

    @abstractmethod
    def generate_orders(self) -> list[Order]:
        """Generate orders based on current strategy state. Called by the engine."""


# ---------------------------------------------------------------------------
# Strategy Registry
# ---------------------------------------------------------------------------


class StrategyRegistry:
    """Central registry for strategy classes and instances.

    Usage::

        registry = StrategyRegistry()
        registry.register(MyStrategy)
        strategy = registry.create("MyStrategy", exchange="NFO")
        registry.enable("MyStrategy")
    """

    def __init__(self) -> None:
        self._classes: dict[str, type[BaseStrategy]] = {}
        self._instances: dict[str, BaseStrategy] = {}

    def register(self, strategy_cls: type[BaseStrategy]) -> None:
        """Register a strategy class by its class name."""
        name = strategy_cls.__name__
        if name in self._classes:
            logger.warning("Strategy '%s' already registered — overwriting", name)
        self._classes[name] = strategy_cls
        logger.info("Registered strategy class: %s", name)

    def unregister(self, name: str) -> None:
        """Remove a strategy class from the registry."""
        self._classes.pop(name, None)
        inst = self._instances.pop(name, None)
        if inst:
            inst.stop()

    def list_registered(self) -> list[str]:
        """Return names of all registered strategy classes."""
        return list(self._classes.keys())

    def list_active(self) -> list[str]:
        """Return names of all instantiated and ACTIVE strategies."""
        return [n for n, s in self._instances.items() if s.is_active]

    def create(self, name: str, **kwargs: Any) -> BaseStrategy:
        """Instantiate a registered strategy class.

        The instance name defaults to the class name. Pass 'instance_name'
        in kwargs to override.
        """
        cls = self._classes.get(name)
        if cls is None:
            raise KeyError(f"Strategy '{name}' not registered")

        instance_name = kwargs.pop("instance_name", name)
        instance = cls(name=instance_name, **kwargs)
        self._instances[instance_name] = instance
        return instance

    def get(self, name: str) -> BaseStrategy | None:
        """Get an instantiated strategy by name."""
        return self._instances.get(name)

    def enable(self, name: str) -> None:
        """Start or resume a strategy instance."""
        inst = self._instances.get(name)
        if inst is None:
            raise KeyError(f"No instance named '{name}' — call create() first")
        if inst.state == StrategyState.PAUSED:
            inst.resume()
        else:
            inst.start()

    def disable(self, name: str) -> None:
        """Pause a running strategy instance."""
        inst = self._instances.get(name)
        if inst is None:
            raise KeyError(f"No instance named '{name}'")
        inst.pause()

    def stop_all(self) -> None:
        """Stop every instantiated strategy."""
        for inst in self._instances.values():
            inst.stop()
