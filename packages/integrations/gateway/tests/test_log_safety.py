from __future__ import annotations

import logging

import pytest

from flinttrade_gateway.log_safety import account_ref, selector_ref
from flinttrade_gateway.registry import BrokerRegistry
from flinttrade_gateway.session import BrokerSession
from flinttrade_gateway.ticker import BrokerTicker


def test_account_log_refs_are_stable_and_non_reversible() -> None:
    raw = "UPX-PRIVATE-ACCOUNT-12345"

    first = account_ref(raw)
    second = account_ref(raw)

    assert first == second
    assert first.startswith("account#")
    assert raw not in first
    assert selector_ref("upstox", raw) == f"upstox:{first}"


def test_registry_logs_selector_without_raw_account_id(caplog: pytest.LogCaptureFixture) -> None:
    registry = BrokerRegistry()
    raw_account = "UPX-PRIVATE-ACCOUNT-12345"

    with caplog.at_level(logging.INFO, logger="flinttrade.gateway.registry"):
        registry.put_session("upstox", raw_account, object())
        registry.remove_session_for("upstox", raw_account)

    logs = "\n".join(caplog.messages)
    assert raw_account not in logs
    assert "upstox:account#" in logs
    assert "Session registered for selector" in logs
    assert "Session evicted for selector" in logs


def test_broker_session_logs_without_raw_account_id(monkeypatch, caplog: pytest.LogCaptureFixture) -> None:
    class FakeAdapter:
        def authenticate(self, _credentials):  # type: ignore[no-untyped-def]
            return "token", None

    raw_account = "DHAN-PRIVATE-ACCOUNT-12345"
    monkeypatch.setattr("flinttrade_gateway.session.load_broker_adapter", lambda _broker: FakeAdapter())
    session = BrokerSession(raw_account, "dhan", "Private label")

    with caplog.at_level(logging.INFO, logger="flinttrade.gateway.session"):
        session.authenticate({"access_token": "secret"})
        session.disconnect()

    logs = "\n".join(caplog.messages)
    assert raw_account not in logs
    assert "Private label" not in logs
    assert "account#" in logs


def test_ticker_logs_without_raw_account_id(caplog: pytest.LogCaptureFixture) -> None:
    raw_account = "TICK-PRIVATE-ACCOUNT-12345"
    ticker = BrokerTicker(raw_account, object())

    with caplog.at_level(logging.WARNING, logger="flinttrade.gateway.ticker"):
        ticker.on_disconnect()

    logs = "\n".join(caplog.messages)
    assert raw_account not in logs
    assert "account#" in logs

