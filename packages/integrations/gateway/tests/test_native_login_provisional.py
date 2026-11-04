"""Fresh replay admission and sealed-session continuity with inert provider I/O."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import requests

from flinttrade_core.broker_identity import BrokerSelector
from flinttrade_gateway.brokers.dhan import DhanAdapter
from flinttrade_gateway.native_login import BROKER_LOGIN_RETRY_MESSAGE, establish_native_sessions


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from flinttrade_gateway.brokers._base import Session
    from tests.registry_fixtures import RegistryFixture

_spec = importlib.util.spec_from_file_location(
    "_provisional_registry_fixtures", Path(__file__).resolve().parents[4] / "tests" / "registry_fixtures.py"
)
_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixtures)
pytestmark = pytest.mark.integration


@pytest.fixture
def provisional_runtime(
    tmp_path: "Path",
    monkeypatch: "pytest.MonkeyPatch",
) -> "Iterator[tuple[RegistryFixture, BrokerSelector, DhanAdapter, list[Session]]]":
    """Own a provisional registry, real Dhan adapter and every captured synthetic session.

    Args:
        tmp_path: Disposable workspace directory supplied by pytest.
        monkeypatch: Scoped replacements restored after this test.

    Yields:
        Registry fixture, exact selector, adapter and captured sessions until original-owner disposal.
    """
    exact = _fixtures.RegistryFixture(tmp_path)
    selector = BrokerSelector("dhan", "Case")
    exact.store.put_credentials(
        selector,
        "dhan",
        "Synthetic",
        {"client_id": "Case", "access_token": "synthetic-token"},
        expected=exact.store.selector_state(selector).version,
    )
    adapter = DhanAdapter()
    sessions = []
    login = adapter.login

    async def observe(credentials):
        session = await login(credentials)
        sessions.append(session)
        return session

    monkeypatch.setattr(adapter, "login", observe)
    yield exact, selector, adapter, sessions
    current = exact.registry.snapshot_selector(selector)
    if current.present:
        exact.owner.remove_session_for_exact(selector, expected_registry=current)
    for receipt in tuple(exact.owner._retirements):
        retired = exact.owner.claim_retired_candidate(receipt)
        adapter.dispose_session(retired.session)
        exact.owner.release_retired_candidate(retired)
    for session in sessions:
        adapter.dispose_session(session)
    exact.close()


@pytest.mark.parametrize("verify", [False, True])
@pytest.mark.parametrize("profile", ["ok", "timeout"])
def test_provisional_replay_requires_strict_profile_and_owned_custody(
    provisional_runtime: "tuple[RegistryFixture, BrokerSelector, DhanAdapter, list[Session]]",
    monkeypatch: "pytest.MonkeyPatch",
    verify: "bool",
    profile: "str",
) -> None:
    """Require strict profile verification and owned cleanup for provisional replay.

    Args:
        provisional_runtime: Owned registry fixture, exact selector, real Dhan adapter and captured sessions.
        monkeypatch: Scoped replacements restored after this test.
        verify: Whether fresh profile verification is enabled for replay admission.
        profile: Successful or timed-out fresh provider profile control.
    """
    exact, selector, adapter, sessions = provisional_runtime
    calls = []
    expiry = (datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(hours=2)).replace(second=0, microsecond=0)

    def send(transport, request, **kwargs):
        calls.append((request.method, request.url, len(exact.registry._prepared)))
        assert request.method == "GET" and request.url == "https://api.dhan.co/v2/profile"
        if profile == "timeout":
            raise requests.Timeout("synthetic profile interruption")
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(
            {"dhanClientId": "Case", "tokenValidity": expiry.strftime("%d/%m/%Y %H:%M")}
        ).encode()
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    result = asyncio.run(
        establish_native_sessions(
            {"dhan": adapter},
            exact.registry,
            exact.store,
            ["dhan:Case"],
            verify=verify,
            mutation_admission=lambda: None,
            registry_publication_owner=exact.owner,
            workspace_path=exact.path,
        )
    )
    if profile == "timeout":
        assert result == {"dhan:Case": BROKER_LOGIN_RETRY_MESSAGE}
        assert not exact.registry.snapshot_selector(selector).present
        assert len(exact.owner._retirements) == 1
    else:
        assert result == {"dhan:Case": "ok"}
        assert exact.registry.snapshot_exact_state(selector).expires_at == expiry.timestamp()
        assert exact.registry.snapshot_exact_state(selector).status == "connected"
    assert calls == [("GET", "https://api.dhan.co/v2/profile", 1)]


def test_transient_fresh_replay_does_not_retire_verified_prior_session(
    provisional_runtime: "tuple[RegistryFixture, BrokerSelector, DhanAdapter, list[Session]]",
    monkeypatch: "pytest.MonkeyPatch",
) -> None:
    """Preserve the verified prior session after a transient fresh replay failure.

    Args:
        provisional_runtime: Owned registry fixture, exact selector, real Dhan adapter and captured sessions.
        monkeypatch: Scoped replacements restored after this test.
    """
    exact, selector, adapter, sessions = provisional_runtime
    expiry = (datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(hours=2)).replace(second=0, microsecond=0)
    fail = []

    def send(transport, request, **kwargs):
        assert request.url == "https://api.dhan.co/v2/profile"
        if fail:
            raise requests.Timeout("synthetic continuity interruption")
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(
            {"dhanClientId": "Case", "tokenValidity": expiry.strftime("%d/%m/%Y %H:%M")}
        ).encode()
        return response

    monkeypatch.setattr(requests.Session, "send", send)

    def replay():
        return asyncio.run(
            establish_native_sessions(
                {"dhan": adapter},
                exact.registry,
                exact.store,
                ["dhan:Case"],
                mutation_admission=lambda: None,
                registry_publication_owner=exact.owner,
                workspace_path=exact.path,
            )
        )

    assert replay() == {"dhan:Case": "ok"}
    before = exact.registry.snapshot_exact_state(selector)
    fail.append(True)
    assert replay() == {"dhan:Case": BROKER_LOGIN_RETRY_MESSAGE}
    assert exact.registry.snapshot_exact_state(selector) == before
    assert exact.session("dhan", "Case").expires_at == expiry.timestamp()
    assert len(exact.owner._retirements) == 1  # failed new candidate, never the prior session


def test_owner_shortens_expiry_without_mutable_handle_or_extension(
    provisional_runtime: "tuple[RegistryFixture, BrokerSelector, DhanAdapter, list[Session]]",
    monkeypatch: "pytest.MonkeyPatch",
) -> None:
    """Shorten expiry through the actual owner without mutating or extending a sealed handle.

    Args:
        provisional_runtime: Owned registry fixture, exact selector, real Dhan adapter and captured sessions.
        monkeypatch: Scoped replacements restored after this test.
    """
    from flinttrade_core.account_mutation_contracts import RegistrySessionUnavailable, RegistryVersionValidationError
    from flinttrade_gateway.registry import ManagedLookupAuthority

    exact, selector, adapter, sessions = provisional_runtime
    expiry = (datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(hours=2)).replace(second=0, microsecond=0)

    def send(transport, request, **kwargs):
        assert request.url == "https://api.dhan.co/v2/profile"
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(
            {"dhanClientId": "Case", "tokenValidity": expiry.strftime("%d/%m/%Y %H:%M")}
        ).encode()
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    result = asyncio.run(
        establish_native_sessions(
            {"dhan": adapter},
            exact.registry,
            exact.store,
            ["dhan:Case"],
            mutation_admission=lambda: None,
            registry_publication_owner=exact.owner,
            workspace_path=exact.path,
        )
    )
    assert result == {"dhan:Case": "ok"}
    handle = exact.session("dhan", "Case")
    binding = handle.version
    authority = ManagedLookupAuthority(binding.credential_version, binding.broker_workspace_version)
    with pytest.raises(AttributeError):
        handle.expires_at = 0
    shortened = expiry.timestamp() - 60
    exact.owner.shorten_session_expiry(handle, shortened, current_authority=authority)
    state = exact.registry.snapshot_exact_state(selector)
    assert state.expires_at == shortened
    assert state.registry_version.generation == binding.registry_version.generation + 1
    assert state.binding.credential_version == binding.credential_version
    with pytest.raises(RegistrySessionUnavailable):
        exact.owner.shorten_session_expiry(handle, shortened, current_authority=authority)
    current = exact.session("dhan", "Case")
    for invalid in (True, None, float("nan"), float("inf"), expiry.timestamp()):
        with pytest.raises(RegistryVersionValidationError):
            exact.owner.shorten_session_expiry(current, invalid, current_authority=authority)
    assert exact.registry.snapshot_exact_state(selector) == state


def test_continuity_observation_shortening_requires_exact_registry_owner(
    provisional_runtime: "tuple[RegistryFixture, BrokerSelector, DhanAdapter, list[Session]]",
    monkeypatch: "pytest.MonkeyPatch",
) -> None:
    """Require the exact registry owner when applying continuity expiry observations.

    Args:
        provisional_runtime: Owned registry fixture, exact selector, real Dhan adapter and captured sessions.
        monkeypatch: Scoped replacements restored after this test.
    """
    from flinttrade_gateway.brokers._base import Session
    from flinttrade_gateway.native_login import SESSION_INVALID_RELOGIN_MESSAGE, verify_native_session
    from flinttrade_gateway.registry import ManagedLookupAuthority

    exact, selector, adapter, sessions = provisional_runtime
    expiry = datetime.now(ZoneInfo("UTC")).timestamp() + 3600
    raw = Session("synthetic-token", expiry, "Case", "dhan")
    exact.publish("dhan", "Case", raw)
    handle = exact.session("dhan", "Case")
    binding = handle.version
    authority = ManagedLookupAuthority(binding.credential_version, binding.broker_workspace_version)

    class Observation:
        # Protocol-unit observer only, not a Dhan provider qualification fixture.
        broker_id = "dhan"

        async def liveness(self, session):
            assert session is handle
            return expiry - 60

    observed = Observation()
    assert asyncio.run(verify_native_session(observed, handle)) == SESSION_INVALID_RELOGIN_MESSAGE
    assert exact.registry.snapshot_exact_state(selector).expires_at == expiry
    assert (
        asyncio.run(
            verify_native_session(observed, handle, registry_publication_owner=exact.owner, current_authority=authority)
        )
        is None
    )
    assert exact.registry.snapshot_exact_state(selector).expires_at == expiry - 60
    assert (
        exact.registry.snapshot_exact_state(selector).registry_version.generation
        == binding.registry_version.generation + 1
    )
