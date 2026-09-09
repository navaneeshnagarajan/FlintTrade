"""Native preparation and replay bind final disposable durable authorities."""

import asyncio
import pytest

from flinttrade_core.broker_identity import BrokerSelector
from flinttrade_core.account_mutation_contracts import RegistrySessionUnavailable
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.native_login import (
    BROKER_LOGIN_RETRY_MESSAGE, CREDENTIALS_UNAVAILABLE_MESSAGE, SESSION_INVALID_RELOGIN_MESSAGE,
    establish_native_session, establish_native_sessions,
)

import importlib.util
from pathlib import Path

_fixture_spec = importlib.util.spec_from_file_location("_registry_fixtures", Path(__file__).resolve().parents[4] / "tests" / "registry_fixtures.py")
_fixture_module = importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture_module)
RegistryFixture = _fixture_module.RegistryFixture

@pytest.fixture
def exact(tmp_path):
    value = RegistryFixture(tmp_path)
    selector = BrokerSelector("dhan", "Case")
    value.store.put_credentials(selector, "dhan", "Synthetic", {"access_token": "old"},
                                expected=value.store.selector_state(selector).version)
    yield value
    value.close()


class Adapter:
    calls = 0
    async def login(self, credentials):
        self.calls += 1
        return Session(credentials["access_token"], 4102444800, "broker-id", "dhan")
    async def funds(self, session):
        return {}


def establish(exact, adapter, **kwargs):
    version = exact.store.selector_state(BrokerSelector("dhan", "Case")).version
    return asyncio.run(establish_native_session(adapter, exact.registry,
        exact.store.retrieve_credentials(BrokerSelector("dhan", "Case")), "dhan", "Case",
        exact.store, mutation_admission=lambda: None, registry_publication_owner=exact.owner,
        workspace_path=exact.path, credential_version=version, **kwargs))


def test_establish_native_session_registers_final_exact_authority(exact):
    candidate = establish(exact, Adapter(), verify=True)
    assert exact.session("dhan", "Case").account_id == "broker-id"
    assert candidate.registry_version.generation == 1


def test_missing_owner_fails_before_login(exact):
    adapter = Adapter()
    with pytest.raises(RegistrySessionUnavailable):
        asyncio.run(establish_native_session(adapter, exact.registry, {}, "dhan", "Case",
                                              mutation_admission=lambda: None))
    assert adapter.calls == 0


@pytest.mark.parametrize("witness", ["missing", "stale"])
def test_replay_requires_the_version_captured_before_credentials(exact, witness):
    selector = BrokerSelector("dhan", "Case")
    before = exact.store.selector_state(selector).version
    credentials = exact.store.retrieve_credentials(selector)
    if witness == "stale":
        exact.store.update_credentials(selector, {"access_token": "successor"}, expected=before)
    adapter = Adapter()
    with pytest.raises(RegistrySessionUnavailable):
        asyncio.run(establish_native_session(adapter, exact.registry, credentials, "dhan", "Case", exact.store,
            mutation_admission=lambda: None, registry_publication_owner=exact.owner, workspace_path=exact.path,
            credential_version=before if witness == "stale" else None))
    assert adapter.calls == 0
    assert not exact.registry.snapshot_selector(selector).present


def test_login_failure_never_publishes_candidate(exact):
    class Failed(Adapter):
        async def login(self, credentials):
            raise RuntimeError("synthetic failure")
    with pytest.raises(RuntimeError):
        establish(exact, Failed())
    assert not exact.registry.snapshot_selector(BrokerSelector("dhan", "Case")).present


def test_write_back_swaps_single_use_artefacts_before_publication(exact):
    class Replay(Adapter):
        def replay_credentials(self, credentials, session):
            return {"access_token": "replay"}
    candidate = establish(exact, Replay())
    state = exact.store.selector_state(BrokerSelector("dhan", "Case"))
    assert state.version.generation == 2
    assert exact.session("dhan", "Case").version.credential_version == state.version
    assert candidate.registry_version.present


