"""Native broker account capture + activation (Phase 1 G4).

The interactive counterpart to the boot-time credential-replay login step
(``flinttrade_gateway.native_login``). Connecting a currently connectable native
broker is a four-step transaction, all fail-closed:

  1. Stage the candidate credentials in an isolated in-memory vault overlay.
  2. Authenticate and probe through an unpublished adapter/registry within a
     configurable wall-clock timeout.
  3. Retire and drain the current ``BrokerRouter`` generation only after the
     candidate session is verified.
  4. Register the selector/ACL, commit the vault row, publish the session, and
     rebuild routing from the new persistent state.

Reads rely on the loopback allowance for local desktop capture; WRITES
(connect/relogin/remove/OAuth start) additionally require a valid session JWT
(G9 — any local process can reach 127.0.0.1, but only the operator's
authenticated app session may mutate broker registration, ACLs, and the
credential vault). The JWT's ``sub`` doubles as the ACL actor so the right
operator principal is authorised (falls back to the single-operator account
username otherwise). The OAuth callback is a browser redirect GET protected by
its one-shot ``state`` token when the broker returns one; Dhan's app-consent
flow is limited to one unambiguous pending ``tokenId`` callback.
"""

from __future__ import annotations

import concurrent.futures
import copy
import functools
import hashlib
import html
import inspect
import json
import logging
import math
import queue
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, jsonify, request

from flinttrade_core.models import Order
from flinttrade_gateway.adapter import BROKER_CATALOG

# The single error-swallowing SDK-attestation wrapper lives in the gateway
# (it owns SDK attestation); an identical copy used to be defined here and
# the two could drift. Imported into this namespace so tests can still
# monkeypatch ``native_account_routes._sdk_attestations_by_pin``.
from flinttrade_gateway.capabilities_routes import _sdk_attestations_by_pin
from flinttrade_gateway.log_safety import selector_ref
from flinttrade_gateway.native_login import BROKER_LOGIN_RETRY_MESSAGE
from .workspace import workspace_dir
from .workspace_migrations import update_workspace_config

logger = logging.getLogger("flinttrade.native_accounts")

# Serialises every in-process native-account mutation, including scheduled
# refresh transactions. Workspace edits also use the process/file-locked
# migration API because other settings routes and processes can still update
# workspace.json concurrently.
NATIVE_ACCOUNT_MUTATION_LOCK = threading.Lock()
_CONNECT_LOCK = NATIVE_ACCOUNT_MUTATION_LOCK


def _serialized(fn: Any) -> Any:
    """Run ``fn`` under ``_CONNECT_LOCK`` so connect transactions never interleave."""

    @functools.wraps(fn)
    def _wrap(*args: Any, **kwargs: Any) -> Any:
        with _CONNECT_LOCK:
            return fn(*args, **kwargs)

    return _wrap

# Native brokers (those with a FlintTrade adapter) — derived from the one
# catalogue so this set can never drift from it (consolidation G40). The
# OpenAlgo bridge uses its own /v1/accounts flow.
_NATIVE_BROKER_IDS = {info.name for info in BROKER_CATALOG.values() if info.native}

# Of those, only the tried-and-tested ones may actually be connected today; the
# rest are catalogued as "coming soon" and rejected server-side (principle 3).
_CONNECTABLE_BROKER_IDS = {info.name for info in BROKER_CATALOG.values() if info.native and info.connectable}
_ACCOUNT_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.@-")

native_accounts_bp = Blueprint("native_accounts", __name__, url_prefix="/api/v1/native")


def _native_connect_unavailable_body(adapter_id: str) -> dict[str, Any]:
    """Return a public, non-secret explanation for a disabled native broker."""
    info = BROKER_CATALOG.get(adapter_id)
    blockers = list(info.native_connect_blockers) if info is not None else []
    return {
        "status": "error",
        "message": f"'{adapter_id}' is not yet available for native connect (coming soon).",
        "data": {"native_connect_blockers": blockers},
    }


def _native_sdk_fields(info: Any) -> dict[str, Any]:
    """Expose repo-managed SDK readiness on native broker catalogue rows."""
    from .broker_sdk_attest import sdk_attestation_fields  # noqa: PLC0415

    return sdk_attestation_fields(info.sdk_pin, attestations=_sdk_attestations_by_pin())


def _native_sdk_not_ready_body(adapter_id: str) -> dict[str, Any] | None:
    """Return a fixed public error body when a native broker SDK is not attested."""
    info = BROKER_CATALOG.get(adapter_id)
    if info is None or not info.native:
        return None

    from .broker_sdk_attest import STATUS_NOT_REQUIRED, STATUS_OK, sdk_attestation_fields  # noqa: PLC0415

    fields = sdk_attestation_fields(info.sdk_pin, attestations=_sdk_attestations_by_pin())
    attestation = fields.get("sdk_attestation") or {}
    status = str(attestation.get("status") or "unknown")
    if status in {STATUS_OK, STATUS_NOT_REQUIRED}:
        return None

    pin = str(attestation.get("pin") or info.sdk_pin or "broker SDK")
    pinned = str(attestation.get("pinned_version") or "").strip()
    installed = str(attestation.get("installed_version") or "").strip()
    bits = [f"{pin}: {status}"]
    if pinned:
        bits.append(f"pinned {pinned}")
    if installed:
        bits.append(f"installed {installed}")
    return {
        "status": "error",
        "data": {
            "connected": False,
            "login": "sdk-not-ready",
            "sdk_attestation": attestation,
        },
        "message": (
            f"{info.display_name} native SDK is not ready ({', '.join(bits)}). "
            "Run `make setup` or `uv sync --frozen --all-packages`, then retry."
        ),
    }


@native_accounts_bp.before_request
def _guard_account_writes() -> Any | None:
    """Require a valid session JWT on every account-management write (G9).

    GETs (list/brokers/read + the state-token-protected OAuth callback) keep
    the loopback allowance; POST/DELETE/PUT/PATCH mutate broker registration,
    ACLs, or the vault and must come from the operator's app session.
    """
    if request.path.startswith(f"{native_accounts_bp.url_prefix}/postbacks/"):
        return None
    if request.method in ("POST", "DELETE", "PUT", "PATCH"):
        from .auth_routes import require_operator_session  # noqa: PLC0415

        return require_operator_session()
    return None


def _operator_actor_id() -> str:
    """Resolve the operator's ACL actor id.

    Prefers the JWT ``sub`` of the calling session; falls back to the single
    account's username (this is a single-operator tool). Never raises.
    """
    auth_header = request.headers.get("Authorization", "")
    raw = auth_header.removeprefix("Bearer ").strip()
    if raw:
        try:
            from .auth_routes import decode_token  # noqa: PLC0415

            payload = decode_token(raw)
            sub = str(payload.get("sub") or "").strip()
            if sub:
                return sub
        except Exception:  # noqa: BLE001 - fall through to the profile username
            pass
    svc = current_app.config.get("AUTH_SERVICE")
    if svc is not None:
        try:
            return str(svc.get_profile().get("username") or "operator")
        except Exception:  # noqa: BLE001
            pass
    return "operator"


def _is_safe_account_id(account_id: str) -> bool:
    """Keep stored selectors bounded and safe for later route/path use."""
    return 0 < len(account_id) <= 80 and all(ch in _ACCOUNT_ID_CHARS for ch in account_id)


def _public_connect_success_body() -> dict[str, Any]:
    """Return only the direct-connect fields consumed by the desktop UI."""
    return {
        "status": "success",
        "data": {
            "connected": True,
            "login": "ok",
        },
        "message": "Native broker account connected.",
    }


def _public_connect_failure_body() -> dict[str, Any]:
    """Return a constant direct-connect failure body with no operator input."""
    return {
        "status": "error",
        "data": {
            "connected": False,
            "login": "failed",
        },
        "message": "Login did not establish a session; credentials were not kept.",
    }


def _public_connect_timeout_body() -> dict[str, Any]:
    """Return a constant candidate-auth timeout body with no operator input."""
    return {
        "status": "error",
        "data": {
            "connected": False,
            "login": "timeout",
        },
        "message": "Broker login timed out; the current account state was not changed.",
    }


def _backend_loopback_base() -> str:
    """This backend's own loopback base, honouring the port override.

    Uses the same resolver the serve path binds with, so a backend started on
    ``FLINTTRADE_BACKEND_PORT=5127`` mints OAuth/postback defaults that land on
    ITSELF — not on a dead (or different) instance at 5100.
    """
    from flinttrade_core.app import _resolve_backend_port  # noqa: PLC0415

    return f"http://127.0.0.1:{_resolve_backend_port()}"


def _default_native_postback_uri(adapter_id: str) -> str:
    """Return the native postback receiver URL.

    The default loopback URL is useful for local diagnostics only; broker
    portals can deliver postbacks to it only when the base URL is replaced with a
    broker-reachable public or tunnelled URL.
    """
    import os  # noqa: PLC0415

    base = os.environ.get(
        "FLINTTRADE_NATIVE_POSTBACK_BASE_URL", _backend_loopback_base()
    ).rstrip("/")
    return f"{base}/api/v1/native/postbacks/{adapter_id}"


_POSTBACK_SECRET_KEYS = {
    "accountid",
    "apikey",
    "apisecret",
    "authorization",
    "auth",
    "bearer",
    "brokerorderid",
    "clientcode",
    "clientid",
    "email",
    "exchangeorderid",
    "ip",
    "ipaddress",
    "mobile",
    "mobilenumber",
    "omsorderid",
    "orderid",
    "phone",
    "phonenumber",
    "primaryip",
    "raw",
    "secondaryip",
    "secret",
    "token",
    "tradeid",
    "ucc",
    "userid",
}
_POSTBACK_VALUE_PATTERNS = (
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"(?<!\d)(?:\+?91[-\s]?)?[6-9]\d{9}(?!\d)"),
    re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"),
    re.compile(r"\b[A-Za-z0-9_-]{20,}\b"),
)


def _normalise_postback_key(key: Any) -> str:
    """Return a lower alphanumeric key for secret-field matching."""
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _redact_postback_string(value: str) -> str:
    """Redact token-like substrings from otherwise useful status text."""
    redacted = value
    for pattern in _POSTBACK_VALUE_PATTERNS:
        redacted = pattern.sub("[redacted]", redacted)
    return redacted


def _redacted_postback_snapshot(payload: Any) -> Any:
    """Keep a small in-memory postback trail without retaining direct IDs."""
    if isinstance(payload, dict):
        redacted: dict[str, Any] = {}
        for key, value in payload.items():
            key_l = _normalise_postback_key(key)
            if key_l in _POSTBACK_SECRET_KEYS or any(
                len(secret) > 3 and secret in key_l for secret in _POSTBACK_SECRET_KEYS
            ):
                redacted[str(key)] = "[redacted]"
            elif isinstance(value, dict | list):
                redacted[str(key)] = _redacted_postback_snapshot(value)
            elif isinstance(value, str):
                redacted[str(key)] = _redact_postback_string(value)
            else:
                redacted[str(key)] = value
        return redacted
    if isinstance(payload, list):
        return [_redacted_postback_snapshot(item) for item in payload[:20]]
    if isinstance(payload, str):
        return _redact_postback_string(payload)
    return payload


@dataclass(frozen=True, slots=True)
class _WorkspaceGeneration:
    """Identity of one atomically replaced workspace.json generation."""

    device: int
    inode: int
    size: int
    modified_ns: int
    changed_ns: int
    digest: bytes


@dataclass(frozen=True, slots=True)
class _SelectorWorkspaceMutation:
    """Exact workspace fields introduced or changed by one selector action."""

    selector: str
    adapter_id: str
    account_id: str
    actor_id: str
    added_registration: bool
    added_actor: bool
    prior_default: str
    changed_default: bool
    workspace_generation: _WorkspaceGeneration


@dataclass(frozen=True, slots=True)
class _CredentialSnapshot:
    """Plaintext-in-memory receipt for restoring one durable vault selector."""

    metadata: dict[str, Any] | None
    credentials: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class _SelectorCredentialGeneration:
    """Opaque selector generation used to reject stale or ABA publication."""

    raw_supported: bool
    raw_row: tuple[Any, ...] | None
    metadata: dict[str, Any] | None
    credentials: dict[str, Any] | None
    store_token: Any


@dataclass(slots=True)
class _CredentialRollbackReceipt:
    """Prior and transaction-owned vault generations for one selector."""

    prior_snapshot: _CredentialSnapshot
    prior_generation: _SelectorCredentialGeneration
    applied_generation: _SelectorCredentialGeneration | None = None


@dataclass(slots=True)
class _PrimaryRollbackReceipt:
    """Primary-metadata rollback guarded by one live SQLite data generation."""

    prior_metadata: dict[str, bool]
    connection: Any | None
    applied_version: int | None = None
    applied_metadata: dict[str, bool] | None = None


@dataclass(frozen=True, slots=True)
class _ExecutionDefaultMutation:
    """Exact execution-default transition introduced by read-only demotion."""

    prior_default: str
    applied_default: str
    changed: bool
    workspace_generation: _WorkspaceGeneration


def _workspace_file_generation(path: Any) -> _WorkspaceGeneration:
    payload = path.read_bytes()
    stat = path.stat()
    return _WorkspaceGeneration(
        device=int(stat.st_dev),
        inode=int(stat.st_ino),
        size=int(stat.st_size),
        modified_ns=int(stat.st_mtime_ns),
        changed_ns=int(stat.st_ctime_ns),
        digest=hashlib.sha256(payload).digest(),
    )


def _update_workspace_generation(
    updater: Any,
    *,
    expected: _WorkspaceGeneration | None = None,
    require_existing: bool = False,
) -> tuple[dict[str, Any], _WorkspaceGeneration] | None:
    """Update workspace.json and capture/compare its generation under one lock."""
    from .workspace_migrations import (  # noqa: PLC0415
        WORKSPACE_VERSION,
        _atomic_write,
        _migration_lock,
        default_workspace_config,
    )

    target_dir = workspace_dir().expanduser().resolve()
    path = target_dir / "workspace.json"
    with _migration_lock(target_dir, wait=True):
        existed = path.exists()
        if require_existing and not existed:
            return None
        if expected is not None:
            if not existed or _workspace_file_generation(path) != expected:
                return None
        current = (
            json.loads(path.read_text(encoding="utf-8"))
            if existed
            else default_workspace_config(initialized=True)
        )
        if current.get("version") != WORKSPACE_VERSION:
            raise ValueError(
                f"workspace update requires version {WORKSPACE_VERSION}; "
                f"got {current.get('version')!r}"
            )
        candidate = copy.deepcopy(current)
        updated = updater(candidate)
        if updated is not None:
            candidate = updated
        if not isinstance(candidate, dict) or candidate.get("version") != WORKSPACE_VERSION:
            raise ValueError("workspace updater must return the current-version configuration")
        _atomic_write(path, json.dumps(candidate, indent=2, sort_keys=True))
        return candidate, _workspace_file_generation(path)


