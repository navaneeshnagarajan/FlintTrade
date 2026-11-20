"""Authenticated read-only operator status.

The document projects state that already has an owner: the session claim,
broker read status, the decision model, the kill switch, the session
decision, broker account status, the order-dispatch ledger, strategy
status, and the paused-update flag. It does not place or cancel an order,
latch or reset the kill switch, start or stop a strategy, write the ledger,
or refresh a broker token.

A section whose owner cannot be read is ``unknown`` with a fixed reason.
The other sections are still returned. A missing value is never filled with
a healthy stand-in.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, jsonify, request

logger = logging.getLogger("flinttrade.operator_status")

_IST = ZoneInfo("Asia/Kolkata")
REASON_UNAVAILABLE = "unavailable"
REASON_UNSCOPED = "unscoped"
_MODES = frozenset({"explore", "practice", "live"})
_ORDER_ENTRY = frozenset({"open", "closed", "auction_entry"})
_STRATEGY_STATUS = frozenset({"running", "stopped", "crashed", "unknown"})
_LIFECYCLE = frozenset({"ACTIVE", "PAUSED", "STOPPED", "ERROR"})
_EXCHANGE = re.compile(r"[A-Za-z]{1,12}")
_SYMBOL = re.compile(r"[A-Za-z0-9._-]{1,32}")
_PHASE = re.compile(r"[a-z0-9_-]{1,32}")
_REASON_TOKEN = re.compile(r"[a-z0-9_]{1,64}")
_SELECTOR = re.compile(r"[A-Za-z0-9]+:[A-Za-z0-9][A-Za-z0-9._-]{0,64}")
_STRATEGY_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def install(blueprint: Blueprint) -> None:
    """Register ``GET /api/v1/operator/status`` on ``blueprint``."""
    blueprint.add_url_rule(
        "/api/v1/operator/status",
        endpoint="operator_status",
        view_func=operator_status,
        methods=["GET"],
    )


def operator_status() -> tuple[Any, int]:
    """Return the operator status document for the signed-in session.

    Account rows and dispatch counts are limited to the selectors that
    session is allowed to use. A request with no session identity leaves
    those sections unscoped. The response never includes a broker token,
    a credential, or an exception message.
    """
    data: dict[str, Any] = {
        "mode": _unknown(),
        "live_unlocked": _unknown(),
        "connected_read": _unknown(REASON_UNSCOPED),
        "laya": _unknown_laya(),
        "kill_switch": _unknown(),
        "session": _unknown(),
        "broker": _unknown(REASON_UNSCOPED),
        "dispatch": _unknown(REASON_UNSCOPED),
        "strategy": _unknown(),
        "migration_blocked": _unknown(),
    }
    try:
        data["mode"] = project_mode()
        data["live_unlocked"] = project_live_unlocked()
        scope = read_scope()
        registry = current_app.config.get("REGISTRY")
        data["connected_read"] = project_connected_read(registry, scope)
        data["broker"] = project_broker(registry, scope)
        data["dispatch"] = project_dispatch(current_app.config.get("ORDER_LIFECYCLE_LEDGER"), scope)
        data["laya"] = project_laya()
        data["kill_switch"] = project_kill_switch(current_app.config.get("SAFETY"))
        data["strategy"] = project_strategy(
            current_app.config.get("STRATEGY_RUNNER"),
            current_app.config.get("SCHEDULER"),
        )
        data["migration_blocked"] = project_migration(current_app.config.get("AUTH_SERVICE"))
        data["session"] = session_from_request()
    except Exception:
        _log("document")
    response = jsonify({"status": "success", "data": data})
    response.headers["Cache-Control"] = "no-store"
    return response, 200


def project_mode() -> dict[str, Any]:
    """Mode claim from the session, or unknown when it is missing or unreadable."""
    try:
        from flinttrade_core.order_routes import _get_mode_from_jwt  # noqa: PLC0415

        claim = _get_mode_from_jwt()
    except Exception:
        _log("mode")
        return _unknown()
    if claim in _MODES:
        return {"status": "ok", "value": claim}
    return _unknown()


def project_live_unlocked() -> dict[str, Any]:
    """Live unlock flag from the same session claim the order path reads."""
    try:
        from flinttrade_core.order_routes import _is_live_mode_unlocked  # noqa: PLC0415

        unlocked = _is_live_mode_unlocked()
    except Exception:
        _log("live_unlocked")
        return _unknown()
    if type(unlocked) is not bool:
        return _unknown()
    return {"status": "ok", "value": unlocked}


def project_connected_read(registry: Any, scope: set[str] | str) -> dict[str, Any]:
    """True when an authorised selector is already stamped Connected (read)."""
    if scope == REASON_UNSCOPED:
        return _unknown(REASON_UNSCOPED)
    if scope == REASON_UNAVAILABLE or registry is None:
        return _unknown()
    listed = getattr(registry, "list_read_smoke_sessions", None)
    if not callable(listed):
        return _unknown()
    try:
        sessions = listed()
    except Exception:
        _log("connected_read")
        return _unknown()
    try:
        matched = _any_authorised_session(sessions, scope)
    except Exception:
        _log("connected_read")
        return _unknown()
    if matched is None:
        return _unknown()
    return {"status": "ok", "value": matched}


def project_broker(registry: Any, scope: set[str] | str) -> dict[str, Any]:
    """Account status per authorised selector, from the broker registry."""
    if scope == REASON_UNSCOPED:
        return _unknown(REASON_UNSCOPED)
    if scope == REASON_UNAVAILABLE or registry is None:
        return _unknown()
    listed = getattr(registry, "list_accounts", None)
    if not callable(listed):
        return _unknown()
    try:
        accounts = listed()
    except Exception:
        _log("broker")
        return _unknown()
    try:
        rows = _broker_rows(accounts, scope)
    except Exception:
        _log("broker")
        return _unknown()
    if rows is None:
        return _unknown()
    return {"status": "ok", "accounts": rows}


def project_dispatch(ledger: Any, scope: set[str] | str) -> dict[str, Any]:
    """Counts of unresolved and non-terminal dispatch attempts for this operator."""
    if scope == REASON_UNSCOPED:
        return _unknown(REASON_UNSCOPED)
    if scope == REASON_UNAVAILABLE or ledger is None:
        return _unknown()
    listed = getattr(ledger, "list_dispatch_attempts", None)
    if not callable(listed):
        return _unknown()
    try:
        attempts = listed()
    except Exception:
        _log("dispatch")
        return _unknown()
    try:
        from flinttrade_engine.local_state_provider import (  # noqa: PLC0415
            DISPATCH_OUTCOME_UNKNOWN,
            NON_TERMINAL_DISPATCH_STATES,
        )

        outcome_unknown = 0
        non_terminal = 0
        for row in attempts:
            if not isinstance(row, Mapping):
                return _unknown()
            key = _selector_key_parts(row.get("adapter_id"), row.get("account_id"))
            if key is None or key not in scope:
                continue
            state = row.get("dispatch_state")
            if not isinstance(state, str):
                return _unknown()
            if state == DISPATCH_OUTCOME_UNKNOWN:
                outcome_unknown += 1
            if state in NON_TERMINAL_DISPATCH_STATES:
                non_terminal += 1
    except Exception:
        _log("dispatch")
        return _unknown()
    return {"status": "ok", "outcome_unknown": outcome_unknown, "non_terminal": non_terminal}


def project_kill_switch(safety: Any) -> dict[str, Any]:
    """Read the kill-switch latch. Does not activate or reset it."""
    if safety is None:
        return _unknown()
    try:
        switch = safety.l5_kill
        active = switch.is_active
        reason = switch.reason
    except Exception:
        _log("kill_switch")
        return _unknown()
    if type(active) is not bool or not _safe_latch_reason(reason):
        return _unknown()
    return {"status": "ok", "active": active, "reason": reason}


def project_laya() -> dict[str, Any]:
    """Decision-model status, reason code, and Live qualification.

    This reads the stored heartbeat. It does not probe the sidecar, start
    it, or admit an order.
    """
    try:
        from flinttrade_engine.laya import LAYA_REASON_CODES, process_laya  # noqa: PLC0415

        engine = process_laya()
        practice, _live, qualified = engine.desk_heartbeat()
        reason, _port = engine.runtime_reason()
    except Exception:
        _log("laya")
        return _unknown_laya()
    status = getattr(practice, "value", None)
    if status not in {"ready", "degraded", "down"}:
        return _unknown_laya()
    if reason is not None and reason not in LAYA_REASON_CODES:
        return _unknown_laya()
    if type(qualified) is not bool:
        return _unknown_laya()
    return {"status": status, "reason_code": reason, "live_qualified": qualified}


def project_strategy(runner: Any, scheduler: Any) -> dict[str, Any]:
    """Strategy rows from the uploaded runner and the live runner projection."""
    if runner is None and scheduler is None:
        return _unknown()
    try:
        from flinttrade_engine.strategy_status import STATUS_REASONS  # noqa: PLC0415

        rows: list[dict[str, Any]] = []
        if runner is not None:
            uploaded = runner.list_strategies()
            if isinstance(uploaded, (str, bytes)) or not isinstance(uploaded, Sequence):
                return _unknown()
            for item in uploaded:
                projected = _uploaded_row(item, STATUS_REASONS)
                if projected is None:
                    return _unknown()
                rows.append(projected)
        if scheduler is not None:
            scheduled = scheduler.status()
            if not isinstance(scheduled, Mapping):
                return _unknown()
            for name in sorted(scheduled):
                projected = _runner_row(name, scheduled[name], STATUS_REASONS)
                if projected is None:
                    return _unknown()
                rows.append(projected)
    except Exception:
        _log("strategy")
        return _unknown()
    return {"status": "ok", "rows": rows}


def project_migration(service: Any) -> dict[str, Any]:
    """Paused-update flag from the account service. Null when the desk may open."""
    if service is None or not callable(getattr(service, "migration_blocked", None)):
        return _unknown()
    try:
        from flinttrade_core.auth_service import MIGRATION_BLOCKED_TWO_OPERATORS  # noqa: PLC0415

        blocked = service.migration_blocked()
    except Exception:
        _log("migration")
        return _unknown()
    if blocked is not None and blocked != MIGRATION_BLOCKED_TWO_OPERATORS:
        return _unknown()
    return {"status": "ok", "value": blocked}


def project_session(exchange: str, symbol: str | None, at: datetime) -> dict[str, Any]:
    """Session decision used for admission, including weekends and holidays."""
    try:
        from flinttrade_engine.market_hours import admit_session  # noqa: PLC0415

        decision = admit_session(exchange, at, symbol=symbol)
        return _project_decision(decision)
    except Exception:
        _log("session")
        return _unknown()


def session_from_request() -> dict[str, Any]:
    """Session section for the request's exchange. NSE when the query omits it."""
    raw_exchange = request.args.get("exchange", "NSE")
    raw_symbol = request.args.get("symbol", "")
    if not isinstance(raw_exchange, str) or _EXCHANGE.fullmatch(raw_exchange) is None:
        return _unknown()
    if raw_symbol in ("", None):
        symbol = None
    elif isinstance(raw_symbol, str) and _SYMBOL.fullmatch(raw_symbol) is not None:
        symbol = raw_symbol
    else:
        return _unknown()
    return project_session(raw_exchange.upper(), symbol, _now())


