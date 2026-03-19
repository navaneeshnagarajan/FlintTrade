"""Strategy flow builder — visual strategy definition as connected nodes.

Absorbs openalgo-flow patterns: N8N-style node graph for defining trading
strategies without code.

Node types:
- SIGNAL: TradingView webhook, ChartInk scan, Python script, cron, manual
- CONDITION: price above/below, OI threshold, time window, indicator value
- ACTION: place order, modify order, cancel order, send alert
- EXIT: stop loss, target, trailing SL, time-based, signal-based

A Flow is a JSON-serializable graph of connected nodes. The FlowBuilder
validates the graph and FlowRunner executes it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any

logger = logging.getLogger("flinttrade.integration.flow_builder")


# ---------------------------------------------------------------------------
# Node types
# ---------------------------------------------------------------------------


class NodeType(StrEnum):
    SIGNAL = "SIGNAL"
    CONDITION = "CONDITION"
    ACTION = "ACTION"
    EXIT = "EXIT"


class SignalSource(StrEnum):
    TRADINGVIEW = "TRADINGVIEW"
    CHARTINK = "CHARTINK"
    PYTHON_SCRIPT = "PYTHON_SCRIPT"
    CRON = "CRON"
    MANUAL = "MANUAL"


class ConditionType(StrEnum):
    PRICE_ABOVE = "PRICE_ABOVE"
    PRICE_BELOW = "PRICE_BELOW"
    OI_THRESHOLD = "OI_THRESHOLD"
    TIME_WINDOW = "TIME_WINDOW"
    INDICATOR_VALUE = "INDICATOR_VALUE"
    PCR_ABOVE = "PCR_ABOVE"
    PCR_BELOW = "PCR_BELOW"


class ActionType(StrEnum):
    PLACE_ORDER = "PLACE_ORDER"
    MODIFY_ORDER = "MODIFY_ORDER"
    CANCEL_ORDER = "CANCEL_ORDER"
    SEND_ALERT = "SEND_ALERT"
    CLOSE_POSITION = "CLOSE_POSITION"


class ExitType(StrEnum):
    STOP_LOSS = "STOP_LOSS"
    TARGET = "TARGET"
    TRAILING_SL = "TRAILING_SL"
    TIME_BASED = "TIME_BASED"
    SIGNAL_BASED = "SIGNAL_BASED"


# ---------------------------------------------------------------------------
# Flow Node
# ---------------------------------------------------------------------------


@dataclass
class FlowNode:
    """A single node in a strategy flow graph."""

    id: str
    node_type: str  # NodeType value
    subtype: str = ""  # SignalSource, ConditionType, ActionType, or ExitType value
    label: str = ""
    config: dict[str, Any] = field(default_factory=dict)
    next_nodes: list[str] = field(default_factory=list)  # IDs of connected nodes

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "node_type": self.node_type,
            "subtype": self.subtype,
            "label": self.label,
            "config": self.config,
            "next_nodes": self.next_nodes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FlowNode:
        return cls(
            id=data["id"],
            node_type=data["node_type"],
            subtype=data.get("subtype", ""),
            label=data.get("label", ""),
            config=data.get("config", {}),
            next_nodes=data.get("next_nodes", []),
        )


# ---------------------------------------------------------------------------
# Flow Definition
# ---------------------------------------------------------------------------


@dataclass
class FlowDefinition:
    """A complete strategy flow — a DAG of connected nodes."""

    name: str
    description: str = ""
    nodes: dict[str, FlowNode] = field(default_factory=dict)
    entry_node_id: str = ""

    def add_node(self, node: FlowNode) -> None:
        self.nodes[node.id] = node

    def connect(self, from_id: str, to_id: str) -> None:
        """Connect one node's output to another node's input."""
        if from_id not in self.nodes:
            raise ValueError(f"Source node '{from_id}' not found")
        if to_id not in self.nodes:
            raise ValueError(f"Target node '{to_id}' not found")
        if to_id not in self.nodes[from_id].next_nodes:
            self.nodes[from_id].next_nodes.append(to_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "entry_node_id": self.entry_node_id,
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FlowDefinition:
        flow = cls(
            name=data["name"],
            description=data.get("description", ""),
            entry_node_id=data.get("entry_node_id", ""),
        )
        for nid, ndata in data.get("nodes", {}).items():
            flow.nodes[nid] = FlowNode.from_dict(ndata)
        return flow

    @classmethod
    def from_json(cls, json_str: str) -> FlowDefinition:
        return cls.from_dict(json.loads(json_str))


# ---------------------------------------------------------------------------
# Flow Validation
# ---------------------------------------------------------------------------


@dataclass
class ValidationError:
    """A single validation issue."""

    node_id: str
    message: str
    severity: str = "error"  # "error" or "warning"


@dataclass
class ValidationResult:
    """Result of flow validation."""

    is_valid: bool = True
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)


def validate_flow(flow: FlowDefinition) -> ValidationResult:
    """Validate a flow definition for structural correctness.

    Checks:
    - At least one node exists
    - Entry node is set and exists
    - Entry node is a SIGNAL type
    - All next_node references are valid
    - No orphan nodes (unreachable from entry)
    - At least one ACTION or EXIT node
    - No self-loops
    """
    result = ValidationResult()

    # Must have nodes
    if not flow.nodes:
        result.is_valid = False
        result.errors.append(ValidationError("", "Flow has no nodes"))
        return result

    # Entry node must exist
    if not flow.entry_node_id:
        result.is_valid = False
        result.errors.append(ValidationError("", "No entry node specified"))
        return result

    if flow.entry_node_id not in flow.nodes:
        result.is_valid = False
        result.errors.append(ValidationError(
            flow.entry_node_id,
            f"Entry node '{flow.entry_node_id}' does not exist",
        ))
        return result

    # Entry must be SIGNAL
    entry = flow.nodes[flow.entry_node_id]
    if entry.node_type != NodeType.SIGNAL.value:
        result.warnings.append(ValidationError(
            entry.id,
            f"Entry node should be SIGNAL type, got {entry.node_type}",
            severity="warning",
        ))

    # Check all connections point to existing nodes
    all_ids = set(flow.nodes.keys())
    for nid, node in flow.nodes.items():
        for target in node.next_nodes:
            if target not in all_ids:
                result.is_valid = False
                result.errors.append(ValidationError(
                    nid,
                    f"Node '{nid}' connects to non-existent node '{target}'",
                ))
            if target == nid:
                result.is_valid = False
                result.errors.append(ValidationError(
                    nid, f"Node '{nid}' has a self-loop",
                ))

    # Check for orphan nodes (not reachable from entry)
    reachable: set[str] = set()
    _walk(flow, flow.entry_node_id, reachable)

    orphans = all_ids - reachable
    for orphan in orphans:
        result.warnings.append(ValidationError(
            orphan,
            f"Node '{orphan}' is not reachable from entry node",
            severity="warning",
        ))

    # Must have at least one ACTION or EXIT
    has_action_or_exit = any(
        n.node_type in (NodeType.ACTION.value, NodeType.EXIT.value)
        for n in flow.nodes.values()
    )
    if not has_action_or_exit:
        result.is_valid = False
        result.errors.append(ValidationError(
            "", "Flow must have at least one ACTION or EXIT node",
        ))

    return result


def _walk(flow: FlowDefinition, node_id: str, visited: set[str]) -> None:
    """Recursively walk the flow graph from a starting node."""
    if node_id in visited:
        return
    visited.add(node_id)
    node = flow.nodes.get(node_id)
    if node:
        for next_id in node.next_nodes:
            _walk(flow, next_id, visited)


# ---------------------------------------------------------------------------
# FlowBuilder — convenience API
# ---------------------------------------------------------------------------


class FlowBuilder:
    """Builder API for constructing strategy flows.

    Usage::

        fb = FlowBuilder("My Strategy")
        sig = fb.add_signal(SignalSource.TRADINGVIEW, label="TV Alert")
        cond = fb.add_condition(ConditionType.PRICE_ABOVE, config={"value": 24000})
        act = fb.add_action(ActionType.PLACE_ORDER, config={"symbol": "NIFTY", "action": "BUY"})
        exit_ = fb.add_exit(ExitType.STOP_LOSS, config={"points": 100})

        fb.connect(sig, cond)
        fb.connect(cond, act)
        fb.connect(act, exit_)

        flow = fb.build()
        result = fb.validate()
    """

    def __init__(self, name: str, description: str = "") -> None:
        self._flow = FlowDefinition(name=name, description=description)
        self._counter = 0

    def _next_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}_{self._counter}"

    def add_signal(
        self,
        source: SignalSource | str,
        label: str = "",
        config: dict[str, Any] | None = None,
    ) -> str:
        """Add a SIGNAL node. Returns node ID."""
        nid = self._next_id("sig")
        subtype = source.value if isinstance(source, SignalSource) else source
        node = FlowNode(
            id=nid, node_type=NodeType.SIGNAL.value,
            subtype=subtype, label=label or subtype,
            config=config or {},
        )
        self._flow.add_node(node)
        # First signal becomes entry
        if not self._flow.entry_node_id:
            self._flow.entry_node_id = nid
        return nid

    def add_condition(
        self,
        condition: ConditionType | str,
        label: str = "",
        config: dict[str, Any] | None = None,
    ) -> str:
        """Add a CONDITION node. Returns node ID."""
        nid = self._next_id("cond")
        subtype = condition.value if isinstance(condition, ConditionType) else condition
        node = FlowNode(
            id=nid, node_type=NodeType.CONDITION.value,
            subtype=subtype, label=label or subtype,
            config=config or {},
        )
        self._flow.add_node(node)
        return nid

    def add_action(
        self,
        action: ActionType | str,
        label: str = "",
        config: dict[str, Any] | None = None,
    ) -> str:
        """Add an ACTION node. Returns node ID."""
        nid = self._next_id("act")
        subtype = action.value if isinstance(action, ActionType) else action
        node = FlowNode(
            id=nid, node_type=NodeType.ACTION.value,
            subtype=subtype, label=label or subtype,
            config=config or {},
        )
        self._flow.add_node(node)
        return nid

    def add_exit(
        self,
        exit_type: ExitType | str,
        label: str = "",
        config: dict[str, Any] | None = None,
    ) -> str:
        """Add an EXIT node. Returns node ID."""
        nid = self._next_id("exit")
        subtype = exit_type.value if isinstance(exit_type, ExitType) else exit_type
        node = FlowNode(
            id=nid, node_type=NodeType.EXIT.value,
            subtype=subtype, label=label or subtype,
            config=config or {},
        )
        self._flow.add_node(node)
        return nid

    def connect(self, from_id: str, to_id: str) -> None:
        """Connect two nodes."""
        self._flow.connect(from_id, to_id)

    def build(self) -> FlowDefinition:
        """Return the built flow definition."""
        return self._flow

    def validate(self) -> ValidationResult:
        """Validate the current flow."""
        return validate_flow(self._flow)

    def to_json(self) -> str:
        """Export flow as JSON."""
        return self._flow.to_json()
