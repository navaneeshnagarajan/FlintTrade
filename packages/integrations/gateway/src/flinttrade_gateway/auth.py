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
import math
import threading
from functools import wraps
from typing import Any

from flask import Blueprint, current_app, g, jsonify, request

from flinttrade_core.broker_account_cutover import guard_broker_account_http, mutation_admission_for

from .adapter import BROKER_CATALOG

logger = logging.getLogger("flinttrade.gateway.auth")

gateway_bp = Blueprint("gateway", __name__, url_prefix="/v1")

_ACCOUNT_NOT_FOUND_MESSAGE = "Broker account not found"
_AUTH_FAILED_MESSAGE = "Broker authentication failed"
_BROKER_NOT_FOUND_MESSAGE = "Broker not found"
_CREDENTIALS_INVALID_MESSAGE = "Invalid broker credentials"


def _is_quarantine_path() -> bool:
    return request.path == "/v1/accounts/quarantine" or request.path.startswith("/v1/accounts/quarantine/")


def guard_quarantine_family() -> Any | None:
    """Full-session recovery proof before body interpretation or unmatched dispatch."""
    if not _is_quarantine_path() or getattr(g, "credential_quarantine_guard_complete", False):
        return None
    from flinttrade_core.auth_routes import (  # noqa: PLC0415
        _OperatorSessionVerificationError,
        verify_operator_session_token,
    )

    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not token:
        token = request.headers.get("X-FlintTrade-Token", "").strip()
    if not token:
        return jsonify({"error": "authentication_required"}), 401
    try:
        principal = verify_operator_session_token(token)
    except _OperatorSessionVerificationError:
        return jsonify({"error": "authentication_required"}), 401
    mutating = request.method in {"POST", "PUT", "PATCH", "DELETE"}
    scope = "admin.accounts.write" if mutating else "admin.accounts.read"
    if scope not in principal.scopes:
        return jsonify({"error": "forbidden"}), 403
    if mutating:
        denied = guard_broker_account_http()
        if denied is not None:
            return denied
    if request.method not in {"GET", "HEAD"}:
        return jsonify({"error": "method_not_allowed"}), 405
    g.credential_quarantine_guard_complete = True
    return None


@gateway_bp.after_request
def apply_quarantine_cache_policy(response: Any) -> Any:
    """Also cover unmatched descendants when registered on the application."""
    if _is_quarantine_path():
        response.headers["Cache-Control"] = "no-store"
    return response


@gateway_bp.before_request
def _guard_management_writes() -> Any | None:
    """Require the operator's app session on every management write (G9).

    Every POST/PUT/DELETE on this blueprint mutates broker accounts,
    credentials, or gateway config — none of which an arbitrary local process
    should be able to do just because it can reach 127.0.0.1. The guard
    callable is injected by the core app factory via
    ``app.config["BROKER_MGMT_WRITE_GUARD"]`` (the gateway package cannot
    import core's JWT machinery without inverting the dependency); when the
    blueprint is mounted without one, authentication retains its standalone
    behaviour. Account availability is checked afterwards in every composition.
    The browser-redirect GET callback checks availability at its own entrypoint.
    """
    if _is_quarantine_path():
        return guard_quarantine_family()
    if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
        return None
    guard = current_app.config.get("BROKER_MGMT_WRITE_GUARD")
    if guard is not None:
        auth_error = guard()
        if auth_error is not None:
            return auth_error
    return guard_broker_account_http()


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


@gateway_bp.route("/accounts/quarantine", methods=["GET"])
def list_quarantined_credentials() -> Any:
    """Read the composed vault's explicit metadata projection, without recreation."""
    denied = guard_quarantine_family()
    if denied is not None:
        return denied
    try:
        entries = _credential_store().list_quarantine()
        return jsonify({"quarantined_credentials": [{
            "quarantine_id": str(entry.ref.quarantine_id),
            "source_vault_incarnation": str(entry.ref.source_vault_incarnation),
            "row_generation": entry.ref.row_generation,
            "reason": entry.reason,
            "provenance": entry.provenance,
        } for entry in entries]})
    except Exception:
        return jsonify({"error": "credential_quarantine_unavailable"}), 503


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














# ---------------------------------------------------------------------------
# OAuth flow
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# Credential-based auth (TOTP / API key)
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# OTP flow
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# Per-broker API rate limits (Account Manager — customisable throttles)
# ---------------------------------------------------------------------------