def _workspace_generation_is_current(expected: _WorkspaceGeneration) -> bool:
    from .workspace_migrations import _migration_lock  # noqa: PLC0415

    target_dir = workspace_dir().expanduser().resolve()
    path = target_dir / "workspace.json"
    with _migration_lock(target_dir, wait=True):
        return path.exists() and _workspace_file_generation(path) == expected


def _register_selector_in_workspace(
    adapter_id: str, account_id: str, actor_id: str, is_primary: bool
) -> _SelectorWorkspaceMutation:
    """Add the native selector to brokers.registered + ACL the operator.

    The returned receipt permits a failed surrounding transaction to undo only
    the fields it changed, preserving unrelated concurrent workspace updates.
    """
    selector = f"{adapter_id}:{account_id}"
    receipt: dict[str, Any] = {}

    def register(config: dict[str, Any]) -> dict[str, Any]:
        brokers = config.setdefault("brokers", {})
        registered = brokers.setdefault("registered", [])
        added_registration = selector not in registered
        if added_registration:
            registered.append(selector)

        adapter_acls = brokers.setdefault("account_acls", {}).setdefault(adapter_id, {})
        actors = adapter_acls.setdefault(account_id, [])
        added_actor = actor_id not in actors
        if added_actor:
            actors.append(actor_id)

        execution = brokers.setdefault("execution", {})
        prior_default = str(execution.get("default") or "")
        changed_default = (is_primary or not prior_default) and prior_default != selector
        if changed_default:
            execution["default"] = selector

        receipt.update(
            added_registration=added_registration,
            added_actor=added_actor,
            prior_default=prior_default,
            changed_default=changed_default,
        )
        return config

    update_result = _update_workspace_generation(register)
    if update_result is None:  # pragma: no cover - an unconditional update cannot decline
        raise RuntimeError("workspace registration did not commit")
    _config, workspace_generation = update_result
    return _SelectorWorkspaceMutation(
        selector=selector,
        adapter_id=adapter_id,
        account_id=account_id,
        actor_id=actor_id,
        added_registration=bool(receipt["added_registration"]),
        added_actor=bool(receipt["added_actor"]),
        prior_default=str(receipt["prior_default"]),
        changed_default=bool(receipt["changed_default"]),
        workspace_generation=workspace_generation,
    )


def _rollback_selector_workspace(
    mutation: _SelectorWorkspaceMutation,
    *,
    expected: _WorkspaceGeneration | None = None,
) -> _WorkspaceGeneration | None:
    """Undo one selector mutation only from its exact workspace generation."""

    def rollback(config: dict[str, Any]) -> dict[str, Any]:
        brokers = config.setdefault("brokers", {})
        registered = brokers.setdefault("registered", [])
        if mutation.added_registration and mutation.selector in registered:
            registered.remove(mutation.selector)

        account_acls = brokers.setdefault("account_acls", {})
        adapter_acls = account_acls.get(mutation.adapter_id, {})
        actors = adapter_acls.get(mutation.account_id, [])
        if mutation.added_actor and mutation.actor_id in actors:
            actors.remove(mutation.actor_id)
        if not actors:
            adapter_acls.pop(mutation.account_id, None)
        if not adapter_acls:
            account_acls.pop(mutation.adapter_id, None)

        execution = brokers.setdefault("execution", {})
        if mutation.changed_default and execution.get("default") == mutation.selector:
            prior = mutation.prior_default
            execution["default"] = prior if prior and prior in registered else ""
        return config

    result = _update_workspace_generation(
        rollback,
        expected=expected or mutation.workspace_generation,
        require_existing=True,
    )
    if result is None:
        return None
    _config, generation = result
    # A fresh workspace keeps the valid default file. Removing it after releasing
    # the migration lock could unlink a concurrent replacement.
    return generation


def _openalgo_bridge_configured() -> bool:
    """True when the OpenAlgo bridge has a usable configuration (an API key).

    A merely *registered* ``openalgo:default`` selector exists in every fresh
    workspace — without an API key it cannot execute anything, so promoting it
    as a write default would just move the failure somewhere quieter.
    """
    try:
        from .config import Settings  # noqa: PLC0415

        return bool(Settings.from_env().openalgo_api_key)
    except Exception:  # noqa: BLE001 - unreadable config means "not configured"
        return False


def _demote_selector_as_execution_default(
    adapter_id: str,
    account_id: str,
    *,
    prior_execution_default: str = "",
) -> tuple[str | None, _ExecutionDefaultMutation | None]:
    """Keep a selector registered, but remove it from the write default.

    Replacement policy is FAIL-CLOSED (repo rule: native write-target
    fail-closed): restore the operator's own prior default when it is still
    registered; otherwise fall back to ``openalgo:default`` ONLY when the
    bridge is both registered and actually configured; otherwise CLEAR the
    default (``""``). NEVER promote an arbitrary other registered selector —
    a silently retargeted live write default would send default-routed orders
    (webhook / agent / basket paths without an explicit selector) through an
    account the operator never chose. An empty default makes those writes
    fail loudly until the operator picks a new one in Settings → Brokers.

    Returns:
        An operator-facing notice describing the write-default change, or
        ``None`` when the selector was not the execution default (nothing
        changed). The notice deliberately names no selectors/account ids —
        connect responses must never echo operator identifiers.
    """
    selector = f"{adapter_id}:{account_id}"
    notice: str | None = None
    receipt: dict[str, Any] = {}
    bridge_configured = _openalgo_bridge_configured()

    def demote(config: dict[str, Any]) -> dict[str, Any]:
        nonlocal notice
        brokers = config.setdefault("brokers", {})
        execution = brokers.setdefault("execution", {})
        current_default = str(execution.get("default") or "")
        if current_default != selector:
            receipt.update(
                prior_default=current_default,
                applied_default=current_default,
                changed=False,
            )
            return config
        registered = [str(entry) for entry in brokers.get("registered", []) if str(entry)]
        if (
            prior_execution_default
            and prior_execution_default != selector
            and prior_execution_default in registered
        ):
            execution["default"] = prior_execution_default
            notice = (
                "This account's session is read-only, so the previous live write "
                "default was restored."
            )
        elif "openalgo:default" in registered and bridge_configured:
            execution["default"] = "openalgo:default"
            notice = (
                "This account's session is read-only, so the live write default "
                "was moved to the OpenAlgo bridge."
            )
        else:
            execution["default"] = ""
            notice = (
                "This account's session is read-only, so it was removed as the "
                "live write default. No write default is set — choose one in "
                "Settings → Brokers."
            )
        receipt.update(
            prior_default=current_default,
            applied_default=str(execution.get("default") or ""),
            changed=True,
        )
        return config

    update_result = _update_workspace_generation(demote, require_existing=True)
    if update_result is None:
        return None, None
    _config, workspace_generation = update_result
    return notice, _ExecutionDefaultMutation(
        prior_default=str(receipt.get("prior_default") or ""),
        applied_default=str(receipt.get("applied_default") or ""),
        changed=bool(receipt.get("changed")),
        workspace_generation=workspace_generation,
    )


def _rollback_execution_default(
    mutation: _ExecutionDefaultMutation,
) -> _WorkspaceGeneration | None:
    """Restore a read-only demotion only from its exact workspace generation."""
    if not mutation.changed:
        return (
            mutation.workspace_generation
            if _workspace_generation_is_current(mutation.workspace_generation)
            else None
        )

    def rollback(config: dict[str, Any]) -> dict[str, Any]:
        execution = config.setdefault("brokers", {}).setdefault("execution", {})
        if str(execution.get("default") or "") == mutation.applied_default:
            execution["default"] = mutation.prior_default
        return config

    result = _update_workspace_generation(
        rollback,
        expected=mutation.workspace_generation,
        require_existing=True,
    )
    if result is None:
        return None
    _config, generation = result
    return generation


def _deregister_selector_in_workspace(adapter_id: str, account_id: str) -> str | None:
    """Remove the native selector from brokers.registered / account_acls / default.

    The inverse of :func:`_register_selector_in_workspace`; used by the remove
    route to drop a disconnected account. Failed connects use the more precise
    :func:`_rollback_selector_workspace`. No-op if there is no workspace.json.

    When the removed selector was ``brokers.execution.default``, the
    replacement follows the SAME fail-closed policy as
    :func:`_demote_selector_as_execution_default` (repo rule: native
    write-target fail-closed): fall back to ``openalgo:default`` ONLY when the
    bridge is both registered and actually configured; otherwise CLEAR the
    default (``""``). NEVER promote an arbitrary other registered selector —
    a silently retargeted live write default would send default-routed orders
    (webhook / agent / basket paths without an explicit selector) through an
    account the operator never chose. An empty default makes those writes
    fail loudly until the operator picks a new one in Settings → Brokers.

    Returns:
        An operator-facing notice describing the write-default change, or
        ``None`` when the removed selector was not the execution default
        (nothing changed). The notice deliberately names no selectors or
        account ids — remove responses must never echo operator identifiers.
    """
    selector = f"{adapter_id}:{account_id}"
    path = workspace_dir() / "workspace.json"
    if not path.exists():
        return None
    notice: str | None = None
    bridge_configured = _openalgo_bridge_configured()

    def deregister(config: dict[str, Any]) -> dict[str, Any]:
        nonlocal notice
        brokers = config.setdefault("brokers", {})
        registered = brokers.setdefault("registered", [])
        if selector in registered:
            registered.remove(selector)
        account_acls = brokers.setdefault("account_acls", {})
        adapter_acls = account_acls.get(adapter_id, {})
        adapter_acls.pop(account_id, None)
        if not adapter_acls:
            account_acls.pop(adapter_id, None)
        execution = brokers.setdefault("execution", {})
        if execution.get("default") == selector:
            if "openalgo:default" in registered and bridge_configured:
                execution["default"] = "openalgo:default"
                notice = (
                    "The removed account was the live write default, so the "
                    "default was moved to the OpenAlgo bridge."
                )
            else:
                execution["default"] = ""
                notice = (
                    "The removed account was the live write default. No write "
                    "default is set — choose one in Settings → Brokers."
                )
        return config

    update_workspace_config(workspace_dir(), deregister)
    return notice


def _schedule_refresh_job(adapter_id: str, *, remove: bool = False) -> None:
    """Add or remove the broker's daily 08:05 IST refresh job on the rotator.

    Keeps the G5 schedule in step with runtime connect/disconnect: boot only
    scheduled the brokers registered at startup, so a broker connected later
    would never get a morning refresh, and a disconnected broker's job would
    keep firing (logging a "no stored accounts" error each morning). Best-effort
    — a missing rotator (APScheduler unavailable) is a no-op.
    """
    rotator = current_app.config.get("CREDENTIALS_ROTATOR")
    if rotator is None:
        return
    try:
        if remove:
            rotator.unschedule(adapter_id)
        else:
            rotator.schedule_daily_refresh(adapter_id, "08:05")
    except Exception:  # noqa: BLE001 - scheduling must not break connect/remove
        logger.warning("Could not update native broker refresh schedule")


def _session_status(registry: Any, adapter_id: str, account_id: str) -> dict[str, Any]:
    """Non-throwing snapshot of a selector's live session, for the UI."""
    try:
        session = registry.get_session_for(adapter_id, account_id)
    except Exception:  # noqa: BLE001 - no session registered
        return {"has_session": False, "expires_at": None, "read_only": False}
    return {
        "has_session": True,
        "expires_at": getattr(session, "expires_at", None),
        "read_only": bool(getattr(session, "is_read_only", False)),
    }


def _stored_native_account(store: Any, adapter_id: str, account_id: str) -> dict[str, Any] | None:
    """Return a vault metadata row for one native selector, without decrypting it."""
    for row in store.list_accounts():
        row_adapter = str(row.get("adapter_id") or row.get("broker") or "")
        row_account = str(row.get("account_id") or "")
        if row_adapter == adapter_id and row_account == account_id:
            return row
    return None


_NO_SELECTOR_GENERATION = object()
_MISSING_REGISTRY_SESSION = object()
_RAW_CREDENTIAL_COLUMNS = (
    "account_id",
    "adapter_id",
    "broker",
    "label",
    "salt",
    "encrypted_creds",
    "is_primary",
    "created_at",
)


def _raw_selector_row(connection: Any, adapter_id: str, account_id: str) -> tuple[Any, ...] | None:
    row = connection.execute(
        "SELECT account_id, adapter_id, broker, label, salt, encrypted_creds, "
        "is_primary, created_at FROM accounts WHERE adapter_id = ? AND account_id = ?",
        (adapter_id, account_id),
    ).fetchone()
    if row is None:
        return None
    return tuple(row[column] for column in _RAW_CREDENTIAL_COLUMNS)


def _raw_selector_generation(
    store: Any,
    adapter_id: str,
    account_id: str,
) -> tuple[bool, tuple[Any, ...] | None]:
    get_connection = getattr(store, "_get_connection", None)
    if not callable(get_connection):
        return False, None
    try:
        with get_connection() as connection:
            return True, _raw_selector_row(connection, adapter_id, account_id)
    except Exception as exc:
        raise RuntimeError("credential row generation is unavailable") from exc


def _selector_credential_generation(
    store: Any,
    adapter_id: str,
    account_id: str,
) -> _SelectorCredentialGeneration:
    """Capture one exact vault generation without exposing credential values."""
    raw_supported, raw_row = _raw_selector_generation(store, adapter_id, account_id)
    if raw_supported:
        return _SelectorCredentialGeneration(
            raw_supported=True,
            raw_row=raw_row,
            metadata=None,
            credentials=None,
            store_token=_NO_SELECTOR_GENERATION,
        )

    metadata = _stored_native_account(store, adapter_id, account_id)
    credentials = (
        dict(store.retrieve_for(adapter_id, account_id))
        if metadata is not None
        else None
    )
    generation = getattr(store, "selector_generation", None)
    token = generation(adapter_id, account_id) if callable(generation) else _NO_SELECTOR_GENERATION
    return _SelectorCredentialGeneration(
        raw_supported=False,
        raw_row=None,
        metadata=dict(metadata) if metadata is not None else None,
        credentials=credentials,
        store_token=token,
    )


