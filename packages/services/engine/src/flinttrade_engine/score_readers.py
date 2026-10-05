"""Readers that score Laya or strategies.

Each reader drops a fill whose strategy is the Practice restore marker via
:func:`flinttrade_core.restored_fills.is_restored_from_backup`. P&L still
includes that fill. Gate hit-rates, the decision-model benchmark, strategy
track-record, Laya and strategy performance stats, and training or eval
exports built from the decision log do not.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from flinttrade_core.restored_fills import is_restored_from_backup


def _get(row: object, name: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(name)
    return getattr(row, name, None)


def _is_restored(row: object) -> bool:
    return is_restored_from_backup(_get(row, "strategy"))


def _pnl(row: object) -> float:
    value = _get(row, "pnl")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def gate_hit_rates(rows: Sequence[object]) -> dict[str, float]:
    """Allow-rate of each proof kind, excluding restored fills.

    Args:
        rows: Decision-log records and fill rows. A row counts when it has a
            proof kind and an ``allow`` flag.

    Returns:
        Map of proof kind to the fraction of rows that were allowed.
    """
    grouped: dict[str, list[bool]] = {}
    for row in rows:
        if _is_restored(row):
            continue
        proof = _get(row, "proof_kind")
        allow = _get(row, "allow")
        if not isinstance(proof, str) or not isinstance(allow, bool):
            continue
        grouped.setdefault(proof, []).append(allow)
    return {
        proof: (sum(flags) / len(flags))
        for proof, flags in sorted(grouped.items())
    }


def decision_model_benchmark(rows: Sequence[object]) -> dict[str, float]:
    """Accuracy of predicted outcomes, excluding restored fills.

    Args:
        rows: Rows that may carry ``predicted`` and ``outcome`` booleans.

    Returns:
        Row count, hit count, and accuracy. Empty input scores as zero.
    """
    hits = 0
    counted = 0
    for row in rows:
        if _is_restored(row):
            continue
        predicted = _get(row, "predicted")
        outcome = _get(row, "outcome")
        if not isinstance(predicted, bool) or not isinstance(outcome, bool):
            continue
        counted += 1
        if predicted is outcome:
            hits += 1
    return {
        "rows": float(counted),
        "hits": float(hits),
        "accuracy": (hits / counted) if counted else 0.0,
    }


def strategy_track_record(rows: Sequence[object]) -> dict[str, dict[str, float]]:
    """Per-strategy trade count, wins, and P&L, excluding restored fills.

    Args:
        rows: Fill rows with a ``strategy`` field. Decision-log records that
            have no strategy are ignored.

    Returns:
        Map of strategy name to ``trades``, ``wins``, and ``pnl``.
    """
    scores: dict[str, dict[str, float]] = {}
    for row in rows:
        if not isinstance(row, Mapping) or "strategy" not in row:
            continue
        if _is_restored(row):
            continue
        strategy = row.get("strategy")
        name = strategy if isinstance(strategy, str) and strategy else "Unknown"
        bucket = scores.setdefault(name, {"trades": 0.0, "wins": 0.0, "pnl": 0.0})
        pnl = _pnl(row)
        bucket["trades"] += 1.0
        bucket["pnl"] += pnl
        if pnl > 0:
            bucket["wins"] += 1.0
    return scores


def performance_stats(rows: Sequence[object]) -> dict[str, Any]:
    """P&L plus the Laya and strategy scores.

    P&L includes restored fills. ``laya`` and ``strategy`` do not.

    Args:
        rows: Decision-log records and fill rows.

    Returns:
        ``pnl``, ``laya`` (gate hit-rates), ``strategy`` (track-record), and
        ``restored`` (how many fills carried the marker).
    """
    restored = sum(1 for row in rows if _is_restored(row))
    return {
        "pnl": sum(_pnl(row) for row in rows),
        "laya": gate_hit_rates(rows),
        "strategy": strategy_track_record(rows),
        "restored": restored,
    }


def training_export(rows: Sequence[object]) -> list[object]:
    """Training rows built from the decision log, without restored fills.

    A row with no ``split`` is a decision-log record and is included. A fill
    is included only when its split is ``train`` and it is not restored.

    Args:
        rows: Decision-log records and candidate fill rows.

    Returns:
        Rows safe to use as a training set.
    """
    return _export(rows, "train")


def eval_export(rows: Sequence[object]) -> list[object]:
    """Eval rows built from the decision log, without restored fills.

    Args:
        rows: Decision-log records and candidate fill rows.

    Returns:
        Rows safe to use as an eval set.
    """
    return _export(rows, "eval")


def _export(rows: Sequence[object], split: str) -> list[object]:
    exported: list[object] = []
    for row in rows:
        if _is_restored(row):
            continue
        row_split = _get(row, "split")
        if row_split is None or row_split == split:
            exported.append(row)
    return exported