def _live_rate_limiter() -> Any | None:
    """Return the limiter owned by the active broker dependency generation."""
    app = current_app._get_current_object()
    router = app.config.get("BROKER_ROUTER")
    limiter = getattr(router, "rate_limiter", None) if router is not None else None
    if limiter is not None:
        return limiter
    dependencies = app.extensions.get("flinttrade_broker_dependencies")
    return getattr(dependencies, "rate_limiter", None)


def _parse_rate(value: Any) -> tuple[bool, float | None]:
    """Validate an optional finite non-negative rate. Returns (ok, value_or_None)."""
    if value is None:
        return True, None
    try:
        rate = float(value)
    except (TypeError, ValueError, OverflowError):
        return False, None
    valid = math.isfinite(rate) and rate >= 0
    return valid, rate if valid else None


@gateway_bp.route("/rate-limits", methods=["GET"])
def get_rate_limits() -> Any:
    """Return the live effective per-broker API rate limits (requests/sec).

    Shape: ``{ "limits": { broker_id: { "order": N, "data": M } } }`` where 0
    means unlimited. Empty when no limiter is active (no adapters with limits).
    """
    limiter = _live_rate_limiter()
    limits = limiter.snapshot() if limiter is not None else {}
    return jsonify({"status": "success", "limits": limits})


def _rate_limit_generation_lease(handler: Any) -> Any:
    """Serialise workspace broker mutation with app-owned generation rebuilds."""
    @wraps(handler)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        mutation_admission_for(current_app)()
        from flinttrade_core.app import _broker_router_drain_timeout  # noqa: PLC0415

        app = current_app._get_current_object()
        lock = app.config.setdefault("BROKER_ROUTER_REBUILD_LOCK", threading.RLock())
        if not lock.acquire(timeout=_broker_router_drain_timeout(app)):
            return jsonify({"status": "error", "message": "Broker routing is busy"}), 503
        try:
            return handler(*args, **kwargs)
        finally:
            lock.release()
    return wrapped


@gateway_bp.route("/rate-limits", methods=["PUT"])
@_rate_limit_generation_lease
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

    # Persist first: a rejected authority update must never alter live limits.
    limiter = _live_rate_limiter()
    app = current_app._get_current_object()
    previous_dependencies = app.extensions.get("flinttrade_broker_dependencies")

    # Persist as the permanent default in workspace.json.
    try:
        from flinttrade_core.workspace import Workspace  # noqa: PLC0415

        ws = Workspace()

        def update_override(config: dict[str, Any]) -> None:
            current_brokers = config.get("brokers")
            brokers = dict(current_brokers) if isinstance(current_brokers, dict) else {}
            current_overrides = brokers.get("rate_limits")
            overrides = dict(current_overrides) if isinstance(current_overrides, dict) else {}
            existing = overrides.get(broker_id)
            entry = dict(existing) if isinstance(existing, dict) else {}
            if order is not None:
                entry["order"] = order
            if data is not None:
                entry["data"] = data
            overrides[broker_id] = entry
            brokers["rate_limits"] = overrides
            config["brokers"] = brokers

        if "REGISTRY" in current_app.config:
            from flinttrade_core.app import retire_broker_dependencies  # noqa: PLC0415

            if not retire_broker_dependencies(current_app._get_current_object()):
                return jsonify({"status": "error", "message": "Broker routing is busy"}), 503
        ws.update(update_override)
    except Exception:  # noqa: BLE001 - rejected authority must stay fail-closed
        logger.warning("Could not persist rate-limit override")
        return jsonify({"status": "error", "message": "Rate-limit configuration unavailable"}), 503

    if "REGISTRY" in current_app.config:
        from flinttrade_core.app import (  # noqa: PLC0415
            broker_reads_published_without_writes,
            configure_broker_router,
        )

        registry = _registry()
        client = app.config.get("CLIENT")
        rebuilt = configure_broker_router(app, registry, app.config.get("CREDENTIAL_STORE"), client)
        if not rebuilt and not broker_reads_published_without_writes(
            app,
            previous_dependencies=previous_dependencies,
            registry=registry,
            broker_client=client,
        ):
            return jsonify({"status": "error", "message": "Broker routing unavailable"}), 503
        limiter = _live_rate_limiter()
        if limiter is None:
            dependencies = app.extensions.get("flinttrade_broker_dependencies")
            limiter = getattr(dependencies, "rate_limiter", None)
    elif limiter is not None:
        limiter.apply_override(broker_id, order=order, data=data)

    limits = limiter.snapshot() if limiter is not None else {}
    return jsonify({"status": "success", "limits": limits})
