"""Flask blueprint for broker authentication and account management.

All endpoints are mounted under /v1/. The blueprint reads
``current_app.config["REGISTRY"]`` (a BrokerRegistry instance) and
``current_app.config["CREDENTIAL_STORE"]`` (a CredentialStore instance)
which are wired in during app startup (Task 8).

CSRF state for OAuth flows is stored in
``current_app.config["OAUTH_STATES"]``, a plain dict that maps
``state_token -> {broker, label, account_id, timestamp}``.
States older than 10 minutes are pruned on every OAuth start request.
"""

from __future__ import annotations

import logging
import secrets
import time
from typing import Any

from flask import Blueprint, current_app, jsonify, redirect, request

from .adapter import BROKER_CATALOG
from .exceptions import AuthFlowError, BrokerNotFoundError, CredentialError
from .log_safety import account_ref
from .models import AuthFlowType

logger = logging.getLogger("flinttrade.gateway.auth")

gateway_bp = Blueprint("gateway", __name__, url_prefix="/v1")

_ACCOUNT_NOT_FOUND_MESSAGE = "Broker account not found"
_AUTH_FAILED_MESSAGE = "Broker authentication failed"
_BROKER_NOT_FOUND_MESSAGE = "Broker not found"
_CREDENTIALS_INVALID_MESSAGE = "Invalid broker credentials"


@gateway_bp.before_request
def _guard_management_writes() -> Any | None:
    """Require the operator's app session on every management write (G9).

    Every POST/PUT/DELETE on this blueprint mutates broker accounts,
    credentials, or gateway config — none of which an arbitrary local process
    should be able to do just because it can reach 127.0.0.1. The guard
    callable is injected by the core app factory via
    ``app.config["BROKER_MGMT_WRITE_GUARD"]`` (the gateway package cannot
    import core's JWT machinery without inverting the dependency); when the
    blueprint is mounted without one (standalone unit tests) writes behave as
    before. The OAuth callback is a browser-redirect GET protected by its
    one-shot ``state`` token, so it is naturally exempt.
    """
    if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
        return None
    guard = current_app.config.get("BROKER_MGMT_WRITE_GUARD")
    if guard is None:
        return None
    return guard()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OAUTH_STATE_TTL: int = 600  # 10 minutes in seconds


def _registry() -> Any:
    """Return the BrokerRegistry from the current app config."""
    return current_app.config["REGISTRY"]


def _credential_store() -> Any:
    """Return the CredentialStore from the current app config."""
    return current_app.config["CREDENTIAL_STORE"]


def _oauth_states() -> dict[str, Any]:
    """Return the OAUTH_STATES dict from the current app config."""
    return current_app.config["OAUTH_STATES"]


def _purge_expired_states() -> None:
    """Remove OAuth states older than _OAUTH_STATE_TTL seconds."""
    now = time.time()
    states = _oauth_states()
    expired = [
        k for k, v in states.items() if now - v.get("timestamp", 0) > _OAUTH_STATE_TTL
    ]
    for key in expired:
        del states[key]


# ---------------------------------------------------------------------------
# Broker catalog
# ---------------------------------------------------------------------------


@gateway_bp.route("/brokers", methods=["GET"])
def list_brokers() -> Any:
    """Return all non-sandbox brokers from the catalog.

    Returns:
        JSON with ``status`` and ``brokers`` list.
    """
    brokers = [info.model_dump() for info in BROKER_CATALOG.values() if not info.is_sandbox]
    return jsonify({"status": "success", "brokers": brokers})


# ---------------------------------------------------------------------------
# Account management
# ---------------------------------------------------------------------------


@gateway_bp.route("/accounts", methods=["GET"])
def list_accounts() -> Any:
    """Return all connected broker accounts.

    Returns:
        JSON with ``status`` and ``accounts`` list.
    """
    try:
        accounts = _registry().list_accounts()
        return jsonify({
            "status": "success",
            "accounts": [a.model_dump() for a in accounts],
        })
    except Exception:
        logger.exception("Failed to list accounts")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


def _reject_coming_soon_native(broker: str) -> Any | None:
    """Reject a native broker that is catalogued but not yet connectable.

    The "coming soon" gate (only live-verified native adapters may connect) is
    enforced on the /api/v1/native/* routes; mirror it on these legacy gateway
    account/OAuth/OTP routes so a native adapter its own surface refuses cannot
    be connected through the back door. Bridge-only brokers (native=False) are
    unaffected — they connect through OpenAlgo regardless. Returns an error
    response tuple to short-circuit, or None to proceed.
    """
    info = BROKER_CATALOG.get(broker)
    if info is not None and info.native and not info.connectable:
        return jsonify({
            "status": "error",
            "message": f"'{broker}' is not yet available for native connect (coming soon).",
        }), 400
    return None


