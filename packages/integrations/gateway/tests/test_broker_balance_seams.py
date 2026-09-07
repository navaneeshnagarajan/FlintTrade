"""Evidence-preserving balance seams for the five native adapters."""

from __future__ import annotations

import asyncio
import time

import pytest

from flinttrade_core.broker_read_port import BalanceEvidence, LotSizeRequest
from flinttrade_gateway.brokers._base import Session


class _BalanceHookTrap:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def _called(self, name: str):
        self.calls.append(name)
        raise AssertionError(f"balance primitive hook executed: {name}")

    def __bool__(self):
        return self._called("bool")

    def __eq__(self, _other):
        return self._called("eq")

    def __float__(self):
        return self._called("float")

    def __hash__(self):
        return self._called("hash")

    def __iter__(self):
        return self._called("iter")

    def __str__(self):
        return self._called("str")


class _CollidingBalanceKey:
    def __init__(self, target: str) -> None:
        self.target = target
        self.calls: list[str] = []

    def __hash__(self) -> int:
        self.calls.append("hash")
        return hash(self.target)

    def __eq__(self, _other: object) -> bool:
        self.calls.append("eq")
        raise AssertionError("balance mapping key comparison executed")


def test_native_balance_converters_preserve_exact_direct_and_derived_evidence() -> None:
    from flinttrade_gateway.brokers.dhan import _balance_snapshot_from_dhan
    from flinttrade_gateway.brokers.groww import _balance_snapshot_from_groww
    from flinttrade_gateway.brokers.indmoney import _balance_snapshot_from_indmoney
    from flinttrade_gateway.brokers.kotakneo import _balance_snapshot_from_kotak
    from flinttrade_gateway.brokers.upstox import _balance_snapshot_from_upstox

    dhan = _balance_snapshot_from_dhan({"data": {"availabelBalance": "100", "utilizedAmount": "20", "sodLimit": "125"}})
    assert (dhan.total_balance, dhan.opening_risk_capital) == (125.0, 125.0)
    assert dhan.total_balance_evidence is BalanceEvidence.DIRECT

    upstox = _balance_snapshot_from_upstox({
        "data": {"available_to_trade": {
            "total": "100", "cash_available_to_trade": {"margin_used": {"total": "10"}, "cash": {"opening_balance": "125"}},
            "pledge_available_to_trade": {"margin_used": {"total": "5"}},
        }}
    })
    assert (upstox.used_margin, upstox.total_balance) == (15.0, 115.0)
    assert upstox.used_margin_evidence is BalanceEvidence.DERIVED_FROM_DIRECT_COMPONENTS

    groww = _balance_snapshot_from_groww({"clear_cash": "100", "net_margin_used": "20", "collateral_available": "30"})
    assert (groww.total_balance, groww.opening_risk_capital) == (130.0, None)

    indmoney = _balance_snapshot_from_indmoney({"withdrawal_balance": "80", "sod_balance": "100"})
    assert (indmoney.available_balance, indmoney.used_margin, indmoney.total_balance) == (80.0, 20.0, 100.0)
    assert indmoney.opening_risk_capital is None

    kotak = _balance_snapshot_from_kotak({"Net": "100", "MarginUsed": "20", "CollateralValue": "999"})
    assert kotak.total_balance == 120.0
    assert kotak.total_balance_evidence is BalanceEvidence.DERIVED_FROM_DIRECT_COMPONENTS


@pytest.mark.parametrize(
    ("module_name", "function_name", "payload"),
    [
        ("dhan", "_balance_snapshot_from_dhan", {"data": {"availabelBalance": "", "availableBalance": "100"}}),
        ("upstox", "_balance_snapshot_from_upstox", {"data": {"available_to_trade": {"total": True}}}),
        (
            "upstox",
            "_balance_snapshot_from_upstox",
            {"data": {"available_to_trade": {"cash_available_to_trade": {"margin_used": {"total": False}}}}},
        ),
        ("groww", "_balance_snapshot_from_groww", {"clear_cash": "NaN"}),
        ("indmoney", "_balance_snapshot_from_indmoney", {"withdrawal_balance": object()}),
        ("kotakneo", "_balance_snapshot_from_kotak", {"Net": "", "avlCash": "100"}),
    ],
)
def test_native_balance_converters_refuse_selected_malformed_values(module_name, function_name, payload) -> None:
    module = __import__(f"flinttrade_gateway.brokers.{module_name}", fromlist=[function_name])
    with pytest.raises(ValueError, match="broker_balance_response_invalid"):
        getattr(module, function_name)(payload)


