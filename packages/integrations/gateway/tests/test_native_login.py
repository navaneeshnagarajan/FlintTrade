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
