"""Shared names for strategy status facts the runners already have.

``state`` stays ``running``, ``stopped``, ``crashed``, or ``unknown``.
``reason`` names why. ``lifecycle`` is present only when the runner holds a
``BaseStrategy``. This module does not add a lifecycle and does not fold the
unused state machines into the live runner.
"""

from __future__ import annotations

from typing import Any

from .strategy import BaseStrategy

REASON_IDLE = "idle"
REASON_RUNNING = "running"
REASON_LEADER_EXITED = "leader_exited"
REASON_TREE_UNREADABLE = "tree_unreadable"
REASON_EXIT_NONZERO = "exit_nonzero"
REASON_EXIT_CLEAN = "exit_clean"
REASON_EXIT_MISSING = "exit_missing"
REASON_CLEANUP_UNPROVEN = "cleanup_unproven"

STATUS_REASONS = frozenset(
    {
        REASON_IDLE,
        REASON_RUNNING,
        REASON_LEADER_EXITED,
        REASON_TREE_UNREADABLE,
        REASON_EXIT_NONZERO,
        REASON_EXIT_CLEAN,
        REASON_EXIT_MISSING,
        REASON_CLEANUP_UNPROVEN,
    }
)


def annotate_status(
    payload: dict[str, Any],
    *,
    reason: str,
    strategy: BaseStrategy | None = None,
) -> dict[str, Any]:
    """Add ``reason`` and, when ``strategy`` is held, its lifecycle."""
    if reason not in STATUS_REASONS:
        raise ValueError(f"Unknown strategy status reason {reason!r}")
    payload["reason"] = reason
    if isinstance(strategy, BaseStrategy):
        payload["lifecycle"] = strategy.state.value
    return payload


def verified_exit_reason(exit_code: int | None) -> str:
    """Name a process exit the runner has already verified."""
    if exit_code is None:
        return REASON_EXIT_MISSING
    if exit_code == 0:
        return REASON_EXIT_CLEAN
    return REASON_EXIT_NONZERO
