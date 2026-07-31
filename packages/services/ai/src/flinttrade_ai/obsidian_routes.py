"""Obsidian vault HTTP routes.

Exposes the :class:`~flinttrade_ai.obsidian_bridge.ObsidianVault` so the terminal
and the AI agent can browse, read, write, and search the operator's Obsidian
vault. The vault path comes from ``FLINTTRADE_OBSIDIAN_VAULT``; when it is unset
the routes return an honest 503 rather than pretending a vault exists.

Routes (all under the backend ``/api/v1`` prefix):

    GET  /api/v1/ai/obsidian/status   — configured? available? vault path
    GET  /api/v1/ai/obsidian/notes    — list every note (relative paths)
    GET  /api/v1/ai/obsidian/note?path=…  — read a note
    POST /api/v1/ai/obsidian/note     — write a note {path, content}
    GET  /api/v1/ai/obsidian/search?q=…   — search notes
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request

from .obsidian_bridge import ObsidianError, ObsidianVault

logger = logging.getLogger("flinttrade.ai.obsidian_routes")

obsidian_bp = Blueprint("obsidian", __name__, url_prefix="/api/v1")

_VAULT_ENV = "FLINTTRADE_OBSIDIAN_VAULT"
_VAULT_WORKSPACE_KEY = "ai.obsidian_vault_path"


def resolve_obsidian_vault_path() -> str:
    """Resolve the vault path: env override first, then the UI-persisted key.

    Shared by these routes and the autonomous agent's vault construction so
    both surfaces agree on one path.
    """
    env_path = os.environ.get(_VAULT_ENV, "").strip()
    if env_path:
        return env_path
    try:
        from flinttrade_core.workspace import Workspace  # noqa: PLC0415

        return str(Workspace().get(_VAULT_WORKSPACE_KEY, "") or "").strip()
    except Exception:  # noqa: BLE001 - config lookup is never fatal
        logger.warning("Failed to load the Obsidian vault path from workspace", exc_info=True)
        return ""


def _vault() -> ObsidianVault | None:
    path = resolve_obsidian_vault_path()
    return ObsidianVault(path) if path else None


def _not_configured() -> tuple[Any, int]:
    return (
        jsonify(
            {
                "status": "error",
                "message": (
                    "Obsidian vault not configured — set the vault path in the "
                    f"Obsidian widget (or the {_VAULT_ENV} environment variable)"
                ),
            }
        ),
        503,
    )


@obsidian_bp.route("/ai/obsidian/config", methods=["GET", "POST"])
def obsidian_config() -> tuple[Any, int]:
    """Read or persist the vault path (workspace ``ai.obsidian_vault_path``).

    POST body: ``{"vault_path": "/path/to/vault"}`` — an empty string clears
    it. A non-empty path must be an existing directory (fail closed on typos).
    The environment variable, when set, overrides the stored value and the
    response says so.
    """
    from flinttrade_core.workspace import Workspace  # noqa: PLC0415

    env_override = bool(os.environ.get(_VAULT_ENV, "").strip())
    if request.method == "GET":
        return (
            jsonify(
                {
                    "status": "success",
                    "data": {
                        "vault_path": resolve_obsidian_vault_path(),
                        "env_override": env_override,
                    },
                }
            ),
            200,
        )

    payload = request.get_json(silent=True) or {}
    vault_path = payload.get("vault_path", "")
    if not isinstance(vault_path, str):
        return jsonify({"status": "error", "message": "vault_path must be a string"}), 400
    vault_path = vault_path.strip()
    # Validate the path the vault will actually open: ObsidianVault expands
    # ``~`` on construction, so checking the unexpanded string refused
    # "~/notes" as non-existent even though the vault opens it happily. This
    # is the operator naming their own vault root — the value is the root, not
    # a name resolved inside one — so the check is an existence probe, and
    # confinement below that root is ObsidianVault._resolve's job.
    # os.path.expanduser, not Path.expanduser: the pathlib form raises
    # RuntimeError whenever the leading ``~`` cannot be resolved - an unknown
    # user on POSIX, or any ``~`` at all when the process has no HOME (a systemd
    # unit without Environment=HOME=, a container run with --env-clear). Both are
    # operator-input cases that must answer 400, and neither can be allowed to
    # escape as a 500.
    if vault_path and not Path(os.path.expanduser(vault_path)).is_dir():
        return (
            jsonify({"status": "error", "message": "vault_path is not an existing directory"}),
            400,
        )

    def _apply(config: dict[str, Any]) -> None:
        config.setdefault("ai", {})["obsidian_vault_path"] = vault_path

    Workspace().update(_apply)
    return (
        jsonify(
            {
                "status": "ok",
                "message": (
                    "Vault path saved — note the environment variable currently overrides it"
                    if env_override
                    else "Vault path saved"
                ),
                "data": {
                    "vault_path": resolve_obsidian_vault_path(),
                    "env_override": env_override,
                },
            }
        ),
        200,
    )


@obsidian_bp.route("/ai/obsidian/status", methods=["GET"])
def obsidian_status() -> tuple[Any, int]:
    vault = _vault()
    return (
        jsonify(
            {
                "status": "success",
                "data": {
                    "configured": vault is not None,
                    "available": bool(vault and vault.available),
                    "vault_path": str(vault.root) if vault else None,
                },
            }
        ),
        200,
    )


@obsidian_bp.route("/ai/obsidian/notes", methods=["GET"])
def obsidian_notes() -> tuple[Any, int]:
    vault = _vault()
    if vault is None:
        return _not_configured()
    return jsonify({"status": "success", "data": vault.list_notes()}), 200


@obsidian_bp.route("/ai/obsidian/note", methods=["GET"])
def obsidian_read() -> tuple[Any, int]:
    vault = _vault()
    if vault is None:
        return _not_configured()
    path = request.args.get("path", "").strip()
    try:
        content = vault.read_note(path)
    except ObsidianError:
        return jsonify({"status": "error", "message": "Requested resource was not found"}), 404
    return jsonify({"status": "success", "data": {"path": path, "content": content}}), 200


@obsidian_bp.route("/ai/obsidian/note", methods=["POST"])
def obsidian_write() -> tuple[Any, int]:
    vault = _vault()
    if vault is None:
        return _not_configured()
    body: dict[str, Any] = request.get_json(silent=True) or {}
    path = str(body.get("path", "")).strip()
    content = str(body.get("content", ""))
    if not path:
        return jsonify({"status": "error", "message": "'path' is required"}), 400
    try:
        rel = vault.write_note(path, content)
    except ObsidianError:
        return jsonify({"status": "error", "message": "Invalid request"}), 400
    return jsonify({"status": "success", "data": {"path": rel}}), 200


@obsidian_bp.route("/ai/obsidian/search", methods=["GET"])
def obsidian_search() -> tuple[Any, int]:
    vault = _vault()
    if vault is None:
        return _not_configured()
    query = request.args.get("q", "")
    return jsonify({"status": "success", "data": vault.search(query)}), 200