def _selector_credential_generation_matches(
    store: Any,
    adapter_id: str,
    account_id: str,
    expected: _SelectorCredentialGeneration,
) -> bool:
    try:
        return _selector_credential_generation(store, adapter_id, account_id) == expected
    except Exception:  # noqa: BLE001 - unreadable state cannot authorise a commit
        return False


def _compare_and_update_selector_credentials(
    store: Any,
    adapter_id: str,
    account_id: str,
    expected: _SelectorCredentialGeneration,
    credentials: dict[str, Any],
) -> _SelectorCredentialGeneration | None:
    """Replace credentials only while ``expected`` is the exact current row."""
    get_connection = getattr(store, "_get_connection", None)
    derive_key = getattr(store, "_derive_key", None)
    if expected.raw_supported and callable(get_connection) and callable(derive_key):
        import os  # noqa: PLC0415

        from flinttrade_gateway.credentials import _SALT_BYTES  # noqa: PLC0415

        payload = json.dumps(credentials).encode("utf-8")
        salt = os.urandom(_SALT_BYTES)
        encrypted = derive_key(salt).encrypt(payload)
        with get_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if _raw_selector_row(connection, adapter_id, account_id) != expected.raw_row:
                    connection.rollback()
                    return None
                cursor = connection.execute(
                    "UPDATE accounts SET salt = ?, encrypted_creds = ? "
                    "WHERE adapter_id = ? AND account_id = ?",
                    (salt, encrypted, adapter_id, account_id),
                )
                if cursor.rowcount != 1:
                    connection.rollback()
                    return None
                raw_row = _raw_selector_row(connection, adapter_id, account_id)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return _SelectorCredentialGeneration(
            raw_supported=True,
            raw_row=raw_row,
            metadata=None,
            credentials=None,
            store_token=_NO_SELECTOR_GENERATION,
        )

    if not _selector_credential_generation_matches(store, adapter_id, account_id, expected):
        return None
    store.update_credentials_for(adapter_id, account_id, credentials)
    return _selector_credential_generation(store, adapter_id, account_id)


def _compare_and_set_selector_primary(
    store: Any,
    adapter_id: str,
    account_id: str,
    expected: _SelectorCredentialGeneration,
    *,
    is_primary: bool,
    fallback_label: str,
) -> _SelectorCredentialGeneration | None:
    """Change one primary flag only from the exact expected vault generation."""
    get_connection = getattr(store, "_get_connection", None)
    if expected.raw_supported and callable(get_connection):
        with get_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if _raw_selector_row(connection, adapter_id, account_id) != expected.raw_row:
                    connection.rollback()
                    return None
                cursor = connection.execute(
                    "UPDATE accounts SET is_primary = ? "
                    "WHERE adapter_id = ? AND account_id = ?",
                    (int(is_primary), adapter_id, account_id),
                )
                if cursor.rowcount != 1:
                    connection.rollback()
                    return None
                raw_row = _raw_selector_row(connection, adapter_id, account_id)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return _SelectorCredentialGeneration(
            raw_supported=True,
            raw_row=raw_row,
            metadata=None,
            credentials=None,
            store_token=_NO_SELECTOR_GENERATION,
        )

    if not _selector_credential_generation_matches(store, adapter_id, account_id, expected):
        return None
    credentials = store.retrieve_for(adapter_id, account_id)
    row = _stored_native_account(store, adapter_id, account_id) or {}
    store.store(
        account_id,
        str(row.get("broker") or adapter_id),
        str(row.get("label") or fallback_label),
        credentials,
        is_primary=is_primary,
        adapter_id=adapter_id,
    )
    return _selector_credential_generation(store, adapter_id, account_id)


def _registry_session_generation(registry: Any, adapter_id: str, account_id: str) -> Any:
    lock = getattr(registry, "_lock", None)
    sessions = getattr(registry, "_adapter_sessions", None)
    if lock is not None and isinstance(sessions, dict):
        with lock:
            return sessions.get((adapter_id, account_id), _MISSING_REGISTRY_SESSION)
    try:
        return registry.get_session_for(adapter_id, account_id)
    except Exception:  # noqa: BLE001 - absence is an explicit generation
        return _MISSING_REGISTRY_SESSION


def _registry_session_generation_matches(
    registry: Any,
    adapter_id: str,
    account_id: str,
    expected: Any,
) -> bool:
    return _registry_session_generation(registry, adapter_id, account_id) is expected


def _compare_and_put_registry_session(
    registry: Any,
    adapter_id: str,
    account_id: str,
    expected: Any,
    candidate: Any,
) -> bool:
    """Publish a session only while the exact captured registry entry remains."""
    lock = getattr(registry, "_lock", None)
    sessions = getattr(registry, "_adapter_sessions", None)
    put_overridden = "put_session" in getattr(registry, "__dict__", {})
    if lock is not None and isinstance(sessions, dict) and not put_overridden:
        with lock:
            current = sessions.get((adapter_id, account_id), _MISSING_REGISTRY_SESSION)
            if current is not expected:
                return False
            sessions[(adapter_id, account_id)] = candidate
            return True
    if not _registry_session_generation_matches(registry, adapter_id, account_id, expected):
        return False
    registry.put_session(adapter_id, account_id, candidate)
    return True


def _compare_and_remove_registry_session(
    registry: Any,
    adapter_id: str,
    account_id: str,
    expected: Any,
) -> bool:
    """Remove a session only while it is still the exact expected object."""
    lock = getattr(registry, "_lock", None)
    sessions = getattr(registry, "_adapter_sessions", None)
    remove_overridden = "remove_session_for" in getattr(registry, "__dict__", {})
    if lock is not None and isinstance(sessions, dict) and not remove_overridden:
        with lock:
            current = sessions.get((adapter_id, account_id), _MISSING_REGISTRY_SESSION)
            if current is not expected:
                return False
            sessions.pop((adapter_id, account_id), None)
            return True
    if not _registry_session_generation_matches(registry, adapter_id, account_id, expected):
        return False
    registry.remove_session_for(adapter_id, account_id)
    return True


def _snapshot_selector_credentials(
    store: Any,
    adapter_id: str,
    account_id: str,
) -> _CredentialSnapshot:
    """Capture one selector before a staged commit, without logging values."""
    metadata = _stored_native_account(store, adapter_id, account_id)
    if metadata is None:
        return _CredentialSnapshot(metadata=None, credentials=None)
    return _CredentialSnapshot(
        metadata=dict(metadata),
        credentials=dict(store.retrieve_for(adapter_id, account_id)),
    )


def _credential_rollback_receipt(
    store: Any,
    adapter_id: str,
    account_id: str,
    snapshot: _CredentialSnapshot,
) -> _CredentialRollbackReceipt:
    return _CredentialRollbackReceipt(
        prior_snapshot=snapshot,
        prior_generation=_selector_credential_generation(store, adapter_id, account_id),
    )


def _commit_candidate_credentials(
    store: Any,
    candidate_store: Any,
    adapter_id: str,
    account_id: str,
    expected: _SelectorCredentialGeneration,
) -> _SelectorCredentialGeneration | None:
    """Commit staged material with an exact selector-generation comparison."""
    candidate = _snapshot_selector_credentials(candidate_store, adapter_id, account_id)
    if candidate.metadata is None or candidate.credentials is None:
        raise RuntimeError("staged credential candidate is incomplete")

    get_connection = getattr(store, "_get_connection", None)
    derive_key = getattr(store, "_derive_key", None)
    replace_metadata = bool(getattr(candidate_store, "_replace_metadata", False))
    durable_method = "store" if replace_metadata else "update_credentials_for"
    method_overridden = (
        durable_method in getattr(store, "__dict__", {})
        or "commit" in getattr(candidate_store, "__dict__", {})
    )
    if (
        expected.raw_supported
        and callable(get_connection)
        and callable(derive_key)
        and not method_overridden
    ):
        import os  # noqa: PLC0415

        from flinttrade_gateway.credentials import _SALT_BYTES  # noqa: PLC0415

        payload = json.dumps(candidate.credentials).encode("utf-8")
        salt = os.urandom(_SALT_BYTES)
        encrypted = derive_key(salt).encrypt(payload)
        with get_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if _raw_selector_row(connection, adapter_id, account_id) != expected.raw_row:
                    connection.rollback()
                    return None
                account_owner = connection.execute(
                    "SELECT adapter_id FROM accounts WHERE account_id = ?",
                    (account_id,),
                ).fetchone()
                if account_owner is not None and str(account_owner["adapter_id"]) != adapter_id:
                    connection.rollback()
                    return None
                if replace_metadata:
                    created_at = str(candidate.metadata.get("created_at") or "")
                    if not created_at:
                        created_at = datetime.now(tz=ZoneInfo("UTC")).isoformat()
                    connection.execute(
                        "INSERT INTO accounts "
                        "(account_id, adapter_id, broker, label, salt, encrypted_creds, "
                        "is_primary, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(account_id) DO UPDATE SET "
                        "adapter_id = excluded.adapter_id, broker = excluded.broker, "
                        "label = excluded.label, salt = excluded.salt, "
                        "encrypted_creds = excluded.encrypted_creds, "
                        "is_primary = excluded.is_primary",
                        (
                            account_id,
                            adapter_id,
                            str(candidate.metadata.get("broker") or adapter_id),
                            str(candidate.metadata.get("label") or account_id),
                            salt,
                            encrypted,
                            int(bool(candidate.metadata.get("is_primary"))),
                            created_at,
                        ),
                    )
                else:
                    cursor = connection.execute(
                        "UPDATE accounts SET salt = ?, encrypted_creds = ? "
                        "WHERE adapter_id = ? AND account_id = ?",
                        (salt, encrypted, adapter_id, account_id),
                    )
                    if cursor.rowcount != 1:
                        connection.rollback()
                        return None
                raw_row = _raw_selector_row(connection, adapter_id, account_id)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        candidate_store.discard()
        return _SelectorCredentialGeneration(
            raw_supported=True,
            raw_row=raw_row,
            metadata=None,
            credentials=None,
            store_token=_NO_SELECTOR_GENERATION,
        )

    if not _selector_credential_generation_matches(store, adapter_id, account_id, expected):
        return None
    candidate_store.commit()
    return _selector_credential_generation(store, adapter_id, account_id)


def _restore_selector_credentials(
    store: Any,
    adapter_id: str,
    account_id: str,
    receipt: _CredentialRollbackReceipt,
) -> bool:
    """Compare-and-restore only the exact transaction-owned vault generation."""
    applied = receipt.applied_generation
    if applied is None:
        return _selector_credential_generation_matches(
            store,
            adapter_id,
            account_id,
            receipt.prior_generation,
        )

    get_connection = getattr(store, "_get_connection", None)
    if applied.raw_supported and receipt.prior_generation.raw_supported and callable(get_connection):
        try:
            with get_connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                if _raw_selector_row(connection, adapter_id, account_id) != applied.raw_row:
                    connection.rollback()
                    logger.critical("Refused stale native credential rollback")
                    return False
                prior_raw = receipt.prior_generation.raw_row
                if prior_raw is None:
                    connection.execute(
                        "DELETE FROM accounts WHERE adapter_id = ? AND account_id = ?",
                        (adapter_id, account_id),
                    )
                else:
                    connection.execute(
                        "UPDATE accounts SET broker = ?, label = ?, salt = ?, "
                        "encrypted_creds = ?, is_primary = ?, created_at = ? "
                        "WHERE adapter_id = ? AND account_id = ?",
                        (
                            prior_raw[2],
                            prior_raw[3],
                            prior_raw[4],
                            prior_raw[5],
                            prior_raw[6],
                            prior_raw[7],
                            adapter_id,
                            account_id,
                        ),
                    )
                connection.commit()
            return True
        except Exception:  # noqa: BLE001 - caller disables routing on rollback loss
            logger.critical("Could not restore native credential transaction")
            return False

    if not _selector_credential_generation_matches(store, adapter_id, account_id, applied):
        logger.critical("Refused stale native credential rollback")
        return False

    snapshot = receipt.prior_snapshot
    try:
        if snapshot.metadata is None:
            remove_for = getattr(store, "remove_for", None)
            if callable(remove_for):
                remove_for(adapter_id, account_id)
            else:
                store.remove(account_id)
        else:
            store.store(
                account_id,
                str(snapshot.metadata.get("broker") or adapter_id),
                str(snapshot.metadata.get("label") or account_id),
                dict(snapshot.credentials or {}),
                is_primary=bool(snapshot.metadata.get("is_primary")),
                adapter_id=adapter_id,
            )
    except Exception:  # noqa: BLE001 - caller disables routing on rollback loss
        logger.critical("Could not restore native credential transaction")
        return False
    return True


def _primary_rollback_receipt(
    store: Any,
    prior_metadata: dict[str, bool],
) -> _PrimaryRollbackReceipt:
    get_connection = getattr(store, "_get_connection", None)
    connection = None
    if callable(get_connection):
        try:
            connection = get_connection()
            connection.execute("PRAGMA data_version").fetchone()
        except Exception:  # noqa: BLE001 - generic stores use metadata comparison
            if connection is not None:
                connection.close()
            connection = None
    return _PrimaryRollbackReceipt(dict(prior_metadata), connection)


def _bind_primary_rollback_receipt(
    store: Any,
    receipt: _PrimaryRollbackReceipt,
) -> None:
    snapshot = getattr(store, "snapshot_primary_metadata")
    receipt.applied_metadata = dict(snapshot())
    if receipt.connection is not None:
        receipt.applied_version = int(
            receipt.connection.execute("PRAGMA data_version").fetchone()[0]
        )