@pytest.mark.parametrize(
    (
        "module_name",
        "function_name",
        "empty_payload",
        "zero_payload",
        "zero_values",
        "zero_evidence",
    ),
    [
        (
            "dhan",
            "_balance_snapshot_from_dhan",
            {"data": {}},
            {
                "data": {
                    "availabelBalance": 0,
                    "availableBalance": 100,
                    "utilizedAmount": 0,
                    "sodLimit": 0,
                }
            },
            (0.0, 0.0, 0.0, 0.0),
            (BalanceEvidence.DIRECT,) * 4,
        ),
        (
            "upstox",
            "_balance_snapshot_from_upstox",
            {"data": {"equity": {}}},
            {"data": {"equity": {"available_margin": 0, "used_margin": 0}}},
            (0.0, 0.0, 0.0, None),
            (
                BalanceEvidence.DIRECT,
                BalanceEvidence.DIRECT,
                BalanceEvidence.DERIVED_FROM_DIRECT_COMPONENTS,
                None,
            ),
        ),
        (
            "groww",
            "_balance_snapshot_from_groww",
            {},
            {"clear_cash": 0, "net_margin_used": 0, "collateral_available": 0},
            (0.0, 0.0, 0.0, None),
            (
                BalanceEvidence.DIRECT,
                BalanceEvidence.DIRECT,
                BalanceEvidence.DERIVED_FROM_DIRECT_COMPONENTS,
                None,
            ),
        ),
        (
            "indmoney",
            "_balance_snapshot_from_indmoney",
            {},
            {"withdrawal_balance": 0, "sod_balance": 0},
            (0.0, 0.0, 0.0, None),
            (
                BalanceEvidence.DIRECT,
                BalanceEvidence.DERIVED_FROM_DIRECT_COMPONENTS,
                BalanceEvidence.DIRECT,
                None,
            ),
        ),
        (
            "kotakneo",
            "_balance_snapshot_from_kotak",
            {},
            {"Net": 0, "avlCash": 100, "MarginUsed": 0},
            (0.0, 0.0, 0.0, None),
            (
                BalanceEvidence.DIRECT,
                BalanceEvidence.DIRECT,
                BalanceEvidence.DERIVED_FROM_DIRECT_COMPONENTS,
                None,
            ),
        ),
    ],
)
def test_native_balance_absence_zero_and_primary_precedence(
    module_name,
    function_name,
    empty_payload,
    zero_payload,
    zero_values,
    zero_evidence,
) -> None:
    module = __import__(f"flinttrade_gateway.brokers.{module_name}", fromlist=[function_name])
    converter = getattr(module, function_name)

    empty = converter(empty_payload)
    assert (
        empty.available_balance,
        empty.used_margin,
        empty.total_balance,
        empty.opening_risk_capital,
    ) == (None, None, None, None)
    assert (
        empty.available_balance_evidence,
        empty.used_margin_evidence,
        empty.total_balance_evidence,
        empty.opening_risk_capital_evidence,
    ) == (None, None, None, None)

    zero = converter(zero_payload)
    assert (
        zero.available_balance,
        zero.used_margin,
        zero.total_balance,
        zero.opening_risk_capital,
    ) == zero_values
    assert (
        zero.available_balance_evidence,
        zero.used_margin_evidence,
        zero.total_balance_evidence,
        zero.opening_risk_capital_evidence,
    ) == zero_evidence


