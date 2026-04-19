"""Order placement flow node — places a market or limit order via OpenAlgo."""

from __future__ import annotations

from typing import Any, Callable, Literal

from .base import FlowContext, FlowNode, FlowResult

OrderAction = Literal["BUY", "SELL"]


class OrderNode(FlowNode):
    """Place a trading order through a provided order function.

    This node does NOT call OpenAlgo directly.  Instead it accepts a
    *place_order_fn* callable so that the flow runner can inject the
    correct client (live, sandbox, paper) without coupling the node to a
    specific client implementation.

    The order parameters may contain ``{variable}`` placeholder strings that
    are resolved from :attr:`FlowContext.variables` at execution time.

    Args:
        symbol: Instrument symbol (e.g. ``"NIFTY25JAN25FUT"``).
        exchange: Exchange code (e.g. ``"NFO"``, ``"NSE"``, ``"MCX"``).
        qty: Quantity.  May be a literal int or a variable name string.
        action: ``"BUY"`` or ``"SELL"``.
        place_order_fn: Callable with signature
            ``(params: dict[str, Any]) -> Any``.  Should forward the order
            to OpenAlgo via :class:`~core.openalgo_client.OpenAlgoClient`.
        order_type: ``"MARKET"`` or ``"LIMIT"``.  Defaults to ``"MARKET"``.
        price: Limit price.  May be a literal float or a variable name string.
            Ignored when *order_type* is ``"MARKET"``.
        output_var: If provided, writes the order response to this context
            variable.
        product: Product type (e.g. ``"MIS"``, ``"NRML"``).  Defaults to
            ``"MIS"``.
        strategy: Strategy name tag forwarded in the order payload.

    Example::

        mock_fn = lambda params: {"status": "success", "orderid": "ORD001"}
        node = OrderNode(
            symbol="NIFTY", exchange="NFO", qty=50,
            action="BUY", place_order_fn=mock_fn,
        )
        result = node.execute(FlowContext())
        assert result.success
    """

    node_type = "order"

    def __init__(
        self,
        symbol: str,
        exchange: str,
        qty: int | str,
        action: OrderAction,
        place_order_fn: Callable[[dict[str, Any]], Any],
        order_type: Literal["MARKET", "LIMIT"] = "MARKET",
        price: float | str | None = None,
        output_var: str | None = None,
        product: str = "MIS",
        strategy: str = "FlowEngine",
    ) -> None:
        self.symbol = symbol
        self.exchange = exchange
        self.qty = qty
        self.action = action
        self.place_order_fn = place_order_fn
        self.order_type = order_type
        self.price = price
        self.output_var = output_var
        self.product = product
        self.strategy = strategy

    def _resolve_str(self, value: str | Any, context: FlowContext) -> Any:
        """Resolve a value that may be a variable name or a literal.

        Args:
            value: A string (variable name lookup) or literal numeric value.
            context: Shared flow context.

        Returns:
            The resolved value.
        """
        if isinstance(value, str):
            resolved = context.get(value, value)
            return resolved
        return value

    def execute(self, context: FlowContext) -> FlowResult:
        """Build and place the order.

        Args:
            context: Shared flow context.

        Returns:
            :class:`FlowResult` with ``output`` as the raw response from
            *place_order_fn*.
        """
        try:
            resolved_symbol = str(self._resolve_str(self.symbol, context))
            resolved_exchange = str(self._resolve_str(self.exchange, context))
            resolved_qty = int(self._resolve_str(self.qty, context))
            resolved_action = str(self._resolve_str(self.action, context)).upper()

            params: dict[str, Any] = {
                "symbol": resolved_symbol,
                "exchange": resolved_exchange,
                "action": resolved_action,
                "quantity": str(resolved_qty),
                "pricetype": self.order_type,
                "product": self.product,
                "strategy": self.strategy,
            }

            if self.order_type == "LIMIT" and self.price is not None:
                params["price"] = str(self._resolve_str(self.price, context))

        except (TypeError, ValueError) as exc:
            return FlowResult.fail(f"OrderNode parameter error: {exc}")

        try:
            response = self.place_order_fn(params)
        except Exception as exc:  # noqa: BLE001
            return FlowResult.fail(f"OrderNode place_order_fn error: {exc}")

        if self.output_var:
            context.set(self.output_var, response)

        return FlowResult.ok(output=response, params=params)
