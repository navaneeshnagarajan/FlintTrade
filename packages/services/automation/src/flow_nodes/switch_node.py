"""Switch/case flow node — routes execution to one of N named branches."""

from __future__ import annotations

from typing import Any, Callable

from .base import FlowContext, FlowNode, FlowResult


class SwitchNode(FlowNode):
    """Route execution to a named branch based on a key value.

    The *value* is resolved either from a :attr:`FlowContext` variable name
    or via a callable.  The resolved value is matched against ``cases``.
    If no match is found, the *default* branch (if provided) is executed.

    Args:
        value: A variable name string or a callable
            ``(context: FlowContext) -> Any`` that returns the key to match.
        cases: Mapping of case key (str) to a list of :class:`FlowNode` objects.
        default: Nodes to execute when no case matches.  ``None`` means no
            default branch.
        output_var: If provided, writes the final output to this context
            variable.

    Example::

        ctx = FlowContext(variables={"mode": "buy"})
        node = SwitchNode(value="mode", cases={"buy": [...], "sell": [...]})
        result = node.execute(ctx)
        assert result.branch == "buy"
    """

    node_type = "switch"

    def __init__(
        self,
        value: str | Callable[[FlowContext], Any],
        cases: dict[str, list[FlowNode]],
        default: list[FlowNode] | None = None,
        output_var: str | None = None,
    ) -> None:
        self.value = value
        self.cases = cases
        self.default = default  # None means no default branch; [] means empty default branch
        self.output_var = output_var

    def execute(self, context: FlowContext) -> FlowResult:
        """Resolve the value and execute the matching branch.

        Args:
            context: Shared flow context.

        Returns:
            :class:`FlowResult` with ``branch`` set to the matched case key,
            or ``"default"`` if no case matched.  ``branch`` is ``None`` when
            no case matches and there is no default.
        """
        try:
            if callable(self.value):
                key: Any = self.value(context)
            else:
                key = context.get(self.value)
        except Exception as exc:  # noqa: BLE001
            return FlowResult.fail(f"SwitchNode value resolution error: {exc}")

        str_key = str(key) if key is not None else ""
        if str_key in self.cases:
            branch_name = str_key
            nodes = self.cases[str_key]
        elif self.default is not None:
            branch_name = "default"
            nodes = self.default
        else:
            return FlowResult.ok(output=None, branch=None, matched=False)

        last_result: FlowResult = FlowResult.ok(output=None, branch=branch_name)
        for node in nodes:
            try:
                last_result = node.execute(context)
                if node.node_id:
                    context.outputs[node.node_id] = last_result
                if not last_result.success:
                    return FlowResult.fail(
                        f"SwitchNode branch '{branch_name}' failed at "
                        f"{node!r}: {last_result.error}"
                    )
            except Exception as exc:  # noqa: BLE001
                return FlowResult.fail(
                    f"SwitchNode branch '{branch_name}' raised: {exc}"
                )

        output: Any = last_result.output
        if self.output_var:
            context.set(self.output_var, output)

        return FlowResult.ok(output=output, branch=branch_name)
