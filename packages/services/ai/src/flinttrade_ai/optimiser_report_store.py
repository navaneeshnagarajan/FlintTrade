"""Persistence for overnight optimisation reports.

:class:`~flinttrade_ai.overnight_optimiser.OvernightOptimiser` produces a
timestamped report dict each night but, until now, only logged and discarded it.
This store is the report sink: it writes each report to a JSON file under a
directory and reads them back so the Lab UI can surface "reports + improvement
suggestions" (the mission requirement). It is plain file I/O — no DB, no DEK —
so it degrades gracefully and is trivial to unit-test with ``tmp_path``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("flinttrade.ai.optimiser_reports")


class OptimiserReportStore:
    """Read/write overnight optimisation reports as JSON files in a directory.

    Args:
        base_dir: Directory the reports live in (created on first write).
    """

    def __init__(self, base_dir: str | Path) -> None:
        self._dir = Path(base_dir).expanduser()

    @staticmethod
    def _safe_name(timestamp: str) -> str:
        """Turn an ISO timestamp into a filesystem-safe file stem."""
        stem = timestamp.replace(":", "-").replace("/", "-").replace("\\", "-").strip()
        return stem or "report"

    def write(self, report: dict[str, Any]) -> str:
        """Persist ``report`` as JSON; return the path. Used as the optimiser sink.

        Named after the report's ``timestamp`` so the file ordering matches the
        run ordering. Never raises into the optimiser — a failed write is logged
        and an empty string returned (the optimiser already swallows sink errors).
        """
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            path = self._dir / f"{self._safe_name(str(report.get('timestamp', '')))}.json"
            path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            logger.info("Wrote optimiser report %s", path)
            return str(path)
        except OSError as exc:
            logger.warning("Could not persist optimiser report: %s", exc)
            return ""

    def list_reports(self) -> list[dict[str, Any]]:
        """Return a summary per stored report, newest first.

        Each summary carries ``timestamp``, ``strategies_seen``,
        ``strategies_optimised`` and the ``file`` name. Unreadable files are
        skipped rather than failing the listing.
        """
        if not self._dir.is_dir():
            return []
        summaries: list[dict[str, Any]] = []
        for path in self._dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            summaries.append(
                {
                    "timestamp": data.get("timestamp", ""),
                    "strategies_seen": data.get("strategies_seen", 0),
                    "strategies_optimised": data.get("strategies_optimised", 0),
                    "file": path.name,
                }
            )
        # ISO-8601 timestamps sort lexicographically; newest first.
        summaries.sort(key=lambda s: str(s["timestamp"]), reverse=True)
        return summaries

    def latest(self) -> dict[str, Any] | None:
        """Return the full most-recent report, or ``None`` if there are none."""
        summaries = self.list_reports()
        if not summaries:
            return None
        try:
            return json.loads((self._dir / summaries[0]["file"]).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
