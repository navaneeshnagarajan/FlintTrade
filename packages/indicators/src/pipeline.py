"""Composable streaming indicator pipeline.

An ``IndicatorPipeline`` chains streaming indicator stages: each stage's
output is fed as the input to the next stage.  Any stage that returns ``None``
(warm-up) propagates ``None`` through the rest of the chain.

All stages must implement an ``update(value: float) -> float | None`` method,
matching the interface of ``StreamingEMA``, ``StreamingSMA``, ``StreamingRSI``,
and similar classes in ``streaming.py``.
"""

from __future__ import annotations

from typing import Any, Protocol


class UpdatableStage(Protocol):
    """Structural protocol for a pipeline stage."""

    def update(self, value: float) -> float | None:
        """Process one tick and return the stage output (or None during warm-up)."""
        ...


class IndicatorPipeline:
    """Composable chain of streaming indicator stages.

    Each stage's ``update()`` output is passed as the input to the next stage.
    If any stage returns ``None`` (still warming up), the remaining stages are
    skipped and ``None`` is returned from the pipeline's own ``update()``.

    Usage::

        from packages.indicators.src.streaming import StreamingEMA
        from packages.indicators.src.pipeline import IndicatorPipeline

        pipeline = IndicatorPipeline(StreamingEMA(10), StreamingEMA(5))
        for price in prices:
            result = pipeline.update(price)

    Args:
        *stages: One or more stage objects, each exposing
            ``update(float) -> float | None``.

    Raises:
        ValueError: If no stages are provided.
    """

    def __init__(self, *stages: Any) -> None:
        if not stages:
            raise ValueError("IndicatorPipeline requires at least one stage.")
        self._stages: tuple[Any, ...] = stages

    def update(self, value: float) -> float | None:
        """Feed one tick through the entire pipeline.

        Args:
            value: Input value for the first stage.

        Returns:
            Output of the last stage, or None if any stage is still warming up.
        """
        current: float | None = value
        for stage in self._stages:
            if current is None:
                return None
            current = stage.update(current)
        return current

    @property
    def stages(self) -> tuple[Any, ...]:
        """Read-only view of the pipeline stages."""
        return self._stages

    def reset(self) -> None:
        """Reset all stages that expose a ``reset()`` method."""
        for stage in self._stages:
            reset_fn = getattr(stage, "reset", None)
            if callable(reset_fn):
                reset_fn()