@pytest.mark.parametrize(
    ("module_name", "function_name", "payload", "expected"),
    [
        ("dhan", "_balance_snapshot_from_dhan", {"data": {"availabelBalance": 10}}, (10.0, None, None, None)),
        (
            "upstox",
            "_balance_snapshot_from_upstox",
            {
                "data": {
                    "available_to_trade": {
                        "total": 10,
                        "cash_available_to_trade": {"margin_used": {"total": 1}},
                    }
                }
            },
            (10.0, None, None, None),
        ),
        ("groww", "_balance_snapshot_from_groww", {"clear_cash": 10}, (10.0, None, None, None)),
        ("indmoney", "_balance_snapshot_from_indmoney", {"sod_balance": 10}, (None, None, 10.0, None)),
        ("kotakneo", "_balance_snapshot_from_kotak", {"Net": 10}, (10.0, None, None, None)),
    ],
)
def test_native_balance_partial_components_never_manufacture_derivations(
    module_name,
    function_name,
    payload,
    expected,
) -> None:
    module = __import__(f"flinttrade_gateway.brokers.{module_name}", fromlist=[function_name])

    snapshot = getattr(module, function_name)(payload)

    assert (
        snapshot.available_balance,
        snapshot.used_margin,
        snapshot.total_balance,
        snapshot.opening_risk_capital,
    ) == expected


@pytest.mark.parametrize(
    ("module_name", "function_name", "payload"),
    [
        ("dhan", "_balance_snapshot_from_dhan", {"data": {"availabelBalance": True}}),
        ("dhan", "_balance_snapshot_from_dhan", {"data": {"utilizedAmount": float("inf")}}),
        ("upstox", "_balance_snapshot_from_upstox", {"data": {"equity": {"available_margin": True}}}),
        (
            "upstox",
            "_balance_snapshot_from_upstox",
            {"data": {"equity": {"used_margin": float("nan")}}},
        ),
        ("groww", "_balance_snapshot_from_groww", {"clear_cash": False}),
        ("groww", "_balance_snapshot_from_groww", {"net_margin_used": float("inf")}),
        ("indmoney", "_balance_snapshot_from_indmoney", {"withdrawal_balance": True}),
        ("indmoney", "_balance_snapshot_from_indmoney", {"sod_balance": float("nan")}),
        ("kotakneo", "_balance_snapshot_from_kotak", {"Net": False}),
        ("kotakneo", "_balance_snapshot_from_kotak", {"MarginUsed": float("inf")}),
    ],
)
def test_each_native_balance_rejects_booleans_and_nonfinite_numbers(module_name, function_name, payload) -> None:
    module = __import__(f"flinttrade_gateway.brokers.{module_name}", fromlist=[function_name])

    with pytest.raises(ValueError, match="broker_balance_response_invalid"):
        getattr(module, function_name)(payload)


@pytest.mark.parametrize(
    ("available_field", "used_field"),
    [
        ("Net", "MarginUsed"),
        ("avlCash", "totMrgnUsd"),
        ("avlMrgn", "mrgnUsd"),
    ],
)
def test_kotak_balance_every_alias_arm_has_direct_evidence(available_field, used_field) -> None:
    from flinttrade_gateway.brokers.kotakneo import _balance_snapshot_from_kotak

    snapshot = _balance_snapshot_from_kotak({available_field: 10, used_field: 2})

    assert (snapshot.available_balance, snapshot.used_margin, snapshot.total_balance) == (10.0, 2.0, 12.0)
    assert (
        snapshot.available_balance_evidence,
        snapshot.used_margin_evidence,
        snapshot.total_balance_evidence,
    ) == (
        BalanceEvidence.DIRECT,
        BalanceEvidence.DIRECT,
        BalanceEvidence.DERIVED_FROM_DIRECT_COMPONENTS,
    )


@pytest.mark.parametrize(
    ("module_name", "function_name", "payload"),
    [
        ("dhan", "_balance_snapshot_from_dhan", lambda trap: {"data": {"availabelBalance": trap}}),
        (
            "upstox",
            "_balance_snapshot_from_upstox",
            lambda trap: {"data": {"equity": {"available_margin": trap}}},
        ),
        ("groww", "_balance_snapshot_from_groww", lambda trap: {"clear_cash": trap}),
        ("indmoney", "_balance_snapshot_from_indmoney", lambda trap: {"withdrawal_balance": trap}),
        ("kotakneo", "_balance_snapshot_from_kotak", lambda trap: {"Net": trap}),
    ],
)
def test_native_balance_hook_objects_are_rejected_without_execution(module_name, function_name, payload) -> None:
    module = __import__(f"flinttrade_gateway.brokers.{module_name}", fromlist=[function_name])
    trap = _BalanceHookTrap()

    with pytest.raises(ValueError, match="broker_balance_response_invalid"):
        getattr(module, function_name)(payload(trap))

    assert trap.calls == []