def read_scope() -> set[str] | str:
    """Selectors the signed-in operator may see, or a fixed unscoped/unavailable token."""
    try:
        from flinttrade_core.order_routes import _decode_request_payload  # noqa: PLC0415

        payload = _decode_request_payload()
    except Exception:
        _log("scope")
        return REASON_UNAVAILABLE
    if not isinstance(payload, dict):
        return REASON_UNSCOPED
    actor = payload.get("sub")
    if not isinstance(actor, str) or not actor.strip():
        actor = payload.get("actor_id")
    if not isinstance(actor, str) or not actor.strip():
        return REASON_UNSCOPED
    router = current_app.config.get("BROKER_ROUTER")
    authorised = getattr(router, "authorised_selectors", None)
    if not callable(authorised):
        return REASON_UNAVAILABLE
    try:
        found = authorised(actor.strip())
    except Exception:
        _log("scope")
        return REASON_UNAVAILABLE
    if isinstance(found, (str, bytes)) or not isinstance(found, Iterable):
        return REASON_UNAVAILABLE
    scope: set[str] = set()
    for item in found:
        key = _bounded_selector(item) if isinstance(item, str) else None
        if key is None:
            return REASON_UNAVAILABLE
        scope.add(key)
    return scope


def _now() -> datetime:
    return datetime.now(_IST)


