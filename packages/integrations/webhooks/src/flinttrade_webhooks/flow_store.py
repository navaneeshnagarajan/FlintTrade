"""File-backed store for FlowBuilder saved workflows.

Each saved workflow is one JSON file at ``<base_dir>/<id>.json`` (by default
``<workspace_dir>/flows/``). The file content is the frontend ``SavedWorkflow``
JSON verbatim plus a server-stamped ``saved_at`` ISO timestamp.

Flow ids are validated against ``[A-Za-z0-9_-]{1,64}`` (``re.fullmatch``, so a
trailing newline can never sneak past a ``$`` anchor) before any path is
built — this is the path-traversal guard (client ids like ``flow_1720…`` fit).
:meth:`FlowFileStore._path_for` is the single choke point every read, write
and delete goes through: it applies that allowlist and then asserts that the
normalised path it produced still sits directly inside ``base_dir``, so
containment is checked rather than merely implied by the alphabet.

Stored files are capped at 512 KiB. Writes are atomic (temp file +
``os.replace``) so a crash mid-save never corrupts an existing flow.

Rejections carry a stable ``REASON_*`` code rather than free-form text;
:data:`REJECTION_MESSAGES` maps each code to the one fixed operator-facing
string a caller may return over HTTP, so exception text never becomes a
response body.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("flinttrade.integration.flow_store")

# Path-traversal guard: the id is used verbatim as the file stem. Always check
# with ``fullmatch`` — ``match`` + ``$`` would accept a trailing "\n" (e.g. an
# %0A-encoded URL segment) and write a file named "<id>\n.json".
FLOW_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# Cap on the stored file content (SavedWorkflow JSON + saved_at).
MAX_FLOW_BYTES = 512 * 1024

# Stable rejection codes for the whole saved-flow surface (the store and the
# routes in front of it both raise FlowStoreError). Codes, not sentences, so
# the operator-facing wording lives in exactly one table below.
REASON_INVALID_ID = "invalid_id"
REASON_TOO_LARGE = "too_large"
REASON_INVALID_NODE = "invalid_node"
REASON_INVALID_EDGE = "invalid_edge"

# The only strings a caller may put in an HTTP response for a rejected flow.
# Every value is a fixed literal — none is derived from caller input or from
# an exception — so returning one verbatim can never leak internals.
REJECTION_MESSAGES: dict[str, str] = {
    REASON_INVALID_ID: "Invalid flow id — use 1-64 characters from letters, digits, underscore, or hyphen",
    REASON_TOO_LARGE: "Workflow too large — stored flows are capped at 512 KiB",
    REASON_INVALID_NODE: "Each node must be an object with a string id",
    REASON_INVALID_EDGE: "Each edge must be an object with string source and target",
}

# Fallback for a code with no entry above (an unreleased code path).
GENERIC_REJECTION_MESSAGE = "Workflow rejected"


class FlowStoreError(ValueError):
    """Raised when a flow id or payload is rejected by the store.

    Args:
        reason: One of the module's ``REASON_*`` codes. The exception's own
            string is the mapped human wording, which is for logs; a caller
            answering an HTTP request should look ``reason`` up in
            :data:`REJECTION_MESSAGES` instead of stringifying the exception,
            so only reviewed, fixed messages ever reach a client.
    """

    def __init__(self, reason: str) -> None:
        """Build the error from a rejection code, deriving its message."""
        super().__init__(REJECTION_MESSAGES.get(reason, GENERIC_REJECTION_MESSAGE))
        self.reason = reason


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
        """Validate ``flow_id`` and return the only path the store may touch.

        The single filesystem choke point of this class — every read, write
        and delete resolves its path here, so both guarantees below hold for
        all of them:

        1. the id is drawn from an allowlisted alphabet that contains no
           separator, no colon and no dot, so it cannot name a parent
           directory, a drive or a hidden extension; and
        2. the normalised path built from it still sits directly inside
           ``base_dir``.

        The second check is redundant given the first, and deliberately so:
        it makes containment a property the code asserts rather than one a
        reader has to re-derive from the regex, and it holds even if the
        alphabet is ever widened.

        Args:
            flow_id: Candidate flow id, as supplied by the caller.

        Returns:
            The normalised ``<base_dir>/<flow_id>.json`` path.

        Raises:
            FlowStoreError: If the id is outside the allowlist, or if the
                normalised path would land outside ``base_dir``.
        """
        if not isinstance(flow_id, str) or not FLOW_ID_RE.fullmatch(flow_id):
            raise FlowStoreError(REASON_INVALID_ID)
        base_dir = os.path.abspath(self._base_dir)
        candidate = os.path.normpath(os.path.join(base_dir, f"{flow_id}.json"))
        if not candidate.startswith(base_dir + os.sep):
            raise FlowStoreError(REASON_INVALID_ID)
        return Path(candidate)

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
        stored["saved_at"] = datetime.now(UTC).isoformat()
        encoded = json.dumps(stored, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > MAX_FLOW_BYTES:
            raise FlowStoreError(REASON_TOO_LARGE)
        # Both the temp file's directory and its prefix come from the checked
        # path, never from the raw id, so the write side inherits _path_for's
        # containment guarantee instead of re-deriving it.
        parent = path.parent
        parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(parent), prefix=f".{path.stem}.", suffix=".tmp")
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
