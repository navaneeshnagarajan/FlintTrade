"""FlowExecutor — executes a DAG of FlowNodes in topological order.

The executor accepts a JSON-compatible spec or a pre-built list of
:class:`FlowNode` objects with explicit dependency declarations.  For
simple linear flows, nodes are executed in the order they are provided.
For DAG flows, a topological sort is applied before execution.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .base import FlowContext, FlowNode, FlowResult

logger = logging.getLogger("flinttrade.automation.flow_executor")


@dataclass
class NodeSpec:
    """Specification of a single node in a flow DAG.

    Attributes:
        node_id: Unique identifier for this node within the flow.
        node: The :class:`FlowNode` instance to execute.
        depends_on: IDs of nodes that must complete successfully before
            this node can run.  An empty list means this node has no
            dependencies (it is a root node).
    """

    node_id: str
    node: FlowNode
    depends_on: list[str] = field(default_factory=list)


@dataclass
class FlowRunResult:
    """Summary of a complete flow execution.

    Attributes:
        success: ``True`` if every node completed without error.
        outputs: Mapping of ``node_id`` to its :class:`FlowResult`.
        failed_node: ID of the first node that failed, or ``None``.
        error: Error description from the failed node, or ``None``.
        context: The final :class:`FlowContext` after all nodes ran.
    """

    success: bool
    outputs: dict[str, FlowResult]
    failed_node: str | None = None
    error: str | None = None
    context: FlowContext = field(default_factory=FlowContext)


class FlowExecutor:
    """Execute a flow DAG in topological order.

    Nodes are executed sequentially within each topological level.  The
    executor stops at the first failure unless *continue_on_error* is set.

    Args:
        continue_on_error: If ``True``, execution continues even if a node
            fails.  Defaults to ``False``.

    Example::

        from packages.automation.src.flow_nodes import (
            FlowExecutor, MathNode, AlertNode, FlowContext
        )

        math_node = MathNode("add", [10, 20], output_var="total")
        alert_node = AlertNode("log", "Total is {total}")

        executor = FlowExecutor()
        result = executor.run_linear([math_node, alert_node])
        assert result.success
    """

    def __init__(self, continue_on_error: bool = False) -> None:
        self.continue_on_error = continue_on_error

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_linear(
        self,
        nodes: list[FlowNode],
        context: FlowContext | None = None,
        initial_variables: dict[str, Any] | None = None,
    ) -> FlowRunResult:
        """Execute a simple linear (no-branch dependency) list of nodes.

        Nodes are executed in the order provided.  Each node receives a
        ``node_id`` equal to its index in the list if not already set.

        Args:
            nodes: Ordered list of :class:`FlowNode` objects.
            context: Pre-populated context.  A fresh :class:`FlowContext`
                is created when ``None``.
            initial_variables: Variables to seed the context with before
                execution starts.

        Returns:
            :class:`FlowRunResult` summarising the execution.
        """
        ctx = context or FlowContext()
        if initial_variables:
            ctx.variables.update(initial_variables)

        specs = [
            NodeSpec(
                node_id=node.node_id or f"node_{i}",
                node=node,
            )
            for i, node in enumerate(nodes)
        ]
        for spec in specs:
            spec.node.node_id = spec.node_id

        return self._execute_specs(specs, ctx)

    def run_dag(
        self,
        specs: list[NodeSpec],
        context: FlowContext | None = None,
        initial_variables: dict[str, Any] | None = None,
    ) -> FlowRunResult:
        """Execute a DAG of nodes in topological order.

        Args:
            specs: List of :class:`NodeSpec` objects with dependency
                declarations.
            context: Pre-populated context.  A fresh :class:`FlowContext`
                is created when ``None``.
            initial_variables: Variables to seed the context with before
                execution starts.

        Returns:
            :class:`FlowRunResult` summarising the execution.

        Raises:
            ValueError: If the dependency graph contains a cycle.
        """
        ctx = context or FlowContext()
        if initial_variables:
            ctx.variables.update(initial_variables)

        try:
            ordered = self._topological_sort(specs)
        except ValueError as exc:
            return FlowRunResult(
                success=False,
                outputs={},
                error=str(exc),
                context=ctx,
            )
        for spec in ordered:
            spec.node.node_id = spec.node_id

        return self._execute_specs(ordered, ctx)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _execute_specs(
        self,
        specs: list[NodeSpec],
        context: FlowContext,
    ) -> FlowRunResult:
        """Execute a pre-ordered list of NodeSpec objects.

        Args:
            specs: Ordered :class:`NodeSpec` list (topologically sorted or
                linear).
            context: Shared flow context.

        Returns:
            :class:`FlowRunResult` with per-node outputs.
        """
        outputs: dict[str, FlowResult] = {}

        for spec in specs:
            logger.debug("Executing node %s (%s)", spec.node_id, spec.node.node_type)
            try:
                result = spec.node.execute(context)
            except Exception as exc:  # noqa: BLE001
                result = FlowResult.fail(f"Unhandled exception in {spec.node_id}: {exc}")

            outputs[spec.node_id] = result
            context.outputs[spec.node_id] = result

            if not result.success:
                logger.warning(
                    "Node %s failed: %s", spec.node_id, result.error
                )
                if not self.continue_on_error:
                    return FlowRunResult(
                        success=False,
                        outputs=outputs,
                        failed_node=spec.node_id,
                        error=result.error,
                        context=context,
                    )

        all_success = all(r.success for r in outputs.values())
        return FlowRunResult(
            success=all_success,
            outputs=outputs,
            context=context,
        )

    @staticmethod
    def _topological_sort(specs: list[NodeSpec]) -> list[NodeSpec]:
        """Return a topologically sorted copy of *specs*.

        Uses Kahn's algorithm.

        Args:
            specs: Nodes with dependency declarations.

        Returns:
            Sorted list of :class:`NodeSpec` objects (roots first).

        Raises:
            ValueError: If the dependency graph contains a cycle.
        """
        by_id: dict[str, NodeSpec] = {s.node_id: s for s in specs}
        in_degree: dict[str, int] = {s.node_id: 0 for s in specs}
        dependents: dict[str, list[str]] = {s.node_id: [] for s in specs}

        for spec in specs:
            for dep in spec.depends_on:
                if dep not in by_id:
                    raise ValueError(
                        f"Node '{spec.node_id}' depends on unknown node '{dep}'"
                    )
                in_degree[spec.node_id] += 1
                dependents[dep].append(spec.node_id)

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        sorted_ids: list[str] = []

        while queue:
            current = queue.pop(0)
            sorted_ids.append(current)
            for dependent in dependents[current]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(sorted_ids) != len(specs):
            cycle_nodes = [nid for nid, deg in in_degree.items() if deg > 0]
            raise ValueError(
                f"Dependency cycle detected among nodes: {cycle_nodes}"
            )

        return [by_id[nid] for nid in sorted_ids]
