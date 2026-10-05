"""FlintTrade strategy lifecycle, managed execution and restart checkpoints.

A strategy produces intents. Its declared execution contract owns submission.
Checkpoint storage is local to the active workspace and starts only on access.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from abc import ABC, abstractmethod
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar

from flinttrade_core.models import OHLCV, Order, Quote

from .strategy_execution import StrategyExecutionContract, StrategyExecutionMode

logger = logging.getLogger("flinttrade.engine.strategy")


def _default_state_root() -> Path:
    """Resolve checkpoint storage when it is needed, honouring workspace changes."""
    from flinttrade_core.workspace import workspace_dir

    return workspace_dir() / "strategies"


class StrategyState(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


class BaseStrategy(ABC):
    """Shared lifecycle and checkpoint interface for native strategy runners."""

    supported_execution_modes: ClassVar[frozenset[StrategyExecutionMode]] = frozenset()
    uses_managed_order_dispatch: ClassVar[bool] = False
    _TRANSITIONS: ClassVar[dict[str, tuple[frozenset[StrategyState], StrategyState]]] = {
        "start": (frozenset({StrategyState.STOPPED, StrategyState.ERROR}), StrategyState.ACTIVE),
        "pause": (frozenset({StrategyState.ACTIVE}), StrategyState.PAUSED),
        "resume": (frozenset({StrategyState.PAUSED}), StrategyState.ACTIVE),
        "stop": (frozenset({StrategyState.ACTIVE, StrategyState.PAUSED, StrategyState.ERROR}), StrategyState.STOPPED),
    }

    def __init__(
        self,
        name: str,
        exchange: str = "NSE",
        product: str = "MIS",
        strategy_id: str | None = None,
        execution_contract: StrategyExecutionContract | None = None,
        state_root: Path | str | None = None,
    ) -> None:
        identifier = strategy_id or re.sub(r"[^a-z0-9_-]+", "_", name.lower()).strip("_")
        if not identifier or not re.fullmatch(r"[A-Za-z0-9_-]+", identifier):
            raise ValueError("strategy_id must be a single non-empty filesystem component")
        self.name, self.exchange, self.product = name, exchange, product
        self._strategy_id = identifier
        self._injected_state_root = None if state_root is None else Path(state_root)
        self._execution_contract = execution_contract
        self._state = StrategyState.STOPPED
        self._error_message = ""

    @property
    def _state_root(self) -> Path:
        return self._injected_state_root if self._injected_state_root is not None else _default_state_root()

    @property
    def _state_dir(self) -> Path:
        return self._state_root / self._strategy_id

    @property
    def state_file(self) -> Path:
        return self._state_dir / "state.json"

    @property
    def state(self) -> StrategyState:
        return self._state

    @property
    def is_active(self) -> bool:
        return self.state is StrategyState.ACTIVE

    @property
    def error_message(self) -> str:
        return self._error_message

    @property
    def execution_contract(self) -> StrategyExecutionContract | None:
        return self._execution_contract

    def require_execution_contract(self) -> StrategyExecutionContract:
        """Require the runner's validated contract before any dispatch."""
        if not isinstance(self.execution_contract, StrategyExecutionContract):
            raise RuntimeError(f"Strategy {self.name!r} has no explicit execution contract")
        self.execution_contract.validate_strategy(self)
        return self.execution_contract

    async def dispatch_order(self, order: Order) -> Any:
        """Delegate submission to the managed execution contract."""
        contract = self.require_execution_contract()
        return await contract.dispatch_order(order)

    def _apply_lifecycle_transition(self, event: str) -> None:
        permitted, destination = self._TRANSITIONS[event]
        if self.state in permitted:
            self._state = destination
            if event == "start":
                self._error_message = ""
            logger.info("Strategy %s: %s -> %s", self.name, event, destination)

    def start(self) -> None:
        self._apply_lifecycle_transition("start")

    def pause(self) -> None:
        self._apply_lifecycle_transition("pause")

    def resume(self) -> None:
        self._apply_lifecycle_transition("resume")

    def stop(self) -> None:
        self._apply_lifecycle_transition("stop")

    def set_error(self, message: str) -> None:
        self._error_message, self._state = message, StrategyState.ERROR
        logger.error("Strategy %s: %s", self.name, message)

    def get_state_dict(self) -> dict[str, Any]:
        """Supply JSON-compatible strategy data for the next checkpoint."""
        return {}

    def save_state(self) -> None:
        """Replace a complete checkpoint using a private, unique staging file.

        Serialisation happens before touching disk. Lifecycle identity cannot
        be replaced by subclass payload. An interrupted write leaves the prior
        checkpoint intact; independent writers never share staging filenames.
        """
        payload = dict(self.get_state_dict())
        payload.update(strategy_id=self._strategy_id, name=self.name,
                       lifecycle_state=str(self.state), error_message=self.error_message)
        encoded = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
        target = self.state_file
        staging: Path | None = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                             prefix=".checkpoint-", suffix=".tmp", delete=False) as stream:
                staging = Path(stream.name)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(staging, target)
        except OSError:
            logger.exception("Checkpoint write failed for %s", self.name)
        finally:
            if staging is not None:
                try:
                    staging.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Checkpoint staging cleanup failed for %s", self.name)

    def load_state(self) -> dict[str, Any] | None:
        """Return a complete JSON object, leaving lifecycle restoration to callers."""
        try:
            payload = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def clear_state(self) -> None:
        """Remove the checkpoint without changing in-memory lifecycle state."""
        try:
            self.state_file.unlink(missing_ok=True)
        except OSError:
            logger.exception("Checkpoint deletion failed for %s", self.name)

    @abstractmethod
    def on_tick(self, quote: Quote) -> None:
        """Consume a native quote."""

    @abstractmethod
    def on_bar(self, bar: OHLCV) -> None:
        """Consume a completed bar."""

    @abstractmethod
    def on_signal(self, signal: dict[str, Any]) -> None:
        """Consume an admitted strategy signal."""

    @abstractmethod
    def generate_orders(self) -> list[Order]:
        """Drain order intents for the managed runner."""