def _apply_primary_metadata(
    store: Any,
    account_id: str,
    receipt: _PrimaryRollbackReceipt,
) -> None:
    """Apply primary flags and bind their generation in one SQLite transaction."""
    connection = receipt.connection
    set_primary = getattr(store, "set_primary", None)
    if connection is None or "set_primary" in getattr(store, "__dict__", {}):
        if not callable(set_primary):
            raise RuntimeError("Credential store cannot set primary accounts")
        set_primary(account_id)
        _bind_primary_rollback_receipt(store, receipt)
        return

    connection.execute("BEGIN IMMEDIATE")
    try:
        exists = connection.execute(
            "SELECT 1 FROM accounts WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        if exists is None:
            raise RuntimeError("primary account disappeared before commit")
        receipt.applied_version = int(
            connection.execute("PRAGMA data_version").fetchone()[0]
        )
        connection.execute(
            "UPDATE accounts SET is_primary = CASE WHEN account_id = ? THEN 1 ELSE 0 END",
            (account_id,),
        )
        rows = connection.execute(
            "SELECT account_id, is_primary FROM accounts"
        ).fetchall()
        receipt.applied_metadata = {
            str(row["account_id"]): bool(row["is_primary"])
            for row in rows
        }
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def _close_primary_rollback_receipt(receipt: _PrimaryRollbackReceipt) -> None:
    if receipt.connection is not None:
        receipt.connection.close()
        receipt.connection = None


def _restore_primary_metadata(
    store: Any,
    receipt: _PrimaryRollbackReceipt,
) -> bool:
    """Restore primary flags only while the exact applied generation remains."""
    if receipt.applied_metadata is None:
        _close_primary_rollback_receipt(receipt)
        return True
    connection = receipt.connection
    if connection is not None and receipt.applied_version is not None:
        try:
            connection.execute("BEGIN IMMEDIATE")
            current_version = int(connection.execute("PRAGMA data_version").fetchone()[0])
            current_rows = connection.execute(
                "SELECT account_id, is_primary FROM accounts"
            ).fetchall()
            current_metadata = {
                str(row["account_id"]): bool(row["is_primary"])
                for row in current_rows
            }
            if (
                current_version != receipt.applied_version
                or current_metadata != receipt.applied_metadata
            ):
                connection.rollback()
                logger.critical("Refused stale native primary-metadata rollback")
                return False
            connection.executemany(
                "UPDATE accounts SET is_primary = ? WHERE account_id = ?",
                [
                    (int(is_primary), account_id)
                    for account_id, is_primary in receipt.prior_metadata.items()
                ],
            )
            connection.commit()
            return True
        except Exception:  # noqa: BLE001 - caller leaves routing unpublished
            connection.rollback()
            logger.critical("Could not restore native primary-metadata transaction")
            return False
        finally:
            _close_primary_rollback_receipt(receipt)

    snapshot = getattr(store, "snapshot_primary_metadata")
    if dict(snapshot()) != receipt.applied_metadata:
        logger.critical("Refused stale native primary-metadata rollback")
        return False
    restore = getattr(store, "restore_primary_metadata")
    restore(receipt.prior_metadata)
    return True


class _RouterRebuildError(RuntimeError):
    """Raised when a router generation cannot be built and published safely."""


class _CandidateLoginTimeoutError(TimeoutError):
    """Raised when isolated candidate authentication exceeds its configured bound."""


_DEFAULT_CANDIDATE_LOGIN_TIMEOUT_SECONDS = 30.0


class _DaemonBoundedExecutor(concurrent.futures.Executor):
    """One-worker executor whose unkillable SDK call cannot delay process exit."""

    def __init__(self) -> None:
        self._work: queue.Queue[
            tuple[
                concurrent.futures.Future[Any],
                Any,
                tuple[Any, ...],
                dict[str, Any],
            ]
            | None
        ] = queue.Queue(maxsize=1)
        self._lock = threading.Lock()
        self._shutdown = False
        self._thread: threading.Thread | None = None

    def submit(
        self,
        fn: Any,
        /,
        *args: Any,
        **kwargs: Any,
    ) -> concurrent.futures.Future[Any]:
        with self._lock:
            if self._shutdown:
                raise RuntimeError("candidate SDK executor is shut down")
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run,
                    name="native-candidate-sdk",
                    daemon=True,
                )
                self._thread.start()
            future: concurrent.futures.Future[Any] = concurrent.futures.Future()
            try:
                self._work.put_nowait((future, fn, args, kwargs))
            except queue.Full as exc:
                raise RuntimeError("candidate SDK executor capacity exceeded") from exc
            return future

    def _run(self) -> None:
        while True:
            item = self._work.get()
            if item is None:
                return
            future, fn, args, kwargs = item
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(fn(*args, **kwargs))
            except BaseException as exc:  # noqa: BLE001 - Future preserves worker failure
                future.set_exception(exc)

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        with self._lock:
            if self._shutdown:
                thread = self._thread
            else:
                self._shutdown = True
                if cancel_futures:
                    try:
                        while queued := self._work.get_nowait():
                            queued[0].cancel()
                    except queue.Empty:
                        pass
                self._work.put(None)
                thread = self._thread
        if wait and thread is not None and thread is not threading.current_thread():
            thread.join()


class _CandidateLoginAttempt:
    """A single isolated attempt that remains owned until real SDK work ends."""

    def __init__(self, coroutine_factory: Any, candidate_store: Any) -> None:
        self.done = threading.Event()
        self.result: Any = None
        self.error: BaseException | None = None
        self._coroutine_factory = coroutine_factory
        self._candidate_store = candidate_store
        self._state_lock = threading.Lock()
        self._abandoned = False
        self._finished = False
        self._thread = threading.Thread(
            target=self._run,
            name="native-candidate-login",
            daemon=True,
        )

    @property
    def finished(self) -> bool:
        with self._state_lock:
            return self._finished

    def start(self) -> None:
        self._thread.start()

    def abandon(self) -> bool:
        """Relinquish the result only if the real attempt has not finished."""
        with self._state_lock:
            if self._finished:
                return False
            self._abandoned = True
            return True

    def _run(self) -> None:
        import asyncio  # noqa: PLC0415

        loop = asyncio.new_event_loop()
        executor = _DaemonBoundedExecutor()
        asyncio.set_event_loop(loop)
        loop._default_executor = executor  # noqa: SLF001 - asyncio.to_thread ownership boundary
        try:
            self.result = loop.run_until_complete(self._coroutine_factory())
        except BaseException as exc:  # noqa: BLE001 - request maps failures to a fixed body
            self.error = exc
        finally:
            executor.shutdown(wait=True)
            loop._default_executor = None  # noqa: SLF001 - prevent a second shutdown in close()
            loop.close()
            with self._state_lock:
                abandoned = self._abandoned
                self._finished = True
            if abandoned:
                try:
                    self._candidate_store.discard()
                except Exception:  # noqa: BLE001 - staged material is already unreachable
                    pass
            self.done.set()
            with _CANDIDATE_RUNNER_LOCK:
                global _ACTIVE_CANDIDATE_ATTEMPT
                if _ACTIVE_CANDIDATE_ATTEMPT is self:
                    _ACTIVE_CANDIDATE_ATTEMPT = None


_CANDIDATE_RUNNER_LOCK = threading.Lock()
_ACTIVE_CANDIDATE_ATTEMPT: _CandidateLoginAttempt | None = None


def _start_candidate_login_attempt(
    coroutine_factory: Any,
    candidate_store: Any,
) -> _CandidateLoginAttempt:
    """Start one process-wide candidate attempt, refusing concurrent retries."""
    global _ACTIVE_CANDIDATE_ATTEMPT

    with _CANDIDATE_RUNNER_LOCK:
        active = _ACTIVE_CANDIDATE_ATTEMPT
        if active is not None and not active.finished:
            candidate_store.discard()
            raise _CandidateLoginTimeoutError("A prior candidate login is still running")
        attempt = _CandidateLoginAttempt(coroutine_factory, candidate_store)
        _ACTIVE_CANDIDATE_ATTEMPT = attempt
        try:
            attempt.start()
        except Exception:
            _ACTIVE_CANDIDATE_ATTEMPT = None
            candidate_store.discard()
            raise _RouterRebuildError("Candidate native login runner failed") from None
        return attempt


def _candidate_login_timeout_seconds(config: Any | None = None) -> float:
    """Return a finite positive timeout for isolated candidate authentication."""
    source = current_app.config if config is None else config
    raw = source.get(
        "NATIVE_CANDIDATE_LOGIN_TIMEOUT_SECONDS",
        _DEFAULT_CANDIDATE_LOGIN_TIMEOUT_SECONDS,
    )
    try:
        timeout = float(raw)
    except (TypeError, ValueError):
        timeout = _DEFAULT_CANDIDATE_LOGIN_TIMEOUT_SECONDS
    if not math.isfinite(timeout) or timeout <= 0:
        return _DEFAULT_CANDIDATE_LOGIN_TIMEOUT_SECONDS
    return timeout


def _run_bounded_candidate_coroutine(
    coroutine_factory: Any,
    attempt_owner: Any,
    *,
    timeout: float,
) -> Any:
    """Run one isolated coroutine without spawning unbounded SDK workers."""
    attempt = _start_candidate_login_attempt(coroutine_factory, attempt_owner)
    if not attempt.done.wait(timeout):
        if attempt.abandon():
            raise _CandidateLoginTimeoutError("Candidate native login timed out")
        attempt.done.wait()
    if attempt.error is not None:
        raise _RouterRebuildError("Candidate native login runner failed") from None
    return attempt.result


def _disable_broker_routing() -> bool:
    """Retire the exact current generation before unpublishing its companions.

    ``retire_broker_router_generation`` retains an undrained router under
    ``BROKER_ROUTER_DRAINING``.  That strong reference is deliberate: a timeout
    or revoke failure must leave the unsafe generation owned and unreachable,
    rather than let a later rebuild silently forget it.
    """
    from .app import _broker_router_drain_timeout, retire_broker_router_generation  # noqa: PLC0415
    from flinttrade_engine.safety import (  # noqa: PLC0415
        GenerationLeaseUnavailableError,
        bounded_generation_lease,
    )

    app = current_app._get_current_object()  # type: ignore[attr-defined]
    rebuild_lock = app.config.setdefault("BROKER_ROUTER_REBUILD_LOCK", threading.RLock())
    try:
        with bounded_generation_lease(
            rebuild_lock,
            timeout_seconds=_broker_router_drain_timeout(app),
        ):
            retired = retire_broker_router_generation(app)
            app.config["SMART_ROUTING"] = {}
            app.config["NATIVE_ADAPTERS"] = {}
            app.config["RECONCILE_TARGETS"] = None
            if not retired:
                logger.critical("Broker routing remains disabled until the retained generation drains")
            return retired
    except GenerationLeaseUnavailableError:
        logger.critical("Broker routing disable timed out waiting for the routing-generation lease")
        return False


def _workspace_execution_default_is_disabled() -> bool:
    """Return whether the operator intentionally has no default write selector."""
    from .workspace import Workspace  # noqa: PLC0415

    try:
        return not str(Workspace().get("brokers.execution.default", "") or "").strip()
    except Exception:  # noqa: BLE001 - unknown config is not an intentional disable
        return False


def _configure_broker_router_checked(store: Any, registry: Any) -> Any:
    """Build a router and reject swallowed or explicit rebuild failures.

    The app-owned builder publishes one complete generation and returns ``True``.
    Every other return value is failure, even if a stale test double left a router
    in app config.
    """
    from .app import configure_broker_router  # noqa: PLC0415

    app = current_app._get_current_object()  # type: ignore[attr-defined]
    try:
        result = configure_broker_router(app, registry, store, app.config.get("CLIENT"))
    except Exception:
        _disable_broker_routing()
        raise _RouterRebuildError("Broker router rebuild raised") from None
    router = app.config.get("BROKER_ROUTER")
    if result is not True or router is None:
        _disable_broker_routing()
        raise _RouterRebuildError("Broker router rebuild failed")
    return router


def _restore_router_from_vault(store: Any, registry: Any) -> bool:
    """Rebuild from durable state, leaving routing unavailable on failure."""
    try:
        _configure_broker_router_checked(store, registry)
    except _RouterRebuildError:
        _disable_broker_routing()
        logger.warning("Native account transaction could not restore broker routing")
        return False
    return True


def _quiesce_current_router() -> bool:
    """Retire the current router through the app-owned generation lifecycle."""
    from .app import retire_broker_router_generation  # noqa: PLC0415

    app = current_app._get_current_object()  # type: ignore[attr-defined]
    try:
        drained = retire_broker_router_generation(app)
    except Exception as exc:  # noqa: BLE001 - reject without exposing exception text
        logger.warning(
            "Native account mutation refused: broker router retirement raised (%s)",
            type(exc).__name__,
        )
        return False
    if drained is not True:
        logger.warning("Native account mutation refused: broker router generation did not retire")
        return False
    return True


def _activate_candidate_credentials(
    candidate_store: Any,
    adapter_id: str,
    account_id: str,
) -> tuple[dict[str, Any], Any | None]:
    """Authenticate through an unpublished adapter within a wall-clock bound."""
    from flinttrade_gateway.brokers.native_factory import build_native_adapters  # noqa: PLC0415
    from flinttrade_gateway.native_login import establish_native_sessions  # noqa: PLC0415
    from flinttrade_gateway.registry import BrokerRegistry  # noqa: PLC0415

    candidate_registry = BrokerRegistry()
    native_adapters = build_native_adapters(
        [adapter_id],
        attest_ok=lambda broker_id: broker_id == adapter_id,
        has_credentials=lambda broker_id: broker_id == adapter_id,
    )
    if adapter_id not in native_adapters:
        raise _RouterRebuildError("Candidate native adapter did not initialise")
    selector = f"{adapter_id}:{account_id}"

    async def _run() -> dict[str, Any]:
        return await establish_native_sessions(
            native_adapters,
            candidate_registry,
            candidate_store,
            [selector],
            verify=True,
        )

    timeout = _candidate_login_timeout_seconds()
    results = _run_bounded_candidate_coroutine(
        _run,
        candidate_store,
        timeout=timeout,
    ) or {}

    try:
        candidate_session = candidate_registry.get_session_for(adapter_id, account_id)
    except Exception:  # noqa: BLE001 - failed candidates intentionally have no session
        candidate_session = None
    return results, candidate_session


def _candidate_session_status(session: Any | None) -> dict[str, Any]:
    """Return the public status snapshot for an isolated candidate session."""
    if session is None:
        return {"has_session": False, "expires_at": None, "read_only": False}
    return {
        "has_session": True,
        "expires_at": getattr(session, "expires_at", None),
        "read_only": bool(getattr(session, "is_read_only", False)),
    }


def _registry_session_or_none(registry: Any, adapter_id: str, account_id: str) -> Any | None:
    """Snapshot one shared registry selector without raising."""
    try:
        return registry.get_session_for(adapter_id, account_id)
    except Exception:  # noqa: BLE001 - a disconnected selector has no prior session
        return None


def _restore_registry_session(
    registry: Any,
    adapter_id: str,
    account_id: str,
    prior_session: Any | None,
    published_session: Any,
) -> bool:
    """Restore prior runtime state only while our published session is current."""
    current = _registry_session_generation(registry, adapter_id, account_id)
    prior_generation = (
        _MISSING_REGISTRY_SESSION if prior_session is None else prior_session
    )
    if current is prior_generation:
        return True
    if current is not published_session:
        logger.critical("Refused stale native session rollback")
        return False
    if prior_session is None:
        return _compare_and_remove_registry_session(
            registry,
            adapter_id,
            account_id,
            published_session,
        )
    return _compare_and_put_registry_session(
        registry,
        adapter_id,
        account_id,
        published_session,
        prior_session,
    )


