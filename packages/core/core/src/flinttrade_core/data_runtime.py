"""Installed shared-data composition; startup performs no provider I/O.

The application owns this runtime until requests and background consumers drain.
Readers borrow its historical pipeline; only this owner closes it.
"""
from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flask import has_request_context, request

from flinttrade_core.auth_routes import decode_token, verify_operator_session_token
from flinttrade_core.auth_scopes import _session_token
from flinttrade_core.data_acquisition import SharedAcquisition
from flinttrade_core.data_contracts import canonical_json, digest, timestamp, validate_identity, validate_scope
from flinttrade_core.db import open_sqlite
from flinttrade_core.owner_file_lock import OwnerSafeFileLock
from flinttrade_core.secure_file import (
    HeldOwnerDirectory,
    validate_owner_owned_directory,
    validate_owner_owned_regular_file,
)
from flinttrade_data.portfolio_evidence import PortfolioEvidence
from flinttrade_historical.historify_jobs import HistorifyJobManager
from flinttrade_historical.pipeline import DataPipeline


class DataSessionRequired(PermissionError):
    """The presented operator session is absent, retired or no longer valid."""


class _PortfolioStore:
    """Connection custody for PortfolioEvidence using the existing secure files/SQLite composition."""

    def __init__(self, workspace: Path) -> None:
        validate_owner_owned_directory(workspace)
        root = workspace / "portfolio-evidence"
        root.mkdir(mode=0o700, exist_ok=True)
        self._directory = HeldOwnerDirectory(root).__enter__()
        self._lock = OwnerSafeFileLock(str(root / "evidence.lock"), timeout=10)
        self._threads = threading.RLock()
        self._pid, self._closed = os.getpid(), False
        self.path = root / "evidence.sqlite"
        try:
            with self._lock:
                exists = self._directory.exists("evidence.sqlite")
                if not exists:
                    if self._directory.exists("established"):
                        raise RuntimeError("established portfolio evidence missing")
                    # Fence an interrupted first initialisation, too: never heal it.
                    self._directory.write_text("established", "portfolio-evidence-v1")
                    self._directory.create_empty_hardened_member("evidence.sqlite")
                    connection = open_sqlite(self.path, durability="full", strict_existing=True)
                    try:
                        PortfolioEvidence(connection)
                    finally:
                        connection.close()
                self._marker = self._directory.read_text("established")
                if self._marker != "portfolio-evidence-v1":
                    raise RuntimeError("portfolio evidence marker invalid")
                info = validate_owner_owned_regular_file(self.path, require_hardened=True)
                self._identity = (info.st_dev, info.st_ino)
            with self._evidence():
                pass
        except BaseException:
            self._directory.__exit__()
            raise

    @contextmanager
    def _evidence(self) -> Iterator[PortfolioEvidence]:
        with self._threads, self._lock:
            if self._closed or self._pid != os.getpid():
                raise RuntimeError("portfolio evidence closed or inherited")
            self._directory.revalidate()
            info = validate_owner_owned_regular_file(self.path, require_hardened=True)
            if (info.st_dev, info.st_ino) != self._identity or self._directory.read_text("established") != self._marker:
                raise RuntimeError("portfolio evidence replaced")
            for suffix in ("-wal", "-shm"):
                name = self.path.name + suffix
                if self._directory.exists(name):
                    validate_owner_owned_regular_file(self.path.with_name(name), require_hardened=True)
            connection = open_sqlite(self.path, durability="full", strict_existing=True)
            try:
                yield PortfolioEvidence(connection, initialise=False)
            finally:
                connection.close()

    def append(self, **values: Any) -> dict[str, Any]:
        with self._evidence() as evidence:
            return evidence.append(**values)

    def read(self, scope: dict[str, Any]) -> dict[str, Any]:
        with self._evidence() as evidence:
            return evidence.read(scope)

    def close(self) -> None:
        with self._threads:
            if not self._closed:
                self._directory.__exit__()
                self._closed = True


