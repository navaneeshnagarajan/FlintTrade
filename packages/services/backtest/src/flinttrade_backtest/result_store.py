"""Per-strategy backtest-results store.

The overnight optimiser
(:class:`~flinttrade_ai.overnight_optimiser.OvernightOptimiser`) refines each
strategy from its *recent performance metrics*, but nothing persisted those
metrics — every backtest run returned them to the caller and discarded them, so
the optimiser only ever saw an empty dict and produced generic rule-based output.

This store is the missing link: ``backtest_routes.backtest_run`` writes each
run's metrics here keyed by strategy name (latest wins), and the optimiser reads
``latest(name)`` back so it refines on real numbers. It is plain JSON file I/O —
no DB, no DEK — so it degrades gracefully and unit-tests with ``tmp_path``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("flinttrade.backtest.result_store")


class BacktestResultStore:
    """Read/write the latest backtest metrics per strategy as JSON files.

    One file per strategy holds that strategy's most recent run (latest wins),
    so ``latest(name)`` answers "how did this strategy last perform?" — exactly
    what the overnight refiner needs.

    Args:
        base_dir: Directory the result files live in (created on first write).
        clock: Optional ``() -> datetime`` injected for deterministic tests.
    """

    def __init__(
        self,
        base_dir: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._dir = Path(base_dir).expanduser()
        self._clock = clock or (lambda: datetime.now(tz=timezone.utc))

    @staticmethod
    def _safe_name(strategy: str) -> str:
        """Turn a strategy name into a filesystem-safe file stem.

        The original name is preserved verbatim inside the file (the ``strategy``
        field), so sanitising the stem never loses the real key.
        """
        stem = "".join(c if (c.isalnum() or c in "-_") else "_" for c in strategy.strip())
        return stem or "strategy"

    def save(
        self,
        strategy: str,
        metrics: dict[str, Any],
        *,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Persist ``metrics`` for ``strategy`` (overwriting any prior run).

        Args:
            strategy: Strategy name — the lookup key for :meth:`latest`.
            metrics: Performance metrics dict from the backtest engine.
            context: Optional run context (symbol, interval, date range).

        Returns:
            The written file path, or ``""`` if persistence failed (never
            raises — a failed write must not sink the backtest response).
        """
        strategy = (strategy or "").strip()
        if not strategy:
            return ""
        record = {
            "strategy": strategy,
            "metrics": dict(metrics or {}),
            "context": dict(context or {}),
            "timestamp": self._clock().isoformat(),
        }
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            path = self._dir / f"{self._safe_name(strategy)}.json"
            path.write_text(json.dumps(record, indent=2), encoding="utf-8")
            logger.info("Saved backtest result for %s", strategy)
            return str(path)
        except OSError as exc:
            logger.warning("Could not persist backtest result for %s: %s", strategy, exc)
            return ""

    def _read(self, path: Path) -> dict[str, Any] | None:
        """Read and parse one record file, or ``None`` if unreadable."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Skipping unreadable backtest result %s: %s", path, exc)
            return None
        return data if isinstance(data, dict) else None

    def latest(self, strategy: str) -> dict[str, Any] | None:
        """Return the most recent metrics dict for ``strategy``, or ``None``.

        Args:
            strategy: Strategy name (matched on the stored ``strategy`` field,
                not the sanitised filename, so it is exact).
        """
        strategy = (strategy or "").strip()
        if not strategy:
            return None
        path = self._dir / f"{self._safe_name(strategy)}.json"
        if not path.is_file():
            return None
        record = self._read(path)
        if record is None or record.get("strategy") != strategy:
            return None
        metrics = record.get("metrics")
        return metrics if isinstance(metrics, dict) else None

    def record(self, strategy: str) -> dict[str, Any] | None:
        """Return the full stored record (metrics + context + timestamp) or ``None``."""
        strategy = (strategy or "").strip()
        if not strategy:
            return None
        path = self._dir / f"{self._safe_name(strategy)}.json"
        if not path.is_file():
            return None
        record = self._read(path)
        return record if (record and record.get("strategy") == strategy) else None

    def names(self) -> list[str]:
        """Return every strategy name with a stored result (sorted).

        Reads the ``strategy`` field from each file so the names are exact even
        when the filename was sanitised.
        """
        if not self._dir.is_dir():
            return []
        names: list[str] = []
        for path in self._dir.glob("*.json"):
            record = self._read(path)
            name = record.get("strategy") if record else None
            if isinstance(name, str) and name:
                names.append(name)
        return sorted(names)