def test_write_back_failure_refuses_publication(exact, monkeypatch):
    class Replay(Adapter):
        def replay_credentials(self, credentials, session):
            return {"access_token": "replay"}
    def fail(*args, **kwargs):
        raise OSError("synthetic")
    monkeypatch.setattr(exact.store, "update_credentials", fail)
    with pytest.raises(OSError):
        establish(exact, Replay())
    assert not exact.registry.snapshot_selector(BrokerSelector("dhan", "Case")).present


def test_unchanged_payload_skips_write(exact):
    establish(exact, Adapter())
    assert exact.store.selector_state(BrokerSelector("dhan", "Case")).version.generation == 1


def test_establish_all_isolates_missing_and_transient_failures(exact):
    class Failed(Adapter):
        async def login(self, credentials):
            raise TimeoutError("synthetic")
    results = asyncio.run(establish_native_sessions({"dhan": Failed()}, exact.registry, exact.store,
        ["dhan:Case", "dhan:Missing"], mutation_admission=lambda: None,
        registry_publication_owner=exact.owner, workspace_path=exact.path))
    assert results == {"dhan:Case": BROKER_LOGIN_RETRY_MESSAGE, "dhan:Missing": CREDENTIALS_UNAVAILABLE_MESSAGE}


def test_transient_classifier_covers_httpx_requests_urllib3_and_stdlib() -> None:
    """The natives use httpx (INDmoney/Groww), urllib3 (Upstox), and requests
    (Dhan/Kotak); a transport blip on any of them must be classified transient
    so the liveness probe keeps a healthy session."""
    import socket

    import httpx
    import requests
    import urllib3

    from flinttrade_gateway.native_login import _is_transient_probe_error

    transient = [
        httpx.ConnectTimeout("t"),
        httpx.ReadTimeout("t"),
        requests.exceptions.ConnectionError("boom"),
        requests.exceptions.Timeout("slow"),
        urllib3.exceptions.NewConnectionError(None, "no route"),  # type: ignore[arg-type]
        urllib3.exceptions.ProtocolError("reset"),
        socket.timeout("timed out"),
        TimeoutError("timed out"),
    ]
    for exc in transient:
        assert _is_transient_probe_error(exc) is True, exc

    # A real auth/broker error is NOT transient — the session must be dropped.
    for exc in (RuntimeError("401 token expired"), ValueError("bad token"), httpx.HTTPStatusError(
        "401", request=httpx.Request("GET", "http://x"), response=httpx.Response(401),
    )):
        assert _is_transient_probe_error(exc) is False, exc


def test_verify_keeps_session_on_transient_error() -> None:
    """A transient transport error keeps the live session (returns None), so a
    momentary blip does not flip a healthy account to needs_relogin."""
    import asyncio

    import requests

    from flinttrade_gateway.native_login import verify_native_session

    class _BlipAdapter:
        async def funds(self, _session):
            raise requests.exceptions.ConnectionError("momentary blip")

    session = Session("synthetic", 4102444800, "1", "dhan")
    err = asyncio.run(verify_native_session(_BlipAdapter(), session))
    assert err is None


def test_verify_keeps_session_on_service_window_error() -> None:
    """Upstox's funds endpoint is offline 12:00 AM–5:30 AM IST nightly and replies
    "... service is accessible from ... service hours". That is NOT proof the token
    is dead, so a freshly-minted session must be KEPT (returns None) rather than
    evicted — otherwise an OAuth connect made after midnight IST always reports
    'login failed' despite a perfectly valid token."""
    import asyncio

    from flinttrade_gateway.native_login import verify_native_session

    class _WindowClosedAdapter:
        async def funds(self, _session):
            raise RuntimeError(
                "The Funds service is accessible from 5:30 AM to 12:00 AM IST daily. "
                "Please try again during these service hours."
            )

    session = Session("synthetic", 4102444800, "UPXTEST", "upstox")
    err = asyncio.run(verify_native_session(_WindowClosedAdapter(), session))
    assert err is None