def _unknown(reason: str = REASON_UNAVAILABLE) -> dict[str, str]:
    return {"status": "unknown", "reason": reason}


def _unknown_laya() -> dict[str, Any]:
    return {"status": "unknown", "reason_code": REASON_UNAVAILABLE, "live_qualified": None}


def _log(section: str) -> None:
    error = sys.exception()
    kind = type(error).__name__ if error is not None else "error"
    logger.warning("Operator status %s could not be read (%s)", section, kind)


def _bounded_selector(value: str) -> str | None:
    if _SELECTOR.fullmatch(value) is None:
        return None
    return value


def _selector_key(selector: Any) -> str | None:
    if isinstance(selector, str):
        return _bounded_selector(selector)
    adapter = getattr(selector, "adapter_id", None)
    account = getattr(selector, "account_id", None)
    return _selector_key_parts(adapter, account)


def _selector_key_parts(adapter: Any, account: Any) -> str | None:
    if not isinstance(adapter, str) or not isinstance(account, str):
        return None
    return _bounded_selector(f"{adapter}:{account}")


def _any_authorised_session(sessions: Any, scope: set[str]) -> bool | None:
    if isinstance(sessions, (str, bytes)) or not isinstance(sessions, Iterable):
        return None
    matched = False
    for item in sessions:
        if not isinstance(item, tuple) or not item:
            return None
        key = _selector_key(item[0])
        if key is None:
            return None
        if key in scope:
            matched = True
    return matched


