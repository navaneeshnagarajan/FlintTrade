from __future__ import annotations

import importlib.util
from pathlib import Path

import logging

import pytest

from flinttrade_gateway.log_safety import account_ref, selector_ref
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



_fixture_spec = importlib.util.spec_from_file_location("_registry_fixtures", Path(__file__).resolve().parents[4] / "tests" / "registry_fixtures.py")
_fixture_module = importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture_module)
RegistryFixture = _fixture_module.RegistryFixture


def test_registry_exact_mutations_emit_no_payload_logs(tmp_path, caplog):
    from flinttrade_core.broker_identity import BrokerSelector
    from flinttrade_gateway.brokers._base import Session
    fixture = RegistryFixture(tmp_path)
    selector = BrokerSelector("upstox", "UPX-PRIVATE-ACCOUNT-12345")
    with caplog.at_level(logging.INFO, logger="flinttrade.gateway.registry"):
        fixture.publish(selector.adapter_id, selector.account_id, Session("secret", 4102444800.0, "raw", "upstox"))
        fixture.owner.remove_session_for_exact(selector, expected_registry=fixture.registry.snapshot_selector(selector))
    assert caplog.messages == []
    fixture.close()


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
