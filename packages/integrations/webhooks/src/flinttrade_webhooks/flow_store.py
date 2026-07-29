"""File-backed store for FlowBuilder saved workflows.

Each saved workflow is one JSON file at ``<base_dir>/<id>.json`` (by default
``<workspace_dir>/flows/``). The file content is the frontend ``SavedWorkflow``
JSON verbatim plus a server-stamped ``saved_at`` ISO timestamp.

Flow ids are validated against ``[A-Za-z0-9_-]{1,64}`` (``re.fullmatch``, so a
trailing newline can never sneak past a ``$`` anchor) before any path is
built — this is the path-traversal guard (client ids like ``flow_1720…`` fit).
Stored files are capped at 512 KiB. Writes are atomic (temp file +
``os.replace``) so a crash mid-save never corrupts an existing flow.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("flinttrade.integration.flow_store")

# Path-traversal guard: the id is used verbatim as the file stem. Always check
# with ``fullmatch`` — ``match`` + ``$`` would accept a trailing "\n" (e.g. an
# %0A-encoded URL segment) and write a file named "<id>\n.json".
FLOW_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# Cap on the stored file content (SavedWorkflow JSON + saved_at).
MAX_FLOW_BYTES = 512 * 1024


class FlowStoreError(ValueError):
    """Raised when a flow id or payload is rejected by the store."""


def _legacy_flows_dir() -> Path:
    """Return the pre-``workspace_dir()`` flows directory.

    Module-level so tests can monkeypatch the probe away from the real home
    directory.

    Returns:
        ``<legacy dot-directory>/flows`` — the fixed ``~/.flinttrade`` root
        every pre-workspace install used, on every OS.
    """
    from flinttrade_core.workspace import legacy_dotdir  # noqa: PLC0415

    return legacy_dotdir() / "flows"


def _default_flows_dir() -> Path:
    """Resolve the flows directory under the active workspace.

    Copies a pre-workspace ``~/.flinttrade/flows`` tree into the workspace
    once, only when no environment override is in force and the workspace
    holds no flows of its own. The legacy tree is retained; user-authored
    flows are never merged or overwritten, so an install that already has
    workspace flows silently keeps them.

    There is deliberately no home-directory fallback: a ``flinttrade_core``
    that cannot be imported is a broken install, and swallowing that would
    write the operator's flows to a second, invisible directory the
    uninstaller cannot purge. ``create_flask_app`` already degrades a failed
    store construction to the routes' 503 branch.

    Returns:
        The ``flows`` directory inside the active workspace directory.
    """
    from flinttrade_core.workspace import (  # noqa: PLC0415
        copy_legacy_directory_once,
        default_workspace_active,
        workspace_dir,
    )

    target = workspace_dir() / "flows"
    if default_workspace_active():
        copy_legacy_directory_once(
            _legacy_flows_dir(),
            target,
            lock_name=".flows-directory-migration.lock",
            label="FlowBuilder flows",
            lock_dir=target.parent,
        )
    return target


class FlowFileStore:
    """One-JSON-file-per-flow store for FlowBuilder saved workflows.

    Args:
        base_dir: Directory holding the ``<id>.json`` files. Defaults to
            ``flows/`` under the FlintTrade workspace, resolved at
            construction time (never at import time).

    Example::

        store = FlowFileStore()  # <workspace_dir>/flows
        saved = store.save_flow("flow_1", {"id": "flow_1", "name": "My flow",
                                           "nodes": [], "edges": [],
                                           "updatedAt": "2026-07-20T09:00:00Z"})
        assert store.get_flow("flow_1")["saved_at"] == saved["saved_at"]
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        """Bind the store to a flows directory, resolving the default lazily.

        Args:
            base_dir: Explicit directory to use. When given, the workspace
                resolver and its legacy-migration probe are both skipped.
        """
        self._base_dir = Path(base_dir) if base_dir is not None else _default_flows_dir()

    @property
    def base_dir(self) -> Path:
        """Directory the store reads and writes flow files in."""
        return self._base_dir

    def _path_for(self, flow_id: str) -> Path:
        """Validate ``flow_id`` and return its file path (traversal guard)."""
        if not isinstance(flow_id, str) or not FLOW_ID_RE.fullmatch(flow_id):
            raise FlowStoreError(
                "Invalid flow id — use 1-64 characters from letters, digits, underscore, or hyphen"
            )
        return self._base_dir / f"{flow_id}.json"

    def list_flows(self) -> list[dict[str, Any]]:
        """List summaries of every stored flow, most recently saved first.

        Returns:
            One ``{id, name, updatedAt, node_count, saved_at}`` dict per
            readable flow file. Unreadable or malformed files are skipped
            with a warning (never raised to the caller).
        """
        if not self._base_dir.is_dir():
            return []
        summaries: list[dict[str, Any]] = []
        for path in sorted(self._base_dir.glob("*.json")):
            try:
                stored = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.warning("Skipping unreadable flow file %s", path.name)
                continue
            if not isinstance(stored, dict):
                logger.warning("Skipping malformed flow file %s (not a JSON object)", path.name)
                continue
            nodes = stored.get("nodes")
            summaries.append(
                {
                    "id": stored.get("id") or path.stem,
                    "name": stored.get("name", ""),
                    "updatedAt": stored.get("updatedAt", ""),
                    "node_count": len(nodes) if isinstance(nodes, list) else 0,
                    "saved_at": stored.get("saved_at", ""),
                }
            )
        summaries.sort(key=lambda s: str(s["saved_at"]), reverse=True)
        return summaries

    def get_flow(self, flow_id: str) -> dict[str, Any] | None:
        """Return the full stored object for ``flow_id``, or None when absent.

        Raises:
            FlowStoreError: If ``flow_id`` fails the id validation.
        """
        path = self._path_for(flow_id)
        if not path.is_file():
            return None
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Flow file %s is unreadable; treating as absent", path.name)
            return None
        if not isinstance(stored, dict):
            logger.warning("Flow file %s is malformed (not a JSON object); treating as absent", path.name)
            return None
        return stored

    def save_flow(self, flow_id: str, workflow: dict[str, Any]) -> dict[str, Any]:
        """Upsert ``workflow`` verbatim (plus ``saved_at``) as ``<id>.json``.

        Args:
            flow_id: The validated flow id (also the file stem).
            workflow: The frontend ``SavedWorkflow`` object, stored verbatim.

        Returns:
            The stored object (the workflow plus the ``saved_at`` stamp).

        Raises:
            FlowStoreError: If the id is invalid or the encoded file content
                exceeds the 512 KiB cap.
        """
        path = self._path_for(flow_id)
        stored = dict(workflow)
        stored["saved_at"] = datetime.now(timezone.utc).isoformat()
        encoded = json.dumps(stored, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > MAX_FLOW_BYTES:
            raise FlowStoreError("Workflow too large — stored flows are capped at 512 KiB")
        self._base_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(self._base_dir), prefix=f".{flow_id}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(encoded)
            os.replace(tmp_name, path)
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise
        return stored

    def delete_flow(self, flow_id: str) -> bool:
        """Delete the stored flow. Returns True when a file was removed.

        Raises:
            FlowStoreError: If ``flow_id`` fails the id validation.
        """
        path = self._path_for(flow_id)
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True
