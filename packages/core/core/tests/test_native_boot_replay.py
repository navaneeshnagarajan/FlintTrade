"""Regression tests for native broker boot replay.

These pin the live Dhan restart failure found during broker validation: native
vault rows must be replayed by the native login path, not the legacy bridge
session authenticator, and replay must work even when app creation happens while
an event loop is already running.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace


def test_reconnect_saved_accounts_skips_native_rows(monkeypatch):
    from flinttrade_core.app import _reconnect_saved_accounts

    class Store:
        def __init__(self):
            self.retrieved: list[str] = []

        def list_accounts(self):
            return [
                {
                    "account_id": "D1",
                    "adapter_id": "dhan",
                    "broker": "dhan",
                    "label": "Dhan native",
                    "is_primary": True,
                },
                {
                    "account_id": "OA1",
                    "adapter_id": "openalgo",
                    "broker": "openalgo",
                    "label": "OpenAlgo bridge",
                    "is_primary": True,
                },
            ]

        def retrieve(self, account_id):
            self.retrieved.append(account_id)
            return {"api_key": "bridge-key"}

    class FakeSession:
        def __init__(self, account_id, broker, label):
            self.account_id = account_id
            self.broker = broker
            self.label = label
            self.credentials = None

        def authenticate(self, credentials):
            self.credentials = credentials

    monkeypatch.setattr("flinttrade_gateway.session.BrokerSession", FakeSession)
    registry = SimpleNamespace(_sessions={}, _primary=None)
    logger = SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)
    store = Store()

    _reconnect_saved_accounts(registry, store, logger)

    assert store.retrieved == ["OA1"]
    assert set(registry._sessions) == {"OA1"}
    assert registry._primary == "OA1"


def test_reestablish_native_sessions_runs_inside_existing_event_loop(monkeypatch):
    from flinttrade_core import app as app_module

    async def fake_establish(native_adapters, registry, credential_store, selectors, *, verify=False):
        assert native_adapters == {
            "dhan": object_marker["dhan"],
            "upstox": object_marker["upstox"],
            "indmoney": object_marker["indmoney"],
        }
        assert selectors == ["dhan:D1", "upstox:U1", "indmoney:I1", "kotakneo:K1", "groww:G1"]
        assert verify is True
        # establish_native_sessions skips selectors whose adapters are not
        # active; Kotak/Groww are still coming-soon, so no status is returned.
        return {"dhan:D1": "ok", "upstox:U1": "ok", "indmoney:I1": "ok"}

    object_marker = {"dhan": object(), "upstox": object(), "indmoney": object()}
    fake_app = SimpleNamespace(
        config={
            "NATIVE_ADAPTERS": {
                "dhan": object_marker["dhan"],
                "upstox": object_marker["upstox"],
                "indmoney": object_marker["indmoney"],
            },
            "REGISTRY": object(),
            "CREDENTIAL_STORE": object(),
        }
    )
    monkeypatch.setattr(
        app_module,
        "_read_workspace_brokers",
        lambda: {"registered": ["dhan:D1", "upstox:U1", "indmoney:I1", "kotakneo:K1", "groww:G1"]},
    )
    monkeypatch.setattr("flinttrade_gateway.native_login.establish_native_sessions", fake_establish)

    async def run_from_loop():
        return app_module._reestablish_native_sessions(fake_app, verify=True)

    assert asyncio.run(run_from_loop()) == {"dhan:D1": "ok", "upstox:U1": "ok", "indmoney:I1": "ok"}
    assert fake_app.config["NATIVE_SESSION_STATUS"] == {
        "dhan:D1": "ok",
        "upstox:U1": "ok",
        "indmoney:I1": "ok",
    }


def test_reestablish_native_sessions_verifies_by_default(monkeypatch):
    from flinttrade_core import app as app_module

    seen: dict[str, bool] = {}

    async def fake_establish(native_adapters, registry, credential_store, selectors, *, verify=False):
        seen["verify"] = verify
        assert selectors == ["upstox:U1"]
        return {"upstox:U1": "ok"}

    fake_app = SimpleNamespace(
        config={
            "NATIVE_ADAPTERS": {"upstox": object()},
            "REGISTRY": object(),
            "CREDENTIAL_STORE": object(),
        }
    )
    monkeypatch.setattr(app_module, "_read_workspace_brokers", lambda: {"registered": ["upstox:U1"]})
    monkeypatch.setattr("flinttrade_gateway.native_login.establish_native_sessions", fake_establish)

    assert app_module._reestablish_native_sessions(fake_app) == {"upstox:U1": "ok"}
    assert seen == {"verify": True}
    assert fake_app.config["NATIVE_SESSION_STATUS"] == {"upstox:U1": "ok"}
