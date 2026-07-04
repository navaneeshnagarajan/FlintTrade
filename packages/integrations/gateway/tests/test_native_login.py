"""Tests for the native credential-replay login step (Phase 1 G3)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from flinttrade_gateway.native_login import (
    establish_native_session,
    establish_native_sessions,
)


class _FakeSession:
    def __init__(self, adapter_id: str, account_id: str) -> None:
        self.adapter_id = adapter_id
        self.account_id = account_id
        self.expires_at = 4_102_444_800.0


class _FakeAdapter:
    """A native adapter stub whose login echoes back a session."""

    def __init__(self, adapter_id: str, *, fail: bool = False) -> None:
        self.adapter_id = adapter_id
        self.fail = fail
        self.login_calls: list[dict[str, Any]] = []

    async def login(self, credentials: dict[str, Any]) -> _FakeSession:
        self.login_calls.append(credentials)
        if self.fail:
            raise RuntimeError("broker rejected credentials")
        return _FakeSession(self.adapter_id, str(credentials.get("account_id", "acct")))


class _FakeRegistry:
    def __init__(self) -> None:
        self.sessions: dict[tuple[str, str], Any] = {}

    def put_session(self, adapter_id: str, account_id: str, session: Any) -> None:
        self.sessions[(adapter_id, account_id)] = session

    def get_session_for(self, adapter_id: str, account_id: str) -> Any:
        return self.sessions[(adapter_id, account_id)]

    def remove_session_for(self, adapter_id: str, account_id: str) -> None:
        self.sessions.pop((adapter_id, account_id), None)


class _FakeStore:
    def __init__(self, rows: dict[tuple[str, str], dict[str, Any]]) -> None:
        self.rows = rows

    def retrieve_for(self, adapter_id: str, account_id: str) -> dict[str, Any]:
        return self.rows[(adapter_id, account_id)]


def test_establish_native_session_registers_the_session() -> None:
    adapter = _FakeAdapter("dhan")
    registry = _FakeRegistry()
    session = asyncio.run(
        establish_native_session(
            adapter, registry, {"access_token": "t", "account_id": "111"}, "dhan", "111"
        )
    )
    assert registry.sessions[("dhan", "111")] is session
    assert adapter.login_calls == [{"access_token": "t", "account_id": "111"}]


def test_establish_native_session_fails_closed() -> None:
    adapter = _FakeAdapter("dhan", fail=True)
    registry = _FakeRegistry()
    with pytest.raises(RuntimeError):
        asyncio.run(
            establish_native_session(adapter, registry, {"access_token": "t"}, "dhan", "111")
        )
    # No session registered on failure — the selector stays sessionless.
    assert registry.sessions == {}


def test_establish_all_isolates_per_selector_failures() -> None:
    adapters = {"dhan": _FakeAdapter("dhan"), "upstox": _FakeAdapter("upstox", fail=True)}
    registry = _FakeRegistry()
    store = _FakeStore(
        {
            ("dhan", "111"): {"access_token": "d"},
            ("upstox", "222"): {"access_token": "u"},
        }
    )
    results = asyncio.run(
        establish_native_sessions(
            adapters, registry, store, ["dhan:111", "upstox:222", "openalgo:default"]
        )
    )
    # Dhan logs in; Upstox fails but is isolated; the bridge selector is skipped.
    assert results["dhan:111"] == "ok"
    assert results["upstox:222"].startswith("login-failed")
    assert "openalgo:default" not in results
    assert ("dhan", "111") in registry.sessions
    assert ("upstox", "222") not in registry.sessions


def test_establish_all_skips_selectors_without_credentials() -> None:
    adapters = {"dhan": _FakeAdapter("dhan")}
    registry = _FakeRegistry()
    store = _FakeStore({})  # no rows
    results = asyncio.run(
        establish_native_sessions(adapters, registry, store, ["dhan:111"])
    )
    assert results["dhan:111"].startswith("no-credentials")
    assert registry.sessions == {}


# ---------------------------------------------------------------------------
# G7 — replayable-credential write-back
# ---------------------------------------------------------------------------


class _ReplayAdapter(_FakeAdapter):
    """Adapter that swaps a one-time TOTP for the minted access token."""

    def replay_credentials(self, credentials: dict[str, Any], session: Any) -> dict[str, Any]:
        replayable = {k: v for k, v in credentials.items() if k != "totp"}
        replayable["access_token"] = "minted-24h-token"
        return replayable


class _WritableStore(_FakeStore):
    def __init__(self, rows: dict[tuple[str, str], dict[str, Any]]) -> None:
        super().__init__(rows)
        self.updates: list[tuple[str, str, dict[str, Any]]] = []

    def update_credentials_for(
        self, adapter_id: str, account_id: str, credentials: dict[str, Any]
    ) -> None:
        self.updates.append((adapter_id, account_id, credentials))
        self.rows[(adapter_id, account_id)] = credentials


def test_write_back_swaps_single_use_artefacts() -> None:
    """After a successful login the vault holds the REPLAYABLE payload — the
    one-time TOTP is gone, the minted access token is in (G7)."""
    adapter = _ReplayAdapter("dhan")
    registry = _FakeRegistry()
    store = _WritableStore({("dhan", "111"): {"client_id": "111", "pin": "1234", "totp": "000111"}})
    asyncio.run(
        establish_native_sessions({"dhan": adapter}, registry, store, ["dhan:111"])
    )
    assert registry.sessions[("dhan", "111")] is not None
    assert store.updates, "vault write-back did not happen"
    stored = store.rows[("dhan", "111")]
    assert "totp" not in stored
    assert stored["access_token"] == "minted-24h-token"
    assert stored["pin"] == "1234"  # reusable material preserved


def test_write_back_failure_never_fails_the_live_session() -> None:
    class _BrokenStore(_WritableStore):
        def update_credentials_for(self, *a: Any, **kw: Any) -> None:
            raise RuntimeError("disk full")

    adapter = _ReplayAdapter("dhan")
    registry = _FakeRegistry()
    session = asyncio.run(
        establish_native_session(
            adapter, registry, {"pin": "1234", "totp": "000111"}, "dhan", "111",
            credential_store=_BrokenStore({}),
        )
    )
    assert registry.sessions[("dhan", "111")] is session  # session survives


def test_adapter_without_replay_hook_writes_nothing() -> None:
    """IndMoney-style adapters (static, already-replayable creds) skip the
    write-back entirely."""
    adapter = _FakeAdapter("indmoney")
    registry = _FakeRegistry()
    store = _WritableStore({("indmoney", "X"): {"access_token": "static"}})
    asyncio.run(
        establish_native_sessions({"indmoney": adapter}, registry, store, ["indmoney:X"])
    )
    assert store.updates == []


def test_unchanged_payload_skips_the_write() -> None:
    class _IdentityReplayAdapter(_FakeAdapter):
        def replay_credentials(self, credentials: dict[str, Any], session: Any) -> dict[str, Any]:
            return dict(credentials)

    adapter = _IdentityReplayAdapter("indmoney")
    registry = _FakeRegistry()
    store = _WritableStore({("indmoney", "X"): {"access_token": "static"}})
    asyncio.run(
        establish_native_sessions({"indmoney": adapter}, registry, store, ["indmoney:X"])
    )
    assert store.updates == []


# ---------------------------------------------------------------------------
# Re-audit fix: transient-error classification across all three HTTP stacks
# ---------------------------------------------------------------------------


def test_transient_classifier_covers_httpx_requests_urllib3_and_stdlib() -> None:
    """The four natives use httpx (IndMoney), urllib3 (Upstox) and requests
    (Dhan/Kotak) — a transport blip on ANY of them must be classified transient
    so the liveness probe keeps a healthy session (audit fix, was httpx-only)."""
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

    registry = _FakeRegistry()
    registry.sessions[("dhan", "1")] = _FakeSession("dhan", "1")
    err = asyncio.run(verify_native_session(_BlipAdapter(), registry, "dhan", "1"))
    assert err is None
    assert ("dhan", "1") in registry.sessions  # kept


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

    registry = _FakeRegistry()
    registry.sessions[("upstox", "UPXTEST")] = _FakeSession("upstox", "UPXTEST")
    err = asyncio.run(verify_native_session(_WindowClosedAdapter(), registry, "upstox", "UPXTEST"))
    assert err is None
    assert ("upstox", "UPXTEST") in registry.sessions  # kept — window closed ≠ dead token


def test_verify_drops_session_on_real_auth_failure() -> None:
    """A genuine auth failure (expired/invalid token) must STILL drop the session
    and surface an error, so the service-window keep-path does not swallow real
    dead tokens and hide needs_relogin."""
    import asyncio

    from flinttrade_gateway.native_login import verify_native_session

    class _DeadTokenAdapter:
        async def funds(self, _session):
            raise RuntimeError("401 Unauthorized: access token expired")

    registry = _FakeRegistry()
    registry.sessions[("upstox", "DEAD")] = _FakeSession("upstox", "DEAD")
    err = asyncio.run(verify_native_session(_DeadTokenAdapter(), registry, "upstox", "DEAD"))
    assert err is not None
    assert "token verification failed" in err
    assert ("upstox", "DEAD") not in registry.sessions  # dropped


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

    registry = _FakeRegistry()
    registry.sessions[("upstox", "DEAD2")] = _FakeSession("upstox", "DEAD2")
    err = asyncio.run(verify_native_session(_DeadButChattyAdapter(), registry, "upstox", "DEAD2"))
    assert err is not None
    assert ("upstox", "DEAD2") not in registry.sessions  # dropped despite service phrasing


def test_verify_evicts_lockout_message_with_retry_copy() -> None:
    """A generic (untyped) locked/dead credential whose text carries retry copy is
    still evicted — the narrowed service-window markers must not keep it alive."""
    import asyncio

    from flinttrade_gateway.native_login import verify_native_session

    class _LockedAdapter:
        async def funds(self, _session):
            raise RuntimeError("Account locked due to too many failed attempts, please try again later")

    registry = _FakeRegistry()
    registry.sessions[("kotakneo", "LOCK")] = _FakeSession("kotakneo", "LOCK")
    err = asyncio.run(verify_native_session(_LockedAdapter(), registry, "kotakneo", "LOCK"))
    assert err is not None
    assert ("kotakneo", "LOCK") not in registry.sessions  # dropped


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

    registry = _FakeRegistry()
    registry.sessions[("dhan", "RL")] = _FakeSession("dhan", "RL")
    err = asyncio.run(verify_native_session(_ThrottledAdapter(), registry, "dhan", "RL"))
    assert err is None
    assert ("dhan", "RL") in registry.sessions  # kept
