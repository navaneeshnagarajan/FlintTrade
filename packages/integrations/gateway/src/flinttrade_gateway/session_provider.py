"""AuthenticatingSessionProvider — per-(actor, account) ACL gate (contract §11.4).

v1.0.1 Identity H2: session lookup that authorises ``request_ctx.actor_id``
against ``workspace.json.brokers.account_acls[adapter_id][account_id]`` BEFORE
the Session leaves the provider.

This is the single enforcement gate for BOTH the read and the write path — the
BrokerRouter obtains every Session (quotes/historical and place_order alike)
through this callable, so an unauthorised read is refused with the same
``SafetyBypassError`` as an unauthorised write. Missing or stale durable authority
and unavailable registry sessions instead raise ``RegistrySessionUnavailable``.
The provider owns the workspace.json dependency; the router stays workspace-agnostic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from flinttrade_core.account_mutation_contracts import RegistrySessionUnavailable
from flinttrade_core.broker_identity import BrokerSelector, CredentialVersion
from flinttrade_core.exceptions import SafetyBypassError
from flinttrade_core.workspace_migrations import (
    WorkspaceSnapshot,
    broker_workspace_version,
    read_workspace_snapshot,
)
from flinttrade_engine.request_context import RequestContext

from .registry import (
    BrokerRegistry,
    ConnectedRegistrySession,
    ManagedLookupAuthority,
)


class AuthenticatingSessionProvider:
    """Session lookup with a per-``(actor, account)`` ACL check (contract §11.4).

    ``account_acls`` shape::

        {
          "dhan": {
            "personal": ["nava@flinttrade.local"],
            "spouse":   ["nava@flinttrade.local", "spouse@flinttrade.local"]
          },
          ...
        }
    """

    def __init__(
        self,
        registry: BrokerRegistry,
        account_acls: dict[str, dict[str, list[str]]],
        *,
        workspace_snapshot: WorkspaceSnapshot | None = None,
        workspace_path: Path | None = None,
        credential_version_for: Callable[[BrokerSelector], CredentialVersion] | None = None,
        coherence_verifier: Callable[[], WorkspaceSnapshot] | None = None,
        enrollment_required: Callable[[], bool] | None = None,
    ) -> None:
        self._registry = registry
        self._acls = account_acls
        self._credential_version_for = credential_version_for
        self._coherence_verifier = coherence_verifier
        self._enrollment_required = enrollment_required
        self._enrolled = (
            coherence_verifier is not None
            or workspace_snapshot is not None
            and "_broker_account_store" in workspace_snapshot.config
        )
        self._pinned_instance_id = (
            workspace_snapshot.version.instance_id
            if workspace_snapshot is not None and workspace_snapshot.version is not None
            else None
        )
        if (workspace_snapshot is None) != (workspace_path is None):
            raise ValueError("workspace binding requires both snapshot and path")
        if workspace_snapshot is not None and workspace_snapshot.version is None:
            raise ValueError("workspace sessions require a persisted workspace")
        self._workspace_path = workspace_path
        self.workspace_version = workspace_snapshot.version if workspace_snapshot is not None else None
        self.broker_workspace_version = (
            broker_workspace_version(workspace_snapshot) if workspace_snapshot is not None else None
        )

    def current_authority_for(self, selector: BrokerSelector) -> Any:
        if self._workspace_path is None:
            raise RegistrySessionUnavailable
        snapshot = self._current_snapshot()
        current = broker_workspace_version(snapshot)
        if current != self.broker_workspace_version:
            raise RegistrySessionUnavailable
        if self._credential_version_for is None:
            raise RegistrySessionUnavailable
        version = self._credential_version_for(selector)
        if type(version) is not CredentialVersion or version.selector != selector:
            raise RegistrySessionUnavailable
        return ManagedLookupAuthority(version, current)

    def _requires_coherence(self) -> bool:
        """Latch trusted enrolment so an older legacy generation loses authority."""
        if not self._enrolled and self._enrollment_required is not None:
            try:
                enrolled = self._enrollment_required()
                if type(enrolled) is not bool:
                    raise ValueError
            except Exception:
                raise RegistrySessionUnavailable from None
            if enrolled:
                self._enrolled = True
        return self._enrolled

    def _current_snapshot(self) -> WorkspaceSnapshot:
        if self._requires_coherence():
            if self._coherence_verifier is None:
                raise RegistrySessionUnavailable
            try:
                verified = self._coherence_verifier()
            except Exception:
                raise RegistrySessionUnavailable from None
            if (type(verified) is not WorkspaceSnapshot or verified.version is None
                    or verified.version.instance_id != self._pinned_instance_id):
                raise RegistrySessionUnavailable
            return verified
        if self._workspace_path is None:
            raise RegistrySessionUnavailable
        return read_workspace_snapshot(self._workspace_path)

    def __call__(self, request_ctx: RequestContext, adapter_id: str, account_id: str) -> ConnectedRegistrySession:
        selector = BrokerSelector(adapter_id, account_id)
        if self._requires_coherence():
            acls = self._current_snapshot().config["brokers"]["account_acls"]
        else:
            acls = self._acls
        allowed_actors = acls.get(adapter_id, {}).get(account_id, [])
        if request_ctx.actor_id not in allowed_actors:
            raise SafetyBypassError(
                f"actor '{request_ctx.actor_id}' is not authorised for "
                f"({adapter_id}, {account_id}). workspace.json.brokers.account_acls "
                f"must list this actor for this account."
            )
        return self._registry.get_connected_session_for(
            selector, current_authority=self.current_authority_for(selector)
        )

    def authorise_if_unclaimed(self, adapter_id: str, account_id: str, actor_id: str) -> bool:
        """Trust-on-first-use: claim an unauthorised ``(adapter, account)`` for ``actor_id``.

        If no actor is yet authorised for the selector, set its allow-list to
        ``[actor_id]`` and return ``True``. If ANY actor is already authorised,
        do nothing and return ``False`` — a later actor must be authorised
        explicitly. In-memory only (mutates the running provider's ACLs); not
        persisted, so a human operator re-establishes authorisation by an actual
        authenticated login each process lifetime. Non-human actors (agents,
        external_intent) are never auto-claimed — they require an explicit
        ``workspace.json`` ``account_acls`` entry.
        """
        per_adapter = self._acls.setdefault(adapter_id, {})
        # Key-presence, NOT truthiness: an explicit empty list ([]) is a
        # deliberate deny-all the operator configured, and must NOT be widened by
        # TOFU. Only a genuinely-absent entry is claimed.
        if account_id in per_adapter:
            return False
        per_adapter[account_id] = [actor_id]
        return True


class ConnectedSessionClientResolver:
    """Resolve only sealed current handles after fresh durable authority reads."""

    def __init__(self, provider: AuthenticatingSessionProvider, registry: BrokerRegistry) -> None:
        if type(provider) is not AuthenticatingSessionProvider or provider._registry is not registry:
            raise RegistrySessionUnavailable
        self._provider = provider
        self._registry = registry

    def broker_client(self, session: ConnectedRegistrySession) -> Any:
        if type(session) is not ConnectedRegistrySession:
            raise RegistrySessionUnavailable
        try:
            selector = session.selector
        except (AttributeError, TypeError):
            raise RegistrySessionUnavailable from None
        if type(selector) is not BrokerSelector:
            raise RegistrySessionUnavailable
        authority = self._provider.current_authority_for(selector)
        return self._registry.client_for_connected_session(session, current_authority=authority)
