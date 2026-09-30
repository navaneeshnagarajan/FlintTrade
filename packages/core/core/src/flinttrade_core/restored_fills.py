"""Shared filter for fills restored from a Practice backup.

Scoring readers import :func:`is_restored_from_backup` instead of comparing
the marker themselves. A restored fill stays in P&L. It does not enter a
Laya score, a strategy score, or a training or eval export.
"""

from __future__ import annotations

RESTORED_FROM_BACKUP = "Restored from backup"


def is_restored_from_backup(strategy: object) -> bool:
    """Return True when ``strategy`` is the Practice restore marker.

    Args:
        strategy: Strategy label stored on a fill, journal row, or export row.

    Returns:
        True only for the exact marker string.
    """
    return strategy == RESTORED_FROM_BACKUP