def _rollback_committed_candidate(
    store: Any,
    registry: Any,
    adapter_id: str,
    account_id: str,
    credential_receipt: _CredentialRollbackReceipt,
    prior_session: Any | None,
    published_session: Any,
    *,
    workspace_mutation: _SelectorWorkspaceMutation | None = None,
    execution_default_mutation: _ExecutionDefaultMutation | None = None,
) -> None:
    """Restore every durable/runtime surface changed after candidate commit."""
    rollback_ok = True
    workspace_generation: _WorkspaceGeneration | None = None
    if execution_default_mutation is not None:
        try:
            workspace_generation = _rollback_execution_default(execution_default_mutation)
            if workspace_generation is None:
                rollback_ok = False
                logger.critical("Refused stale native execution-default rollback")
        except Exception:  # noqa: BLE001 - routing remains unpublished below
            rollback_ok = False
            logger.critical("Could not restore native execution-default transaction")
    if workspace_mutation is not None:
        try:
            expected_workspace_generation = (
                workspace_generation
                if execution_default_mutation is not None
                else workspace_mutation.workspace_generation
            )
            if expected_workspace_generation is None or _rollback_selector_workspace(
                workspace_mutation,
                expected=expected_workspace_generation,
            ) is None:
                rollback_ok = False
                logger.critical("Refused stale native workspace rollback")
        except Exception:  # noqa: BLE001 - routing remains unpublished below
            rollback_ok = False
            logger.critical("Could not restore native workspace transaction")
    if not _restore_selector_credentials(
        store,
        adapter_id,
        account_id,
        credential_receipt,
    ):
        rollback_ok = False
    if not _restore_registry_session(
        registry,
        adapter_id,
        account_id,
        prior_session,
        published_session,
    ):
        rollback_ok = False
    if rollback_ok:
        _restore_router_from_vault(store, registry)
    else:
        _disable_broker_routing()


def _demote_read_only_vault_primary(
    store: Any,
    *,
    account_id: str,
    adapter_id: str,
    fallback_label: str,
    expected_generation: _SelectorCredentialGeneration,
) -> _SelectorCredentialGeneration | None:
    """Clear the primary flag after a connected session proves read-only."""
    try:
        generation = _compare_and_set_selector_primary(
            store,
            adapter_id,
            account_id,
            expected_generation,
            is_primary=False,
            fallback_label=fallback_label,
        )
    except Exception:  # noqa: BLE001
        logger.warning("Could not demote read-only native broker vault primary flag")
        return None
    return generation


def _demote_read_only_connected_account(
    store: Any,
    registry: Any,
    *,
    adapter_id: str,
    account_id: str,
    fallback_label: str,
    prior_execution_default: str = "",
    mutation_sink: list[_ExecutionDefaultMutation] | None = None,
    credential_receipt: _CredentialRollbackReceipt | None = None,
) -> str | None:
    """Remove a connected read-only selector from write-default metadata.

    Never raises: the session itself is healthy at this point and the router
    still fail-closes read-only writes (``BrokerRouter`` rejects
    ``is_read_only`` sessions), so a corrupt/unwritable ``workspace.json``
    must degrade to "connected, demotion deferred" — not turn a successful
    connect/relogin into a 500.

    Returns:
        An operator-facing notice describing the write-default change (or the
        deferral), or ``None`` when the selector was not the write default.
    """
    try:
        notice, mutation = _demote_selector_as_execution_default(
            adapter_id,
            account_id,
            prior_execution_default=prior_execution_default,
        )
        if mutation_sink is not None and mutation is not None:
            mutation_sink.append(mutation)
        if credential_receipt is not None and credential_receipt.applied_generation is not None:
            demoted_generation = _demote_read_only_vault_primary(
                store,
                account_id=account_id,
                adapter_id=adapter_id,
                fallback_label=fallback_label,
                expected_generation=credential_receipt.applied_generation,
            )
            if demoted_generation is None:
                raise RuntimeError("read-only vault generation changed")
            credential_receipt.applied_generation = demoted_generation
    except Exception:  # noqa: BLE001 - demotion is metadata hygiene, not connect-critical
        logger.warning(
            "Read-only write-default demotion deferred for %s — persistent update failed",
            selector_ref(adapter_id, account_id),
        )
        return (
            "This account's session is read-only, but the write-default "
            "demotion could not be applied (workspace update failed). The "
            "account is connected; review the write default in Settings → "
            "Brokers."
        )

    return notice


@_serialized
def _do_connect(
    adapter_id: str,
    account_id: str,
    label: str,
    credentials: dict[str, Any],
    is_primary: bool,
) -> tuple[dict[str, Any], int]:
    """Authenticate a staged candidate, then commit and publish it atomically."""
    store = current_app.config.get("CREDENTIAL_STORE")
    registry = current_app.config.get("REGISTRY")
    if store is None or registry is None:
        return {"status": "error", "message": "Credential store or registry unavailable."}, 503
    sdk_not_ready = _native_sdk_not_ready_body(adapter_id)
    if sdk_not_ready is not None:
        return sdk_not_ready, 503

    try:
        credential_snapshot = _snapshot_selector_credentials(
            store,
            adapter_id,
            account_id,
        )
        credential_receipt = _credential_rollback_receipt(
            store,
            adapter_id,
            account_id,
            credential_snapshot,
        )
        candidate_store = store.stage_credentials_for(
            adapter_id,
            account_id,
            credentials,
            broker=adapter_id,
            label=label,
            is_primary=is_primary,
        )
    except Exception:  # noqa: BLE001
        return {"status": "error", "message": "Could not stage broker auth material"}, 500

    prior_session = _registry_session_or_none(registry, adapter_id, account_id)
    try:
        login_results, candidate_session = _activate_candidate_credentials(
            candidate_store,
            adapter_id,
            account_id,
        )
    except _CandidateLoginTimeoutError:
        return _public_connect_timeout_body(), 504
    except _RouterRebuildError:
        candidate_store.discard()
        return {"status": "error", "message": "Could not activate broker candidate"}, 500

    selector = f"{adapter_id}:{account_id}"
    login_state = login_results.get(selector, "not-activated")
    session_status = _candidate_session_status(candidate_session)
    connected = session_status["has_session"]
    if not connected:
        candidate_store.discard()
        return {
            "status": "error",
            "data": {
                "adapter_id": adapter_id,
                "account_id": account_id,
                "connected": False,
                "login": login_state,
                "session": session_status,
            },
            "message": f"Login did not establish a session ({login_state}); credentials were not kept.",
        }, 502

    if not _selector_credential_generation_matches(
        store,
        adapter_id,
        account_id,
        credential_receipt.prior_generation,
    ):
        candidate_store.discard()
        _disable_broker_routing()
        return {"status": "error", "message": "Broker account changed during login"}, 409
    expected_prior_session = (
        _MISSING_REGISTRY_SESSION if prior_session is None else prior_session
    )
    if not _registry_session_generation_matches(
        registry,
        adapter_id,
        account_id,
        expected_prior_session,
    ):
        candidate_store.discard()
        _disable_broker_routing()
        return {"status": "error", "message": "Broker session changed during login"}, 409

    actor_id = _operator_actor_id()
    if not _quiesce_current_router():
        candidate_store.discard()
        return {"status": "error", "message": "Broker router is still processing writes"}, 503

    try:
        workspace_mutation = _register_selector_in_workspace(
            adapter_id,
            account_id,
            actor_id,
            is_primary,
        )
    except Exception:  # noqa: BLE001
        logger.error("Failed to register native broker selector in workspace")
        candidate_store.discard()
        _restore_router_from_vault(store, registry)
        return {"status": "error", "message": "Could not register broker selector"}, 500

    try:
        committed_generation = _commit_candidate_credentials(
            store,
            candidate_store,
            adapter_id,
            account_id,
            credential_receipt.prior_generation,
        )
        if committed_generation is None:
            raise RuntimeError("credential generation changed before commit")
        credential_receipt.applied_generation = committed_generation
    except Exception:  # noqa: BLE001 - candidate values must never reach logs
        candidate_store.discard()
        _rollback_committed_candidate(
            store,
            registry,
            adapter_id,
            account_id,
            credential_receipt,
            prior_session,
            candidate_session,
            workspace_mutation=workspace_mutation,
        )
        return {"status": "error", "message": "Could not persist broker auth material"}, 500

    try:
        if not _compare_and_put_registry_session(
            registry,
            adapter_id,
            account_id,
            expected_prior_session,
            candidate_session,
        ):
            raise RuntimeError("registry generation changed before publication")
    except Exception:  # noqa: BLE001
        _rollback_committed_candidate(
            store,
            registry,
            adapter_id,
            account_id,
            credential_receipt,
            prior_session,
            candidate_session,
            workspace_mutation=workspace_mutation,
        )
        return {"status": "error", "message": "Could not publish broker session"}, 500

    demotion_notice: str | None = None
    execution_default_mutations: list[_ExecutionDefaultMutation] = []
    if bool(session_status.get("read_only")):
        demotion_notice = _demote_read_only_connected_account(
            store,
            registry,
            account_id=account_id,
            adapter_id=adapter_id,
            fallback_label=label,
            prior_execution_default=workspace_mutation.prior_default,
            mutation_sink=execution_default_mutations,
            credential_receipt=credential_receipt,
        )

    if _workspace_execution_default_is_disabled():
        _disable_broker_routing()
    else:
        try:
            _configure_broker_router_checked(store, registry)
        except _RouterRebuildError:
            _rollback_committed_candidate(
                store,
                registry,
                adapter_id,
                account_id,
                credential_receipt,
                prior_session,
                candidate_session,
                workspace_mutation=workspace_mutation,
                execution_default_mutation=(
                    execution_default_mutations[0]
                    if execution_default_mutations
                    else None
                ),
            )
            return {"status": "error", "message": "Could not publish broker routing"}, 500

    status: dict[str, Any] = current_app.config.setdefault("NATIVE_SESSION_STATUS", {})
    status.update(login_results)

    # G5: runtime connects join the already-running daily refresh schedule.
    _schedule_refresh_job(adapter_id)

    body: dict[str, Any] = {
        "status": "success",
        "data": {
            "adapter_id": adapter_id,
            "account_id": account_id,
            "connected": True,
            "login": login_state,
            "session": session_status,
        },
        "message": f"{adapter_id} account {account_id} connected.",
    }
    if demotion_notice:
        # Surface the write-default change so the UI can tell the operator —
        # a silent workspace.json diff is exactly the failure mode the
        # fail-closed demotion policy exists to prevent.
        body["data"]["notice"] = demotion_notice
    return body, 200


@native_accounts_bp.route("/brokers", methods=["GET"])
def list_native_brokers() -> Any:
    """The connect catalogue: each native broker + its supported login methods.

    The connect UI renders forms/flows from this, so the operator can pick their
    preferred login method per broker (full broker support). Secret fields are
    flagged so the UI masks them.
    """
    brokers = []
    for info in BROKER_CATALOG.values():
        if not info.native:
            continue
        row = {
            "adapter_id": info.name,
            "display_name": info.display_name,
            "connectable": info.connectable,
            "requires_static_ip": info.requires_static_ip,
            "native_connect_blockers": list(info.native_connect_blockers),
            "exchanges": list(info.exchanges),
            "auth_methods": [m.model_dump() for m in info.auth_methods],
            "mcp": info.mcp.model_dump() if info.mcp is not None else None,
            "oauth_redirect_uri": _default_oauth_redirect_uri(),
            "postback_uri": _default_native_postback_uri(info.name),
        }
        row.update(_native_sdk_fields(info))
        brokers.append(row)
    return jsonify({"status": "success", "data": {"brokers": brokers}})


@native_accounts_bp.route("/accounts", methods=["POST"])
def connect_native_account() -> Any:
    """Connect a native broker: store creds, register, activate, log in.

    Body: ``{adapter_id, account_id, label?, credentials, is_primary?}``.
    """
    body: dict[str, Any] = request.get_json(silent=True) or {}
    adapter_id = str(body.get("adapter_id", "")).strip().lower()
    account_id = str(body.get("account_id", "")).strip()
    label = str(body.get("label") or adapter_id)
    credentials = body.get("credentials")
    is_primary = bool(body.get("is_primary", False))

    if adapter_id not in _NATIVE_BROKER_IDS:
        return jsonify({
            "status": "error",
            "message": "adapter_id is not a native broker.",
        }), 400
    if adapter_id not in _CONNECTABLE_BROKER_IDS:
        return jsonify(_native_connect_unavailable_body(adapter_id)), 400
    if not _is_safe_account_id(account_id):
        return jsonify({"status": "error", "message": "account_id must use letters, numbers, dot, underscore, @ or hyphen."}), 400
    if not isinstance(credentials, dict) or not credentials:
        return jsonify({"status": "error", "message": "credentials (a non-empty object) is required."}), 400

    _body_out, code = _do_connect(adapter_id, account_id, label, credentials, is_primary)
    if code == 200:
        success_body = _public_connect_success_body()
        notice = _body_out.get("data", {}).get("notice")
        if notice:
            # The fixed public body carries no operator input; the demotion
            # notice is a constant server-side string (no ids), safe to echo.
            success_body["data"]["notice"] = notice
        return jsonify(success_body), 200
    if code == 503 and _body_out.get("data", {}).get("login") == "sdk-not-ready":
        return jsonify(_body_out), 503
    if code == 504:
        return jsonify(_public_connect_timeout_body()), 504
    return jsonify(_public_connect_failure_body()), 502


# ---------------------------------------------------------------------------
# OAuth redirect flow (Upstox, Dhan app-consent, and any native with an
# oauth_redirect auth flow). The operator opens the broker's authorisation
# dialog; the broker redirects the browser back to our loopback callback with a
# single-use ``code`` or Dhan ``tokenId``, which the adapter's login() exchanges
# for an access token. The app's api_secret is held only transiently in the
# in-memory pending store for the exchange.
# ---------------------------------------------------------------------------

_OAUTH_PENDING: dict[str, dict[str, Any]] = {}
_OAUTH_TTL_SECONDS = 600.0


