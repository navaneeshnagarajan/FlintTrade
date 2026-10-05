"""Synthetic-only account acceptance fixtures using real encrypted participants."""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from uuid import uuid4

from flask import Flask

from flinttrade_core import auth_routes
from flinttrade_core.account_lifecycle_contracts import AccountActorContext, AccountMutationKind, AccountMutationRequest
from flinttrade_core.auth_service import AuthService
from flinttrade_core.broker_account_lifecycle import BrokerAccountLifecycleOwner
from flinttrade_core.broker_account_workspace import BrokerAccountWorkspace
from flinttrade_core.broker_identity import BrokerSelector
from flinttrade_core.broker_read_port import BalanceEvidence, BalanceSnapshot, ExactReadTarget
from flinttrade_core.secure_file import harden_directory
from flinttrade_core.workspace_migrations import (
    broker_workspace_version,
    default_workspace_config,
    write_workspace_config,
)
from flinttrade_engine.request_context import RequestContext
from flinttrade_gateway.account_transaction_store import AccountTransactionStore
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.credentials import CredentialStore
from flinttrade_gateway.native_login import prepare_native_session
from flinttrade_gateway.rate_limiter import BrokerRateLimiter
from flinttrade_gateway.registry import create_owned_registry


class SyntheticAdapter:
    broker_id = "dhan"

    def __init__(self):
        self.logins = 0
        self.reads = 0
        self.sessions = []
        self.cleaned = []
        self.auth_entered = threading.Event()
        self.auth_release = threading.Event()
        self.auth_release.set()
        self.cleanup_release = threading.Event()
        self.cleanup_release.set()
        self.read_release = threading.Event()
        self.read_release.set()
        self.read_entered = threading.Event()
        self.read_only = False
        self.auth_error = None
        self.after_auth = None

    async def login(self, credentials):
        self.logins += 1
        self.auth_entered.set()
        await asyncio.to_thread(self.auth_release.wait)
        if self.auth_error is not None:
            raise self.auth_error
        session = Session(
            "synthetic-output",
            time.time() + 3600,
            "synthetic",
            "dhan",
            read_only_until_at=time.time() + 1800 if self.read_only else None,
        )
        self.sessions.append(session)
        if self.after_auth is not None:
            self.after_auth()
        return session

    async def liveness(self, session):
        return None

    def replay_credentials(self, credentials, session):
        return {"token": "synthetic-replay"}

    async def quotes(self, session, symbols):
        self.reads += 1
        self.read_entered.set()
        await asyncio.to_thread(self.read_release.wait)
        return [{"symbol": "INFY", "exchange": "NSE", "ltp": 100.0, "available": True}]

    async def balance_snapshot(self, session):
        self.reads += 1
        return BalanceSnapshot(
            100.0,
            BalanceEvidence.DIRECT,
            20.0,
            BalanceEvidence.DIRECT,
            120.0,
            BalanceEvidence.DERIVED_FROM_DIRECT_COMPONENTS,
            125.0,
            BalanceEvidence.DIRECT,
        )

    def cleanup(self, payload):
        self.cleanup_release.wait()
        session = payload.session if hasattr(payload, "session") else payload
        if not any(value is session for value in self.cleaned):
            self.cleaned.append(session)

    def authenticate(self, request, credentials, prior_retirement):
        return asyncio.run(
            prepare_native_session(self, dict(credentials), verify=True, mutation_admission=lambda: None)
        )


class SyntheticAccountHarness:
    def __init__(self, path: Path, proof, api, *, accounts=("Synthetic",), seed=None):
        self.path = path
        harden_directory(path)
        self.app = Flask("synthetic-account-acceptance")
        self.app.config["JWT_SECRET"] = "synthetic-signing-key-" + "x" * 64
        self.auth = AuthService(path / "auth.db")
        self.auth.setup_account("operator", "operator@example.test", "synthetic-password")
        self.app.config["AUTH_SERVICE"] = self.auth
        with self.app.app_context():
            self.token = auth_routes._create_token("operator")
            principal = auth_routes.verify_operator_session_token(self.token)
        self.actor = AccountActorContext(principal.actor_ref, principal.session_binding)
        config = default_workspace_config()
        config["brokers"]["account_acls"] = {"dhan": {account: ["operator"] for account in accounts}}
        if seed is not None:
            seed(config)
        write_workspace_config(path, config, expected_version=None)
        self.credentials = CredentialStore(path / "vault.db", "synthetic-password")
        self.store = AccountTransactionStore(self.credentials, workspace_path=path, backend_proof=proof)
        self.workspace = BrokerAccountWorkspace(path, self.store, proof)
        self.workspace.enrol()
        self.registry, self.registry_owner = create_owned_registry(mutation_admission=lambda: None)
        self.adapter = SyntheticAdapter()
        self.limiter = BrokerRateLimiter({"dhan": {"data": 10000.0, "quote": 10000.0}})
        self.runtime = api.BrokerAccountReadRuntime(
            registry=self.registry,
            workspace_path=path,
            credential_version_for=lambda selector: self.credentials.selector_state(selector).version,
            adapters={"dhan": self.adapter},
            rate_limiter=self.limiter,
            runtime_accepting_requests=lambda: True,
        )
        self.lifecycle = BrokerAccountLifecycleOwner(
            path, proof, retire_generations=self.runtime.retire, rebuild_lock=threading.RLock()
        )
        self.coordinator = api.BrokerAccountTransactionCoordinator(
            self.store,
            self.workspace,
            self.lifecycle,
            self.registry_owner,
            self.adapter,
            self.runtime,
            lambda: None,
            verify_current_actor=self.verify_actor,
        )

    def verify_actor(self):
        with self.app.app_context():
            principal = auth_routes.verify_operator_session_token(self.token)
            return AccountActorContext(principal.actor_ref, principal.session_binding)

    def verify_read(self, selector):
        with self.app.app_context():
            auth_routes.verify_operator_session_token(self.token)
            payload = auth_routes.decode_token(self.token)
        return RequestContext(
            jti=payload["jti"],
            actor_type="human",
            actor_id=payload["sub"],
            mode=payload["mode"],
            selector=f"{selector.adapter_id}:{selector.account_id}",
        )

    def request(self, kind=AccountMutationKind.CONNECT, *, account="Synthetic", credentials=None, roles=()):
        snapshot = self.workspace.assert_coherent()
        selector = BrokerSelector("dhan", account)
        return AccountMutationRequest(
            uuid4(),
            kind,
            selector,
            self.actor,
            snapshot.version,
            broker_workspace_version(snapshot),
            self.credentials.selector_state(selector).version,
            "dhan",
            account,
            None if kind is AccountMutationKind.REMOVE else credentials or {"token": "synthetic-input"},
            roles,
        )

    def bind(self, selector):
        return self.runtime.read_owner.bind(
            target=ExactReadTarget(selector), verify_current_authority=lambda: self.verify_read(selector)
        )

    def close(self):
        self.adapter.auth_release.set()
        self.adapter.cleanup_release.set()
        self.adapter.read_release.set()
        closed = self.lifecycle.close_and_drain(5.0)
        if not closed:
            active = self.store.active_operation(self.store.owner_capability(self.lifecycle._proof))
            assert active is not None and active.state.value in {"authentication_unknown", "blocked", "plan_ready"}
            assert self.lifecycle.snapshot().cleanup_pending == 0
        self.credentials.close()
        self.auth.close()