def test_verify_drops_session_on_real_auth_failure() -> None:
    """A genuine auth failure (expired/invalid token) must STILL drop the session
    and surface an error, so the service-window keep-path does not swallow real
    dead tokens and hide needs_relogin."""
    import asyncio

    from flinttrade_gateway.native_login import verify_native_session

    class _DeadTokenAdapter:
        async def funds(self, _session):
            raise RuntimeError("401 Unauthorized: access token expired")

    session = Session("synthetic", 4102444800, "DEAD", "upstox")
    err = asyncio.run(verify_native_session(_DeadTokenAdapter(), session))
    assert err == SESSION_INVALID_RELOGIN_MESSAGE


def test_verify_auth_failure_status_does_not_echo_broker_payload() -> None:
    """Broker SDK exceptions can contain account ids or raw payload fragments.

    The replay verifier should only return the safe re-login status that the UI
    can surface, never the exception string itself.
    """
    import asyncio

    from flinttrade_gateway.native_login import verify_native_session

    class _DeadTokenAdapter:
        async def funds(self, _session):
            raise RuntimeError(
                "401 Unauthorized: access token expired for account UPXSECRET123 token abcdef1234567890"
            )

    session = Session("synthetic", 4102444800, "UPXSECRET123", "upstox")
    err = asyncio.run(verify_native_session(_DeadTokenAdapter(), session))

    assert err == SESSION_INVALID_RELOGIN_MESSAGE
    assert "UPXSECRET123" not in err
    assert "abcdef1234567890" not in err


def test_verify_evicts_typed_auth_failure_despite_service_phrasing() -> None:
    """A typed auth failure (SessionExpired) is evicted even when its message ALSO
    carries service-window/retry phrasing — auth detection takes precedence over
    the keep-on-service-window path, so a dead token is never masked as connected.
    (Review finding: the earlier substring-only classifier could keep it.)"""
    import asyncio

    from flinttrade_core.exceptions import SessionExpired

    from flinttrade_gateway.native_login import verify_native_session

    class _DeadButChattyAdapter:
        async def funds(self, _session):
            raise SessionExpired(
                "Token expired — service temporarily unavailable, please try again during service hours"
            )

    session = Session("synthetic", 4102444800, "DEAD2", "upstox")
    err = asyncio.run(verify_native_session(_DeadButChattyAdapter(), session))
    assert err is not None


def test_verify_evicts_lockout_message_with_retry_copy() -> None:
    """A generic (untyped) locked/dead credential whose text carries retry copy is
    still evicted — the narrowed service-window markers must not keep it alive."""
    import asyncio

    from flinttrade_gateway.native_login import verify_native_session

    class _LockedAdapter:
        async def funds(self, _session):
            raise RuntimeError("Account locked due to too many failed attempts, please try again later")

    session = Session("synthetic", 4102444800, "LOCK", "kotakneo")
    err = asyncio.run(verify_native_session(_LockedAdapter(), session))
    assert err is not None


def test_verify_keeps_session_on_typed_rate_limit() -> None:
    """A 429 (typed RateLimitError) means the token is fine but throttled — keep
    the live session rather than false-alarm needs_relogin. Recognised by TYPE,
    not by a "rate limit"/"too many requests" substring (which would collide with
    a genuine lockout message)."""
    import asyncio

    from flinttrade_core.exceptions import RateLimitError

    from flinttrade_gateway.native_login import verify_native_session

    class _ThrottledAdapter:
        async def funds(self, _session):
            raise RateLimitError("429 request rate exceeded", endpoint="funds")

    session = Session("synthetic", 4102444800, "RL", "dhan")
    err = asyncio.run(verify_native_session(_ThrottledAdapter(), session))
    assert err is None