def _default_oauth_redirect_uri() -> str:
    """The loopback redirect URI the operator registers in the broker app.

    Defaults to this backend's own callback, honouring the port override so it
    lands on the instance that holds the pending OAuth state. Overridable via
    ``FLINTTRADE_OAUTH_REDIRECT_URI`` for public URLs / the desktop shell.
    """
    import os  # noqa: PLC0415

    return os.environ.get(
        "FLINTTRADE_OAUTH_REDIRECT_URI",
        f"{_backend_loopback_base()}/api/v1/native/oauth/callback",
    )


def _purge_expired_oauth() -> None:
    import time  # noqa: PLC0415

    now = time.time()
    for state in [s for s, v in _OAUTH_PENDING.items() if now - v.get("ts", 0) > _OAUTH_TTL_SECONDS]:
        _OAUTH_PENDING.pop(state, None)


def _pop_pending_oauth_callback(*, state: str, returned_token_id: bool) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve a callback to a pending OAuth start without leaking pending secrets.

    Most brokers echo our CSRF ``state`` and must match it exactly. Dhan's app
    consent docs only promise a ``tokenId`` on redirect, so support that broker
    shape when there is one clear pending Dhan login. Multiple pending Dhan
    approvals are ambiguous and fail closed; a broker ``code`` without state is
    never accepted.
    """

    if state:
        pending = _OAUTH_PENDING.pop(state, None)
        if pending is None:
            return None, "Login link expired or invalid - start again from FlintTrade."
        return pending, None

    if not returned_token_id:
        return None, "Login link expired or invalid - start again from FlintTrade."

    matches = [(s, v) for s, v in _OAUTH_PENDING.items() if v.get("adapter_id") == "dhan"]
    if len(matches) == 1:
        matched_state, pending = matches[0]
        _OAUTH_PENDING.pop(matched_state, None)
        return pending, None
    if not matches:
        return None, "Login link expired or invalid - start again from FlintTrade."
    return None, "Dhan login link is ambiguous or expired - start again from FlintTrade."


@native_accounts_bp.route("/oauth/start", methods=["POST"])
def native_oauth_start() -> Any:
    """Begin an OAuth connect: return the broker authorisation URL.

    Body: ``{adapter_id, account_id, api_key, api_secret, label?, is_primary?}``.
    Stores the app secret + account transiently keyed by a CSRF ``state``; the
    operator opens ``auth_url`` and approves; the broker redirects to our
    callback with the ``code`` or Dhan ``tokenId``.
    """
    import secrets  # noqa: PLC0415
    import time  # noqa: PLC0415

    body: dict[str, Any] = request.get_json(silent=True) or {}
    adapter_id = str(body.get("adapter_id", "")).strip().lower()
    account_id = str(body.get("account_id", "")).strip()
    api_key = str(body.get("api_key", "")).strip()
    api_secret = str(body.get("api_secret", "")).strip()

    if adapter_id not in _NATIVE_BROKER_IDS:
        return jsonify({"status": "error", "message": "adapter_id is not a native broker."}), 400
    if adapter_id not in _CONNECTABLE_BROKER_IDS:
        return jsonify(_native_connect_unavailable_body(adapter_id)), 400
    if not _is_safe_account_id(account_id):
        return jsonify({"status": "error", "message": "account_id must use letters, numbers, dot, underscore, @ or hyphen."}), 400
    if not (api_key and api_secret):
        return jsonify({
            "status": "error",
            "message": "account_id, api_key and api_secret are required.",
        }), 400
    sdk_not_ready = _native_sdk_not_ready_body(adapter_id)
    if sdk_not_ready is not None:
        return jsonify(sdk_not_ready), 503

    native_adapters = current_app.config.get("NATIVE_ADAPTERS") or {}
    # The adapter class exposes build_login_url even when dormant — resolve from
    # the class so OAuth start works before the native is activated.
    from flinttrade_gateway.brokers.native_factory import NATIVE_ADAPTER_CLASSES  # noqa: PLC0415

    adapter_cls = NATIVE_ADAPTER_CLASSES.get(adapter_id)
    builder = getattr(native_adapters.get(adapter_id), "build_login_url", None) or getattr(
        adapter_cls, "build_login_url", None
    )
    if builder is None:
        return jsonify({
            "status": "error",
            "message": f"{adapter_id} does not support an OAuth redirect flow.",
        }), 400

    redirect_uri = _default_oauth_redirect_uri()
    state = secrets.token_urlsafe(24)
    _purge_expired_oauth()
    _OAUTH_PENDING[state] = {
        "adapter_id": adapter_id,
        "account_id": account_id,
        "api_key": api_key,
        "api_secret": api_secret,
        "redirect_uri": redirect_uri,
        "label": str(body.get("label") or adapter_id),
        "is_primary": bool(body.get("is_primary", False)),
        "ts": time.time(),
    }
    try:
        params = inspect.signature(builder).parameters
        if "account_id" in params or "api_secret" in params:
            auth_url = builder(api_key, redirect_uri, state, account_id=account_id, api_secret=api_secret)
        else:
            auth_url = builder(api_key, redirect_uri, state)
    except Exception as exc:  # noqa: BLE001 - never echo app secrets / broker responses
        _OAUTH_PENDING.pop(state, None)
        logger.warning("Native OAuth start failed for %s (%s)", adapter_id, type(exc).__name__)
        return jsonify({"status": "error", "message": "Could not start broker OAuth login."}), 502
    return jsonify({
        "status": "success",
        "data": {
            "auth_url": auth_url,
            "state": state,
            "redirect_uri": redirect_uri,
            "postback_uri": _default_native_postback_uri(adapter_id),
        },
    })


@native_accounts_bp.route("/oauth/callback", methods=["GET"])
def native_oauth_callback() -> Any:
    """Broker OAuth redirect target: exchange the code and connect the account.

    Query: ``?code=<single-use>&state=<csrf>`` or Dhan's
    ``?tokenId=<single-use>``. Looks up the pending app secret/account, runs the
    connect transaction with ``{code, api_key, api_secret, redirect_uri}`` (the
    adapter's login() exchanges the code/token for an access token), and returns
    a small HTML result the operator sees in the redirected tab.
    """
    oauth_code = request.args.get("code") or ""
    token_id = request.args.get("tokenId") or request.args.get("token_id") or ""
    code = oauth_code or token_id
    state = request.args.get("state", "")
    _purge_expired_oauth()
    pending, error = _pop_pending_oauth_callback(state=state, returned_token_id=bool(token_id and not oauth_code))
    if pending is None:
        return _oauth_result_html(error or "Login link expired or invalid - start again from FlintTrade.", ok=False), 400
    if not code:
        # The broker can redirect with an error instead of a code.
        logger.warning("Native OAuth callback returned no authorisation code")
        return _oauth_result_html("Broker did not return an authorisation code.", ok=False), 400

    adapter_id = pending["adapter_id"]
    account_id = pending["account_id"]
    client_id = account_id if adapter_id == "dhan" else pending["api_key"]
    credentials = {
        "code": code,
        "token_id": code,
        "api_key": pending["api_key"],
        "app_id": pending["api_key"],
        "api_secret": pending["api_secret"],
        "client_id": client_id,
        "redirect_uri": pending["redirect_uri"],
    }
    body_out, http_code = _do_connect(
        adapter_id, account_id, pending["label"], credentials, pending["is_primary"]
    )
    connected = bool(body_out.get("data", {}).get("connected"))
    notice = str(body_out.get("data", {}).get("notice") or "")
    msg = (
        f"{adapter_id} account connected - you can close this tab and return to FlintTrade."
        if connected
        else "Login failed - return to FlintTrade and try again."
    )
    if connected and notice:
        msg = f"{msg} {notice}"
    return _oauth_result_html(msg, ok=connected), (200 if connected else 502)


def _oauth_result_html(message: str, ok: bool) -> str:
    colour = "#22c55e" if ok else "#ef4444"
    safe = html.escape(message, quote=True)
    return (
        "<!doctype html><meta charset='utf-8'><title>FlintTrade — broker login</title>"
        "<body style='font-family:system-ui,sans-serif;background:#0a0a0f;color:#e5e7eb;"
        "display:flex;align-items:center;justify-content:center;height:100vh;margin:0'>"
        f"<div style='max-width:32rem;padding:2rem;text-align:center'>"
        f"<div style='font-size:2rem;color:{colour}'>{'✓' if ok else '✕'}</div>"
        f"<p style='font-size:1rem;line-height:1.5'>{safe}</p></div></body>"
    )


@native_accounts_bp.route("/postbacks/<adapter_id>", methods=["POST"])
def native_broker_postback(adapter_id: str) -> Any:
    """Receive native broker order-update postbacks.

    Upstox requires an open unauthenticated POST endpoint for app registration.
    The live order path still uses gated broker reads/writes; this endpoint only
    acknowledges broker push updates and keeps a bounded in-memory, redacted
    trail for diagnostics/runtime consumers.
    """
    adapter_id = adapter_id.strip().lower()
    if adapter_id not in _NATIVE_BROKER_IDS:
        return jsonify({"status": "error", "message": "adapter_id is not a native broker."}), 404
    if request.content_length is not None and request.content_length > 256_000:
        return jsonify({"status": "error", "message": "postback payload too large."}), 413

    payload: Any = request.get_json(silent=True) if request.is_json else None
    if payload is None:
        raw = request.get_data(cache=False, as_text=True)[:8_192]
        payload = {"raw": raw}
    event = {
        "adapter_id": adapter_id,
        "received_at": time.time(),
        "update_type": str(payload.get("update_type") or payload.get("type") or "unknown")
        if isinstance(payload, dict)
        else "unknown",
        "payload": _redacted_postback_snapshot(payload),
    }
    bucket = current_app.config.setdefault("NATIVE_POSTBACK_EVENTS", {}).setdefault(adapter_id, [])
    bucket.append(event)
    del bucket[:-100]
    logger.info("Native broker postback received for %s (%s)", adapter_id, event["update_type"])
    return jsonify({"status": "success", "data": {"accepted": True}}), 200


@native_accounts_bp.route("/accounts/<adapter_id>/<account_id>/login", methods=["POST"])
@_serialized
def relogin_native_account(adapter_id: str, account_id: str) -> Any:
    """Re-authenticate a native account (daily re-auth / token refresh).

    Body (optional): ``{credentials}`` — fresh credentials to re-store first
    (e.g. a new daily access token); omit to replay the stored credentials.
    """
    adapter_id = adapter_id.strip().lower()
    if adapter_id not in _NATIVE_BROKER_IDS:
        return jsonify({"status": "error", "message": f"'{adapter_id}' is not a native broker."}), 400
    if adapter_id not in _CONNECTABLE_BROKER_IDS:
        return jsonify(_native_connect_unavailable_body(adapter_id)), 400

    store = current_app.config.get("CREDENTIAL_STORE")
    registry = current_app.config.get("REGISTRY")
    if store is None or registry is None:
        return jsonify({"status": "error", "message": "Credential store or registry unavailable."}), 503
    sdk_not_ready = _native_sdk_not_ready_body(adapter_id)
    if sdk_not_ready is not None:
        return jsonify(sdk_not_ready), 503

    try:
        row = _stored_native_account(store, adapter_id, account_id)
    except Exception:  # noqa: BLE001
        return jsonify({"status": "error", "message": "Could not list accounts"}), 500
    if row is None:
        return jsonify({"status": "error", "message": "Native broker account not found."}), 404

    body: dict[str, Any] = request.get_json(silent=True) or {}
    fresh = body.get("credentials")
    try:
        credential_snapshot = _snapshot_selector_credentials(
            store,
            adapter_id,
            account_id,
        )
        credential_receipt = _credential_rollback_receipt(
            store,
            adapter_id,
            account_id,
            credential_snapshot,
        )
        credentials = (
            fresh
            if isinstance(fresh, dict) and fresh
            else dict(credential_snapshot.credentials or {})
        )
        candidate_store = store.stage_credentials_for(
            adapter_id,
            account_id,
            credentials,
        )
    except Exception:  # noqa: BLE001
        return jsonify({"status": "error", "message": "Could not stage broker credentials"}), 500

    prior_session = _registry_session_or_none(registry, adapter_id, account_id)
    try:
        login_results, candidate_session = _activate_candidate_credentials(
            candidate_store,
            adapter_id,
            account_id,
        )
    except _CandidateLoginTimeoutError:
        return jsonify(_public_connect_timeout_body()), 504
    except _RouterRebuildError:
        candidate_store.discard()
        return jsonify({"status": "error", "message": "Could not activate broker login."}), 500

    selector = f"{adapter_id}:{account_id}"
    session_status = _candidate_session_status(candidate_session)
    connected = session_status["has_session"]
    if not connected:
        candidate_store.discard()
        return jsonify({
            "status": "error",
            "data": {
                "login": login_results.get(selector, "not-activated"),
                "session": session_status,
            },
        }), 502

    if not _selector_credential_generation_matches(
        store,
        adapter_id,
        account_id,
        credential_receipt.prior_generation,
    ):
        candidate_store.discard()
        _disable_broker_routing()
        return jsonify({
            "status": "error",
            "message": "Broker account changed during login.",
        }), 409
    expected_prior_session = (
        _MISSING_REGISTRY_SESSION if prior_session is None else prior_session
    )
    if not _registry_session_generation_matches(
        registry,
        adapter_id,
        account_id,
        expected_prior_session,
    ):
        candidate_store.discard()
        _disable_broker_routing()
        return jsonify({
            "status": "error",
            "message": "Broker session changed during login.",
        }), 409

    if not _quiesce_current_router():
        candidate_store.discard()
        return jsonify({
            "status": "error",
            "message": "Broker router is still processing writes; account was not changed.",
        }), 503

    try:
        committed_generation = _commit_candidate_credentials(
            store,
            candidate_store,
            adapter_id,
            account_id,
            credential_receipt.prior_generation,
        )
        if committed_generation is None:
            raise RuntimeError("credential generation changed before commit")
        credential_receipt.applied_generation = committed_generation
    except Exception:  # noqa: BLE001 - never log candidate credential values
        candidate_store.discard()
        _rollback_committed_candidate(
            store,
            registry,
            adapter_id,
            account_id,
            credential_receipt,
            prior_session,
            candidate_session,
        )
        logger.warning("Could not persist verified native broker credentials")
        return jsonify({"status": "error", "message": "Could not persist broker credentials."}), 500

    try:
        if not _compare_and_put_registry_session(
            registry,
            adapter_id,
            account_id,
            expected_prior_session,
            candidate_session,
        ):
            raise RuntimeError("registry generation changed before publication")
    except Exception:  # noqa: BLE001
        _rollback_committed_candidate(
            store,
            registry,
            adapter_id,
            account_id,
            credential_receipt,
            prior_session,
            candidate_session,
        )
        return jsonify({"status": "error", "message": "Could not publish broker session."}), 500

    demotion_notice: str | None = None
    execution_default_mutations: list[_ExecutionDefaultMutation] = []
    if bool(session_status.get("read_only")):
        demotion_notice = _demote_read_only_connected_account(
            store,
            registry,
            adapter_id=adapter_id,
            account_id=account_id,
            fallback_label=str(row.get("label") or adapter_id),
            mutation_sink=execution_default_mutations,
            credential_receipt=credential_receipt,
        )

    if _workspace_execution_default_is_disabled():
        _disable_broker_routing()
    else:
        try:
            _configure_broker_router_checked(store, registry)
        except _RouterRebuildError:
            _rollback_committed_candidate(
                store,
                registry,
                adapter_id,
                account_id,
                credential_receipt,
                prior_session,
                candidate_session,
                execution_default_mutation=(
                    execution_default_mutations[0]
                    if execution_default_mutations
                    else None
                ),
            )
            return jsonify({"status": "error", "message": "Could not publish broker routing."}), 500

    status: dict[str, Any] = current_app.config.setdefault("NATIVE_SESSION_STATUS", {})
    status.update(login_results)

    data: dict[str, Any] = {
        "login": login_results.get(selector, "not-activated"),
        "session": session_status,
    }
    if demotion_notice:
        data["notice"] = demotion_notice
    return jsonify({
        "status": "success",
        "data": data,
    }), 200


@native_accounts_bp.route("/accounts", methods=["GET"])
def list_native_accounts() -> Any:
    """List native accounts in the vault with their live session status."""
    store = current_app.config.get("CREDENTIAL_STORE")
    registry = current_app.config.get("REGISTRY")
    if store is None:
        return jsonify({"status": "error", "message": "Credential store unavailable."}), 503
    try:
        rows = store.list_accounts()
    except Exception:  # noqa: BLE001
        return jsonify({"status": "error", "message": "Could not list accounts"}), 500

    login_status: dict[str, Any] = current_app.config.get("NATIVE_SESSION_STATUS") or {}
    accounts = []
    for row in rows:
        adapter_id = str(row.get("adapter_id") or row.get("broker") or "")
        if adapter_id not in _NATIVE_BROKER_IDS:
            continue
        account_id = str(row.get("account_id") or "")
        entry = {
            "adapter_id": adapter_id,
            "account_id": account_id,
            "label": row.get("label"),
            "is_primary": bool(row.get("is_primary")),
        }
        if registry is not None:
            entry.update(_session_status(registry, adapter_id, account_id))
        # G7 — a sessionless selector whose last replay attempt failed needs a
        # FRESH login (stale/single-use credentials), not just "no session".
        # Keep retryable broker/login outages distinct so the UI does not tell
        # the operator to re-authenticate when FlintTrade simply could not
        # reach/verify the broker yet.
        if not entry.get("has_session"):
            last = str(login_status.get(f"{adapter_id}:{account_id}") or "")
            if last and last != "ok":
                entry["login_error"] = last
                if last == BROKER_LOGIN_RETRY_MESSAGE:
                    entry["login_retryable"] = True
                else:
                    entry["needs_relogin"] = True
        accounts.append(entry)
    return jsonify({"status": "success", "data": {"accounts": accounts}})


_READ_METHODS = {
    "funds": ("funds",),
    "limits": ("limits",),
    "positions": ("positions",),
    "holdings": ("holdings",),
    "profile": ("profile", "user_profile"),
    "orders": ("order_book",),
    "orderstatus": ("order_details",),
    "orderhistory": ("order_history",),
    "ordertrades": ("order_trades",),
    "trades": ("trade_book",),
    "ltp": ("ltp", "ltp_quotes"),
    "quotes": ("quotes",),
    # quote_details falls back to the ltp read so the verb exists uniformly for
    # every broker — the terminal must never branch on adapter_id to pick a verb.
    "quote_details": ("quote_details", "ltp", "ltp_quotes"),
    "ohlc": ("ohlc", "ohlc_quotes"),
    "depth": ("market_depth",),
    "margin": ("margin_calculator",),
    "scrip_master": ("scrip_master",),
    "holidays": ("market_holidays",),
    "timings": ("market_timings",),
    "optiongreeks": ("option_greeks",),
    "history": ("historical",),
    "expiry": ("expiry_list",),
    "optionchain": ("option_chain",),
    "search": ("search_instruments", "search_symbols"),
    "search_scrip": ("search_scrip",),
}
_READ_KINDS = set(_READ_METHODS)


def _split_query_list(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _native_quote_read_args() -> tuple[tuple[Any, ...] | None, str | None]:
    symbols: list[str] = []
    for value in request.args.getlist("symbols"):
        symbols.extend(_split_query_list(value))
    symbol = str(request.args.get("symbol") or "").strip()
    if symbol:
        exchange = str(request.args.get("exchange") or "NSE").strip().upper() or "NSE"
        symbols.append(symbol if ":" in symbol else f"{exchange}:{symbol}")
    if not symbols:
        return None, "quotes read requires symbol or symbols."
    return (symbols,), None


def _native_depth_read_args() -> tuple[tuple[Any, ...] | None, str | None]:
    symbols: list[str] = []
    for value in request.args.getlist("symbols"):
        symbols.extend(_split_query_list(value))
    symbol = str(request.args.get("symbol") or "").strip()
    if symbol:
        exchange = str(request.args.get("exchange") or "NSE").strip().upper() or "NSE"
        symbols.append(symbol if ":" in symbol else f"{exchange}:{symbol}")
    if not symbols:
        return None, "depth read requires symbol or symbols."
    return (symbols,), None


def _native_quote_details_read_args() -> tuple[tuple[Any, ...] | None, str | None]:
    args, message = _native_quote_read_args()
    if message is not None or args is None:
        return None, message
    quote_type = str(request.args.get("quote_type") or request.args.get("type") or "all").strip().lower() or "all"
    return (args[0], quote_type), None


def _native_margin_read_args() -> tuple[tuple[Any, ...] | None, str | None]:
    symbol = str(request.args.get("symbol") or "").strip()
    if not symbol:
        return None, "margin read requires symbol."
    quantity = str(request.args.get("quantity") or request.args.get("qty") or "").strip()
    if not quantity:
        return None, "margin read requires quantity or qty."
    try:
        if float(quantity) <= 0:
            return None, "margin read requires a positive quantity."
    except ValueError:
        return None, "margin read requires a numeric quantity."
    try:
        order = Order(
            symbol=symbol,
            exchange=str(request.args.get("exchange") or "NSE").strip().upper() or "NSE",
            action=str(request.args.get("action") or request.args.get("side") or "BUY").strip().upper() or "BUY",
            product=str(request.args.get("product") or "MIS").strip().upper() or "MIS",
            quantity=quantity,
            pricetype=str(request.args.get("pricetype") or request.args.get("order_type") or "MARKET").strip().upper()
            or "MARKET",
            price=str(request.args.get("price") or "0").strip() or "0",
            trigger_price=str(request.args.get("trigger_price") or request.args.get("triggerPrice") or "0").strip()
            or "0",
        )
    except Exception:  # noqa: BLE001 - public route returns a fixed validation message
        return None, "margin read received invalid order fields."
    return (order,), None


def _native_order_status_read_args() -> tuple[tuple[Any, ...] | None, str | None]:
    order_id = str(
        request.args.get("order_id")
        or request.args.get("orderId")
        or request.args.get("orderid")
        or ""
    ).strip()
    if not order_id:
        return None, "orderstatus read requires order_id or orderId."
    return (order_id,), None


def _native_limits_read_args() -> tuple[tuple[Any, ...] | None, str | None]:
    segment = str(request.args.get("segment") or "ALL").strip().upper() or "ALL"
    exchange = str(request.args.get("exchange") or "ALL").strip().upper() or "ALL"
    product = str(request.args.get("product") or "ALL").strip().upper() or "ALL"
    return (segment, exchange, product), None


def _native_scrip_master_read_args() -> tuple[tuple[Any, ...] | None, str | None]:
    exchange = str(request.args.get("exchange") or request.args.get("segment") or "").strip().upper()
    return ((exchange,) if exchange else ()), None


def _native_holidays_read_args() -> tuple[tuple[Any, ...] | None, str | None]:
    holiday_date = str(request.args.get("date") or "").strip()
    return ((holiday_date,) if holiday_date else ()), None


def _native_timings_read_args() -> tuple[tuple[Any, ...] | None, str | None]:
    timing_date = str(request.args.get("date") or "").strip()
    if not timing_date:
        timing_date = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    return (timing_date,), None


def _native_history_read_args() -> tuple[tuple[Any, ...] | None, str | None]:
    payload: dict[str, Any] = {}
    flag_keys = {"intraday", "expired"}
    for key in (
        "symbol",
        "exchange",
        "interval",
        "timeframe",
        "start_date",
        "end_date",
        "from_date",
        "to_date",
        "start",
        "end",
        "start_time",
        "end_time",
        "instrument",
        "instrument_type",
        "instrument_key",
        "intraday",
        "expired",
    ):
        if key in request.args:
            value = str(request.args.get(key) or "")
            payload[key] = value.strip().lower() in {"1", "true", "yes", "on"} if key in flag_keys else value
    if not str(payload.get("symbol") or payload.get("instrument_key") or "").strip():
        return None, "history read requires symbol or instrument_key."
    return (payload,), None


def _native_expiry_read_args() -> tuple[tuple[Any, ...] | None, str | None]:
    symbol = str(request.args.get("symbol") or request.args.get("underlying") or "").strip()
    if not symbol:
        return None, "expiry read requires symbol or underlying."
    exchange = str(request.args.get("exchange") or "NSE_INDEX").strip().upper() or "NSE_INDEX"
    return (symbol, exchange), None


def _native_option_chain_read_args() -> tuple[tuple[Any, ...] | None, str | None]:
    payload: dict[str, Any] = {}
    symbol = str(request.args.get("symbol") or request.args.get("underlying") or "").strip()
    if not symbol:
        return None, "optionchain read requires symbol or underlying."
    payload["symbol"] = symbol
    payload["underlying"] = symbol
    payload["exchange"] = str(request.args.get("exchange") or "NSE_INDEX").strip().upper() or "NSE_INDEX"
    expiry = str(request.args.get("expiry") or request.args.get("expiry_date") or "").strip()
    if expiry:
        payload["expiry"] = expiry
        payload["expiry_date"] = expiry
    instrument_key = str(request.args.get("instrument_key") or "").strip()
    if instrument_key:
        payload["instrument_key"] = instrument_key
    return (payload,), None


def _native_search_read_args() -> tuple[tuple[Any, ...] | None, str | None]:
    query = str(request.args.get("query") or request.args.get("q") or "").strip()
    if not query:
        return None, "search read requires query or q."
    return (query[:80],), None


def _native_search_scrip_read_args() -> tuple[tuple[Any, ...] | None, str | None]:
    symbol = str(request.args.get("symbol") or request.args.get("query") or request.args.get("q") or "").strip()
    if not symbol:
        return None, "search_scrip read requires symbol, query or q."
    exchange = str(request.args.get("exchange") or "NSE").strip().upper() or "NSE"
    return (symbol[:80], exchange), None


def _truthy_query_arg(name: str, default: bool) -> bool:
    value = request.args.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _native_read_kwargs(kind: str) -> dict[str, Any]:
    if kind != "search_scrip":
        return {}
    kwargs: dict[str, Any] = {}
    for query_key, arg_name in (
        ("expiry", "expiry"),
        ("option_type", "option_type"),
        ("strike_price", "strike_price"),
    ):
        value = str(request.args.get(query_key) or "").strip()
        if value:
            kwargs[arg_name] = value.upper() if query_key == "option_type" else value
    if "ignore_50multiple" in request.args:
        kwargs["ignore_50multiple"] = _truthy_query_arg("ignore_50multiple", True)
    return kwargs


def _native_read_args(kind: str) -> tuple[tuple[Any, ...] | None, str | None]:
    if kind == "limits":
        return _native_limits_read_args()
    if kind in {"ltp", "quotes"}:
        return _native_quote_read_args()
    if kind == "quote_details":
        return _native_quote_details_read_args()
    if kind == "ohlc":
        return _native_quote_read_args()
    if kind == "depth":
        return _native_depth_read_args()
    if kind == "margin":
        return _native_margin_read_args()
    if kind == "orderstatus":
        return _native_order_status_read_args()
    if kind in {"orderhistory", "ordertrades"}:
        return _native_order_status_read_args()
    if kind == "scrip_master":
        return _native_scrip_master_read_args()
    if kind == "holidays":
        return _native_holidays_read_args()
    if kind == "timings":
        return _native_timings_read_args()
    if kind == "optiongreeks":
        return _native_quote_read_args()
    if kind == "history":
        return _native_history_read_args()
    if kind == "expiry":
        return _native_expiry_read_args()
    if kind == "optionchain":
        return _native_option_chain_read_args()
    if kind == "search":
        return _native_search_read_args()
    if kind == "search_scrip":
        return _native_search_scrip_read_args()
    return (), None


def _canonical_ltp_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _split_requested_symbol(entry: str) -> tuple[str, str]:
    text = str(entry or "").strip()
    if ":" in text:
        exchange, symbol = text.split(":", 1)
        return symbol.strip(), (exchange.strip().upper() or "NSE")
    return text, "NSE"


def _canonical_ltp_rows(value: Any, requested: list[Any]) -> list[dict[str, Any]]:
    """Normalise an ltp/quote_details read to ONE canonical row shape.

    Broker adapters return three incompatible shapes for the same verb — a
    ``{"EXCHANGE:SYMBOL": price}`` map (Groww/INDmoney), a list of raw SDK rows
    (Upstox/Kotak), or a single record. The core reads facade is the ONLY place
    broker differences are absorbed (architecture north star), so every shape is
    unified here to ``[{"symbol", "exchange", "ltp", ...extras}]`` and the
    terminal stays a thin envelope reader.
    """
    fallback_symbol, fallback_exchange = (
        _split_requested_symbol(requested[0]) if requested else ("", "NSE")
    )

    def _row(record: dict[str, Any]) -> dict[str, Any]:
        return {
            **record,
            "symbol": str(record.get("symbol") or record.get("trading_symbol") or fallback_symbol),
            "exchange": str(record.get("exchange") or fallback_exchange),
            "ltp": _canonical_ltp_float(
                record.get("ltp") or record.get("last_price") or record.get("last_traded_price")
            ),
        }

    if isinstance(value, list):
        return [_row(item) for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        if any(key in value for key in ("ltp", "last_price", "last_traded_price")):
            return [_row(value)]
        rows: list[dict[str, Any]] = []
        for key, price in value.items():
            symbol, exchange = _split_requested_symbol(str(key))
            rows.append({"symbol": symbol or fallback_symbol, "exchange": exchange, "ltp": _canonical_ltp_float(price)})
        return rows
    return [{"symbol": fallback_symbol, "exchange": fallback_exchange, "ltp": _canonical_ltp_float(value)}]


def _submit_live_positions_mtm(
    value: Any,
    *,
    adapter_id: str,
    account_id: str,
) -> None:
    """Submit one locally computed account MTM snapshot with its exact selector."""
    from .l2_state import PortfolioSafetyState  # noqa: PLC0415

    if not isinstance(value, PortfolioSafetyState):
        logger.error("Live position MTM ignored because local portfolio accounting is incomplete")
        return
    safety = current_app.config.get("SAFETY")
    submit = getattr(safety, "submit_daily_mtm", None)
    if not callable(submit):
        logger.error("Live position MTM is unavailable because the safety runtime is not configured")
        return
    try:
        submit(
            value.daily_pnl,
            adapter_id=adapter_id,
            account_id=account_id,
        )
    except Exception as exc:  # noqa: BLE001 - a live MTM failure must not create a raw exit path
        logger.error("Live position MTM submission failed closed (%s)", type(exc).__name__)


@native_accounts_bp.route("/accounts/<adapter_id>/<account_id>/<kind>", methods=["GET"])
def read_native_account(adapter_id: str, account_id: str, kind: str) -> Any:
    """Read a native account's account book or read-only market data via its adapter.

    Exercises the live broker session end-to-end (a real broker API call using
    the stored token). Reads are not gated (no order), only require an
    established session. Account-book reads return the adapter's raw result;
    ltp/quote_details are normalised to one canonical row shape here so broker
    payload differences never leak past the core facade.
    """
    import asyncio  # noqa: PLC0415

    adapter_id = adapter_id.strip().lower()
    kind = kind.strip().lower()
    if kind not in _READ_KINDS:
        return jsonify({"status": "error", "message": f"kind must be one of {sorted(_READ_KINDS)}."}), 400

    native_adapters = current_app.config.get("NATIVE_ADAPTERS") or {}
    registry = current_app.config.get("REGISTRY")
    adapter = native_adapters.get(adapter_id)
    if adapter is None:
        return jsonify({
            "status": "error",
            "message": f"Native adapter '{adapter_id}' is not active (not connected / not attested).",
        }), 404
    try:
        session = registry.get_session_for(adapter_id, account_id)
    except Exception:  # noqa: BLE001
        return jsonify({
            "status": "error",
            "message": f"No live session for {adapter_id}:{account_id} — connect or re-login first.",
        }), 409

    reader = None
    chosen_method = ""
    for method_name in _READ_METHODS[kind]:
        reader = getattr(adapter, method_name, None)
        if reader is not None:
            chosen_method = method_name
            break
    if reader is None:
        return jsonify({"status": "error", "message": f"{adapter_id} adapter has no '{kind}' read."}), 400
    args, message = _native_read_args(kind)
    if message is not None:
        return jsonify({"status": "error", "message": message}), 400
    call_args = args or ()
    if kind == "quote_details" and chosen_method in {"ltp", "ltp_quotes"}:
        # The ltp fallback takes only the symbols list — drop quote_type.
        call_args = call_args[:1]
    kwargs = _native_read_kwargs(kind)
    try:
        result = asyncio.run(reader(session, *call_args, **kwargs))
    except NotImplementedError:
        return jsonify({"status": "error", "message": f"{adapter_id} adapter does not support {kind} reads."}), 501
    except Exception as exc:  # noqa: BLE001 - classify before surfacing a public route error
        from flinttrade_gateway.native_login import (  # noqa: PLC0415
            should_drop_session_after_probe_error,
            should_keep_session_after_probe_error,
        )

        if should_keep_session_after_probe_error(exc):
            logger.info(
                "Native read %s %s temporarily unavailable but session remains connected: %s",
                adapter_id,
                kind,
                exc,
            )
            return jsonify({
                "status": "error",
                "message": "Broker read is temporarily unavailable; the session remains connected.",
                "data": {"retryable": True},
            }), 503
        if should_drop_session_after_probe_error(exc):
            try:
                registry.remove_session_for(adapter_id, account_id)
            except Exception:  # noqa: BLE001 - read failure response must still be deterministic
                pass
            login_status: dict[str, Any] = current_app.config.setdefault("NATIVE_SESSION_STATUS", {})
            login_status[f"{adapter_id}:{account_id}"] = "Broker session expired or invalid; re-login required."
            logger.warning("Native read %s %s proved the session invalid; session dropped", adapter_id, kind)
            return jsonify({
                "status": "error",
                "message": "Broker session expired or invalid; re-login required.",
            }), 409
        logger.warning("Native read %s %s failed: %s", adapter_id, kind, exc)
        return jsonify({"status": "error", "message": "Broker read failed"}), 502

    # Pydantic models -> dicts for JSON.
    def _dump(v: Any) -> Any:
        if hasattr(v, "model_dump"):
            return v.model_dump()
        if isinstance(v, list):
            return [_dump(x) for x in v]
        return v

    data = _dump(result)
    if kind == "positions":
        try:
            from .l2_state import gather_safety_state  # noqa: PLC0415

            portfolio_state = asyncio.run(
                gather_safety_state(current_app.config, adapter_id, account_id=account_id)
            )
        except Exception as exc:  # noqa: BLE001 - never fall back to broker aggregate P&L
            logger.error("Local live-position MTM calculation is unavailable: %s", type(exc).__name__)
        else:
            _submit_live_positions_mtm(
                portfolio_state,
                adapter_id=adapter_id,
                account_id=account_id,
            )
    if kind in {"ltp", "quote_details"}:
        requested = list(args[0]) if args and isinstance(args[0], (list, tuple)) else []
        data = _canonical_ltp_rows(data, requested)
    return jsonify({"status": "success", "data": data})


@native_accounts_bp.route("/accounts/<adapter_id>/<account_id>/set-primary", methods=["POST"])
@_serialized
def set_primary_native_account(adapter_id: str, account_id: str) -> Any:
    """Promote a live native selector to the workspace execution default."""
    adapter_id = adapter_id.strip().lower()
    if adapter_id not in _NATIVE_BROKER_IDS:
        return jsonify({"status": "error", "message": "Broker is not a native broker."}), 404
    if adapter_id not in _CONNECTABLE_BROKER_IDS:
        return jsonify(_native_connect_unavailable_body(adapter_id)), 400

    store = current_app.config.get("CREDENTIAL_STORE")
    registry = current_app.config.get("REGISTRY")
    if store is None or registry is None:
        return jsonify({"status": "error", "message": "Credential store or registry unavailable."}), 503

    try:
        row = _stored_native_account(store, adapter_id, account_id)
    except Exception:  # noqa: BLE001
        return jsonify({"status": "error", "message": "Could not list accounts"}), 500
    if row is None:
        return jsonify({"status": "error", "message": "Native broker account not found."}), 404

    try:
        session = registry.get_session_for(adapter_id, account_id)
    except Exception:  # noqa: BLE001
        return jsonify({
            "status": "error",
            "message": "Broker account has no live session; re-authenticate first.",
        }), 409
    if bool(getattr(session, "is_read_only", False)):
        return jsonify({
            "status": "error",
            "message": "Broker account is read-only and cannot be used as the live write default.",
        }), 409

    snapshot_primary = getattr(store, "snapshot_primary_metadata", None)
    restore_primary = getattr(store, "restore_primary_metadata", None)
    if not callable(snapshot_primary) or not callable(restore_primary):
        return jsonify({"status": "error", "message": "Credential store cannot update primary metadata."}), 500
    try:
        prior_primary_metadata = snapshot_primary()
        primary_receipt = _primary_rollback_receipt(store, prior_primary_metadata)
    except Exception:  # noqa: BLE001
        return jsonify({"status": "error", "message": "Could not snapshot primary metadata."}), 500

    workspace_mutation: _SelectorWorkspaceMutation | None = None
    try:
        workspace_mutation = _register_selector_in_workspace(
            adapter_id,
            account_id,
            _operator_actor_id(),
            True,
        )

        _apply_primary_metadata(store, account_id, primary_receipt)

        _configure_broker_router_checked(store, registry)
    except Exception:  # noqa: BLE001
        rollback_ok = True
        if workspace_mutation is not None:
            try:
                if _rollback_selector_workspace(workspace_mutation) is None:
                    rollback_ok = False
                    logger.warning("Refused stale workspace primary rollback")
            except Exception:  # noqa: BLE001
                rollback_ok = False
                logger.warning("Could not restore workspace primary metadata")
        if rollback_ok:
            try:
                if not _restore_primary_metadata(store, primary_receipt):
                    rollback_ok = False
            except Exception:  # noqa: BLE001
                rollback_ok = False
                logger.warning("Could not restore vault primary metadata")
        else:
            _close_primary_rollback_receipt(primary_receipt)
        if rollback_ok:
            _restore_router_from_vault(store, registry)
        else:
            _disable_broker_routing()
        logger.warning("Could not set native primary broker account")
        return jsonify({"status": "error", "message": "Could not set primary native account."}), 500

    _close_primary_rollback_receipt(primary_receipt)
    return jsonify({
        "status": "success",
        "data": {
            "account": {
                "adapter_id": adapter_id,
                "account_id": account_id,
                "label": row.get("label"),
                "is_primary": True,
            }
        },
    })


@native_accounts_bp.route("/accounts/<adapter_id>/<account_id>", methods=["DELETE"])
@_serialized
def remove_native_account(adapter_id: str, account_id: str) -> Any:
    """Remove a native account without exposing partially deleted state."""
    adapter_id = adapter_id.strip().lower()
    store = current_app.config.get("CREDENTIAL_STORE")
    registry = current_app.config.get("REGISTRY")
    if store is None or registry is None:
        return jsonify({"status": "error", "message": "Credential store or registry unavailable."}), 503

    try:
        prior_meta = _stored_native_account(store, adapter_id, account_id)
    except Exception:  # noqa: BLE001
        return jsonify({"status": "error", "message": "Could not list accounts"}), 500
    if prior_meta is None:
        # DELETE is selector-scoped and idempotent. A wrong adapter must neither
        # reveal nor remove a same-account-id row owned by another broker.
        return jsonify({
            "status": "success",
            "message": f"{adapter_id} account {account_id} removed.",
            "data": {},
        })

    # Capture the encrypted row's plaintext before any mutation. The credentials
    # never leave this transaction; they are needed only to restore the exact row
    # if the independently locked workspace write cannot commit.
    try:
        prior_credentials = store.retrieve_for(adapter_id, account_id)
    except Exception:  # noqa: BLE001
        logger.warning("Could not read native broker credentials before removal")
        return jsonify({"status": "error", "message": "Could not remove native account."}), 500

    if not _quiesce_current_router():
        return jsonify({
            "status": "error",
            "message": "Broker router is still processing writes; account was not changed.",
        }), 503

    try:
        remove_for = getattr(store, "remove_for", None)
        if callable(remove_for):
            remove_for(adapter_id, account_id)
        else:
            store.remove(account_id)
    except Exception:  # noqa: BLE001
        logger.warning("Credential delete failed for %s", selector_ref(adapter_id, account_id))
        _restore_router_from_vault(store, registry)
        return jsonify({"status": "error", "message": "Could not remove native account."}), 500

    # Commit workspace state before evicting the live session. If the workspace
    # is locked or unwritable, restore the vault row and leave runtime state
    # untouched so the operator can retry safely.
    default_notice: str | None = None
    try:
        default_notice = _deregister_selector_in_workspace(adapter_id, account_id)
    except Exception:  # noqa: BLE001
        vault_restored = True
        try:
            store.store(
                account_id,
                str(prior_meta.get("broker") or adapter_id),
                str(prior_meta.get("label") or account_id),
                prior_credentials,
                is_primary=bool(prior_meta.get("is_primary")),
                adapter_id=adapter_id,
            )
        except Exception:  # noqa: BLE001
            vault_restored = False
            logger.critical("Could not restore native broker vault row after workspace removal failure")
        if not vault_restored:
            # The workspace still names the selector but its credential row no
            # longer exists. Evict the session and rebuild from disk so the
            # reachable write path fails closed instead of keeping an
            # unrepairable in-memory account alive.
            try:
                registry.remove_session_for(adapter_id, account_id)
            except Exception:  # noqa: BLE001 - the router rebuild is the safety boundary
                pass
        _restore_router_from_vault(store, registry)
        logger.warning("Selector deregister failed for %s", selector_ref(adapter_id, account_id))
        return jsonify({"status": "error", "message": "Could not remove native account."}), 500

    # The old generation is drained and persistent removal is committed. Evict
    # the session before publishing a replacement so the new router cannot ever
    # resolve a removed selector through a stale registry entry.
    try:
        registry.remove_session_for(adapter_id, account_id)
    except Exception:  # noqa: BLE001 - no session is fine
        pass
    if _workspace_execution_default_is_disabled():
        _disable_broker_routing()
    else:
        try:
            _configure_broker_router_checked(store, registry)
        except _RouterRebuildError:
            _disable_broker_routing()
            logger.warning("Native account removed but broker routing rebuild failed")
            return jsonify({
                "status": "error",
                "message": "Native account removed; routing is unavailable.",
            }), 500

    # Drop any stale login-status entry so a later re-add of the same selector
    # doesn't inherit a phantom "needs fresh login" from the removed account.
    status_map = current_app.config.get("NATIVE_SESSION_STATUS")
    if isinstance(status_map, dict):
        status_map.pop(f"{adapter_id}:{account_id}", None)

    # If that was the broker's last account, stop its daily refresh job so it
    # doesn't fire every morning against a broker with nothing to refresh.
    try:
        remaining = any(
            str(r.get("adapter_id") or r.get("broker") or "") == adapter_id
            for r in store.list_accounts()
        )
    except Exception:  # noqa: BLE001
        remaining = True
    if not remaining:
        _schedule_refresh_job(adapter_id, remove=True)

    body: dict[str, Any] = {
        "status": "success",
        "message": f"{adapter_id} account {account_id} removed.",
        "data": {},
    }
    if default_notice:
        # Surface the write-default change so the UI can tell the operator —
        # a silent workspace.json diff is exactly the failure mode the
        # fail-closed replacement policy exists to prevent.
        body["data"]["notice"] = default_notice
    return jsonify(body)
