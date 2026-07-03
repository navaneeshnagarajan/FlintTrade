"""Native broker account capture + activation (Phase 1 G4).

The interactive counterpart to the boot-time credential-replay login step
(``flinttrade_gateway.native_login``). Connecting a native broker
(Dhan/Upstox/Kotak Neo/IndMoney) is a four-step transaction, all fail-closed:

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

These routes rely on the loopback allowance for local desktop capture; when a
session JWT is present its ``sub`` is used as the ACL actor so the right
operator principal is authorised (falls back to the single-operator account
username otherwise). Broker-management auth hardening is tracked as G9.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from .workspace import workspace_dir

logger = logging.getLogger("flinttrade.native_accounts")

# Only the four founder-broker natives may be captured through this path; the
# OpenAlgo bridge uses its own /v1/accounts flow.
_NATIVE_BROKER_IDS = {"dhan", "upstox", "kotakneo", "indmoney"}

native_accounts_bp = Blueprint("native_accounts", __name__, url_prefix="/api/v1/native")


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


def _session_status(registry: Any, adapter_id: str, account_id: str) -> dict[str, Any]:
    """Non-throwing snapshot of a selector's live session, for the UI."""
    try:
        session = registry.get_session_for(adapter_id, account_id)
    except Exception:  # noqa: BLE001 - no session registered
        return {"has_session": False, "expires_at": None}
    return {
        "has_session": True,
        "expires_at": getattr(session, "expires_at", None),
    }


def _activate_after_credentials(adapter_id: str, account_id: str) -> dict[str, Any]:
    """Rebuild the router and log the native in; return its login result."""
    from .app import _reestablish_native_sessions, configure_broker_router  # noqa: PLC0415

    app = current_app._get_current_object()  # type: ignore[attr-defined]
    configure_broker_router(
        app,
        app.config.get("REGISTRY"),
        app.config.get("CREDENTIAL_STORE"),
        app.config.get("CLIENT"),
    )
    results = _reestablish_native_sessions(app)
    return results


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
            "message": f"'{adapter_id}' is not a native broker. Native brokers: {sorted(_NATIVE_BROKER_IDS)}.",
        }), 400
    if not account_id:
        return jsonify({"status": "error", "message": "account_id is required."}), 400
    if not isinstance(credentials, dict) or not credentials:
        return jsonify({"status": "error", "message": "credentials (a non-empty object) is required."}), 400

    store = current_app.config.get("CREDENTIAL_STORE")
    registry = current_app.config.get("REGISTRY")
    if store is None or registry is None:
        return jsonify({"status": "error", "message": "Credential store or registry unavailable."}), 503

    # 1. Persist credentials (encrypted) under the composite selector.
    try:
        store.store(account_id, adapter_id, label, credentials, is_primary=is_primary, adapter_id=adapter_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to store native credentials for %s:%s", adapter_id, account_id)
        return jsonify({"status": "error", "message": f"Could not store credentials: {exc}"}), 500

    # 2. Register the selector + ACL the operator in workspace.json.
    actor_id = _operator_actor_id()
    try:
        _register_selector_in_workspace(adapter_id, account_id, actor_id, is_primary)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to register selector %s:%s in workspace", adapter_id, account_id)
        return jsonify({"status": "error", "message": f"Could not register broker selector: {exc}"}), 500

    # 3 + 4. Rebuild the router (activates the native) and log it in.
    login_results = _activate_after_credentials(adapter_id, account_id)
    selector = f"{adapter_id}:{account_id}"
    login_state = login_results.get(selector, "not-activated")
    session_status = _session_status(registry, adapter_id, account_id)

    connected = session_status["has_session"]
    return jsonify({
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
            else f"Credentials stored but login did not establish a session: {login_state}"
        ),
    }), (200 if connected else 502)


@native_accounts_bp.route("/accounts/<adapter_id>/<account_id>/login", methods=["POST"])
def relogin_native_account(adapter_id: str, account_id: str) -> Any:
    """Re-authenticate a native account (daily re-auth / token refresh).

    Body (optional): ``{credentials}`` — fresh credentials to re-store first
    (e.g. a new daily access token); omit to replay the stored credentials.
    """
    adapter_id = adapter_id.strip().lower()
    if adapter_id not in _NATIVE_BROKER_IDS:
        return jsonify({"status": "error", "message": f"'{adapter_id}' is not a native broker."}), 400

    store = current_app.config.get("CREDENTIAL_STORE")
    registry = current_app.config.get("REGISTRY")
    if store is None or registry is None:
        return jsonify({"status": "error", "message": "Credential store or registry unavailable."}), 503

    body: dict[str, Any] = request.get_json(silent=True) or {}
    fresh = body.get("credentials")
    if isinstance(fresh, dict) and fresh:
        try:
            existing_label = adapter_id
            store.store(account_id, adapter_id, existing_label, fresh, adapter_id=adapter_id)
        except Exception as exc:  # noqa: BLE001
            return jsonify({"status": "error", "message": f"Could not store fresh credentials: {exc}"}), 500

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
    except Exception as exc:  # noqa: BLE001
        return jsonify({"status": "error", "message": f"Could not list accounts: {exc}"}), 500

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
        accounts.append(entry)
    return jsonify({"status": "success", "data": {"accounts": accounts}})


_READ_KINDS = {"funds", "positions", "holdings", "profile"}


@native_accounts_bp.route("/accounts/<adapter_id>/<account_id>/<kind>", methods=["GET"])
def read_native_account(adapter_id: str, account_id: str, kind: str) -> Any:
    """Read a native account's funds/positions/holdings/profile via its adapter.

    Exercises the live broker session end-to-end (a real broker API call using
    the stored token). Reads are not gated (no order), only require an
    established session. Returns the adapter's raw read result.
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

    reader = getattr(adapter, kind, None)
    if reader is None:
        return jsonify({"status": "error", "message": f"{adapter_id} adapter has no '{kind}' read."}), 400
    try:
        result = asyncio.run(reader(session))
    except Exception as exc:  # noqa: BLE001 - surface the broker error verbatim
        logger.warning("Native read %s/%s %s failed: %s", adapter_id, account_id, kind, exc)
        return jsonify({"status": "error", "message": f"Broker read failed: {exc}"}), 502

    # Pydantic models -> dicts for JSON.
    def _dump(v: Any) -> Any:
        if hasattr(v, "model_dump"):
            return v.model_dump()
        if isinstance(v, list):
            return [_dump(x) for x in v]
        return v

    return jsonify({"status": "success", "data": _dump(result)})


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
        store.remove(account_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Credential delete failed for %s:%s: %s", adapter_id, account_id, exc)

    # Deregister the selector from workspace.json.
    try:
        selector = f"{adapter_id}:{account_id}"
        path = workspace_dir() / "workspace.json"
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        brokers = data.get("brokers", {})
        if selector in brokers.get("registered", []):
            brokers["registered"].remove(selector)
        brokers.get("account_acls", {}).get(adapter_id, {}).pop(account_id, None)
        if brokers.get("execution", {}).get("default") == selector:
            brokers["execution"]["default"] = ""
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Selector deregister failed for %s:%s: %s", adapter_id, account_id, exc)

    # Rebuild so the removed native drops out of routing.
    from .app import configure_broker_router  # noqa: PLC0415

    app = current_app._get_current_object()  # type: ignore[attr-defined]
    configure_broker_router(app, registry, store, app.config.get("CLIENT"))
    return jsonify({"status": "success", "message": f"{adapter_id} account {account_id} removed."})