def _reject_coming_soon_native_account(account_id: str) -> Any | None:
    """Reject account-id operations when the existing account is disabled native.

    Legacy gateway operations such as reconnect and set-primary receive only an
    ``account_id``. If a native broker is later demoted back to
    ``connectable=False`` after an old account row already exists, those routes
    must honour the same gate as fresh connect routes instead of reactivating or
    promoting a coming-soon adapter.
    """
    try:
        accounts = _registry().list_accounts()
    except Exception:
        logger.exception("Failed to inspect account %s before broker gate", account_ref(account_id))
        return jsonify({"status": "error", "message": "Internal server error"}), 500
    for account in accounts:
        if str(account.account_id) == str(account_id):
            return _reject_coming_soon_native(str(account.broker))
    return None


@gateway_bp.route("/accounts", methods=["POST"])
def add_account() -> Any:
    """Add a new broker account.

    Request body (JSON):
        broker (str): Canonical broker name.
        label (str): Human-readable label for this account.
        credentials (dict): Broker-specific credentials.
        account_id (str, optional): Caller-supplied account ID; defaults to
            a random token when omitted.

    Returns:
        JSON with ``status`` and ``account`` info on success, or an error
        with the appropriate HTTP status code.
    """
    body: dict[str, Any] = request.get_json(silent=True) or {}
    broker: str = body.get("broker", "")
    label: str = body.get("label", "")
    credentials: dict[str, Any] = body.get("credentials", {})
    account_id: str = body.get("account_id") or secrets.token_hex(8)

    if not broker:
        return jsonify({"status": "error", "message": "Missing required field: broker"}), 400
    coming_soon = _reject_coming_soon_native(broker)
    if coming_soon is not None:
        return coming_soon

    try:
        info = _registry().add_account(account_id, broker, label, credentials)
        return jsonify({"status": "success", "account": info.model_dump()}), 201
    except BrokerNotFoundError:
        return jsonify({"status": "error", "message": _BROKER_NOT_FOUND_MESSAGE}), 404
    except AuthFlowError:
        return jsonify({"status": "error", "message": _AUTH_FAILED_MESSAGE}), 401
    except CredentialError:
        return jsonify({"status": "error", "message": _CREDENTIALS_INVALID_MESSAGE}), 400
    except Exception:
        logger.exception("Failed to add account broker=%r", broker)
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@gateway_bp.route("/accounts/<account_id>", methods=["DELETE"])
def remove_account(account_id: str) -> Any:
    """Remove a broker account from the registry.

    Args:
        account_id: Path parameter — the account to remove.

    Returns:
        JSON with ``status`` on success, or an error response.
    """
    try:
        _registry().remove_account(account_id)
        return jsonify({"status": "success"}), 200
    except BrokerNotFoundError:
        return jsonify({"status": "error", "message": _ACCOUNT_NOT_FOUND_MESSAGE}), 404
    except Exception:
        logger.exception("Failed to remove account %s", account_ref(account_id))
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@gateway_bp.route("/accounts/<account_id>/reconnect", methods=["POST"])
def reconnect_account(account_id: str) -> Any:
    """Re-authenticate an existing account.

    Uses credentials stored in the CredentialStore when no body credentials
    are provided.

    Args:
        account_id: Path parameter — the account to reconnect.

    Returns:
        JSON with ``status`` and updated ``account`` info.
    """
    body: dict[str, Any] = request.get_json(silent=True) or {}
    credentials: dict[str, Any] | None = body.get("credentials") or None

    coming_soon = _reject_coming_soon_native_account(account_id)
    if coming_soon is not None:
        return coming_soon

    try:
        info = _registry().reconnect_account(
            account_id,
            credentials=credentials,
            credential_store=_credential_store() if credentials is None else None,
        )
        return jsonify({"status": "success", "account": info.model_dump()})
    except BrokerNotFoundError:
        return jsonify({"status": "error", "message": _ACCOUNT_NOT_FOUND_MESSAGE}), 404
    except AuthFlowError:
        return jsonify({"status": "error", "message": _AUTH_FAILED_MESSAGE}), 401
    except CredentialError:
        return jsonify({"status": "error", "message": _CREDENTIALS_INVALID_MESSAGE}), 400
    except Exception:
        logger.exception("Failed to reconnect account %s", account_ref(account_id))
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@gateway_bp.route("/accounts/<account_id>/set-primary", methods=["POST"])
def set_primary(account_id: str) -> Any:
    """Designate an account as the primary for order routing.

    Args:
        account_id: Path parameter — the account to promote.

    Returns:
        JSON with ``status`` on success, or an error response.
    """
    coming_soon = _reject_coming_soon_native_account(account_id)
    if coming_soon is not None:
        return coming_soon

    try:
        _registry().set_primary(account_id)
        return jsonify({"status": "success"})
    except BrokerNotFoundError:
        return jsonify({"status": "error", "message": _ACCOUNT_NOT_FOUND_MESSAGE}), 404
    except Exception:
        logger.exception("Failed to set primary account %s", account_ref(account_id))
        return jsonify({"status": "error", "message": "Internal server error"}), 500


