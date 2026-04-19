"""Delay flow node — pauses DAG execution for a fixed number of seconds."""

from __future__ import annotations

import time

from .base import FlowContext, FlowNode, FlowResult


class DelayNode(FlowNode):
    """Pause execution for *seconds* seconds before passing control on.

    Useful for rate-limiting, cooldown periods between orders, or
    simulating human reaction times in paper-trading flows.

    Args:
        seconds: Duration to sleep in seconds.  Must be >= 0.

    Raises:
        ValueError: If *seconds* is negative.

    Example::

        node = DelayNode(seconds=2)
        result = node.execute(FlowContext())
        assert result.success
        assert result.output == 2
    """

    node_type = "delay"

    def __init__(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError(f"DelayNode: seconds must be >= 0, got {seconds!r}")
        self.seconds = seconds

    def execute(self, context: FlowContext) -> FlowResult:
        """Sleep for the configured duration.

        Args:
            context: Shared flow context (not modified).

        Returns:
            :class:`FlowResult` with ``output`` equal to actual sleep duration.
        """
        try:
            start = time.monotonic()
            time.sleep(self.seconds)
            elapsed = time.monotonic() - start
        except Exception as exc:  # noqa: BLE001
            return FlowResult.fail(f"DelayNode error: {exc}")
        return FlowResult.ok(output=elapsed, requested_seconds=self.seconds)