def _broker_rows(accounts: Any, scope: set[str]) -> list[dict[str, str]] | None:
    from flinttrade_gateway.models import AccountStatus  # noqa: PLC0415

    allowed = {status.value for status in AccountStatus}
    if isinstance(accounts, (str, bytes)) or not isinstance(accounts, Iterable):
        return None
    rows: list[dict[str, str]] = []
    for account in accounts:
        key = _selector_key_parts(getattr(account, "adapter_id", None), getattr(account, "account_id", None))
        if key is None or key not in scope:
            continue
        status = getattr(account, "status", None)
        value = status.value if isinstance(status, AccountStatus) else None
        if value is None and isinstance(status, str) and status in allowed:
            value = status
        if value is None:
            rows.append({"selector": key, "status": "unknown", "reason": REASON_UNAVAILABLE})
        else:
            rows.append({"selector": key, "status": value})
    rows.sort(key=lambda row: row["selector"])
    return rows


def _safe_latch_reason(reason: Any) -> bool:
    return isinstance(reason, str) and len(reason) <= 200 and all(ord(character) >= 32 for character in reason)


def _strategy_identity(value: Any) -> str | None:
    if not isinstance(value, str) or _STRATEGY_ID.fullmatch(value) is None:
        return None
    return value


def _lifecycle(item: Mapping[str, Any]) -> str | None | bool:
    """Return the lifecycle, None when absent, or False when the value is not a known state."""
    if "lifecycle" not in item or item.get("lifecycle") is None:
        return None
    lifecycle = item.get("lifecycle")
    if lifecycle not in _LIFECYCLE:
        return False
    return lifecycle


def _uploaded_row(item: Any, reasons: frozenset[str]) -> dict[str, Any] | None:
    if not isinstance(item, Mapping):
        return None
    status = item.get("state")
    reason = item.get("reason")
    identifier = _strategy_identity(item.get("strategy_id"))
    if status not in _STRATEGY_STATUS or reason not in reasons or identifier is None:
        return None
    lifecycle = _lifecycle(item)
    if lifecycle is False:
        return None
    retained = item.get("ownership_retained") is True
    if status == "unknown" and not retained:
        return None
    return {
        "kind": "uploaded",
        "id": identifier,
        "status": status,
        "reason": reason,
        "lifecycle": lifecycle,
        "ownership_retained": retained,
    }


def _runner_row(name: Any, item: Any, reasons: frozenset[str]) -> dict[str, Any] | None:
    identifier = _strategy_identity(name)
    if identifier is None or not isinstance(item, Mapping):
        return None
    status = item.get("process_state")
    reason = item.get("reason")
    if status not in _STRATEGY_STATUS or reason not in reasons:
        return None
    lifecycle = _lifecycle(item)
    if lifecycle is False:
        return None
    retained = item.get("ownership_retained") is True
    if status == "unknown" and not retained:
        return None
    return {
        "kind": "runner",
        "id": identifier,
        "status": status,
        "reason": reason,
        "lifecycle": lifecycle,
        "ownership_retained": retained,
    }


def _project_decision(decision: Any) -> dict[str, Any]:
    exchange = getattr(decision, "exchange", None)
    phase = getattr(decision, "phase", None)
    order_entry = getattr(decision, "order_entry", None)
    reason = getattr(decision, "reason", None)
    if not isinstance(exchange, str) or not exchange.isascii() or not exchange.isupper():
        return _unknown()
    if len(exchange) > 12 or not exchange.isalpha():
        return _unknown()
    if phase is not None and (not isinstance(phase, str) or _PHASE.fullmatch(phase) is None):
        return _unknown()
    if order_entry not in _ORDER_ENTRY:
        return _unknown()
    if not isinstance(reason, str) or _REASON_TOKEN.fullmatch(reason) is None:
        return _unknown()
    return {
        "status": "ok",
        "exchange": exchange,
        "phase": phase,
        "order_entry": order_entry,
        "order_close": _iso(getattr(decision, "order_close", None)),
        "square_off": _iso(getattr(decision, "square_off", None)),
        "reason": reason,
    }


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise TypeError("session instant is not a timestamp")
    return value.isoformat()
