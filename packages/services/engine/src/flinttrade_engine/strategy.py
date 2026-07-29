"""Base strategy interface and strategy registry.

All user strategies inherit from BaseStrategy. The StrategyRegistry manages
discovery, enabling/disabling, and lifecycle.

State persistence (adapted from trading-strategies-openalgo pattern):
    Each strategy can persist its state to
    ``<workspace_dir>/strategies/<strategy_id>/state.json`` so it can resume
    after a crash without losing position tracking.  Call ``save_state()``
    after each tick/bar and ``load_state()`` at startup.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar

from flinttrade_core.models import OHLCV, Order, Quote

from .strategy_execution import StrategyExecutionContract, StrategyExecutionMode

logger = logging.getLogger("flinttrade.engine.strategy")


# ---------------------------------------------------------------------------
# Strategy state root helper
# ---------------------------------------------------------------------------


def _default_state_root() -> Path:
    """Resolve the directory holding one state directory per strategy.

    Resolution happens on every call (never at import time, and never during
    strategy construction) so a workspace override applied mid-process — as
    pytest and Gunicorn preload+fork both do — is honoured. Because
    :func:`~flinttrade_core.workspace.workspace_dir` creates and hardens the
    workspace root, callers must reach this only when they are about to touch
    state on disk.

    There is deliberately no legacy-state migration here. Before this module
    used :func:`~flinttrade_core.workspace.workspace_dir`, it already resolved
    the same platform-specific root, so a default install has nothing to
    migrate; divergence exists only for installs that set
    ``FLINTTRADE_HOME``/``FLINTTRADE_WORKSPACE_DIR``, and a probe that fired
    under an override would copy real state into every throwaway workspace.

    Returns:
        The ``strategies`` directory inside the active workspace directory.
    """
    from flinttrade_core.workspace import workspace_dir  # noqa: PLC0415

    return workspace_dir() / "strategies"


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

    Args:
        name: Human-readable strategy name.
        exchange: Default exchange for generated orders.
        product: Default product type for generated orders.
        strategy_id: Stable identifier used as the state directory name.
            Falls back to a slugified ``name``.
        execution_contract: Optional execution contract governing how orders
            reach the broker.
        state_root: Directory holding one state directory per strategy.
            Defaults to ``strategies/`` under the active FlintTrade workspace,
            resolved on first state access — never at import time and never
            during construction, so building a strategy (in a test, a registry
            scan, a dry run) writes nothing to disk. Injecting a root is the
            supported way for tests to keep state off the real workspace.
    """

    supported_execution_modes: ClassVar[frozenset[StrategyExecutionMode]] = frozenset()
    uses_managed_order_dispatch: ClassVar[bool] = False

    def __init__(
        self,
        name: str,
        exchange: str = "NSE",
        product: str = "MIS",
        strategy_id: str | None = None,
        execution_contract: StrategyExecutionContract | None = None,
        state_root: Path | str | None = None,
    ) -> None:
        self.name = name
        self.exchange = exchange
        self.product = product
        self._state = StrategyState.STOPPED
        self._error_message: str = ""
        self._execution_contract = execution_contract
        # State persistence: use strategy_id as the directory name (falls back
        # to slugified name when not provided).
        self._strategy_id: str = strategy_id or name.lower().replace(" ", "_")
        # Only the injected root is bound here. The workspace default is
        # resolved on access instead, because resolving it creates and hardens
        # the workspace root — construction must stay free of disk writes.
        self._injected_state_root: Path | None = Path(state_root) if state_root is not None else None

    # -- State properties --

    @property
    def _state_root(self) -> Path:
        """Directory holding one state directory per strategy, resolved per access."""
        injected = self._injected_state_root
        return injected if injected is not None else _default_state_root()

    @property
    def _state_dir(self) -> Path:
        """This strategy's own state directory, resolved per access."""
        return self._state_root / self._strategy_id

    @property
    def state(self) -> StrategyState:
        return self._state

    @property
    def error_message(self) -> str:
        return self._error_message

    @property
    def is_active(self) -> bool:
        return self._state == StrategyState.ACTIVE

    @property
    def execution_contract(self) -> StrategyExecutionContract | None:
        """Explicit runtime contract required by :class:`StrategyRunner`."""
        return self._execution_contract

    def require_execution_contract(self) -> StrategyExecutionContract:
        """Return and validate the declared scheduler execution contract."""
        contract = self._execution_contract
        if not isinstance(contract, StrategyExecutionContract):
            raise RuntimeError(f"Strategy {self.name!r} has no explicit execution contract")
        contract.validate_strategy(self)
        return contract

    async def dispatch_order(self, order: Order) -> Any:
        """Submit an order only through the strategy's managed contract."""
        return await self.require_execution_contract().dispatch_order(order)

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

    # -- State persistence --

    @property
    def state_file(self) -> Path:
        """Absolute path to the JSON state file for this strategy.

        Returns:
            Path object pointing to
            ``<state root>/<strategy_id>/state.json``.
        """
        return self._state_dir / "state.json"

    def save_state(self) -> None:
        """Persist strategy state to a JSON file.

        Serialises ``self.get_state_dict()`` (which subclasses should override
        to include their own fields) together with lifecycle metadata.  The
        file is written atomically via a temporary sibling file to avoid
        partial writes.

        Called after each tick/bar processing so the strategy can resume from
        the last known state after a crash.
        """
        self._state_dir.mkdir(parents=True, exist_ok=True)

        payload: dict[str, Any] = {
            "strategy_id": self._strategy_id,
            "name": self.name,
            "lifecycle_state": str(self._state),
            "error_message": self._error_message,
        }
        payload.update(self.get_state_dict())

        tmp_path = self.state_file.with_suffix(".tmp")
        try:
            tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp_path.replace(self.state_file)
            logger.debug("State saved for strategy '%s'", self.name)
        except OSError as exc:
            logger.error("Failed to save state for strategy '%s': %s", self.name, exc)
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def load_state(self) -> dict[str, Any] | None:
        """Load previously saved state from disk.

        Returns:
            Parsed state dict on success, or ``None`` if no state file exists
            or the file cannot be parsed.
        """
        if not self.state_file.exists():
            logger.debug(
                "No saved state found for strategy '%s' at %s",
                self.name, self.state_file,
            )
            return None

        try:
            raw = self.state_file.read_text(encoding="utf-8")
            data: dict[str, Any] = json.loads(raw)
            logger.info(
                "State loaded for strategy '%s' from %s", self.name, self.state_file
            )
            return data
        except (OSError, json.JSONDecodeError) as exc:
            logger.error(
                "Failed to load state for strategy '%s': %s", self.name, exc
            )
            return None

    def clear_state(self) -> None:
        """Delete the saved state file for this strategy.

        Call on strategy stop or explicit reset so stale state is not reloaded
        on the next startup.
        """
        if self.state_file.exists():
            try:
                self.state_file.unlink()
                logger.info(
                    "State cleared for strategy '%s' (%s)", self.name, self.state_file
                )
            except OSError as exc:
                logger.error(
                    "Failed to clear state for strategy '%s': %s", self.name, exc
                )
        else:
            logger.debug(
                "clear_state: no state file found for strategy '%s'", self.name
            )

    def get_state_dict(self) -> dict[str, Any]:
        """Return strategy-specific state to persist.

        Override in subclasses to add any fields that should survive a restart
        (e.g. open position tracking, indicator values, trade counters).

        The base implementation returns an empty dict so the lifecycle metadata
        saved by :meth:`save_state` is still written even when a subclass does
        not override this method.

        Returns:
            Dict of serialisable values to merge into the state payload.
        """
        return {}

    # -- Abstract hooks --

    @abstractmethod
    def on_tick(self, quote: Quote) -> None:
        """Called on every LTP / quote update from WebSocket."""

    @abstractmethod
    def on_bar(self, bar: OHLCV) -> None:
        """Called on every completed OHLCV bar."""

    @abstractmethod
    def on_signal(self, signal: dict[str, Any]) -> None:
        """Called when an external signal arrives (webhook, scheduled scan, etc.)."""

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
