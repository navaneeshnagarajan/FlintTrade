"""Collect one authorised native analysis input and durably receipt it before use.

This boundary owns no broker client, grant lifecycle beyond one request, or order
capability. The published broker generation supplies all reads and its existing
persistent event loop; the shared audit logger supplies durable input recording.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from flask import current_app, request

from .broker_identity import parse_broker_selector, serialise_broker_selector
from .broker_read_port import (
    BalanceSnapshot,
    BrokerDataRole,
    BrokerReadErrorCode,
    BrokerReadFailure,
    BrokerReadSuccess,
    DataRoleReadTarget,
    DepthSnapshot,
    ExactReadTarget,
    HistoricalRequest,
    HistoricalSnapshot,
    InstrumentRef,
    QuoteRequest,
    QuoteSnapshot,
)

_CONTEXT_TIMEOUT_SECONDS = 15.0
_MAX_CONTEXT_BYTES = 60 * 1024
_INPUT_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._&:+/\-]{0,127}", re.ASCII)
_ERROR_STATUS = {
    "broker_context_invalid_request": 400,
    "broker_context_authentication_required": 401,
    "broker_context_forbidden": 403,
    "broker_context_unavailable": 503,
    "broker_context_stale": 409,
    "broker_context_read_failed": 503,
    "broker_context_invalid_response": 502,
    "broker_context_audit_unavailable": 503,
    "broker_context_timeout": 504,
}


class BrokerContextError(Exception):
    """Closed public failure code; provider and session details never escape."""

    def __init__(self, code: str) -> None:
        self.code = code if code in _ERROR_STATUS else "broker_context_unavailable"
        self.status_code = _ERROR_STATUS[self.code]
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class BrokerAnalysisContext:
    """Detached exact model input and its durable audit event reference."""

    market_data: dict[str, Any]
    receipt: dict[str, str]


def _session_identity(token: str) -> tuple[str, str, str]:
    from .auth_routes import decode_token
    from .auth_scopes import resolve_session_scopes

    try:
        claims = decode_token(token)
    except Exception:
        raise BrokerContextError("broker_context_authentication_required") from None
    subject, jti, mode = claims.get("sub"), claims.get("jti"), claims.get("mode")
    if (
        claims.get("type") != "session"
        or type(subject) is not str or not subject.strip()
        or type(jti) is not str or not jti.strip()
        or type(mode) is not str or mode not in {"explore", "practice", "live"}
        or type(claims.get("exp")) not in {int, float}
    ):
        raise BrokerContextError("broker_context_authentication_required")
    try:
        if len(subject.encode("utf-8")) > 1024 or len(jti.encode("utf-8")) > 256:
            raise ValueError
    except (ValueError, UnicodeError):
        raise BrokerContextError("broker_context_authentication_required") from None
    if "admin.accounts.read" not in resolve_session_scopes(claims):
        raise BrokerContextError("broker_context_forbidden")
    return subject, jti, mode


def _json_default(value: object) -> str:
    if type(value) is UUID:
        return str(value)
    raise TypeError("non-JSON broker context")


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False, default=_json_default)


def _read_value(outcome: object, expected: type) -> Any:
    if type(outcome) is BrokerReadFailure:
        if outcome.code is BrokerReadErrorCode.UNAUTHORISED:
            code = "broker_context_forbidden"
        elif outcome.code in {BrokerReadErrorCode.TARGET_STALE, BrokerReadErrorCode.REVOKED}:
            code = "broker_context_stale"
        elif outcome.code is BrokerReadErrorCode.MALFORMED_RESPONSE:
            code = "broker_context_invalid_response"
        else:
            code = "broker_context_read_failed"
        raise BrokerContextError(code)
    if type(outcome) is not BrokerReadSuccess or type(outcome.value) is not expected:
        raise BrokerContextError("broker_context_invalid_response")
    return outcome.value


def _recent_history(value: HistoricalSnapshot, read_request: HistoricalRequest) -> HistoricalSnapshot:
    """Order native ISO/epoch candles before truncation; reject ambiguous times."""
    earliest = datetime.fromisoformat(read_request.start_date).replace(tzinfo=ZoneInfo("Asia/Kolkata"))
    now = datetime.now(UTC)
    timed_bars = []
    try:
        for bar in value.bars:
            stamp = bar.timestamp
            if len(stamp) > 64:
                raise ValueError
            if re.fullmatch(r"-?\d+(?:\.\d+)?", stamp):
                seconds = float(stamp)
                if abs(seconds) >= 100_000_000_000:
                    seconds /= 1000
                instant = datetime.fromtimestamp(seconds, UTC)
            else:
                instant = datetime.fromisoformat(stamp)
            if instant.tzinfo is None or not earliest <= instant <= now:
                raise ValueError
            timed_bars.append((instant, bar))
        timed_bars.sort(key=lambda pair: pair[0])
        if not timed_bars or len({instant for instant, _ in timed_bars}) != len(timed_bars):
            raise ValueError
    except (ValueError, OverflowError, OSError):
        raise BrokerContextError("broker_context_invalid_response") from None
    return replace(value, bars=tuple(bar for _, bar in timed_bars[-128:]))


def collect_configured_broker_context(symbol: str, exchange: str) -> BrokerAnalysisContext:
    """Collect configured market data and exact execution-account balance.

    Requires a current full operator session with account-read scope and every
    selected account's ACL. All grants are revoked even when reads time out.
    Source timestamps are unknown for quote/depth/balance; ``observed_at`` is
    collection time, not proof of market freshness. No broker writes occur.
    """
    from flinttrade_data.audit_logger import AuditLogger
    from flinttrade_engine.request_context import RequestContext
    from flinttrade_gateway.broker_read_service import BrokerReadOwner
    from flinttrade_gateway.registry import RegistryPublicationOwner
    from flinttrade_gateway.routing_config import RoutingConfig

    from .app import _BrokerRuntimeDependencies
    from .openalgo_client import OpenAlgoClient
    from .workspace_migrations import broker_workspace_version, read_workspace_snapshot

    if (type(symbol) is not str or not _INPUT_PATTERN.fullmatch(symbol)
            or type(exchange) is not str or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,15}", exchange)):
        raise BrokerContextError("broker_context_invalid_request")
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.startswith("Bearer ") else request.headers.get("X-FlintTrade-Token", "").strip()
    if not token or len(token) > 16_384:
        raise BrokerContextError("broker_context_authentication_required")
    identity = _session_identity(token)
    app = current_app._get_current_object()
    dependencies = app.extensions.get("flinttrade_broker_dependencies")
    if type(dependencies) is not _BrokerRuntimeDependencies:
        raise BrokerContextError("broker_context_unavailable")
    owner = dependencies.read_owner
    client = dependencies.openalgo_client
    audit = app.config.get("AUDIT")
    if (type(owner) is not BrokerReadOwner or not isinstance(client, OpenAlgoClient)
            or type(audit) is not AuditLogger or type(dependencies.config) is not RoutingConfig):
        raise BrokerContextError("broker_context_unavailable")
    deadline = time.monotonic() + _CONTEXT_TIMEOUT_SECONDS
    started_at = datetime.now(UTC).isoformat()
    ports = []
    outcomes = []

    def remaining() -> float:
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise BrokerContextError("broker_context_timeout")
        return seconds

    def check_generation() -> None:
        remaining()
        publication_owner = dependencies.registry_publication_owner
        if (
            app.config.get("RUNTIME_ACCEPTING_REQUESTS", True) is not True
            or app.extensions.get("flinttrade_broker_dependencies") is not dependencies
            or app.extensions.get("flinttrade_broker_dependencies_draining") is not None
            or dependencies.read_owner is not owner or dependencies.openalgo_client is not client
            or app.config.get("CLIENT") is not client or app.config.get("OPENALGO_CLIENT") is not client
            or app.config.get("REGISTRY") is not dependencies.registry
            or app.config.get("ACTIVE_BROKER_ADAPTERS") is not dependencies.adapters
            or type(publication_owner) is not RegistryPublicationOwner
            or app.extensions.get("flinttrade.registry_publication_owner") is not publication_owner
            or not publication_owner.owns(dependencies.registry)
        ):
            raise BrokerContextError("broker_context_stale")
        snapshot = read_workspace_snapshot(dependencies.workspace_path)
        if (
            broker_workspace_version(snapshot) != broker_workspace_version(dependencies.workspace_snapshot)
            or dependencies.session_provider.broker_workspace_version != broker_workspace_version(snapshot)
            or RoutingConfig.from_workspace(snapshot.as_dict()["brokers"]) != dependencies.config
        ):
            raise BrokerContextError("broker_context_stale")

    def authority(selector):
        with app.app_context():
            check_generation()
            if _session_identity(token) != identity:
                raise BrokerContextError("broker_context_authentication_required")
        return RequestContext(identity[1], "human", identity[0], identity[2],
                              selector=serialise_broker_selector(selector))

    def check_inputs_current() -> None:
        check_generation()
        for outcome in outcomes:
            provenance = outcome.provenance
            selector = provenance.selector
            handle = dependencies.session_provider(authority(selector), selector.adapter_id, selector.account_id)
            binding = handle.version
            if any(getattr(binding, field, None) != getattr(provenance, field) for field in (
                "registry_version", "credential_version", "workspace_version", "broker_workspace_version",
            )):
                raise BrokerContextError("broker_context_stale")

    try:
        check_generation()
        instrument = InstrumentRef(symbol, exchange)
        config = dependencies.config
        quote_selector = parse_broker_selector(config.data.quote)
        history_selector = parse_broker_selector(config.data.historical)
        execution_selector = parse_broker_selector(config.resolve("execution", instrument))
        for target, selector in (
            (DataRoleReadTarget(BrokerDataRole.QUOTE), quote_selector),
            (DataRoleReadTarget(BrokerDataRole.HISTORICAL), history_selector),
            (ExactReadTarget(execution_selector), execution_selector),
        ):
            port = owner.bind(target=target, verify_current_authority=lambda selected=selector: authority(selected))
            if type(port) is BrokerReadFailure:
                remaining()  # The read owner deliberately masks verifier exceptions.
                _read_value(port, object)
            ports.append(port)

        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        history_request = HistoricalRequest(instrument, "5m", (today - timedelta(days=3)).isoformat(), today.isoformat())
        quote_request = QuoteRequest(instrument)

        async def collect() -> dict[str, Any]:
            records = {}
            for name, call, expected, read_request in (
                ("quote", lambda: ports[0].quote(quote_request), QuoteSnapshot, quote_request),
                ("depth", lambda: ports[0].depth(quote_request), DepthSnapshot, quote_request),
                ("historical", lambda: ports[1].historical(history_request), HistoricalSnapshot, history_request),
                ("balance", ports[2].balance, BalanceSnapshot, None),
            ):
                outcome = await call()
                remaining()
                if (name == "depth" and type(outcome) is BrokerReadFailure
                        and outcome.code is BrokerReadErrorCode.UNSUPPORTED):
                    # Native adapters do not all expose the read-port depth
                    # contract. Missing capability is not empty market depth.
                    records[name] = {
                        "request": asdict(read_request), "value": None, "provenance": None,
                        "observed_at": datetime.now(UTC).isoformat(), "source_as_of": None,
                        "error_code": "unsupported",
                    }
                    continue
                value = _read_value(outcome, expected)
                outcomes.append(outcome)
                extra = {}
                if name == "quote" and (not value.available or value.ltp is None or value.ltp <= 0):
                    raise BrokerContextError("broker_context_invalid_response")
                if name == "balance" and value.available_balance is None:
                    raise BrokerContextError("broker_context_invalid_response")
                if name == "depth":
                    extra = {"omitted_bids": max(0, len(value.bids) - 5), "omitted_asks": max(0, len(value.asks) - 5)}
                    value = replace(value, bids=value.bids[:5], asks=value.asks[:5])
                if name == "historical":
                    extra = {"omitted_bars": max(0, len(value.bars) - 128)}
                    value = _recent_history(value, history_request)
                records[name] = {
                    "request": asdict(read_request) if read_request is not None else None,
                    "value": asdict(value), "provenance": asdict(outcome.provenance),
                    "observed_at": datetime.now(UTC).isoformat(),
                    "source_as_of": value.bars[-1].timestamp if name == "historical" else None,
                    **extra,
                }
            return records

        records = client.run_sync(collect(), timeout=remaining())
        check_inputs_current()
        market_data = {
            "schema_version": 1, "symbol": symbol, "exchange": exchange,
            "capture_started_at": started_at, "capture_completed_at": datetime.now(UTC).isoformat(),
            "execution_selector": serialise_broker_selector(execution_selector), **records,
        }
        canonical = _canonical(market_data)
        if len(canonical.encode("utf-8")) > _MAX_CONTEXT_BYTES:
            raise BrokerContextError("broker_context_invalid_response")
        market_data = json.loads(canonical)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        event_id = str(uuid4())
        try:
            remaining()
            acknowledged = audit.log_idempotent_event(
                "AI_BROKER_ANALYSIS_INPUT", event_id=event_id,
                fields={"input_digest": digest, "market_data": market_data},
            )
            if acknowledged != event_id:
                raise ValueError("audit event was not acknowledged")
        except BrokerContextError:
            raise
        except Exception:
            raise BrokerContextError("broker_context_audit_unavailable") from None
        check_inputs_current()
        return BrokerAnalysisContext(market_data, {"event_id": event_id, "input_digest": digest})
    except BrokerContextError:
        raise
    except TimeoutError:
        raise BrokerContextError("broker_context_timeout") from None
    except Exception:
        raise BrokerContextError("broker_context_unavailable") from None
    finally:
        for port in ports:
            owner.revoke(port)