class StrategyRegistry:
    """Hold strategy factories separately from named runtime instances."""

    def __init__(self) -> None:
        self._classes: dict[str, type[BaseStrategy]] = {}
        self._instances: dict[str, BaseStrategy] = {}

    def register(self, strategy_cls: type[BaseStrategy]) -> None:
        self._classes[strategy_cls.__name__] = strategy_cls

    def unregister(self, name: str) -> None:
        self._classes.pop(name, None)
        instance = self._instances.pop(name, None)
        if instance is not None:
            instance.stop()

    def list_registered(self) -> list[str]:
        return list(self._classes)

    def list_active(self) -> list[str]:
        return [name for name in self._instances if self._instances[name].is_active]

    def create(self, name: str, **kwargs: Any) -> BaseStrategy:
        try:
            factory = self._classes[name]
        except KeyError as exc:
            raise KeyError(f"Strategy {name!r} not registered") from exc
        instance_name = kwargs.pop("instance_name", name)
        strategy = factory(name=instance_name, **kwargs)
        self._instances[instance_name] = strategy
        return strategy

    def get(self, name: str) -> BaseStrategy | None:
        return self._instances.get(name)

    def _instance(self, name: str) -> BaseStrategy:
        try:
            return self._instances[name]
        except KeyError as exc:
            raise KeyError(f"No instance named {name!r}") from exc

    def enable(self, name: str) -> None:
        strategy = self._instance(name)
        (strategy.resume if strategy.state is StrategyState.PAUSED else strategy.start)()

    def disable(self, name: str) -> None:
        self._instance(name).pause()

    def stop_all(self) -> None:
        for name in tuple(self._instances):
            self._instances[name].stop()
