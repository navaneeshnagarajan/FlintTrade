"""Strategy instance lifecycle manager.

Manages the full create → deploy → monitor → stop lifecycle of strategy
instances in a production trading environment.

Adapted from AlgoTrade (marketcalls/AlgoTrade) strategy instance model,
redesigned for FlintTrade's pure-Python, dataclass-first architecture:
- No SQLAlchemy ORM (uses in-memory dict store; persistence is a separate concern)
- No Flask Blueprint (engine is a standalone Python package)
- Builds on existing StrategyRegistry and BaseStrategy from strategy.py
- Full type coverage, dataclasses, and StrEnum state machine
- Thread-safe state mutations via a lock for concurrent use
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

logger = logging.getLogger("flinttrade.engine.strategy_lifecycle")


# ---------------------------------------------------------------------------
# Status enum
# ---------------------------------------------------------------------------


class InstanceStatus(StrEnum):
    """Lifecycle states for a deployed strategy instance.

    Transitions::

        created → running ↔ paused → stopped
                                    ↘ error
    """

    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


# ---------------------------------------------------------------------------
# StrategyInstance dataclass
# ---------------------------------------------------------------------------


@dataclass
class StrategyInstance:
    """A deployed strategy instance with full state tracking.

    Attributes:
        strategy_id:   Unique ID for this instance (auto-generated UUID).
        name:          Human-readable display name.
        strategy_class_name: Name of the strategy class in StrategyRegistry.
        symbols:       List of instruments this instance trades.
        exchange:      Exchange code (NSE, NFO, MCX, BSE, etc.).
        product:       Product type (MIS, CNC, NRML).
        parameters:    Strategy-specific parameters (stop-loss %, lot size, etc.).
        status:        Current lifecycle status.
        created_at:    ISO-format timestamp when instance was created.
        started_at:    ISO-format timestamp of most recent start. None if never started.
        stopped_at:    ISO-format timestamp of most recent stop. None if never stopped.
        last_signal:   Most recent signal generated ("BUY"/"SELL"/"HOLD"/None).
        error_message: Set when status is ERROR.
        cycle_count:   Number of on_tick/on_bar cycles completed.
        trade_count:   Number of orders placed by this instance.
        daily_pnl:     Running P&L for the current session.
    """

    strategy_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    strategy_class_name: str = ""
    symbols: list[str] = field(default_factory=list)
    exchange: str = "NSE"
    product: str = "MIS"
    parameters: dict[str, Any] = field(default_factory=dict)
    status: InstanceStatus = InstanceStatus.CREATED
    created_at: str = field(default_factory=lambda: _now_iso())
    started_at: str | None = None
    stopped_at: str | None = None
    last_signal: str | None = None
    error_message: str = ""
    cycle_count: int = 0
    trade_count: int = 0
    daily_pnl: float = 0.0

    @property
    def is_running(self) -> bool:
        return self.status == InstanceStatus.RUNNING

    @property
    def is_stopped(self) -> bool:
        return self.status in (InstanceStatus.STOPPED, InstanceStatus.ERROR)

    def as_dict(self) -> dict[str, Any]:
        """Serialisable representation for API responses."""
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "strategy_class_name": self.strategy_class_name,
            "symbols": self.symbols,
            "exchange": self.exchange,
            "product": self.product,
            "parameters": self.parameters,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "last_signal": self.last_signal,
            "error_message": self.error_message,
            "cycle_count": self.cycle_count,
            "trade_count": self.trade_count,
            "daily_pnl": self.daily_pnl,
        }


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class StrategyLifecycleError(Exception):
    """Raised when a lifecycle transition is invalid or fails."""


class InstanceNotFoundError(StrategyLifecycleError):
    """Raised when a strategy_id is not found in the manager."""


class InvalidTransitionError(StrategyLifecycleError):
    """Raised when a state transition is not allowed from the current status."""


# ---------------------------------------------------------------------------
# StrategyLifecycleManager
# ---------------------------------------------------------------------------


class StrategyLifecycleManager:
    """Manage strategy deployment lifecycle: create → deploy → monitor → stop.

    Thread-safe: all state mutations acquire a shared lock so the manager can
    be used safely from background threads or async workers (via to_thread).

    Adapted from AlgoTrade's StrategyInstance model and controller pattern,
    redesigned as a pure in-memory lifecycle manager without ORM dependencies.

    Usage::

        manager = StrategyLifecycleManager(registry=my_registry)

        # Create and deploy
        instance = manager.create_instance(
            strategy_class_name="EMACrossover",
            name="NIFTY EMA 20/50",
            symbols=["NIFTY25JULFUT"],
            exchange="NFO",
            parameters={"fast_period": 20, "slow_period": 50},
        )
        manager.deploy(instance.strategy_id)

        # Inspect
        info = manager.get_status(instance.strategy_id)
        print(info.status)  # "running"

        # Pause, resume, stop
        manager.pause(instance.strategy_id)
        manager.resume(instance.strategy_id)
        manager.stop(instance.strategy_id)

        # List
        running = manager.list_instances(status_filter=InstanceStatus.RUNNING)
    """

    def __init__(self, registry: Any | None = None) -> None:
        """Initialise the lifecycle manager.

        Args:
            registry: A StrategyRegistry instance. When provided, deploy()
                      will also start the corresponding BaseStrategy object
                      via registry.enable(). Pass None for testing / offline use.
        """
        self._registry = registry
        self._instances: dict[str, StrategyInstance] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_instance(
        self,
        strategy_class_name: str,
        name: str,
        symbols: list[str],
        exchange: str = "NSE",
        product: str = "MIS",
        parameters: dict[str, Any] | None = None,
        strategy_id: str | None = None,
    ) -> StrategyInstance:
        """Create a new strategy instance in CREATED state.

        Does NOT start or deploy the strategy — call deploy() to activate.

        Args:
            strategy_class_name: Name of the registered strategy class.
            name:                Human-readable display name for this instance.
            symbols:             List of instruments (e.g. ["NIFTY25JULFUT"]).
            exchange:            Exchange code. Defaults to "NSE".
            product:             Product type. Defaults to "MIS".
            parameters:          Strategy-specific config dict.
            strategy_id:         Override auto-generated UUID (useful for tests).

        Returns:
            The newly created StrategyInstance.

        Raises:
            ValueError: If name or strategy_class_name is empty.
        """
        if not name.strip():
            raise ValueError("Instance name must be non-empty")
        if not strategy_class_name.strip():
            raise ValueError("strategy_class_name must be non-empty")
        if not symbols:
            raise ValueError("symbols must be non-empty")

        instance = StrategyInstance(
            strategy_id=strategy_id or str(uuid.uuid4()),
            name=name.strip(),
            strategy_class_name=strategy_class_name,
            symbols=list(symbols),
            exchange=exchange,
            product=product,
            parameters=dict(parameters or {}),
            status=InstanceStatus.CREATED,
        )

        with self._lock:
            self._instances[instance.strategy_id] = instance

        logger.info(
            "Created strategy instance '%s' [%s] for %s",
            name, instance.strategy_id[:8], symbols,
        )
        return instance

    # ------------------------------------------------------------------
    # Deploy / Start
    # ------------------------------------------------------------------

    def deploy(self, instance_id: str) -> StrategyInstance:
        """Transition a CREATED or PAUSED instance to RUNNING.

        Also calls registry.enable() if a registry was provided.

        Args:
            instance_id: UUID of the instance to deploy.

        Returns:
            Updated StrategyInstance.

        Raises:
            InstanceNotFoundError: If instance_id does not exist.
            InvalidTransitionError: If current status does not allow start.
        """
        inst = self._get_or_raise(instance_id)

        if inst.status not in (InstanceStatus.CREATED, InstanceStatus.PAUSED):
            raise InvalidTransitionError(
                f"Cannot deploy instance with status '{inst.status}'. "
                "Only CREATED or PAUSED instances can be deployed."
            )

        with self._lock:
            inst.status = InstanceStatus.RUNNING
            inst.started_at = _now_iso()
            inst.error_message = ""

        if self._registry is not None:
            try:
                self._registry.enable(inst.strategy_class_name)
            except Exception as exc:
                logger.warning(
                    "Registry enable failed for '%s': %s — instance is RUNNING but strategy hook not activated",
                    inst.strategy_class_name, exc,
                )

        logger.info("Deployed strategy instance '%s' [%s]", inst.name, instance_id[:8])
        return inst

    # ------------------------------------------------------------------
    # Pause
    # ------------------------------------------------------------------

    def pause(self, instance_id: str) -> StrategyInstance:
        """Pause a RUNNING instance.

        The instance retains its state and can be resumed. Does NOT square off
        any open positions — the calling layer is responsible for that.

        Args:
            instance_id: UUID of the instance to pause.

        Returns:
            Updated StrategyInstance.

        Raises:
            InstanceNotFoundError: If instance_id does not exist.
            InvalidTransitionError: If instance is not RUNNING.
        """
        inst = self._get_or_raise(instance_id)

        if inst.status != InstanceStatus.RUNNING:
            raise InvalidTransitionError(
                f"Cannot pause instance with status '{inst.status}'. Only RUNNING instances can be paused."
            )

        with self._lock:
            inst.status = InstanceStatus.PAUSED

        if self._registry is not None:
            try:
                self._registry.disable(inst.strategy_class_name)
            except Exception as exc:
                logger.warning("Registry disable failed for '%s': %s", inst.strategy_class_name, exc)

        logger.info("Paused strategy instance '%s'", inst.name)
        return inst

    # ------------------------------------------------------------------
    # Resume
    # ------------------------------------------------------------------

    def resume(self, instance_id: str) -> StrategyInstance:
        """Resume a PAUSED instance back to RUNNING.

        Args:
            instance_id: UUID of the instance to resume.

        Returns:
            Updated StrategyInstance.

        Raises:
            InstanceNotFoundError: If instance_id does not exist.
            InvalidTransitionError: If instance is not PAUSED.
        """
        inst = self._get_or_raise(instance_id)

        if inst.status != InstanceStatus.PAUSED:
            raise InvalidTransitionError(
                f"Cannot resume instance with status '{inst.status}'. Only PAUSED instances can be resumed."
            )

        with self._lock:
            inst.status = InstanceStatus.RUNNING
            inst.started_at = _now_iso()

        if self._registry is not None:
            try:
                self._registry.enable(inst.strategy_class_name)
            except Exception as exc:
                logger.warning("Registry enable (resume) failed: %s", exc)

        logger.info("Resumed strategy instance '%s'", inst.name)
        return inst

    # ------------------------------------------------------------------
    # Stop
    # ------------------------------------------------------------------

    def stop(self, instance_id: str) -> StrategyInstance:
        """Stop a RUNNING, PAUSED, or ERROR instance.

        A stopped instance cannot be resumed — create a new instance to restart.

        Args:
            instance_id: UUID of the instance to stop.

        Returns:
            Updated StrategyInstance.

        Raises:
            InstanceNotFoundError: If instance_id does not exist.
            InvalidTransitionError: If instance is already STOPPED or CREATED.
        """
        inst = self._get_or_raise(instance_id)

        stoppable = (InstanceStatus.RUNNING, InstanceStatus.PAUSED, InstanceStatus.ERROR)
        if inst.status not in stoppable:
            raise InvalidTransitionError(
                f"Cannot stop instance with status '{inst.status}'."
            )

        with self._lock:
            inst.status = InstanceStatus.STOPPED
            inst.stopped_at = _now_iso()

        if self._registry is not None:
            try:
                registry_inst = self._registry.get(inst.strategy_class_name)
                if registry_inst is not None:
                    registry_inst.stop()
            except Exception as exc:
                logger.warning("Registry stop failed for '%s': %s", inst.strategy_class_name, exc)

        logger.info("Stopped strategy instance '%s'", inst.name)
        return inst

    # ------------------------------------------------------------------
    # Mark error
    # ------------------------------------------------------------------

    def mark_error(self, instance_id: str, message: str) -> StrategyInstance:
        """Transition a RUNNING or PAUSED instance to ERROR state.

        Args:
            instance_id: UUID of the instance.
            message:     Human-readable description of the error.

        Returns:
            Updated StrategyInstance.

        Raises:
            InstanceNotFoundError: If instance_id does not exist.
        """
        inst = self._get_or_raise(instance_id)

        with self._lock:
            inst.status = InstanceStatus.ERROR
            inst.error_message = message
            inst.stopped_at = _now_iso()

        logger.error("Strategy instance '%s' errored: %s", inst.name, message)
        return inst

    # ------------------------------------------------------------------
    # Record signal / trade
    # ------------------------------------------------------------------

    def record_signal(self, instance_id: str, signal: str) -> None:
        """Update last_signal for an instance.

        Args:
            instance_id: UUID of the instance.
            signal:      Signal string ("BUY", "SELL", "HOLD").
        """
        inst = self._instances.get(instance_id)
        if inst:
            with self._lock:
                inst.last_signal = signal

    def record_trade(self, instance_id: str, pnl: float = 0.0) -> None:
        """Increment trade_count and update daily_pnl for an instance.

        Args:
            instance_id: UUID of the instance.
            pnl:         Net P&L of the completed trade.
        """
        inst = self._instances.get(instance_id)
        if inst:
            with self._lock:
                inst.trade_count += 1
                inst.daily_pnl += pnl

    def increment_cycle(self, instance_id: str) -> None:
        """Increment the cycle counter for an instance.

        Args:
            instance_id: UUID of the instance.
        """
        inst = self._instances.get(instance_id)
        if inst:
            with self._lock:
                inst.cycle_count += 1

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_status(self, instance_id: str) -> StrategyInstance:
        """Return the current StrategyInstance for the given ID.

        Args:
            instance_id: UUID of the instance.

        Returns:
            Current StrategyInstance.

        Raises:
            InstanceNotFoundError: If instance_id does not exist.
        """
        return self._get_or_raise(instance_id)

    def list_instances(
        self,
        status_filter: InstanceStatus | None = None,
    ) -> list[StrategyInstance]:
        """Return all instances, optionally filtered by status.

        Args:
            status_filter: If provided, only return instances with this status.

        Returns:
            List of StrategyInstance objects sorted by creation time.
        """
        with self._lock:
            instances = list(self._instances.values())

        if status_filter is not None:
            instances = [i for i in instances if i.status == status_filter]

        return sorted(instances, key=lambda i: i.created_at)

    def remove(self, instance_id: str) -> None:
        """Remove an instance from the manager (must be STOPPED or ERROR).

        Args:
            instance_id: UUID of the instance.

        Raises:
            InstanceNotFoundError: If instance_id does not exist.
            InvalidTransitionError: If instance is not in a terminal state.
        """
        inst = self._get_or_raise(instance_id)
        if inst.status not in (InstanceStatus.STOPPED, InstanceStatus.ERROR, InstanceStatus.CREATED):
            raise InvalidTransitionError(
                f"Cannot remove instance with status '{inst.status}'. Stop it first."
            )

        with self._lock:
            self._instances.pop(instance_id, None)

        logger.info("Removed strategy instance '%s' [%s]", inst.name, instance_id[:8])

    def stop_all(self) -> list[str]:
        """Stop every running or paused instance.

        Returns:
            List of instance_ids that were stopped.
        """
        stopped_ids: list[str] = []
        for inst in list(self._instances.values()):
            if inst.status in (InstanceStatus.RUNNING, InstanceStatus.PAUSED):
                try:
                    self.stop(inst.strategy_id)
                    stopped_ids.append(inst.strategy_id)
                except StrategyLifecycleError as exc:
                    logger.warning("stop_all: failed to stop '%s': %s", inst.name, exc)
        return stopped_ids

    @property
    def instance_count(self) -> int:
        """Total number of managed instances."""
        return len(self._instances)

    @property
    def running_count(self) -> int:
        """Number of currently RUNNING instances."""
        return sum(1 for i in self._instances.values() if i.status == InstanceStatus.RUNNING)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_or_raise(self, instance_id: str) -> StrategyInstance:
        inst = self._instances.get(instance_id)
        if inst is None:
            raise InstanceNotFoundError(f"No instance with ID '{instance_id}'")
        return inst


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """Current UTC datetime as ISO-8601 string."""
    from datetime import timezone
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
