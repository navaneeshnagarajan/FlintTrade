"""Flow Visual Builder — high-level flow management API.

Provides :class:`FlowManager` for registering, serialising, and executing
named automation flows built from the :mod:`flow_nodes` library.

Flows are stored as JSON specs in memory and optionally persisted to disk.
The JSON schema mirrors the :class:`~flow_nodes.executor.NodeSpec` structure
so that the React Flow Builder widget can round-trip flow definitions.

Example JSON spec::

    {
        "flow_id": "morning_alert",
        "nodes": [
            {
                "node_id": "check_signal",
                "node_type": "math",
                "operation": "add",
                "operands": ["open_price", 10],
                "output_var": "target"
            },
            {
                "node_id": "send_alert",
                "node_type": "alert",
                "channel": "log",
                "message": "Target reached: {target}",
                "depends_on": ["check_signal"]
            }
        ]
    }
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .flow_nodes import (
    AlertNode,
    AndGate,
    DelayNode,
    FlowNode,
    HTTPRequestNode,
    IfThenElseNode,
    MathNode,
    NotGate,
    OrderNode,
    OrGate,
    SwitchNode,
    XorGate,
)
from .flow_nodes.base import FlowContext
from .flow_nodes.executor import FlowExecutor, FlowRunResult, NodeSpec

logger = logging.getLogger("flinttrade.automation.flows")


class FlowError(Exception):
    """Raised when a flow operation cannot be completed."""


# ---------------------------------------------------------------------------
# Flow definition dataclass
# ---------------------------------------------------------------------------


@dataclass
class FlowDefinition:
    """A named, serialisable automation flow.

    Attributes:
        flow_id: Unique identifier for this flow.
        name: Human-readable display name.
        description: Optional description.
        spec: Raw JSON-compatible dict representing the flow node graph.
        enabled: Whether the flow is active.
        tags: Optional list of category/label strings.
    """

    flow_id: str
    name: str
    description: str = ""
    spec: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict."""
        return {
            "flow_id": self.flow_id,
            "name": self.name,
            "description": self.description,
            "spec": self.spec,
            "enabled": self.enabled,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FlowDefinition:
        """Deserialise from a dict.

        Args:
            data: Dict representation (as produced by :meth:`to_dict`).

        Returns:
            Populated :class:`FlowDefinition`.
        """
        return cls(
            flow_id=data.get("flow_id", str(uuid.uuid4())),
            name=data.get("name", "Unnamed Flow"),
            description=data.get("description", ""),
            spec=data.get("spec", {}),
            enabled=data.get("enabled", True),
            tags=data.get("tags", []),
        )


# ---------------------------------------------------------------------------
# Node builder — converts JSON spec dicts to FlowNode instances
# ---------------------------------------------------------------------------


def _build_node_from_spec(node_spec: dict[str, Any]) -> FlowNode:
    """Instantiate a :class:`FlowNode` from a JSON spec dict.

    Currently supports stateless nodes only (logic gates, delay, math,
    alert, order).  HTTP and conditional nodes require additional wiring
    that should be injected by the caller.

    Args:
        node_spec: Dict with at minimum ``"node_type"`` and node-specific
            parameter keys.

    Returns:
        A ready-to-execute :class:`FlowNode` instance.

    Raises:
        FlowError: If the ``node_type`` is unknown or parameters are invalid.
    """
    nt = node_spec.get("node_type", "")
    try:
        if nt == "and_gate":
            return AndGate(inputs=node_spec["inputs"])
        if nt == "or_gate":
            return OrGate(inputs=node_spec["inputs"])
        if nt == "not_gate":
            return NotGate(input_var=node_spec["input_var"])
        if nt == "xor_gate":
            return XorGate(input_a=node_spec["input_a"], input_b=node_spec["input_b"])
        if nt == "delay":
            return DelayNode(seconds=float(node_spec["seconds"]))
        if nt == "math":
            return MathNode(
                operation=node_spec["operation"],
                operands=node_spec["operands"],
                output_var=node_spec.get("output_var"),
            )
        if nt == "alert":
            return AlertNode(
                channel=node_spec["channel"],
                message=node_spec["message"],
                # channel_fn must be injected externally — not serialisable
                channel_fn=node_spec.get("_channel_fn"),
            )
        if nt == "http_request":
            return HTTPRequestNode(
                url=node_spec["url"],
                method=node_spec.get("method", "GET"),
                headers=node_spec.get("headers", {}),
                body=node_spec.get("body"),
                output_var=node_spec.get("output_var"),
                timeout=float(node_spec.get("timeout", 10.0)),
            )
        if nt == "if_then_else":
            condition = node_spec.get("condition_var") or node_spec.get("condition", "")
            return IfThenElseNode(
                condition=condition,
                output_var=node_spec.get("output_var"),
            )
        if nt == "switch":
            return SwitchNode(
                value=node_spec.get("value_var") or node_spec.get("value", ""),
                cases={k: [] for k in node_spec.get("cases", {})},
                output_var=node_spec.get("output_var"),
            )
        if nt == "order":
            place_fn = node_spec.get("_place_order_fn")
            if place_fn is None:
                raise FlowError("OrderNode requires '_place_order_fn' to be injected")
            return OrderNode(
                symbol=node_spec["symbol"],
                exchange=node_spec["exchange"],
                qty=node_spec["qty"],
                action=node_spec["action"],
                place_order_fn=place_fn,
                order_type=node_spec.get("order_type", "MARKET"),
                price=node_spec.get("price"),
                output_var=node_spec.get("output_var"),
                product=node_spec.get("product", "MIS"),
                strategy=node_spec.get("strategy", "FlowEngine"),
            )
    except KeyError as exc:
        raise FlowError(f"Missing parameter {exc} for node_type '{nt}'") from exc
    except Exception as exc:
        raise FlowError(f"Failed to build node '{nt}': {exc}") from exc

    raise FlowError(f"Unknown node_type: '{nt}'")


# ---------------------------------------------------------------------------
# FlowManager
# ---------------------------------------------------------------------------


class FlowManager:
    """Register, store, and execute named automation flows.

    Thread-safe.  Flows can be persisted to a JSON file and reloaded
    across restarts.

    Args:
        storage_path: Optional path to a JSON file for persistence.  When
            ``None``, flows are stored in memory only.

    Example::

        manager = FlowManager()
        flow = manager.register(
            name="My Alert Flow",
            spec={"nodes": [{"node_id": "n1", "node_type": "alert",
                             "channel": "log", "message": "Hello!"}]},
        )
        result = manager.run(flow.flow_id)
        assert result.success
    """

    def __init__(self, storage_path: Path | str | None = None) -> None:
        self._flows: dict[str, FlowDefinition] = {}
        self._lock = threading.Lock()
        self._storage_path = Path(storage_path) if storage_path else None
        if self._storage_path and self._storage_path.exists():
            self._load_from_disk()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        spec: dict[str, Any],
        description: str = "",
        flow_id: str | None = None,
        enabled: bool = True,
        tags: list[str] | None = None,
    ) -> FlowDefinition:
        """Register a new flow definition.

        Args:
            name: Human-readable flow name.
            spec: JSON-compatible dict describing the node graph.
            description: Optional description.
            flow_id: Override auto-generated UUID.
            enabled: Whether the flow is initially active.
            tags: Optional category labels.

        Returns:
            The registered :class:`FlowDefinition`.
        """
        fid = flow_id or str(uuid.uuid4())
        flow = FlowDefinition(
            flow_id=fid,
            name=name,
            description=description,
            spec=spec,
            enabled=enabled,
            tags=tags or [],
        )
        with self._lock:
            self._flows[fid] = flow
        logger.info("Registered flow '%s' (id=%s)", name, fid)
        if self._storage_path:
            self._save_to_disk()
        return flow

    def unregister(self, flow_id: str) -> None:
        """Remove a flow by ID.

        Args:
            flow_id: UUID of the flow to remove.

        Raises:
            FlowError: If the flow does not exist.
        """
        with self._lock:
            if flow_id not in self._flows:
                raise FlowError(f"Flow '{flow_id}' not found")
            del self._flows[flow_id]
        if self._storage_path:
            self._save_to_disk()

    def get(self, flow_id: str) -> FlowDefinition:
        """Return a flow by ID.

        Args:
            flow_id: UUID of the flow.

        Returns:
            The matching :class:`FlowDefinition`.

        Raises:
            FlowError: If the flow does not exist.
        """
        with self._lock:
            flow = self._flows.get(flow_id)
        if flow is None:
            raise FlowError(f"Flow '{flow_id}' not found")
        return flow

    def list_flows(self, enabled_only: bool = False) -> list[FlowDefinition]:
        """Return all registered flows.

        Args:
            enabled_only: If ``True``, return only enabled flows.

        Returns:
            List of :class:`FlowDefinition` objects.
        """
        with self._lock:
            flows = list(self._flows.values())
        if enabled_only:
            flows = [f for f in flows if f.enabled]
        return flows

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run(
        self,
        flow_id: str,
        initial_variables: dict[str, Any] | None = None,
        node_overrides: dict[str, Any] | None = None,
    ) -> FlowRunResult:
        """Execute a registered flow by ID.

        Args:
            flow_id: UUID of the flow to execute.
            initial_variables: Variables to pre-populate the context with.
            node_overrides: Dict of ``node_id`` → additional spec values
                (e.g. to inject ``_place_order_fn`` at runtime).

        Returns:
            :class:`FlowRunResult` summarising execution.

        Raises:
            FlowError: If the flow does not exist or is disabled.
        """
        flow = self.get(flow_id)
        if not flow.enabled:
            raise FlowError(f"Flow '{flow_id}' is disabled")

        raw_nodes: list[dict[str, Any]] = flow.spec.get("nodes", [])
        if not raw_nodes:
            logger.warning("Flow '%s' has no nodes — returning empty success", flow_id)
            return FlowRunResult(success=True, outputs={}, context=FlowContext())

        specs: list[NodeSpec] = []
        for raw in raw_nodes:
            merged = dict(raw)
            if node_overrides and raw.get("node_id") in node_overrides:
                merged.update(node_overrides[raw["node_id"]])
            try:
                node = _build_node_from_spec(merged)
            except FlowError as exc:
                return FlowRunResult(
                    success=False,
                    outputs={},
                    failed_node=merged.get("node_id", "?"),
                    error=str(exc),
                )
            spec = NodeSpec(
                node_id=merged.get("node_id", str(uuid.uuid4())),
                node=node,
                depends_on=merged.get("depends_on", []),
            )
            specs.append(spec)

        executor = FlowExecutor()
        context = FlowContext(variables=initial_variables or {})
        try:
            return executor.run_dag(specs, context=context)
        except ValueError as exc:
            return FlowRunResult(
                success=False,
                outputs={},
                error=str(exc),
                context=context,
            )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_to_disk(self) -> None:
        """Persist all flow definitions to JSON.  Called under the lock."""
        assert self._storage_path is not None
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = [f.to_dict() for f in self._flows.values()]
        with open(self._storage_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        logger.debug("Saved %d flow(s) to %s", len(data), self._storage_path)

    def _load_from_disk(self) -> None:
        """Load flow definitions from JSON.  Called during __init__."""
        assert self._storage_path is not None
        try:
            with open(self._storage_path, encoding="utf-8") as fh:
                data: list[dict[str, Any]] = json.load(fh)
            for item in data:
                fd = FlowDefinition.from_dict(item)
                self._flows[fd.flow_id] = fd
            logger.info("Loaded %d flow(s) from %s", len(data), self._storage_path)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not load flows from %s: %s", self._storage_path, exc)
