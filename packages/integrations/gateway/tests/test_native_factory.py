"""Tests for the native-adapter activation factory (dormant -> live bridge)."""

from __future__ import annotations

import pytest

from flinttrade_gateway.adapter import BROKER_CATALOG
from flinttrade_gateway.brokers._base import BrokerAdapter
from flinttrade_gateway.brokers.dhan import DhanAdapter
from flinttrade_gateway.brokers.groww import GrowwAdapter
from flinttrade_gateway.brokers.indmoney import IndMoneyAdapter
from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
from flinttrade_gateway.brokers.native_factory import (
    NATIVE_ADAPTER_CLASSES,
    SDK_PIN_BY_BROKER,
    build_native_adapters,
    is_native_broker,
)
from flinttrade_gateway.brokers.upstox import UpstoxAdapter

pytestmark = pytest.mark.unit

_ALL_OK = {"dhan", "upstox", "kotakneo", "indmoney", "groww"}


def test_catalog_covers_native_adapters():
    native_catalogue_ids = {broker_id for broker_id, info in BROKER_CATALOG.items() if info.native}
    assert native_catalogue_ids == _ALL_OK
    assert set(NATIVE_ADAPTER_CLASSES) == _ALL_OK
    assert set(SDK_PIN_BY_BROKER) == native_catalogue_ids
    assert NATIVE_ADAPTER_CLASSES["dhan"] is DhanAdapter
    assert NATIVE_ADAPTER_CLASSES["upstox"] is UpstoxAdapter
    assert NATIVE_ADAPTER_CLASSES["kotakneo"] is KotakNeoAdapter
    assert NATIVE_ADAPTER_CLASSES["indmoney"] is IndMoneyAdapter
    assert NATIVE_ADAPTER_CLASSES["groww"] is GrowwAdapter


def test_sdk_pins_are_derived_from_broker_catalogue():
    """Native SDK attestation pins must have one catalogue source of truth."""
    expected = {
        broker_id: info.sdk_pin
        for broker_id, info in BROKER_CATALOG.items()
        if info.native
    }
    assert SDK_PIN_BY_BROKER == expected


def test_rest_only_native_declares_no_sdk_pin():
    """REST-only natives have no third-party SDK pin.

    IndMoney sets its pin to ``None``, which ``attest_ok`` treats as trivially
    attested — credentials remain the only activation gate. Groww now has the
    official SDK installed for attestation/parity, even though the adapter still
    uses FlintTrade's REST transport.
    """
    assert BROKER_CATALOG["indmoney"].sdk_pin is None
    assert SDK_PIN_BY_BROKER["indmoney"] is None
    assert BROKER_CATALOG["dhan"].sdk_pin == "dhanhq"
    assert SDK_PIN_BY_BROKER["dhan"] == "dhanhq"
    assert BROKER_CATALOG["groww"].sdk_pin == "growwapi"
    assert SDK_PIN_BY_BROKER["groww"] == "growwapi"


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


def test_coming_soon_natives_never_activate_from_factory():
    skips: list[tuple[str, str]] = []
    out = build_native_adapters(
        ["kotakneo", "groww"],
        attest_ok=lambda _b: True,
        has_credentials=lambda _b: True,
        on_skip=lambda b, why: skips.append((b, why)),
    )

    assert out == {}
    assert skips == [
        ("kotakneo", "coming-soon-not-live-verified"),
        ("groww", "coming-soon-not-live-verified"),
    ]


@pytest.mark.parametrize(
    "broker_id, kwarg_name, cls",
    [
        ("dhan", "security_resolver", DhanAdapter),
        ("upstox", "instrument_resolver", UpstoxAdapter),
    ],
)
def test_adapter_kwargs_passed_through_per_broker(broker_id, kwarg_name, cls):
    # Each native takes a DIFFERENTLY-named resolver kwarg; a rename here must
    # fail the test rather than silently produce an unresolvable adapter.
    seen = {}

    def kwargs(bid: str) -> dict:
        seen[bid] = True
        return {kwarg_name: lambda s, e: "TOKEN"}

    out = build_native_adapters(
        [broker_id],
        attest_ok=lambda _b: True,
        has_credentials=lambda _b: True,
        adapter_kwargs=kwargs,
    )
    assert isinstance(out[broker_id], cls)
    assert seen == {broker_id: True}


def test_adapter_kwargs_wrong_key_raises_typeerror():
    # A wrong kwarg for an adapter surfaces a clear TypeError (keyword-only,
    # no **kwargs catch-all) rather than silently dropping the adapter.
    with pytest.raises(TypeError):
        build_native_adapters(
            ["upstox"],
            attest_ok=lambda _b: True,
            has_credentials=lambda _b: True,
            adapter_kwargs=lambda _b: {"security_resolver": lambda s, e: "x"},  # wrong for Upstox
        )


def test_duplicate_ids_constructed_once():
    out = build_native_adapters(
        ["dhan", "dhan"],
        attest_ok=lambda _b: True,
        has_credentials=lambda _b: True,
    )
    assert set(out) == {"dhan"}