# ---------------------------------------------------------------------------
# OAuth flow
# ---------------------------------------------------------------------------


@gateway_bp.route("/auth/oauth/start", methods=["POST"])
def oauth_start() -> Any:
    """Initiate an OAuth redirect flow for a broker.

    Request body (JSON):
        broker (str): Canonical broker name with ``oauth_redirect`` flow.
        label (str, optional): Human-readable label for the new account.
        account_id (str, optional): Account ID to associate with the callback.

    Returns:
        JSON with ``redirect_url`` and ``state`` on success.
    """
    body: dict[str, Any] = request.get_json(silent=True) or {}
    broker: str = body.get("broker", "")
    label: str = body.get("label", "")
    account_id: str = body.get("account_id", "")

    if not broker:
        return jsonify({"status": "error", "message": "Missing required field: broker"}), 400

    if broker not in BROKER_CATALOG:
        return jsonify({"status": "error", "message": _BROKER_NOT_FOUND_MESSAGE}), 404
    coming_soon = _reject_coming_soon_native(broker)
    if coming_soon is not None:
        return coming_soon

    broker_info = BROKER_CATALOG[broker]
    if broker_info.auth_flow != AuthFlowType.oauth_redirect:
        return jsonify({
            "status": "error",
            "message": f"Broker '{broker}' does not use OAuth redirect flow",
        }), 400

    # Generate CSRF state token
    state = secrets.token_urlsafe(32)

    # Prune expired states before adding a new one
    _purge_expired_states()

    _oauth_states()[state] = {
        "broker": broker,
        "label": label,
        "account_id": account_id,
        "timestamp": time.time(),
    }

    # Build redirect URL (template may be None for some OAuth brokers)
    oauth_template = broker_info.oauth_url_template or ""
    redirect_url = oauth_template.replace("{state}", state) if oauth_template else ""

    return jsonify({
        "status": "success",
        "redirect_url": redirect_url,
        "state": state,
    })


@gateway_bp.route("/auth/oauth/callback", methods=["GET"])
def oauth_callback() -> Any:
    """Handle the OAuth callback from a broker.

    Query parameters:
        state (str): The CSRF state token generated by :func:`oauth_start`.
        code (str): The authorisation code from the broker.

    Returns:
        A redirect to ``/setup?auth=success`` on success, or
        ``/setup?auth=error`` on any failure.
    """
    state: str = request.args.get("state", "")
    code: str = request.args.get("code", "")

    states = _oauth_states()

    if not state or state not in states:
        logger.warning("OAuth callback with invalid/missing state %r", state)
        return redirect("/setup?auth=error")

    # Consume the state to prevent replay attacks
    state_data = states.pop(state)
    broker: str = state_data["broker"]
    label: str = state_data["label"]
    account_id: str = state_data["account_id"] or secrets.token_hex(8)

    coming_soon = _reject_coming_soon_native(broker)
    if coming_soon is not None:
        return redirect("/setup?auth=error")

    try:
        # Authenticate via the registry/adapter
        credentials = {"code": code}
        _registry().add_account(account_id, broker, label, credentials)
        _credential_store().store(
            account_id,
            broker,
            label,
            credentials,
        )
        return redirect("/setup?auth=success")
    except (BrokerNotFoundError, AuthFlowError, CredentialError):
        logger.warning("OAuth callback auth failure")
        return redirect("/setup?auth=error")
    except Exception:
        logger.exception("OAuth callback unexpected error")
        return redirect("/setup?auth=error")


# ---------------------------------------------------------------------------
# Credential-based auth (TOTP / API key)
# ---------------------------------------------------------------------------


