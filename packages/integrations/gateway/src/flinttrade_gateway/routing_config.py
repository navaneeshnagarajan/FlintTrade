"""RoutingConfig — parsed, validated view of ``workspace.json.brokers`` (contract §13).

The operator declares, per task, which broker account serves it: execution
(optionally overridden by market segment), tick stream, historical bars, option
chains, quotes, and global indices. Plus an optional failover order, a
cost-aware-routing toggle, and a per-``(adapter_id, account_id)`` actor ACL.

Every selector is the canonical composite ``'adapter_id:account_id'`` (identity
X7) — an operator-facing string. The router splits on the first colon to recover
the registry key ``(adapter_id, account_id)``. Two namespaces must never be
conflated: the bare ``adapter_id`` is the registry key; the composite selector is
the workspace-facing form.

A malformed ``brokers`` block raises :class:`RoutingConfigError` at parse time so
the trading surface never comes up with an unparseable routing config; the
operator edits ``workspace.json`` by hand and restarts (parsing never mutates the
file).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from flinttrade_engine.request_context import parse_selector

logger = logging.getLogger("flinttrade.gateway.routing")

# The task vocabulary the router can resolve (contract §13.2). ``cost_aware.tasks``
# must be a subset of this set.
KNOWN_TASKS: frozenset[str] = frozenset(
    {
        "execution",
        "data.ticks",
        "data.historical",
        "data.option_chains",
        "data.quote",
        "data.global_indices",
    }
)


class RoutingConfigError(ValueError):
    """Raised when ``workspace.json.brokers`` is malformed (contract §13.3).

    Surfaced at app startup as a single fatal, actionable error. Parsing a
    routing config never mutates ``workspace.json``.
    """


@dataclass(frozen=True)
class ExecutionRouting:
    """Which account executes orders, optionally overridden per market segment."""

    default: str
    by_segment: dict[str, str] = field(default_factory=dict)  # "F&O" -> selector


@dataclass(frozen=True)
class DataRouting:
    """Which account serves each market-data task."""

    ticks: str
    historical: str
    option_chains: str
    quote: str
    global_indices: str = ""


@dataclass(frozen=True)
class FailoverConfig:
    """Ordered failover allowlist; empty/disabled means no failover."""

    enabled: bool = False
    order: tuple[str, ...] = ()


@dataclass(frozen=True)
class CostAwareConfig:
    """Cost-aware routing toggle and the tasks it applies to."""

    enabled: bool = False
    tasks: tuple[str, ...] = ()


@dataclass(frozen=True)
class RoutingHint:
    """Per-call override for routing decisions (contract §13.4).

    Empty strings mean "use config"; ``account_id == ''`` means "the default
    account for the resolved adapter".

    Use cases:
        - Force a specific adapter (override config): ``adapter_id='dhan'``
        - Ditto multi-account fan-out: ``account_id='spouse'``
        - Test/replay: bypass config entirely.
    """

    adapter_id: str = ""
    account_id: str = ""
    skip_failover: bool = False


@dataclass(frozen=True)
class RoutingConfig:
    """The parsed, validated ``workspace.json.brokers`` block (contract §13.2)."""

    registered: tuple[str, ...]
    execution: ExecutionRouting
    data: DataRouting
    failover: FailoverConfig
    cost_aware: CostAwareConfig
    # v1.0.1 Identity H2: per-(adapter_id, account_id) actor authorisation.
    # Shape: {adapter_id: {account_id: [actor_id, ...]}}. Consumed by
    # AuthenticatingSessionProvider, which raises SafetyBypassError on a miss.
    account_acls: dict[str, dict[str, list[str]]] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Resolution (contract §13.2)
    # ------------------------------------------------------------------

    def resolve(self, task: str, payload: Any = None) -> str | None:
        """Return the composite selector for ``task``, or ``None`` to fall through.

        For ``"execution"`` a by-segment override (e.g. ``"F&O"``) wins when the
        payload carries a matching exchange; otherwise the default is used.
        """
        if task == "execution":
            if payload is not None and hasattr(payload, "exchange"):
                key = self._exchange_to_segment_key(_exchange_str(payload.exchange))
                if key in self.execution.by_segment:
                    return self.execution.by_segment[key]
            return self.execution.default
        if task == "data.ticks":
            return self.data.ticks
        if task == "data.historical":
            return self.data.historical
        if task == "data.option_chains":
            return self.data.option_chains
        if task == "data.quote":
            return self.data.quote
        if task == "data.global_indices":
            return self.data.global_indices or self.execution.default
        return None

    @staticmethod
    def _exchange_to_segment_key(exchange: str) -> str:
        if exchange in ("NFO", "BFO", "MCX"):
            return "F&O"
        return exchange

    # ------------------------------------------------------------------
    # Parsing + validation (contract §13.1 / §13.3)
    # ------------------------------------------------------------------

    @classmethod
    def from_workspace(cls, brokers: dict[str, Any]) -> "RoutingConfig":
        """Parse and validate a ``workspace.json.brokers`` block.

        Args:
            brokers: The ``brokers`` mapping from a migrated ``workspace.json``.

        Returns:
            A validated :class:`RoutingConfig`.

        Raises:
            RoutingConfigError: On any malformed selector, missing required key,
                a selector absent from ``registered``, or a ``cost_aware.tasks``
                entry outside the known task set. Unauthorised accounts (no actor
                in ``account_acls``) only emit a warning.
        """
        if not isinstance(brokers, dict):
            raise RoutingConfigError("brokers block must be a mapping")

        registered = tuple(brokers.get("registered") or ())

        execution_raw = brokers.get("execution") or {}
        if "default" not in execution_raw:
            raise RoutingConfigError("brokers.execution.default is required")
        by_segment = {
            str(k): str(v) for k, v in execution_raw.items() if k != "default"
        }
        execution = ExecutionRouting(
            default=str(execution_raw["default"]),
            by_segment=by_segment,
        )

        data_raw = brokers.get("data") or {}
        for required in ("ticks", "historical", "option_chains"):
            if required not in data_raw:
                raise RoutingConfigError(f"brokers.data.{required} is required")
        # quote is required by the dataclass but, for backwards compatibility with
        # configs predating the field, falls back to option_chains.
        quote = str(data_raw.get("quote") or data_raw["option_chains"])
        data = DataRouting(
            ticks=str(data_raw["ticks"]),
            historical=str(data_raw["historical"]),
            option_chains=str(data_raw["option_chains"]),
            quote=quote,
            global_indices=str(data_raw.get("global_indices") or ""),
        )

        failover_raw = brokers.get("failover") or {}
        failover = FailoverConfig(
            enabled=bool(failover_raw.get("enabled", False)),
            order=tuple(str(s) for s in (failover_raw.get("order") or ())),
        )

        cost_aware_raw = brokers.get("cost_aware") or {}
        cost_aware = CostAwareConfig(
            enabled=bool(cost_aware_raw.get("enabled", False)),
            tasks=tuple(str(t) for t in (cost_aware_raw.get("tasks") or ())),
        )

        account_acls = brokers.get("account_acls") or {}

        cfg = cls(
            registered=registered,
            execution=execution,
            data=data,
            failover=failover,
            cost_aware=cost_aware,
            account_acls=account_acls,
        )
        cfg._validate()
        return cfg

    def _validate(self) -> None:
        registered = set(self.registered)

        # Every selector referenced anywhere must parse to (adapter_id, account_id)
        # and appear in ``registered``.
        referenced: list[tuple[str, str]] = []  # (selector, json-path)
        referenced.append((self.execution.default, "brokers.execution.default"))
        for seg, sel in self.execution.by_segment.items():
            referenced.append((sel, f"brokers.execution.{seg}"))
        for field_name in ("ticks", "historical", "option_chains", "quote"):
            referenced.append((getattr(self.data, field_name), f"brokers.data.{field_name}"))
        if self.data.global_indices:
            referenced.append((self.data.global_indices, "brokers.data.global_indices"))
        for sel in self.failover.order:
            referenced.append((sel, "brokers.failover.order"))

        for selector, path in referenced:
            try:
                adapter_id, account_id = parse_selector(selector)
            except ValueError as exc:
                raise RoutingConfigError(
                    f"invalid routing selector {selector!r} at {path}: "
                    "must be 'adapter_id:account_id'"
                ) from exc
            if registered and selector not in registered:
                raise RoutingConfigError(
                    f"routing selector {selector!r} at {path} is not in "
                    f"brokers.registered {sorted(registered)}"
                )
            # account_acls coverage is a WARNING, not a hard error (§13.3): an
            # operator may stage an account before authorising any actor for it.
            actors = self.account_acls.get(adapter_id, {}).get(account_id)
            if not actors:
                logger.warning(
                    "routing selector %r (%s) has no authorised actor in "
                    "brokers.account_acls[%r][%r] — no one can use this account "
                    "until you add an actor_id there",
                    selector, path, adapter_id, account_id,
                )

        unknown = set(self.cost_aware.tasks) - KNOWN_TASKS
        if unknown:
            raise RoutingConfigError(
                f"brokers.cost_aware.tasks contains unknown task(s) {sorted(unknown)}; "
                f"known tasks are {sorted(KNOWN_TASKS)}"
            )


def _exchange_str(exchange: Any) -> str:
    """Normalise an exchange that may be an enum (``.value``) or a plain string."""
    return exchange.value if hasattr(exchange, "value") else str(exchange)