class DataRuntime:
    """One app's local history and exact authenticated data authority."""

    def __init__(self, app: Any, workspace: Path) -> None:
        self.app = app
        self.workspace = Path(workspace)
        self.portfolio = _PortfolioStore(self.workspace)
        try:
            self.history = DataPipeline()
        except BaseException:
            self.portfolio.close()
            raise
        self.acquisition = SharedAcquisition()
        self.downloads = HistorifyJobManager()
        self.closed = False
        self._lock = threading.RLock()
        self._registered: set[str] = set()
        self._sources: set[object] = set()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self.maintenance_error: str | None = None

    def principal(self, token: str | None = None) -> tuple[Any, dict[str, Any]]:
        """Revalidate the existing session, never reinterpret an API key."""
        if self.closed or self._stop.is_set() or self.app.config.get("RUNTIME_ACCEPTING_REQUESTS", True) is not True:
            raise RuntimeError("data runtime unavailable")
        token = token if token is not None else _session_token()
        if not token:
            raise DataSessionRequired("operator session required")
        try:
            principal = verify_operator_session_token(token)
            claims = decode_token(token)
            binding = self.app.config["AUTH_SERVICE"].current_session_binding()
            if binding is None or (claims.get("oid"), claims.get("epoch")) != binding:
                raise ValueError
        except Exception:
            raise DataSessionRequired("current operator session required") from None
        if "admin.accounts.read" not in principal.scopes:
            raise PermissionError("account read permission required")
        return principal, claims

    def scope(self) -> dict[str, Any]:
        """Scope installed history, not a guessed execution account or run.

        Native account/run scope is resolved at its bound read owner instead.
        Operator epoch changes never adopt earlier history generations.
        """
        principal, claims = self.principal()
        manual = has_request_context() and request.path == "/api/v1/data/portfolio/evidence"
        identity = principal.actor_ref + ":" + claims["oid"]
        return validate_scope({"principal_id": principal.actor_ref + ":" + claims["oid"],
                               "environment": "manual_ledger" if manual else "local_history",
                               "account_id": "manual:" + identity if manual else None,
                               "run_id": None, "generation": claims["epoch"]})

    def evidence_write_allowed(self) -> bool:
        """Account-read permission alone cannot append operator-owned facts."""
        principal, _ = self.principal()
        return "admin.accounts.write" in principal.scopes

    @property
    def active_sources(self) -> int:
        """Number of actual acquired readers, without invoking expiry as a side effect."""
        with self._lock:
            return len(self._sources)

    def _maintain(self) -> None:
        while not self._stop.wait(0.25):
            try:
                with self.app.app_context():
                    self.acquisition.expire()
                self.maintenance_error = None
            except Exception:
                # Keep unresolved ownership for close/retry; do not restart a provider.
                self.maintenance_error = "acquisition_retirement_pending"

    def _start_maintenance(self) -> None:
        with self._lock:
            if self.closed or self._stop.is_set():
                raise RuntimeError("data runtime closing")
            if self._worker is None:
                self._worker = threading.Thread(target=self._maintain, name="data-lease-expiry", daemon=True)
                self._worker.start()

    def datasets(self) -> dict[str, Any]:
        """List recorded evidence separately from deliberately frozen native feeds."""
        scope = self.scope()
        datasets = [{"dataset_id": "history:" + item["snapshot_id"], "snapshot_id": item["snapshot_id"],
                     "source_kind": "recorded_history", "label": "Recorded history — not a live broker feed",
                     "identity": item["identity"], "coverage": item["coverage"], "status": item["status"],
                     "execution_authority": False} for item in self.history.history_snapshots(scope=scope)]
        datasets.extend({"dataset_id": "native:" + role, "source_kind": "native", "status": "unavailable",
                         "label": "Native " + role + " — unavailable until read cutover",
                         "reason": "native_read_cutover_unavailable", "execution_authority": False}
                        for role in ("quote", "historical", "ticks"))
        return {"scope": scope, "datasets": datasets, "legacy_history": "unqualified_legacy",
                "portfolio": "Explicit imported/manual records; not a broker book"}

    def acquire(self, dataset_id: str, *, scope: dict[str, Any]) -> dict[str, Any]:
        """Acquire a concrete, persisted historical source; never remote fallback."""
        if dataset_id.startswith("native:"):
            raise RuntimeError("native_read_cutover_unavailable")
        if not dataset_id.startswith("history:"):
            raise KeyError(dataset_id)
        if scope != self.scope():
            raise PermissionError("data scope mismatch")
        identifier = dataset_id.removeprefix("history:")
        token = _session_token()
        principal, _ = self.principal(token)
        key = dataset_id + ":" + digest({"scope": scope, "session": principal.session_binding})
        with self._lock:
            if key not in self._registered:
                snapshot = self.history.history_snapshot(identifier, scope=scope)
                if snapshot is None or not snapshot["bars"]:
                    raise KeyError(identifier)

                def authorised() -> bool:
                    with self.app.app_context():
                        current, claims = self.principal(token)
                        return current == principal and claims["epoch"] == scope["generation"]

                def open_history(publish):
                    evidence = self.history.history_snapshot(identifier, scope=scope)
                    if evidence is None:
                        raise RuntimeError("history evidence missing")
                    handle = object()
                    with self._lock:
                        self._sources.add(handle)
                    def close():
                        with self._lock:
                            self._sources.discard(handle)
                    try:
                        publish({"sequence": 0, "kind": "snapshot",
                                 "observed_at": max((bar["timestamp"] for bar in evidence["bars"]), key=timestamp),
                                 "published_at": None,
                                 "retrieved_at": max((part["retrieved_at"] for part in evidence["contributors"]),
                                                     key=timestamp), "payload": evidence})
                    except BaseException:
                        close()
                        raise
                    return close

                self.acquisition.register(key, identity=snapshot["identity"], scope=scope,
                    source={"connection_id": "local-history", "provider": "recorded_history",
                            "environment": "local_history", "account_id": None,
                            "auth_generation": scope["generation"], "configuration_generation": 0},
                    policy_revision=identifier, max_age_seconds=snapshot["identity"]["interval_seconds"],
                    lease_seconds=60, open_feed=open_history, authorised=authorised)
                self._registered.add(key)
        self._start_maintenance()
        result = self.acquisition.acquire(key, scope=scope)
        result["snapshot"]["dataset_id"] = dataset_id
        return result

    def read(self, lease_id: str, *, scope: dict[str, Any], after_sequence: int | None = None) -> dict[str, Any]:
        """Keep catalogue identity stable; internal session keys are not UI IDs."""
        result = self.acquisition.read(lease_id, scope=scope, after_sequence=after_sequence)
        if result["dataset_id"].startswith("history:"):
            result["dataset_id"] = ":".join(result["dataset_id"].split(":")[:2])
        return result

    def release(self, lease_id: str, *, scope: dict[str, Any]) -> bool:
        """Release the exact view lease without changing the source selection."""
        return self.acquisition.release(lease_id, scope=scope)

    def acquire_native_history(self, *, identity: dict[str, Any], query: Any,
                               policy: dict[str, Any], token: str) -> dict[str, Any]:
        """Share an existing internal native read grant, not an HTTP cutover bypass.

        Instrument crosswalk, units and calendar facts must already be qualified
        by the caller. No ticker-derived metadata, default account or new broker
        session is created. Source failures never trigger another provider.
        """
        from flinttrade_core.app import _BrokerRuntimeDependencies
        from flinttrade_core.broker_identity import parse_broker_selector
        from flinttrade_core.broker_read_port import (
            BrokerDataRole,
            BrokerReadFailure,
            BrokerReadSuccess,
            DataRoleReadTarget,
            HistoricalRequest,
        )
        from flinttrade_engine.request_context import RequestContext
        from flinttrade_gateway.broker_read_service import BrokerReadOwner
        from flinttrade_historical.history_manifest import build_history

        if has_request_context():
            raise RuntimeError("native_read_cutover_unavailable")
        identity = validate_identity(identity)
        policy = json.loads(canonical_json(policy))
        intervals = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "D": 86400, "1d": 86400}
        if (type(query) is not HistoricalRequest or identity["instrument_id"] != query.instrument.instrument_id
                or identity.get("native_symbol") != query.instrument.symbol
                or identity.get("native_exchange") != query.instrument.exchange
                or intervals.get(query.interval) != identity["interval_seconds"]):
            raise ValueError("qualified crosswalk and interval required")
        encoding = identity.get("native_timestamp_encoding")
        if encoding not in {"iso8601", "unix_seconds", "unix_milliseconds"}:
            raise ValueError("qualified native timestamp encoding required")
        principal, claims = self.principal(token)
        deps = self.app.extensions.get("flinttrade_broker_dependencies")
        if type(deps) is not _BrokerRuntimeDependencies or type(deps.read_owner) is not BrokerReadOwner:
            raise RuntimeError("native read owner unavailable")
        raw_selector = deps.config.data.historical
        selector = parse_broker_selector(raw_selector)
        context = RequestContext(claims["jti"], "human", claims["sub"], claims["mode"], selector=raw_selector)
        binding = deps.session_provider(context, selector.adapter_id, selector.account_id).version
        scope = validate_scope({"principal_id": principal.actor_ref + ":" + claims["oid"],
                                "environment": context.mode, "account_id": raw_selector, "run_id": None,
                                "generation": binding.registry_version.generation})
        revision = digest(json.loads(json.dumps(asdict(binding), default=str)))
        source = {"connection_id": raw_selector, "provider": selector.adapter_id, "environment": context.mode,
                  "account_id": selector.account_id, "auth_generation": binding.credential_version.generation,
                  "configuration_generation": binding.broker_workspace_version.generation}
        # Validate the entire calendar and source policy before provider I/O.
        empty = {"identity": identity, "source": source, "revision": revision, "status": "unavailable",
                 "retrieved_at": datetime.now(UTC).isoformat(), "bars": []}
        build_history(identity=identity, scope=scope, policy=policy, contributors=[empty])
        key = "native-history:" + digest({"identity": identity, "query": asdict(query), "policy": policy,
                                         "scope": scope, "binding": revision, "session": principal.session_binding})

        def authority():
            with self.app.app_context():
                current, _ = self.principal(token)
                if (current != principal or self.app.extensions.get("flinttrade_broker_dependencies") is not deps
                        or self.app.extensions.get("flinttrade_broker_dependencies_draining") is not None
                        or self.app.config.get("BROKER_CLIENT") is not deps.broker_client
                        or self.app.config.get("REGISTRY") is not deps.registry
                        or not deps.registry_publication_owner.owns(deps.registry)
                        or deps.session_provider(context, selector.adapter_id, selector.account_id).version != binding):
                    raise PermissionError("native read generation retired")
            return context

        def authorised():
            authority()
            return True

        def open_native(publish):
            port = deps.read_owner.bind(target=DataRoleReadTarget(BrokerDataRole.HISTORICAL),
                                        verify_current_authority=authority)
            if type(port) is BrokerReadFailure:
                raise RuntimeError("native read refused")
            cancelled = threading.Event()
            handle = object()

            def collect():
                try:
                    # Wait for actual completion. Cancelling an SDK await cannot
                    # prove its worker stopped; close retains this exact worker.
                    outcome = deps.broker_client.run_sync(port.historical(query), timeout=None)
                    if cancelled.is_set():
                        return
                    authority()
                    if type(outcome) is not BrokerReadSuccess:
                        raise RuntimeError("native source unavailable")
                    bars = [asdict(bar) for bar in outcome.value.bars]
                    if encoding != "iso8601":
                        from decimal import Decimal
                        for bar in bars:
                            value = Decimal(bar["timestamp"])
                            if not value.is_finite():
                                raise ValueError("invalid native timestamp")
                            seconds = value if encoding == "unix_seconds" else value / 1000
                            bar["timestamp"] = datetime.fromtimestamp(float(seconds), UTC).isoformat()
                    evidence = self.history.publish_history(identity=identity, scope=scope, policy=policy,
                        contributors=[{**empty, "bars": bars, "status": "available",
                                       "retrieved_at": datetime.now(UTC).isoformat()}])
                    if evidence["bars"]:
                        publish({"sequence": 0, "kind": "snapshot", "payload": evidence,
                                 "observed_at": evidence["bars"][-1]["timestamp"], "published_at": None,
                                 "retrieved_at": evidence["contributors"][0]["retrieved_at"]})
                    else:
                        raise RuntimeError("native source empty")
                except Exception:
                    publish({"sequence": 0, "kind": "unavailable", "reason": "source_unavailable"})

            worker = threading.Thread(target=collect, name="data-native-history", daemon=True)
            with self._lock:
                self._sources.add(handle)
            def close():
                cancelled.set()
                deps.read_owner.revoke(port)
                worker.join(timeout=1)
                if worker.is_alive():
                    raise RuntimeError("native source still draining")
                with self._lock:
                    self._sources.discard(handle)
            try:
                worker.start()
            except BaseException:
                deps.read_owner.revoke(port)
                with self._lock:
                    self._sources.discard(handle)
                raise
            return close

        with self._lock:
            if key not in self._registered:
                self.acquisition.register(key, identity=identity, source=source, scope=scope,
                    policy_revision=revision, max_age_seconds=identity["interval_seconds"], lease_seconds=60,
                    open_feed=open_native, authorised=authorised)
                self._registered.add(key)
        self._start_maintenance()
        return self.acquisition.acquire(key, scope=scope)

    def connector(self) -> Any:
        """Return the existing connector borrowing this exact history owner."""
        from flinttrade_backtest.data_connector import DataConnector
        if self.closed or self._stop.is_set():
            raise RuntimeError("data runtime closed")
        return DataConnector(pipeline=self.history)

    def close(self) -> None:
        """Close after all consumers drain; retain dependencies if a feed cannot stop."""
        self._stop.set()
        if not self.downloads.close(timeout=5):
            raise RuntimeError("historical download workers still draining")
        if self._worker is not None:
            self._worker.join(timeout=5)
            if self._worker.is_alive():
                raise RuntimeError("data maintenance still draining")
        self.acquisition.close()
        self.history.retire()
        self.portfolio.close()
        self.closed = True


def install_data_runtime(app: Any, workspace: Path) -> None:
    """Bind normal-factory history, acquisition and server-derived scope once."""
    if app.config.get("DATA_RUNTIME") is not None:
        return
    runtime = DataRuntime(app, workspace)
    app.config.update(DATA_RUNTIME=runtime, DATA_ACQUISITION_OWNER=runtime.acquisition,
                      DATA_SCOPE_RESOLVER=runtime.scope, HISTORY_PIPELINE=runtime.history,
                      HISTORIFY_JOB_MANAGER=runtime.downloads,
                      PORTFOLIO_EVIDENCE_OWNER=runtime.portfolio,
                      DATA_EVIDENCE_WRITE_ALLOWED=runtime.evidence_write_allowed,
                      BACKTEST_DATA_CONNECTOR_FACTORY=runtime.connector)
    from flinttrade_core.data_runtime_routes import install_data_routes
    install_data_routes(app)
