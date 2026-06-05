"""Tests for the native-adapter activation factory (dormant -> live bridge)."""

from __future__ import annotations

import pytest

from flinttrade_gateway.brokers._base import BrokerAdapter
from flinttrade_gateway.brokers.dhan import DhanAdapter
from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
from flinttrade_gateway.brokers.native_factory import (
    NATIVE_ADAPTER_CLASSES,
    SDK_PIN_BY_BROKER,
    build_native_adapters,
    is_native_broker,
)
from flinttrade_gateway.brokers.upstox import UpstoxAdapter

pytestmark = pytest.mark.unit

_ALL_OK = {"dhan", "upstox", "kotakneo"}


def test_catalog_covers_three_natives():
    assert set(NATIVE_ADAPTER_CLASSES) == _ALL_OK
    assert set(SDK_PIN_BY_BROKER) == _ALL_OK
    assert NATIVE_ADAPTER_CLASSES["dhan"] is DhanAdapter
    assert NATIVE_ADAPTER_CLASSES["upstox"] is UpstoxAdapter
    assert NATIVE_ADAPTER_CLASSES["kotakneo"] is KotakNeoAdapter


def test_is_native_broker():
    assert is_native_broker("dhan") and is_native_broker("kotakneo")
    assert not is_native_broker("openalgo")


def test_nothing_activates_when_unattested():
    # Default no-SDK environment: attest_ok always False → empty (dormant).
    out = build_native_adapters(
        ["dhan", "upstox", "kotakneo"],
        attest_ok=lambda _b: False,
        has_credentials=lambda _b: True,
    )
    assert out == {}


def test_nothing_activates_without_credentials():
    out = build_native_adapters(
        ["dhan", "upstox"],
        attest_ok=lambda _b: True,
        has_credentials=lambda _b: False,
    )
    assert out == {}


def test_activates_only_brokers_passing_both_gates():
    out = build_native_adapters(
        ["dhan", "upstox", "kotakneo", "openalgo"],
        attest_ok=lambda b: b in {"dhan", "kotakneo"},
        has_credentials=lambda b: b in {"dhan", "upstox"},
    )
    # dhan: attested + credentialled → activated. upstox: no attest. kotakneo: no creds.
    assert set(out) == {"dhan"}
    assert isinstance(out["dhan"], BrokerAdapter)


def test_openalgo_and_unknown_ids_never_construct():
    out = build_native_adapters(
        ["openalgo", "zerodha"],
        attest_ok=lambda _b: True,
        has_credentials=lambda _b: True,
    )
    assert out == {}


def test_skip_reasons_reported():
    skips: list[tuple[str, str]] = []
    build_native_adapters(
        ["dhan", "upstox"],
        attest_ok=lambda b: b == "dhan",
        has_credentials=lambda _b: False,
        on_skip=lambda b, why: skips.append((b, why)),
    )
    # dhan attested but no creds; upstox not attested → reported first.
    assert ("dhan", "no-credentials") in skips
    assert ("upstox", "sdk-not-attested") in skips


def test_adapter_kwargs_passed_through():
    resolver_called = {}

    def kwargs(broker_id: str) -> dict:
        resolver_called[broker_id] = True
        return {"security_resolver": lambda s, e: "1"} if broker_id == "dhan" else {}

    out = build_native_adapters(
        ["dhan"],
        attest_ok=lambda _b: True,
        has_credentials=lambda _b: True,
        adapter_kwargs=kwargs,
    )
    assert isinstance(out["dhan"], DhanAdapter)
    assert resolver_called == {"dhan": True}


def test_duplicate_ids_constructed_once():
    out = build_native_adapters(
        ["dhan", "dhan"],
        attest_ok=lambda _b: True,
        has_credentials=lambda _b: True,
    )
    assert set(out) == {"dhan"}
