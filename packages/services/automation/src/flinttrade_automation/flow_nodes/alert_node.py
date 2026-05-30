"""Alert flow node — sends a message via Telegram or email channels."""

from __future__ import annotations

from typing import Any, Callable, Literal

from .base import FlowContext, FlowNode, FlowResult

AlertChannel = Literal["telegram", "email", "log"]


class AlertNode(FlowNode):
    """Send an alert through a configured channel.

    The *message* may contain ``{variable}`` placeholders that are resolved
    from :attr:`FlowContext.variables` at execution time.

    Channels:

    - ``"telegram"``: Calls ``channel_fn(message: str)`` which should be a
      bound method of a :class:`~automation.telegram_bot.TelegramBot`
      instance.
    - ``"email"``: Calls ``channel_fn(message: str)`` with an email-capable
      callable.
    - ``"log"``: Writes to the Python logger (always available, no
      *channel_fn* required).

    Args:
        channel: Delivery channel.
        message: Message template string.  Supports ``str.format_map``
            substitution from ``context.variables``.
        channel_fn: Callable that accepts ``(message: str)`` and delivers
            the alert.  Required for ``"telegram"`` and ``"email"`` channels.

    Example::

        node = AlertNode(
            channel="log",
            message="Signal fired for {symbol} at {price}",
        )
        result = node.execute(FlowContext(variables={"symbol": "NIFTY", "price": 24000}))
        assert result.success
    """

    node_type = "alert"

    def __init__(
        self,
        channel: AlertChannel,
        message: str,
        channel_fn: Callable[[str], Any] | None = None,
    ) -> None:
        self.channel = channel
        self.message = message
        self.channel_fn = channel_fn

    def execute(self, context: FlowContext) -> FlowResult:
        """Format and send the alert.

        Args:
            context: Shared flow context.  Variables are used for message
                template substitution.

        Returns:
            :class:`FlowResult` with ``output`` as the formatted message.
        """
        import logging as _logging

        try:
            formatted = self.message.format_map(context.variables)
        except KeyError as exc:
            return FlowResult.fail(f"AlertNode template error: missing variable {exc}")
        except Exception as exc:  # noqa: BLE001
            return FlowResult.fail(f"AlertNode template error: {exc}")

        if self.channel == "log":
            _logging.getLogger("flinttrade.automation.alert_node").info(
                "Alert [%s]: %s", self.channel, formatted
            )
            return FlowResult.ok(output=formatted, channel=self.channel)

        if self.channel_fn is None:
            return FlowResult.fail(
                f"AlertNode: channel_fn is required for channel='{self.channel}'"
            )

        try:
            self.channel_fn(formatted)
        except Exception as exc:  # noqa: BLE001
            return FlowResult.fail(f"AlertNode delivery error ({self.channel}): {exc}")

        return FlowResult.ok(output=formatted, channel=self.channel)
