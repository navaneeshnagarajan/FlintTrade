"""IfThenElse conditional flow node."""

from __future__ import annotations

from typing import Any, Callable

from .base import FlowContext, FlowNode, FlowResult


class IfThenElseNode(FlowNode):
    """Evaluate a condition and route execution to a true or false branch.

    The condition may be supplied as:

    - A **callable** ``(context: FlowContext) -> bool``.
    - A **string** naming a variable in :attr:`FlowContext.variables` whose
      truthiness determines the branch.

    The branches themselves are optional lists of :class:`FlowNode` objects.
    If a branch list is provided, each node in that branch is executed in
    order with the same context.  The final :class:`FlowResult` from the
    branch is returned; if the branch is empty, a successful result with
    ``output=None`` is returned.

    Args:
        condition: A callable or variable name string.
        true_branch: Nodes to execute when the condition is truthy.
        false_branch: Nodes to execute when the condition is falsy.
        output_var: If provided, writes the branch result's output to this
            variable in :attr:`FlowContext.variables`.

    Example::

        ctx = FlowContext(variables={"signal": True})
        node = IfThenElseNode(condition="signal")
        result = node.execute(ctx)
        assert result.branch == "true"
    """

    node_type = "if_then_else"

    def __init__(
        self,
        condition: Callable[[FlowContext], bool] | str,
        true_branch: list[FlowNode] | None = None,
        false_branch: list[FlowNode] | None = None,
        output_var: str | None = None,
    ) -> None:
        self.condition = condition
        self.true_branch = true_branch or []
        self.false_branch = false_branch or []
        self.output_var = output_var

    def execute(self, context: FlowContext) -> FlowResult:
        """Evaluate condition and execute the chosen branch.

        Args:
            context: Shared flow context.

        Returns:
            :class:`FlowResult` with ``branch`` set to ``"true"`` or
            ``"false"``.
        """
        try:
            if callable(self.condition):
                cond_value: bool = bool(self.condition(context))
            else:
                cond_value = bool(context.get(self.condition))
        except Exception as exc:  # noqa: BLE001
            return FlowResult.fail(f"IfThenElseNode condition error: {exc}")

        branch_name = "true" if cond_value else "false"
        nodes = self.true_branch if cond_value else self.false_branch

        last_result: FlowResult = FlowResult.ok(output=None, branch=branch_name)
        for node in nodes:
            try:
                last_result = node.execute(context)
                if node.node_id:
                    context.outputs[node.node_id] = last_result
                if not last_result.success:
                    return FlowResult.fail(
                        f"IfThenElseNode branch '{branch_name}' failed at "
                        f"{node!r}: {last_result.error}",
                    )
            except Exception as exc:  # noqa: BLE001
                return FlowResult.fail(
                    f"IfThenElseNode branch '{branch_name}' raised: {exc}"
                )

        output: Any = last_result.output
        if self.output_var:
            context.set(self.output_var, output)

        return FlowResult.ok(output=output, branch=branch_name)