@gateway_bp.route("/auth/credentials", methods=["POST"])
def submit_credentials() -> Any:
    """Submit credentials directly for TOTP or API-key brokers.

    Request body (JSON):
        broker (str): Canonical broker name.
        label (str): Human-readable account label.
        account_id (str, optional): Account ID; generated if omitted.
        credentials (dict): Key-value credentials (client_id, password,
            totp, api_key, etc.).

    Returns:
        JSON with ``status`` and ``account`` info on success.
    """
    body: dict[str, Any] = request.get_json(silent=True) or {}
    broker: str = body.get("broker", "")
    label: str = body.get("label", "")
    account_id: str = body.get("account_id") or secrets.token_hex(8)
    credentials: dict[str, Any] = body.get("credentials", {})

    if not broker:
        return jsonify({"status": "error", "message": "Missing required field: broker"}), 400

    if broker not in BROKER_CATALOG:
        return jsonify({"status": "error", "message": f"Broker not found: {broker}"}), 404
    coming_soon = _reject_coming_soon_native(broker)
    if coming_soon is not None:
        return coming_soon

    try:
        info = _registry().add_account(account_id, broker, label, credentials)
        _credential_store().store(account_id, broker, label, credentials)
        return jsonify({"status": "success", "account": info.model_dump()}), 201
    except BrokerNotFoundError:
        return jsonify({"status": "error", "message": _BROKER_NOT_FOUND_MESSAGE}), 404
    except AuthFlowError:
        return jsonify({"status": "error", "message": _AUTH_FAILED_MESSAGE}), 401
    except CredentialError:
        return jsonify({"status": "error", "message": _CREDENTIALS_INVALID_MESSAGE}), 400
    except Exception:
        logger.error("Failed to submit broker auth material for broker=%r", broker)
        return jsonify({"status": "error", "message": "Internal server error"}), 500


# ---------------------------------------------------------------------------
# OTP flow
# ---------------------------------------------------------------------------


@gateway_bp.route("/auth/otp/request", methods=["POST"])
def otp_request() -> Any:
    """Request an OTP from a broker (SMS-based flow).

    Request body (JSON):
        broker (str): Canonical broker name.
        mobile (str): Registered mobile number for OTP delivery.

    Returns:
        JSON with ``status`` on success.
    """
    body: dict[str, Any] = request.get_json(silent=True) or {}
    broker: str = body.get("broker", "")

    if not broker:
        return jsonify({"status": "error", "message": "Missing required field: broker"}), 400

    if broker not in BROKER_CATALOG:
        return jsonify({"status": "error", "message": _BROKER_NOT_FOUND_MESSAGE}), 404
    coming_soon = _reject_coming_soon_native(broker)
    if coming_soon is not None:
        return coming_soon

    broker_info = BROKER_CATALOG[broker]
    if broker_info.auth_flow != AuthFlowType.otp_sms:
        return jsonify({
            "status": "error",
            "message": "Broker does not use OTP SMS flow",
        }), 400

    # OTP dispatch is broker-specific; the adapter handles the actual call.
    # For the blueprint layer we validate inputs and delegate.
    try:
        credentials = {"action": "request_otp", **{k: v for k, v in body.items() if k != "broker"}}
        # Use the registry to get/create a session — the adapter's authenticate
        # handles "request_otp" action for OTP brokers.
        _registry().add_account(
            body.get("account_id") or secrets.token_hex(8),
            broker,
            body.get("label", ""),
            credentials,
        )
        return jsonify({"status": "success", "message": "OTP sent"})
    except BrokerNotFoundError:
        return jsonify({"status": "error", "message": _BROKER_NOT_FOUND_MESSAGE}), 404
    except AuthFlowError:
        return jsonify({"status": "error", "message": _AUTH_FAILED_MESSAGE}), 401
    except Exception:
        logger.exception("OTP request failed for broker=%r", broker)
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@gateway_bp.route("/auth/otp/verify", methods=["POST"])
def otp_verify() -> Any:
    """Verify an OTP submitted by the user.

    Request body (JSON):
        broker (str): Canonical broker name.
        account_id (str): Account to authenticate.
        otp (str): The one-time password received via SMS.
        credentials (dict, optional): Additional credentials if needed.

    Returns:
        JSON with ``status`` and ``account`` info on success.
    """
    body: dict[str, Any] = request.get_json(silent=True) or {}
    broker: str = body.get("broker", "")
    account_id: str = body.get("account_id") or secrets.token_hex(8)
    otp: str = body.get("otp", "")
    credentials: dict[str, Any] = body.get("credentials", {})

    if not broker:
        return jsonify({"status": "error", "message": "Missing required field: broker"}), 400
    if not otp:
        return jsonify({"status": "error", "message": "Missing required field: otp"}), 400

    if broker not in BROKER_CATALOG:
        return jsonify({"status": "error", "message": _BROKER_NOT_FOUND_MESSAGE}), 404

    # otp_verify is a fully connect-completing native entrypoint that does not
    # depend on a prior otp_request (it takes broker/account_id from its own
    # body), so it must enforce the coming-soon gate itself — otherwise a native
    # adapter whose own surface refuses connection could be attached via this
    # back door. Mirrors the guard on add_account/oauth_start/submit_credentials/
    # otp_request.
    coming_soon = _reject_coming_soon_native(broker)
    if coming_soon is not None:
        return coming_soon

    try:
        full_credentials = {"otp": otp, **credentials}
        info = _registry().add_account(account_id, broker, body.get("label", ""), full_credentials)
        _credential_store().store(account_id, broker, body.get("label", ""), full_credentials)
        return jsonify({"status": "success", "account": info.model_dump()}), 201
    except BrokerNotFoundError:
        return jsonify({"status": "error", "message": _BROKER_NOT_FOUND_MESSAGE}), 404
    except AuthFlowError:
        return jsonify({"status": "error", "message": _AUTH_FAILED_MESSAGE}), 401
    except CredentialError:
        return jsonify({"status": "error", "message": _CREDENTIALS_INVALID_MESSAGE}), 400
    except Exception:
        logger.exception("OTP verify failed for broker=%r account=%s", broker, account_ref(account_id))
        return jsonify({"status": "error", "message": "Internal server error"}), 500


