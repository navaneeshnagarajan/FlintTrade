"""Native broker account capture + activation (Phase 1 G4).

The interactive counterpart to the boot-time credential-replay login step
(``flinttrade_gateway.native_login``). Connecting a currently connectable native
broker is a four-step transaction, all fail-closed:

  1. Encrypt + persist the broker credentials to the vault, keyed by the
     composite ``(adapter_id, account_id)`` selector.
  2. Register the selector in ``workspace.json brokers.registered`` and grant
     the operator actor an ACL entry in ``brokers.account_acls`` (so reads and
     gated writes for this selector are authorised).
  3. Rebuild the ``BrokerRouter`` — the native adapter, previously dormant for
     want of credentials, now attests + has-credentials + is-registered and so
     activates.
  4. Run the native adapter's ``login()`` and register the resulting session,
     so the selector is immediately live.

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

import functools
import html
import inspect
import json
import logging
import re
import threading
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, jsonify, request

from flinttrade_core.models import Order
from flinttrade_gateway.adapter import BROKER_CATALOG
from flinttrade_gateway.log_safety import selector_ref
from flinttrade_gateway.native_login import BROKER_LOGIN_RETRY_MESSAGE
from .workspace import workspace_dir

logger = logging.getLogger("flinttrade.native_accounts")

# Serialises the whole connect transaction. _do_connect snapshots workspace.json,
# runs a multi-second broker login, then restores the snapshot verbatim on
# failure — so two connects overlapping in time could let the restore of a
# FAILED one clobber the workspace a concurrent SUCCEEDED one just wrote. This is
# a single-operator desktop tool (connects are normally sequential), but the lock
# closes the window cheaply: connects run one at a time.
_CONNECT_LOCK = threading.Lock()


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


def _sdk_attestations_by_pin() -> dict[str, dict[str, Any]]:
    """Return installed SDK attestation rows keyed by brokers.lock pin name."""
    try:
        from .broker_sdk_attest import attestations_by_pin  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover - optional during isolated imports
        logger.warning("Broker SDK attestation unavailable for native catalogue (%s)", exc)
        return {}
    try:
        return attestations_by_pin()
    except Exception as exc:  # pragma: no cover - route must remain non-fatal
        logger.warning("Broker SDK attestation failed for native catalogue (%s)", exc)
        return {}


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


def _register_selector_in_workspace(
    adapter_id: str, account_id: str, actor_id: str, is_primary: bool
) -> None:
    """Add the native selector to brokers.registered + ACL the operator.

    Read-modify-write of ``workspace.json``. Idempotent — re-connecting the same
    account does not duplicate the selector or the actor. When ``is_primary`` (or
    no execution default is set yet) the selector becomes ``brokers.execution.default``.
    """
    selector = f"{adapter_id}:{account_id}"
    path = workspace_dir() / "workspace.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    else:
        # No workspace.json yet — seed from the spec defaults so the existing
        # brokers block (incl. the openalgo:default registration) is preserved
        # rather than clobbered by a partial write.
        from .workspace_migrations import default_workspace_config  # noqa: PLC0415

        data = default_workspace_config()

    brokers = data.setdefault("brokers", {})
    registered = brokers.setdefault("registered", [])
    if selector not in registered:
        registered.append(selector)

    acls = brokers.setdefault("account_acls", {})
    adapter_acls = acls.setdefault(adapter_id, {})
    actors = adapter_acls.setdefault(account_id, [])
    if actor_id not in actors:
        actors.append(actor_id)

    execution = brokers.setdefault("execution", {})
    if is_primary or not execution.get("default"):
        execution["default"] = selector

    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tmp.replace(path)


def _snapshot_workspace() -> str | None:
    """Return the raw workspace.json text (or None if it does not exist yet).

    Paired with :func:`_restore_workspace` for a transactional connect: a failed
    connect must revert EVERY workspace mutation (registered, account_acls, AND
    ``execution.default``) to exactly its prior state — surgically blanking the
    default would brick the order path when a working default already existed.
    """
    path = workspace_dir() / "workspace.json"
    return path.read_text(encoding="utf-8") if path.exists() else None


def _restore_workspace(snapshot: str | None) -> None:
    """Restore workspace.json to a snapshot from :func:`_snapshot_workspace`."""
    path = workspace_dir() / "workspace.json"
    if snapshot is None:
        # There was no workspace.json before the attempt — remove one the
        # register step may have created so nothing partial is left behind.
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
        return
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(snapshot, encoding="utf-8")
    tmp.replace(path)


def _deregister_selector_in_workspace(adapter_id: str, account_id: str) -> None:
    """Remove the native selector from brokers.registered / account_acls / default.

    The inverse of :func:`_register_selector_in_workspace`; used by the remove
    route to drop a disconnected account (the failed-connect rollback instead
    restores the whole workspace snapshot via :func:`_restore_workspace`). No-op
    if there is no workspace.json.
    """
    selector = f"{adapter_id}:{account_id}"
    path = workspace_dir() / "workspace.json"
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    brokers = data.get("brokers", {})
    if selector in brokers.get("registered", []):
        brokers["registered"].remove(selector)
    brokers.get("account_acls", {}).get(adapter_id, {}).pop(account_id, None)
    execution = brokers.setdefault("execution", {})
    registered = [str(entry) for entry in brokers.get("registered", []) if str(entry)]
    if execution.get("default") == selector:
        if "openalgo:default" in registered:
            execution["default"] = "openalgo:default"
        elif registered:
            execution["default"] = registered[0]
        else:
            execution["default"] = ""
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tmp.replace(path)


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


def _activate_after_credentials(adapter_id: str, account_id: str) -> dict[str, Any]:
    """Rebuild the router and log the native in; return its login result.

    ``verify=True``: this is an interactive operator action (connect / daily
    re-auth), so probe the freshly-established session against the broker — a
    dead token must report ``needs_relogin`` here, not a false "connected".
    """
    from .app import _reestablish_native_sessions, configure_broker_router  # noqa: PLC0415

    app = current_app._get_current_object()  # type: ignore[attr-defined]
    configure_broker_router(
        app,
        app.config.get("REGISTRY"),
        app.config.get("CREDENTIAL_STORE"),
        app.config.get("CLIENT"),
    )
    results = _reestablish_native_sessions(app, verify=True)
    return results


def _restore_vault_after_failed_store(
    store: Any,
    *,
    account_id: str,
    adapter_id: str,
    label: str,
    is_new_account: bool,
    prior_meta: dict[str, Any] | None,
    prior_credentials: dict[str, Any] | None,
) -> None:
    """Undo the vault overwrite made by a failed connect transaction."""
    if is_new_account:
        try:
            remove_for = getattr(store, "remove_for", None)
            if callable(remove_for):
                remove_for(adapter_id, account_id)
            else:
                store.remove(account_id)
        except Exception:  # noqa: BLE001 - best effort; nothing to clean up
            pass
    elif prior_credentials is not None:
        try:
            store.store(
                account_id, adapter_id, str((prior_meta or {}).get("label") or label),
                prior_credentials, is_primary=bool((prior_meta or {}).get("is_primary")), adapter_id=adapter_id,
            )
        except Exception:  # noqa: BLE001
            logger.warning("Could not restore prior native broker vault row")


@_serialized
def _do_connect(
    adapter_id: str,
    account_id: str,
    label: str,
    credentials: dict[str, Any],
    is_primary: bool,
) -> tuple[dict[str, Any], int]:
    """Store creds → register + ACL → rebuild router → login → session.

    The shared connect transaction used by both the direct-credential POST and
    the OAuth callback. Returns ``(response_body, http_status)``. Fail-closed at
    each stage. Serialised by ``_CONNECT_LOCK`` (see above) so an overlapping
    connect's failure-rollback can never clobber another connect's workspace
    write.
    """
    store = current_app.config.get("CREDENTIAL_STORE")
    registry = current_app.config.get("REGISTRY")
    if store is None or registry is None:
        return {"status": "error", "message": "Credential store or registry unavailable."}, 503
    sdk_not_ready = _native_sdk_not_ready_body(adapter_id)
    if sdk_not_ready is not None:
        return sdk_not_ready, 503

    # --- Snapshot everything the connect will mutate, for a transactional
    # rollback on failure. new-vs-existing is decided by PRESENCE via
    # list_accounts (which never decrypts), so an existing-but-undecryptable row
    # is not misread as brand-new and destroyed. The workspace snapshot lets a
    # failed connect revert registered/account_acls/execution.default to EXACTLY
    # the prior state — a working default must never be blanked by a rollback.
    prior_meta: dict[str, Any] | None = None
    try:
        for row in store.list_accounts():
            if (
                str(row.get("adapter_id") or row.get("broker") or "") == adapter_id
                and str(row.get("account_id") or "") == account_id
            ):
                prior_meta = row
                break
    except Exception:  # noqa: BLE001 - treat an unreadable listing as no prior row
        prior_meta = None
    is_new_account = prior_meta is None
    prior_credentials: dict[str, Any] | None = None
    if not is_new_account:
        try:
            prior_credentials = store.retrieve_for(adapter_id, account_id)
        except Exception:  # noqa: BLE001 - existing but undecryptable: keep the row, can't restore creds
            prior_credentials = None
    ws_snapshot = _snapshot_workspace()

    try:
        store.store(account_id, adapter_id, label, credentials, is_primary=is_primary, adapter_id=adapter_id)
    except Exception:  # noqa: BLE001
        return {"status": "error", "message": "Could not store broker auth material"}, 500

    actor_id = _operator_actor_id()
    try:
        _register_selector_in_workspace(adapter_id, account_id, actor_id, is_primary)
    except Exception:  # noqa: BLE001
        logger.error("Failed to register native broker selector in workspace")
        try:
            _restore_workspace(ws_snapshot)
        except Exception:  # noqa: BLE001
            logger.warning("Workspace rollback failed after native selector registration error")
        _restore_vault_after_failed_store(
            store,
            account_id=account_id,
            adapter_id=adapter_id,
            label=label,
            is_new_account=is_new_account,
            prior_meta=prior_meta,
            prior_credentials=prior_credentials,
        )
        return {"status": "error", "message": "Could not register broker selector"}, 500

    login_results = _activate_after_credentials(adapter_id, account_id)
    selector = f"{adapter_id}:{account_id}"
    login_state = login_results.get(selector, "not-activated")
    session_status = _session_status(registry, adapter_id, account_id)
    connected = session_status["has_session"]
    if connected:
        # G5: give the freshly connected broker a daily 08:05 IST refresh job on
        # the already-running rotator (configure_session_rotation only scheduled
        # brokers present at boot). Idempotent (replace_existing).
        _schedule_refresh_job(adapter_id)
    else:
        # Failed connect: revert the workspace mutation in full (registered,
        # ACL, and execution.default all back to their prior values), then fix
        # up the vault row.
        try:
            _restore_workspace(ws_snapshot)
        except Exception:  # noqa: BLE001
            logger.warning("Workspace rollback failed for native broker connect")
        if is_new_account:
            # Brand-new connect that never established a session — purge the
            # just-stored row so a dead OAuth code / stale TOTP is not replayed.
            _restore_vault_after_failed_store(
                store,
                account_id=account_id,
                adapter_id=adapter_id,
                label=label,
                is_new_account=is_new_account,
                prior_meta=prior_meta,
                prior_credentials=prior_credentials,
            )
        elif prior_credentials is not None:
            # Re-connect of an existing account: restore the FULL prior vault row
            # (credentials + label + is_primary) the store.store() overwrite just
            # clobbered — update_credentials_for alone would leave the metadata
            # wrong.
            _restore_vault_after_failed_store(
                store,
                account_id=account_id,
                adapter_id=adapter_id,
                label=label,
                is_new_account=is_new_account,
                prior_meta=prior_meta,
                prior_credentials=prior_credentials,
            )
    return {
        "status": "success" if connected else "error",
        "data": {
            "adapter_id": adapter_id,
            "account_id": account_id,
            "connected": connected,
            "login": login_state,
            "session": session_status,
        },
        "message": (
            f"{adapter_id} account {account_id} connected."
            if connected
            else f"Login did not establish a session ({login_state}); credentials were not kept."
        ),
    }, (200 if connected else 502)


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
        return jsonify({
            "status": "error",
            "message": f"'{adapter_id}' is not yet available for native connect (coming soon).",
        }), 400
    if not _is_safe_account_id(account_id):
        return jsonify({"status": "error", "message": "account_id must use letters, numbers, dot, underscore, @ or hyphen."}), 400
    if not isinstance(credentials, dict) or not credentials:
        return jsonify({"status": "error", "message": "credentials (a non-empty object) is required."}), 400

    _body_out, code = _do_connect(adapter_id, account_id, label, credentials, is_primary)
    if code == 200:
        return jsonify(_public_connect_success_body()), 200
    if code == 503 and _body_out.get("data", {}).get("login") == "sdk-not-ready":
        return jsonify(_body_out), 503
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
        return jsonify({
            "status": "error",
            "message": f"'{adapter_id}' is not yet available for native connect (coming soon).",
        }), 400
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
    msg = (
        f"{adapter_id} account connected - you can close this tab and return to FlintTrade."
        if connected
        else "Login failed - return to FlintTrade and try again."
    )
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
def relogin_native_account(adapter_id: str, account_id: str) -> Any:
    """Re-authenticate a native account (daily re-auth / token refresh).

    Body (optional): ``{credentials}`` — fresh credentials to re-store first
    (e.g. a new daily access token); omit to replay the stored credentials.
    """
    adapter_id = adapter_id.strip().lower()
    if adapter_id not in _NATIVE_BROKER_IDS:
        return jsonify({"status": "error", "message": f"'{adapter_id}' is not a native broker."}), 400
    if adapter_id not in _CONNECTABLE_BROKER_IDS:
        return jsonify({
            "status": "error",
            "message": f"'{adapter_id}' is not yet available for native connect (coming soon).",
        }), 400

    store = current_app.config.get("CREDENTIAL_STORE")
    registry = current_app.config.get("REGISTRY")
    if store is None or registry is None:
        return jsonify({"status": "error", "message": "Credential store or registry unavailable."}), 503
    sdk_not_ready = _native_sdk_not_ready_body(adapter_id)
    if sdk_not_ready is not None:
        return jsonify(sdk_not_ready), 503

    body: dict[str, Any] = request.get_json(silent=True) or {}
    fresh = body.get("credentials")
    if isinstance(fresh, dict) and fresh:
        # Payload-only update: re-authenticating an EXISTING account must not
        # reset its label to the adapter id or clear its is_primary flag (which
        # store()'s ON CONFLICT upsert would). update_credentials_for swaps just
        # the encrypted payload and leaves the metadata + created_at intact.
        try:
            store.update_credentials_for(adapter_id, account_id, fresh)
        except Exception:  # noqa: BLE001
            return jsonify({"status": "error", "message": "Could not store fresh credentials"}), 500

    login_results = _activate_after_credentials(adapter_id, account_id)
    selector = f"{adapter_id}:{account_id}"
    session_status = _session_status(registry, adapter_id, account_id)
    connected = session_status["has_session"]
    return jsonify({
        "status": "success" if connected else "error",
        "data": {"login": login_results.get(selector, "not-activated"), "session": session_status},
    }), (200 if connected else 502)


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
    if kind in {"ltp", "quote_details"}:
        requested = list(args[0]) if args and isinstance(args[0], (list, tuple)) else []
        data = _canonical_ltp_rows(data, requested)
    return jsonify({"status": "success", "data": data})


@native_accounts_bp.route("/accounts/<adapter_id>/<account_id>/set-primary", methods=["POST"])
def set_primary_native_account(adapter_id: str, account_id: str) -> Any:
    """Promote a live native selector to the workspace execution default."""
    adapter_id = adapter_id.strip().lower()
    if adapter_id not in _NATIVE_BROKER_IDS:
        return jsonify({"status": "error", "message": "Broker is not a native broker."}), 404
    if adapter_id not in _CONNECTABLE_BROKER_IDS:
        return jsonify({"status": "error", "message": "Native broker connect is coming soon."}), 400

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

    snapshot = _snapshot_workspace()
    try:
        _register_selector_in_workspace(adapter_id, account_id, _operator_actor_id(), True)

        from .app import configure_broker_router  # noqa: PLC0415

        app = current_app._get_current_object()  # type: ignore[attr-defined]
        configure_broker_router(app, registry, store, app.config.get("CLIENT"))

        set_primary = getattr(store, "set_primary", None)
        if not callable(set_primary):
            raise RuntimeError("Credential store cannot set primary accounts")
        set_primary(account_id)
    except Exception:  # noqa: BLE001
        _restore_workspace(snapshot)
        try:
            from .app import configure_broker_router  # noqa: PLC0415

            app = current_app._get_current_object()  # type: ignore[attr-defined]
            configure_broker_router(app, registry, store, app.config.get("CLIENT"))
        except Exception:  # noqa: BLE001 - best-effort rollback refresh
            pass
        logger.warning("Could not set native primary broker account")
        return jsonify({"status": "error", "message": "Could not set primary native account."}), 500

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
def remove_native_account(adapter_id: str, account_id: str) -> Any:
    """Remove a native account: drop its session, credentials, and selector."""
    adapter_id = adapter_id.strip().lower()
    store = current_app.config.get("CREDENTIAL_STORE")
    registry = current_app.config.get("REGISTRY")
    if store is None or registry is None:
        return jsonify({"status": "error", "message": "Credential store or registry unavailable."}), 503

    # Drop the live session first so no dispatch can race the credential delete.
    try:
        registry.remove_session_for(adapter_id, account_id)
    except Exception:  # noqa: BLE001 - no session is fine
        pass
    try:
        remove_for = getattr(store, "remove_for", None)
        if callable(remove_for):
            remove_for(adapter_id, account_id)
        else:
            store.remove(account_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Credential delete failed for %s: %s", selector_ref(adapter_id, account_id), exc)

    # Deregister the selector from workspace.json.
    try:
        _deregister_selector_in_workspace(adapter_id, account_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Selector deregister failed for %s: %s", selector_ref(adapter_id, account_id), exc)

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

    # Rebuild so the removed native drops out of routing.
    from .app import configure_broker_router  # noqa: PLC0415

    app = current_app._get_current_object()  # type: ignore[attr-defined]
    configure_broker_router(app, registry, store, app.config.get("CLIENT"))
    return jsonify({"status": "success", "message": f"{adapter_id} account {account_id} removed."})