def test_dhan_balance_rejects_dict_subclasses_before_mapping_hooks() -> None:
    from flinttrade_gateway.brokers.dhan import _balance_snapshot_from_dhan

    calls: list[str] = []

    class DictTrap(dict):
        def get(self, *_args, **_kwargs):
            calls.append("get")
            raise AssertionError("get executed")

        def __contains__(self, _key):
            calls.append("contains")
            raise AssertionError("contains executed")

        def __getitem__(self, _key):
            calls.append("getitem")
            raise AssertionError("getitem executed")

    with pytest.raises(ValueError, match="broker_balance_response_invalid"):
        _balance_snapshot_from_dhan(DictTrap())

    assert calls == []


@pytest.mark.parametrize(
    ("module_name", "function_name", "target", "payload"),
    [
        ("dhan", "_balance_snapshot_from_dhan", "status", lambda key: {key: 0}),
        ("dhan", "_balance_snapshot_from_dhan", "availabelBalance", lambda key: {"data": {key: 0}}),
        ("upstox", "_balance_snapshot_from_upstox", "data", lambda key: {key: 0}),
        ("upstox", "_balance_snapshot_from_upstox", "available_to_trade", lambda key: {"data": {key: 0}}),
        (
            "upstox",
            "_balance_snapshot_from_upstox",
            "total",
            lambda key: {"data": {"available_to_trade": {key: 0}}},
        ),
        (
            "upstox",
            "_balance_snapshot_from_upstox",
            "margin_used",
            lambda key: {"data": {"available_to_trade": {"cash_available_to_trade": {key: 0}}}},
        ),
        (
            "upstox",
            "_balance_snapshot_from_upstox",
            "margin_used",
            lambda key: {"data": {"available_to_trade": {"pledge_available_to_trade": {key: 0}}}},
        ),
        (
            "upstox",
            "_balance_snapshot_from_upstox",
            "total",
            lambda key: {
                "data": {"available_to_trade": {"cash_available_to_trade": {"margin_used": {key: 0}}}}
            },
        ),
        (
            "upstox",
            "_balance_snapshot_from_upstox",
            "total",
            lambda key: {
                "data": {"available_to_trade": {"pledge_available_to_trade": {"margin_used": {key: 0}}}}
            },
        ),
        (
            "upstox",
            "_balance_snapshot_from_upstox",
            "opening_balance",
            lambda key: {"data": {"available_to_trade": {"cash_available_to_trade": {"cash": {key: 0}}}}},
        ),
        (
            "upstox",
            "_balance_snapshot_from_upstox",
            "available_margin",
            lambda key: {"data": {"equity": {key: 0}}},
        ),
        ("groww", "_balance_snapshot_from_groww", "clear_cash", lambda key: {key: 0}),
        ("indmoney", "_balance_snapshot_from_indmoney", "withdrawal_balance", lambda key: {key: 0}),
        ("kotakneo", "_balance_snapshot_from_kotak", "data", lambda key: {key: 0}),
        ("kotakneo", "_balance_snapshot_from_kotak", "Net", lambda key: {"data": {key: 0}}),
    ],
)
def test_every_native_balance_map_rejects_non_string_keys_without_comparison_hooks(
    module_name,
    function_name,
    target,
    payload,
) -> None:
    module = __import__(f"flinttrade_gateway.brokers.{module_name}", fromlist=[function_name])
    trap = _CollidingBalanceKey(target)
    response = payload(trap)
    trap.calls.clear()

    with pytest.raises(ValueError, match="broker_balance_response_invalid"):
        getattr(module, function_name)(response)

    assert trap.calls == []