# ---------------------------------------------------------------------------
# Per-broker API rate limits (Account Manager — customisable throttles)
# ---------------------------------------------------------------------------


def _live_rate_limiter() -> Any | None:
    """The running BrokerRouter's rate limiter, or None when unthrottled."""
    router = current_app.config.get("BROKER_ROUTER")
    return getattr(router, "rate_limiter", None) if router is not None else None


def _parse_rate(value: Any) -> tuple[bool, float | None]:
    """Validate an optional non-negative rate. Returns (ok, value_or_None)."""
    if value is None:
        return True, None
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return False, None
    return (rate >= 0, rate if rate >= 0 else None)


@gateway_bp.route("/rate-limits", methods=["GET"])
def get_rate_limits() -> Any:
    """Return the live effective per-broker API rate limits (requests/sec).

    Shape: ``{ "limits": { broker_id: { "order": N, "data": M } } }`` where 0
    means unlimited. Empty when no limiter is active (no adapters with limits).
    """
    limiter = _live_rate_limiter()
    limits = limiter.snapshot() if limiter is not None else {}
    return jsonify({"status": "success", "limits": limits})


@gateway_bp.route("/rate-limits", methods=["PUT"])
def update_rate_limits() -> Any:
    """Set a broker's order/data API rate limit (requests/sec; 0 = unlimited).

    Body: ``{ "broker_id": str, "order"?: number, "data"?: number }``. The change
    is applied live to the running limiter AND persisted to workspace.json
    (``brokers.rate_limits``) so it survives a restart.
    """
    body: dict[str, Any] = request.get_json(silent=True) or {}
    broker_id = str(body.get("broker_id", "")).strip()
    if not broker_id:
        return jsonify({"status": "error", "message": "broker_id is required"}), 400

    ok_order, order = _parse_rate(body.get("order"))
    ok_data, data = _parse_rate(body.get("data"))
    if not ok_order or not ok_data:
        return jsonify({"status": "error", "message": "order/data must be non-negative numbers"}), 400
    if order is None and data is None:
        return jsonify({"status": "error", "message": "provide at least one of order/data"}), 400

    # Apply live to the running limiter (if any).
    limiter = _live_rate_limiter()
    if limiter is not None:
        limiter.apply_override(broker_id, order=order, data=data)

    # Persist as the permanent default in workspace.json.
    try:
        from flinttrade_core.workspace import Workspace  # noqa: PLC0415

        ws = Workspace()
        overrides = ws.get("brokers.rate_limits", {})
        overrides = dict(overrides) if isinstance(overrides, dict) else {}
        existing = overrides.get(broker_id)
        entry = dict(existing) if isinstance(existing, dict) else {}
        if order is not None:
            entry["order"] = order
        if data is not None:
            entry["data"] = data
        overrides[broker_id] = entry
        ws.set("brokers.rate_limits", overrides)
        ws.save()
    except Exception as exc:  # noqa: BLE001 - persistence is best-effort
        logger.warning("Could not persist rate-limit override for %s: %s", broker_id, exc)

    limits = limiter.snapshot() if limiter is not None else {}
    return jsonify({"status": "success", "limits": limits})