def test_boot_replay_rejects_real_same_value_credential_aba(exact):
    selector = BrokerSelector("dhan", "Case")
    before = exact.store.selector_state(selector).version
    class Racing(Adapter):
        async def login(self, credentials):
            exact.store.update_credentials(selector, dict(credentials), expected=before)
            return await super().login(credentials)
    with pytest.raises(RegistrySessionUnavailable):
        establish(exact, Racing())
    assert exact.store.selector_state(selector).version.generation == before.generation + 1
    assert not exact.registry.snapshot_selector(selector).present


def test_boot_replay_rejects_credentials_changed_during_retrieval(exact, monkeypatch):
    selector = BrokerSelector("dhan", "Case")
    before = exact.store.selector_state(selector).version
    retrieve = exact.store.retrieve_for

    def retrieve_then_replace(adapter_id, account_id):
        credentials = retrieve(adapter_id, account_id)
        exact.store.update_credentials(selector, {"access_token": "successor"}, expected=before)
        return credentials

    monkeypatch.setattr(exact.store, "retrieve_for", retrieve_then_replace)
    adapter = Adapter()
    results = asyncio.run(establish_native_sessions({"dhan": adapter}, exact.registry, exact.store,
        ["dhan:Case"], mutation_admission=lambda: None,
        registry_publication_owner=exact.owner, workspace_path=exact.path))
    assert adapter.calls == 0
    assert results == {"dhan:Case": CREDENTIALS_UNAVAILABLE_MESSAGE}
    assert not exact.registry.snapshot_selector(selector).present
    assert exact.store.selector_state(selector).version.generation == before.generation + 1


def test_boot_replay_does_not_adopt_post_authentication_credential_version(exact, monkeypatch):
    selector = BrokerSelector("dhan", "Case")
    state_for = exact.store.selector_state
    publications = []
    publish = exact.owner.publish_prepared_candidate

    def record_publication(*args, **kwargs):
        publications.append(1)
        return publish(*args, **kwargs)

    class Racing(Adapter):
        async def login(self, credentials):
            # Mutate just after the first post-authentication freshness read.
            def state_then_replace(key):
                state = state_for(key)
                monkeypatch.setattr(exact.store, "selector_state", state_for)
                exact.store.update_credentials(selector, {"access_token": "successor"}, expected=state.version)
                return state
            monkeypatch.setattr(exact.store, "selector_state", state_then_replace)
            return await super().login(credentials)

    monkeypatch.setattr(exact.owner, "publish_prepared_candidate", record_publication)
    with pytest.raises(RegistrySessionUnavailable):
        establish(exact, Racing())
    assert publications == []
    assert not exact.registry.snapshot_selector(selector).present


def test_boot_replay_retains_its_cas_version_when_another_writer_follows(exact, monkeypatch):
    selector = BrokerSelector("dhan", "Case")
    update = exact.store.update_credentials
    own_versions = []
    publications = []
    publish = exact.owner.publish_prepared_candidate

    def update_then_replace(key, credentials, *, expected):
        committed = update(key, credentials, expected=expected)
        own_versions.append(committed)
        update(key, {"access_token": "successor"}, expected=committed)
        return committed

    def record_publication(*args, **kwargs):
        publications.append(1)
        return publish(*args, **kwargs)

    class Replay(Adapter):
        def replay_credentials(self, credentials, session):
            return {"access_token": "replayed"}

    monkeypatch.setattr(exact.store, "update_credentials", update_then_replace)
    monkeypatch.setattr(exact.owner, "publish_prepared_candidate", record_publication)
    with pytest.raises(RegistrySessionUnavailable):
        establish(exact, Replay())
    assert own_versions[0].generation == 2
    assert exact.store.selector_state(selector).version.generation == 3
    assert publications == []
    assert not exact.registry.snapshot_selector(selector).present
