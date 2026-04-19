"""Logic gate flow nodes: AND, OR, NOT, XOR.

Each gate reads boolean values from the shared :class:`FlowContext` by
variable name and produces a boolean ``output`` in its :class:`FlowResult`.
"""

from __future__ import annotations

from .base import FlowContext, FlowNode, FlowResult


class AndGate(FlowNode):
    """Boolean AND of two or more named context variables.

    All inputs must evaluate to ``True`` for the output to be ``True``.

    Args:
        inputs: List of variable names in :attr:`FlowContext.variables`
            to AND together.  An empty list produces ``True`` (vacuous
            truth, consistent with Python's ``all()``).

    Example::

        ctx = FlowContext(variables={"a": True, "b": False})
        gate = AndGate(inputs=["a", "b"])
        result = gate.execute(ctx)
        assert result.output is False
    """

    node_type = "and_gate"

    def __init__(self, inputs: list[str]) -> None:
        self.inputs = inputs

    def execute(self, context: FlowContext) -> FlowResult:
        """Evaluate AND over all named inputs.

        Args:
            context: Shared flow context.

        Returns:
            ``FlowResult`` with ``output`` as a bool.
        """
        try:
            result = all(bool(context.get(k)) for k in self.inputs)
        except Exception as exc:  # noqa: BLE001
            return FlowResult.fail(f"AndGate error: {exc}")
        return FlowResult.ok(output=result)


class OrGate(FlowNode):
    """Boolean OR of two or more named context variables.

    At least one input must evaluate to ``True`` for the output to be ``True``.

    Args:
        inputs: List of variable names in :attr:`FlowContext.variables`.
            An empty list produces ``False``.
    """

    node_type = "or_gate"

    def __init__(self, inputs: list[str]) -> None:
        self.inputs = inputs

    def execute(self, context: FlowContext) -> FlowResult:
        """Evaluate OR over all named inputs.

        Args:
            context: Shared flow context.

        Returns:
            ``FlowResult`` with ``output`` as a bool.
        """
        try:
            result = any(bool(context.get(k)) for k in self.inputs)
        except Exception as exc:  # noqa: BLE001
            return FlowResult.fail(f"OrGate error: {exc}")
        return FlowResult.ok(output=result)


class NotGate(FlowNode):
    """Boolean NOT of a single named context variable.

    Args:
        input_var: Variable name in :attr:`FlowContext.variables` to negate.
    """

    node_type = "not_gate"

    def __init__(self, input_var: str) -> None:
        self.input_var = input_var

    def execute(self, context: FlowContext) -> FlowResult:
        """Evaluate NOT for the named input.

        Args:
            context: Shared flow context.

        Returns:
            ``FlowResult`` with ``output`` as a bool.
        """
        try:
            result = not bool(context.get(self.input_var))
        except Exception as exc:  # noqa: BLE001
            return FlowResult.fail(f"NotGate error: {exc}")
        return FlowResult.ok(output=result)


class XorGate(FlowNode):
    """Boolean XOR of exactly two named context variables.

    Outputs ``True`` when the two inputs differ.

    Args:
        input_a: First variable name.
        input_b: Second variable name.
    """

    node_type = "xor_gate"

    def __init__(self, input_a: str, input_b: str) -> None:
        self.input_a = input_a
        self.input_b = input_b

    def execute(self, context: FlowContext) -> FlowResult:
        """Evaluate XOR for the two named inputs.

        Args:
            context: Shared flow context.

        Returns:
            ``FlowResult`` with ``output`` as a bool.
        """
        try:
            a = bool(context.get(self.input_a))
            b = bool(context.get(self.input_b))
            result = a ^ b
        except Exception as exc:  # noqa: BLE001
            return FlowResult.fail(f"XorGate error: {exc}")
        return FlowResult.ok(output=result)
