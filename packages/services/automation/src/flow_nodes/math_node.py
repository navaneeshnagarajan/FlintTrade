"""Math operation flow node — performs arithmetic on context variables."""

from __future__ import annotations

from typing import Literal

from .base import FlowContext, FlowNode, FlowResult

MathOperation = Literal["add", "sub", "mul", "div", "mod"]


class MathNode(FlowNode):
    """Perform a binary arithmetic operation on one or more operands.

    Operands may be supplied as:

    - A **literal** numeric value (``int`` or ``float``).
    - A **string** naming a variable in :attr:`FlowContext.variables`.

    For operations with more than two operands (add, mul), the operation is
    applied left-to-right (fold).

    Args:
        operation: One of ``"add"``, ``"sub"``, ``"mul"``, ``"div"``,
            ``"mod"``.
        operands: Two or more values.  Each element is either a number or
            a context variable name (str).
        output_var: If provided, writes the result to this context variable.

    Raises:
        ValueError: If fewer than two operands are supplied.

    Example::

        ctx = FlowContext(variables={"price": 100.0, "qty": 5})
        node = MathNode(operation="mul", operands=["price", "qty"],
                        output_var="notional")
        result = node.execute(ctx)
        assert result.output == 500.0
        assert ctx.get("notional") == 500.0
    """

    node_type = "math"

    def __init__(
        self,
        operation: MathOperation,
        operands: list[int | float | str],
        output_var: str | None = None,
    ) -> None:
        if len(operands) < 2:
            raise ValueError("MathNode requires at least 2 operands")
        self.operation = operation
        self.operands = operands
        self.output_var = output_var

    def _resolve_operand(self, operand: int | float | str, context: FlowContext) -> float:
        """Resolve an operand to a numeric value.

        Args:
            operand: Literal number or variable name string.
            context: Shared flow context for variable lookup.

        Returns:
            Numeric value as a float.

        Raises:
            TypeError: If the resolved value cannot be converted to float.
        """
        if isinstance(operand, (int, float)):
            return float(operand)
        val = context.get(operand)
        if val is None:
            raise TypeError(f"MathNode: variable '{operand}' not found in context")
        return float(val)

    def execute(self, context: FlowContext) -> FlowResult:
        """Perform the arithmetic operation and store the result.

        Args:
            context: Shared flow context.

        Returns:
            :class:`FlowResult` with ``output`` as the numeric result.
        """
        try:
            values = [self._resolve_operand(op, context) for op in self.operands]
        except (TypeError, ValueError) as exc:
            return FlowResult.fail(f"MathNode operand error: {exc}")

        try:
            result: float = values[0]
            for v in values[1:]:
                if self.operation == "add":
                    result += v
                elif self.operation == "sub":
                    result -= v
                elif self.operation == "mul":
                    result *= v
                elif self.operation == "div":
                    if v == 0:
                        return FlowResult.fail("MathNode: division by zero")
                    result /= v
                elif self.operation == "mod":
                    if v == 0:
                        return FlowResult.fail("MathNode: modulo by zero")
                    result %= v
                else:
                    return FlowResult.fail(f"MathNode: unknown operation '{self.operation}'")
        except Exception as exc:  # noqa: BLE001
            return FlowResult.fail(f"MathNode arithmetic error: {exc}")

        if self.output_var:
            context.set(self.output_var, result)

        return FlowResult.ok(output=result)
