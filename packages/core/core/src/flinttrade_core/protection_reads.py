"""Quote-only independent read authority, using the existing versioned read port."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .ai_broker_context import BrokerAnalysisContext
from .practice_agent_adapter import PracticeAgentError


def collect_protection_quote(services: Any, scope: Any, symbol: str, exchange: str) -> BrokerAnalysisContext:
    """Consume one bounded read and revoke its port, never read funds/history."""
    from flinttrade_data.audit_logger import AuditLogger
    from flinttrade_engine.request_context import RequestContext
    from flinttrade_gateway.broker_read_service import BrokerReadOwner

    from .app import _BrokerRuntimeDependencies
    from .broker_client import BrokerClient
    from .broker_identity import parse_broker_selector
    from .broker_read_port import BrokerReadSuccess, ExactReadTarget, InstrumentRef, QuoteRequest, QuoteSnapshot
    from .protection_grants import _encoded

    revision, value = services.validate(scope)
    policy, app = value["policy"], services.app
    read = policy["read"]
    if (policy["position"]["symbol"] != symbol or policy["position"]["exchange"] != exchange
            or read["valid_until"] <= time.time()):
        raise PracticeAgentError("protection_read_scope_or_expiry")
    dependencies = app.extensions.get("flinttrade_broker_dependencies")
    if type(dependencies) is not _BrokerRuntimeDependencies:
        raise PracticeAgentError("protection_read_unavailable")
    owner, client, audit = dependencies.read_owner, dependencies.broker_client, app.config.get("AUDIT")
    if type(owner) is not BrokerReadOwner or not isinstance(client, BrokerClient) or type(audit) is not AuditLogger:
        raise PracticeAgentError("protection_read_unavailable")
    selector = parse_broker_selector(read["selector"])

    def authority() -> RequestContext:
        current_revision, current = services.validate(scope)
        if (current_revision != revision or current["policy"]["read"] != read
                or read["valid_until"] <= time.time()
                or app.extensions.get("flinttrade_broker_dependencies") is not dependencies
                or app.config.get("CLIENT") is not client or app.config.get("BROKER_CLIENT") is not client
                or app.config.get("REGISTRY") is not dependencies.registry
                or app.config.get("RUNTIME_ACCEPTING_REQUESTS") is not True):
            raise PracticeAgentError("protection_read_retired")
        return RequestContext("protection-read:" + scope.run_id, "human", current["subject"], "practice",
                              selector=read["selector"])

    authority()
    with services._db().transaction() as db:
        row = db.execute("SELECT revision,value FROM grants WHERE run_id=?", (scope.run_id,)).fetchone()
        latest = json.loads(row[1])
        if row[0] != revision or latest["reads"] >= read["max_reads"] or latest["revoked"]:
            raise PracticeAgentError("protection_read_budget")
        latest["reads"] += 1
        db.execute("UPDATE grants SET value=? WHERE run_id=?", (_encoded(latest), scope.run_id))
    port = owner.bind(target=ExactReadTarget(selector), verify_current_authority=authority)
    try:
        instrument = InstrumentRef(symbol, exchange)
        outcome = client.run_sync(port.quote(QuoteRequest(instrument)), timeout=read["max_age_seconds"])
        authority()
        if (type(outcome) is not BrokerReadSuccess or type(outcome.value) is not QuoteSnapshot
                or not outcome.value.available or outcome.value.ltp is None or outcome.value.ltp <= 0
                or outcome.value.instrument != instrument):
            raise PracticeAgentError("protection_read_invalid")
        def verify_current() -> None:
            handle = dependencies.session_provider(authority(), selector.adapter_id, selector.account_id)
            if any(getattr(handle.version, field) != getattr(outcome.provenance, field)
                   for field in ("registry_version", "credential_version", "workspace_version", "broker_workspace_version")):
                raise PracticeAgentError("protection_read_retired")

        verify_current()
        data = {"symbol": symbol, "exchange": exchange, "quote": {
            "value": asdict(outcome.value), "observed_at": datetime.now(UTC).isoformat(),
            "source_as_of": None, "provenance": asdict(outcome.provenance)}}
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False)
        data = json.loads(canonical)
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        event_id = str(uuid4())
        if audit.log_idempotent_event("PROTECTION_QUOTE", event_id=event_id,
                                     fields={"input_digest": digest, "market_data": data}) != event_id:
            raise PracticeAgentError("protection_read_audit_unavailable")
        authority()
        services._read_receipts[event_id] = (scope, revision, digest, time.time(), read["max_age_seconds"], verify_current)
        return BrokerAnalysisContext(data, {"event_id": event_id, "input_digest": digest})
    except PracticeAgentError:
        raise
    except Exception:
        raise PracticeAgentError("protection_read_unavailable") from None
    finally:
        owner.revoke(port)