@pytest.mark.parametrize(
    ("module_name", "function_name", "payload"),
    [
        (
            "upstox",
            "_balance_snapshot_from_upstox",
            {"data": {"equity": {"available_margin": 1e308, "used_margin": 1e308}}},
        ),
        ("groww", "_balance_snapshot_from_groww", {"clear_cash": 1e308, "collateral_available": 1e308}),
        ("indmoney", "_balance_snapshot_from_indmoney", {"withdrawal_balance": -1e308, "sod_balance": 1e308}),
        ("kotakneo", "_balance_snapshot_from_kotak", {"Net": 1e308, "MarginUsed": 1e308}),
    ],
)
def test_native_balance_rejects_post_arithmetic_overflow(module_name, function_name, payload) -> None:
    module = __import__(f"flinttrade_gateway.brokers.{module_name}", fromlist=[function_name])

    with pytest.raises(ValueError, match="broker_balance_response_invalid"):
        getattr(module, function_name)(payload)


def test_native_balance_methods_call_the_existing_endpoint_once() -> None:
    from flinttrade_gateway.brokers.dhan import DhanAdapter
    from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
    from flinttrade_gateway.brokers.upstox import UpstoxAdapter

    class Client:
        def __init__(self, method: str, payload: object) -> None:
            self.calls = 0
            setattr(self, method, self.call)
            self.payload = payload

        def call(self):
            self.calls += 1
            return self.payload

    session = Session("synthetic", time.time() + 3600, "Synthetic", "synthetic")
    cases = (
        (DhanAdapter, "get_fund_limits", {"data": {"availabelBalance": "100"}}),
        (UpstoxAdapter, "funds", {"data": {"equity": {"available_margin": "100", "used_margin": "20"}}}),
        (KotakNeoAdapter, "funds", {"Net": "100", "MarginUsed": "20"}),
    )
    for adapter_type, method, payload in cases:
        client = Client(method, payload)
        adapter = adapter_type(client_factory=lambda _session, client=client: client)
        asyncio.run(adapter.balance_snapshot(session))
        assert client.calls == 1


def test_rest_native_balance_methods_call_the_existing_endpoint_once() -> None:
    from flinttrade_gateway.brokers.groww import GrowwAdapter
    from flinttrade_gateway.brokers.indmoney import IndMoneyAdapter

    class Transport:
        def __init__(self, payload: object) -> None:
            self.calls = 0
            self.payload = payload

        def __call__(self, *args, **kwargs):
            self.calls += 1
            return 200, self.payload

    session = Session("synthetic", time.time() + 3600, "Synthetic", "synthetic")
    cases = (
        (GrowwAdapter, {"status": "SUCCESS", "payload": {"clear_cash": "100"}}),
        (IndMoneyAdapter, {"status": "success", "data": {"withdrawal_balance": "100"}}),
    )
    for adapter_type, payload in cases:
        transport = Transport(payload)
        adapter = adapter_type(http_factory=lambda transport=transport: transport)
        asyncio.run(adapter.balance_snapshot(session))
        assert transport.calls == 1


def test_groww_and_indmoney_lot_size_wrappers_use_only_existing_instrument_rows(monkeypatch) -> None:
    from flinttrade_gateway.brokers.groww import GrowwAdapter
    from flinttrade_gateway.brokers.indmoney import IndMoneyAdapter

    session = Session("synthetic", time.time() + 3600, "Synthetic", "synthetic")
    groww = GrowwAdapter(http_factory=lambda: None)
    indmoney = IndMoneyAdapter(http_factory=lambda: None)
    calls = []

    async def groww_rows(_session):
        calls.append("groww")
        return [{"trading_symbol": "NIFTY", "exchange": "NSE", "lot_size": "75", "instrument_token": "1"}]

    async def indmoney_rows(_session, source):
        calls.append(("indmoney", source))
        return [
            {"TRADING_SYMBOL": "NIFTY", "EXCH": "NSE", "SEGMENT": "E", "LOT_UNITS": "75", "SECURITY_ID": "2"}
        ]

    monkeypatch.setattr(groww, "_strict_lot_size_instruments", groww_rows)
    monkeypatch.setattr(indmoney, "_strict_instruments", indmoney_rows)
    request = LotSizeRequest("NSE", ("NIFTY",))
    assert asyncio.run(groww.instrument_lot_sizes(session, request))[0]["instrument_id"] == "1"
    assert asyncio.run(indmoney.instrument_lot_sizes(session, request))[0]["instrument_id"] == "2"
    assert calls == ["groww", ("indmoney", "equity")]
