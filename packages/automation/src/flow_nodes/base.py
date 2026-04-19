"""Base types for the FlintTrade flow node system.

All flow nodes inherit from :class:`FlowNode` and communicate through
:class:`FlowContext` (shared mutable state) and :class:`FlowResult`
(the typed return value of each node execution).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FlowContext:
    """Shared execution context passed between flow nodes in a DAG.

    Nodes may read previous outputs from :attr:`outputs` and write their
    own output under their ``node_id``.  The :attr:`variables` dict holds
    named values that nodes can get and set by name (e.g. the result of
    a previous MathNode or HTTPRequestNode).

    Attributes:
        variables: Named values shared across all nodes in the flow.
        outputs: Mapping of ``node_id`` to the :class:`FlowResult` produced
            by that node.
        metadata: Arbitrary metadata injected by the flow runner (e.g.
            trigger source, account_id, strategy_name).
    """

    variables: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, "FlowResult"] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def set(self, key: str, value: Any) -> None:
        """Write a named variable into the shared context.

        Args:
            key: Variable name.
            value: Any JSON-serialisable value.
        """
        self.variables[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Read a named variable from the shared context.

        Args:
            key: Variable name.
            default: Value returned when *key* is absent.

        Returns:
            The stored value, or *default*.
        """
        return self.variables.get(key, default)


@dataclass
class FlowResult:
    """The outcome of executing a single :class:`FlowNode`.

    Attributes:
        success: ``True`` if the node executed without error.
        output: The primary output value produced by the node.
        error: Error message if ``success`` is ``False``, else ``None``.
        branch: For branching nodes (e.g. IfThenElse, Switch), the name
            of the branch that was taken (e.g. ``"true"``, ``"false"``,
            or a case key).  ``None`` for non-branching nodes.
        metadata: Optional extra data attached by the node.
    """

    success: bool
    output: Any = None
    error: str | None = None
    branch: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(
        cls,
        output: Any = None,
        branch: str | None = None,
        **metadata: Any,
    ) -> "FlowResult":
        """Convenience factory for a successful result.

        Args:
            output: The node's primary output value.
            branch: Branch taken (for conditional nodes).
            **metadata: Arbitrary key-value pairs stored in ``metadata``.

        Returns:
            :class:`FlowResult` with ``success=True``.
        """
        return cls(success=True, output=output, branch=branch, metadata=dict(metadata))

    @classmethod
    def fail(cls, error: str, **metadata: Any) -> "FlowResult":
        """Convenience factory for a failed result.

        Args:
            error: Human-readable error description.
            **metadata: Arbitrary key-value pairs stored in ``metadata``.

        Returns:
            :class:`FlowResult` with ``success=False``.
        """
        return cls(success=False, error=error, metadata=dict(metadata))


class FlowNode(ABC):
    """Abstract base class for all flow nodes.

    Every concrete node must declare a unique :attr:`node_type` class
    variable and implement :meth:`execute`.

    Attributes:
        node_type: Short string identifier (e.g. ``"and_gate"``).
        node_id: Instance identifier set by the flow runner.  May be
            ``None`` until attached to a :class:`FlowExecutor`.
    """

    node_type: str = "base"
    node_id: str | None = None

    @abstractmethod
    def execute(self, context: FlowContext) -> FlowResult:
        """Execute the node's logic and return a result.

        Args:
            context: The shared flow context.  Nodes may read from
                ``context.variables`` and ``context.outputs``, and should
                write their output back to ``context`` if downstream nodes
                need to consume it by name.

        Returns:
            :class:`FlowResult` describing success or failure.
        """

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(node_id={self.node_id!r})"
