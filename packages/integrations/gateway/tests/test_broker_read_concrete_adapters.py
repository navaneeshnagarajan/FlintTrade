"""Strict broker-read projections through real adapters and the real owner."""

from __future__ import annotations

import copy
import csv
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from flinttrade_core.broker_identity import BrokerSelector, CredentialVersion
from flinttrade_core.broker_read_port import (
    BatchQuoteRequest,
    BrokerLotSizeResponseInvalid,
    BrokerOrderFamily,
    BrokerReadErrorCode,
    BrokerReadFailure,
    BrokerReadResponseInvalid,
    BrokerReadSuccess,
    ExactReadTarget,
    HistoricalRequest,
    InstrumentRef,
    LotSizeRequest,
    MarginRequest,
    OrderStateRequest,
    PortfolioGreeksRequest,
    PortfolioPositionRef,
    QuoteRequest,
)
from flinttrade_core.secure_file import harden_directory
from flinttrade_core.workspace_migrations import (
    broker_workspace_version,
    compare_and_swap_workspace,
    read_workspace_snapshot,
)
from flinttrade_engine.request_context import RequestContext
from flinttrade_gateway import registry as registry_api
from flinttrade_gateway.broker_read_service import create_broker_read_owner
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.dhan import DhanAdapter
from flinttrade_gateway.brokers.dhan_mapping import build_security_resolver
from flinttrade_gateway.brokers.groww import GrowwAdapter
from flinttrade_gateway.brokers.groww_mapping import BASE_URL as GROWW_BASE_URL
from flinttrade_gateway.brokers.groww_mapping import from_trade as from_groww_trade
from flinttrade_gateway.brokers.indmoney import IndMoneyAdapter
from flinttrade_gateway.brokers.indmoney_mapping import BASE_URL as INDMONEY_BASE_URL
from flinttrade_gateway.brokers.indmoney_mapping import to_epoch_ms as indmoney_epoch_ms
from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
from flinttrade_gateway.brokers.upstox import UpstoxAdapter
from flinttrade_gateway.session_provider import AuthenticatingSessionProvider

pytestmark = pytest.mark.unit

GROWW_INSTRUMENTS_URL = "https://growwapi-assets.groww.in/instruments/instrument.csv"


class _Limiter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def acquire(self, adapter_id: str, kind: str) -> None:
        self.calls.append((adapter_id, kind))


@dataclass
class _BoundAdapter:
    owner: Any
    port: Any
    limiter: _Limiter
    registry_owner: Any
    registry: Any
    selector: BrokerSelector
    workspace_path: Path
    authority_context: list[RequestContext | None]
    verifier_calls: list[str]


@pytest.fixture
def bind_adapter(tmp_path: Path):
    bound: list[_BoundAdapter] = []

    def bind(adapter_id: str, adapter: object, client: object) -> _BoundAdapter:
        workspace_path = tmp_path / f"workspace-{adapter_id}-{len(bound)}"
        workspace_path.mkdir()
        harden_directory(workspace_path)
        selector = BrokerSelector(adapter_id, "Synthetic")

        def initialise(config: dict[str, Any]) -> None:
            config["brokers"]["account_acls"] = {adapter_id: {"Synthetic": ["actor"]}}
            config["brokers"]["data"].update(
                {
                    "quote": f"{adapter_id}:Synthetic",
                    "historical": f"{adapter_id}:Synthetic",
                    "option_chains": f"{adapter_id}:Synthetic",
                    "global_indices": f"{adapter_id}:Synthetic",
                }
            )

        workspace = compare_and_swap_workspace(workspace_path, None, initialise)
        credential = CredentialVersion(selector, uuid4(), 1)
        authority = registry_api.ManagedSessionAuthority(
            credential,
            workspace.version,
            broker_workspace_version(workspace),
        )
        registry, registry_owner = registry_api.create_owned_registry()
        session = Session("synthetic-token", time.time() + 3600, "Synthetic", adapter_id)
        registered_client = object() if callable(client) else client
        receipt = registry_owner.prepare_session_candidate(
            selector,
            session,
            expected_registry=registry.snapshot_selector(selector),
            authority=authority,
            broker=adapter_id,
            label="Synthetic",
            client=registered_client,
        )
        registry_owner.publish_prepared_candidate(receipt, current_authority=authority)
        provider = AuthenticatingSessionProvider(
            registry,
            {adapter_id: {"Synthetic": ["actor"]}},
            workspace_snapshot=workspace,
            workspace_path=workspace_path,
            credential_version_for=lambda target: credential if target == selector else None,
        )
        limiter = _Limiter()
        owner = create_broker_read_owner(
            registry=registry,
            session_provider=provider,
            adapters={adapter_id: adapter},
            workspace_path=workspace_path,
            rate_limiter=limiter,
            runtime_accepting_requests=lambda: True,
        )
        context = RequestContext(
            "jti",
            "human",
            "actor",
            "practice",
            selector=f"{adapter_id}:Synthetic",
        )
        authority_context: list[RequestContext | None] = [context]
        verifier_calls: list[str] = []

        def verify_current_authority() -> RequestContext | None:
            verifier_calls.append("verify")
            return authority_context[0]

        port = owner.bind(
            target=ExactReadTarget(selector),
            verify_current_authority=verify_current_authority,
        )
        assert not isinstance(port, BrokerReadFailure)
        verifier_calls.clear()
        item = _BoundAdapter(
            owner,
            port,
            limiter,
            registry_owner,
            registry,
            selector,
            workspace_path,
            authority_context,
            verifier_calls,
        )
        bound.append(item)
        return item

    yield bind

    for item in bound:
        item.owner.close(timeout=1.0)


class _DhanHTTP:
    def __init__(self, client: _DhanClient) -> None:
        self._client = client

    def get(self, _path: str) -> object:
        return self._client._read("conditional")


class _DhanClient:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.responses: dict[str, object] = {}
        self.errors: set[str] = set()
        self.dhan_http = _DhanHTTP(self)

    def _read(self, name: str) -> object:
        self.calls.append(name)
        if name in self.errors:
            raise RuntimeError("synthetic Dhan SDK failure")
        return copy.deepcopy(self.responses[name])

    def get_order_list(self) -> object:
        return self._read("order_book")

    def get_trade_book(self) -> object:
        return self._read("trade_book")

    def get_positions(self) -> object:
        return self._read("positions")

    def get_holdings(self) -> object:
        return self._read("holdings")

    def get_forever(self) -> object:
        return self._read("forever")

    def get_super_order_list(self) -> object:
        return self._read("super")

    def option_chain(self, _security_id: str, _segment: str, _expiry: str) -> object:
        return self._read("option_chain")


def _dhan_rows(client: _DhanClient) -> None:
    client.responses.update({
        "positions": {"status": "success", "data": [{
            "tradingSymbol": "TCS",
            "securityId": "101",
            "exchangeSegment": "NSE_EQ",
            "productType": "CNC",
            "netQty": 0,
        }]},
        "holdings": {"status": "success", "data": [{
            "tradingSymbol": "TCS",
            "securityId": "101",
            "exchange": "NSE",
            "totalQty": 0,
        }]},
        "trade_book": {"status": "success", "data": [{
            "orderId": "DT1",
            "tradingSymbol": "TCS",
            "securityId": "101",
            "exchangeSegment": "NSE_EQ",
            "transactionType": "BUY",
            "productType": "CNC",
            "tradedQuantity": 0,
            "tradedPrice": 0,
            "exchangeTime": "2026-09-07T09:20:00+05:30",
        }]},
        "order_book": {"status": "success", "data": [{
            "orderId": "DO1",
            "orderStatus": "PENDING",
            "tradingSymbol": "TCS",
            "securityId": "101",
            "exchangeSegment": "NSE_EQ",
            "transactionType": "BUY",
            "orderType": "LIMIT",
            "productType": "CNC",
            "quantity": 1,
            "filledQty": 0,
            "price": 0,
        }]},
        "forever": {"status": "success", "data": []},
        "super": {"status": "success", "data": []},
        "conditional": {"status": "success", "data": []},
    })


def _dhan_forever_row() -> dict[str, object]:
    return {
        "orderId": "DF1",
        "orderStatus": "PENDING",
        "orderFlag": "SINGLE",
        "tradingSymbol": "TCS",
        "securityId": "101",
        "exchangeSegment": "NSE_EQ",
        "transactionType": "BUY",
        "orderType": "LIMIT",
        "productType": "CNC",
        "quantity": 1,
        "filledQty": 0,
        "price": 0,
        "triggerPrice": 0,
    }


def _dhan_super_row() -> dict[str, object]:
    return {
        "orderId": "DS1",
        "orderStatus": "PENDING",
        "tradingSymbol": "TCS",
        "securityId": "101",
        "exchangeSegment": "NSE_EQ",
        "transactionType": "BUY",
        "orderType": "LIMIT",
        "productType": "CNC",
        "quantity": 1,
        "filledQty": 0,
        "price": 0,
    }


async def _dhan_surface(bound: _BoundAdapter, surface: str):
    if surface == "positions":
        return await bound.port.positions()
    if surface == "holdings":
        return await bound.port.holdings()
    if surface == "trades":
        return await bound.port.trades()
    family = {
        "orders": BrokerOrderFamily.REGULAR,
        "forever": BrokerOrderFamily.FOREVER,
        "super": BrokerOrderFamily.SUPER,
    }[surface]
    return await bound.port.order_states(OrderStateRequest(family))


@pytest.mark.asyncio
async def test_dhan_supported_surfaces_preserve_zero_optional_absence_and_exact_ledgers(bind_adapter) -> None:
    client = _DhanClient()
    _dhan_rows(client)
    bound = bind_adapter("dhan", DhanAdapter(client_factory=lambda _session: client), client)

    for surface, expected in (
        ("positions", ["positions"]),
        ("holdings", ["holdings"]),
        ("trades", ["trade_book"]),
        ("orders", ["order_book", "forever", "super", "conditional"]),
    ):
        start = len(client.calls)
        outcome = await _dhan_surface(bound, surface)
        assert isinstance(outcome, BrokerReadSuccess)
        if surface == "orders":
            assert outcome.value[0].quantity == "1"
            assert outcome.value[0].filled_quantity == "0"
        else:
            assert outcome.value[0].quantity == "0"
        assert client.calls[start:] == expected
    assert (await bound.port.positions()).value[0].average_price is None
    assert (await bound.port.holdings()).value[0].average_price is None

    client.responses["forever"] = {"status": "success", "data": [_dhan_forever_row()]}
    start = len(client.calls)
    forever = await _dhan_surface(bound, "forever")
    assert isinstance(forever, BrokerReadSuccess)
    assert forever.value[0].quantity == "1"
    assert forever.value[0].filled_quantity == "0"
    assert client.calls[start:] == ["forever"]

    client.responses["super"] = {"status": "success", "data": [_dhan_super_row()]}
    start = len(client.calls)
    super_orders = await _dhan_surface(bound, "super")
    assert isinstance(super_orders, BrokerReadSuccess)
    assert super_orders.value[0].quantity == "1"
    assert super_orders.value[0].filled_quantity == "0"
    assert client.calls[start:] == ["super"]


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["regular", "forever", "super"])
async def test_dhan_safety_horizon_omits_absent_optional_order_numerics(bind_adapter, family: str) -> None:
    client = _DhanClient()
    _dhan_rows(client)
    client.responses["order_book"] = {"status": "success", "data": []}
    if family == "regular":
        row = _dhan_rows_for_safety_regular()
        row.pop("price")
        client.responses["order_book"] = {"status": "success", "data": [row]}
    elif family == "forever":
        row = _dhan_forever_row()
        for name in ("filledQty", "price", "triggerPrice"):
            row.pop(name)
        client.responses["forever"] = {"status": "success", "data": [row]}
    else:
        row = _dhan_super_row()
        row.pop("price")
        row["legDetails"] = [
            {"legName": "TARGET_LEG", "orderStatus": "PENDING", "quantity": 1, "filledQty": 0},
            {"legName": "STOP_LOSS_LEG", "orderStatus": "PENDING", "quantity": 1, "filledQty": 0},
        ]
        client.responses["super"] = {"status": "success", "data": [row]}
    bound = bind_adapter("dhan", DhanAdapter(client_factory=lambda _session: client), client)

    outcome = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR))

    assert isinstance(outcome, BrokerReadSuccess)
    assert outcome.value
    assert all(row.price is None and row.trigger_price is None for row in outcome.value)
    if family == "forever":
        assert outcome.value[0].filled_quantity is None
    assert client.calls == ["order_book", "forever", "super", "conditional"]


def _dhan_rows_for_safety_regular() -> dict[str, object]:
    return {
        "orderId": "DO1",
        "orderStatus": "PENDING",
        "tradingSymbol": "TCS",
        "securityId": "101",
        "exchangeSegment": "NSE_EQ",
        "transactionType": "BUY",
        "orderType": "LIMIT",
        "productType": "CNC",
        "quantity": 1,
        "filledQty": 0,
        "price": 0,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["regular", "forever", "super"])
async def test_dhan_terminal_safety_rows_do_not_fabricate_optional_numerics(bind_adapter, family: str) -> None:
    client = _DhanClient()
    _dhan_rows(client)
    client.responses["order_book"] = {"status": "success", "data": []}
    terminal = {"orderId": f"{family}-done", "orderStatus": "REJECTED"}
    client.responses[{"regular": "order_book", "forever": "forever", "super": "super"}[family]] = {
        "status": "success",
        "data": [terminal],
    }
    bound = bind_adapter("dhan", DhanAdapter(client_factory=lambda _session: client), client)

    outcome = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR))

    assert isinstance(outcome, BrokerReadSuccess)
    assert len(outcome.value) == 1
    row = outcome.value[0]
    assert row.quantity is row.filled_quantity is row.price is row.trigger_price is None


@pytest.mark.asyncio
async def test_dhan_oco_safety_child_does_not_fabricate_fill_evidence(bind_adapter) -> None:
    client = _DhanClient()
    _dhan_rows(client)
    client.responses["order_book"] = {"status": "success", "data": []}
    row = _dhan_forever_row()
    row.update({"orderFlag": "OCO", "quantity1": 1, "price1": 90, "triggerPrice1": 95})
    client.responses["forever"] = {"status": "success", "data": [row]}
    bound = bind_adapter("dhan", DhanAdapter(client_factory=lambda _session: client), client)

    outcome = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR))

    assert isinstance(outcome, BrokerReadSuccess)
    child = next(item for item in outcome.value if item.leg_name == "STOP_LOSS_LEG")
    assert child.filled_quantity is None


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["regular", "forever", "super"])
async def test_dhan_active_safety_order_requires_provider_pricetype(bind_adapter, family: str) -> None:
    client = _DhanClient()
    _dhan_rows(client)
    client.responses["order_book"] = {"status": "success", "data": []}
    row = {
        "regular": _dhan_rows_for_safety_regular,
        "forever": _dhan_forever_row,
        "super": _dhan_super_row,
    }[family]()
    row.pop("orderType")
    if family == "super":
        row["legDetails"] = [
            {"legName": "TARGET_LEG", "orderStatus": "PENDING", "quantity": 1},
            {"legName": "STOP_LOSS_LEG", "orderStatus": "PENDING", "quantity": 1},
        ]
    client.responses[{"regular": "order_book", "forever": "forever", "super": "super"}[family]] = {
        "status": "success",
        "data": [row],
    }
    bound = bind_adapter("dhan", DhanAdapter(client_factory=lambda _session: client), client)

    assert await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR)) == BrokerReadFailure(
        BrokerReadErrorCode.MALFORMED_RESPONSE
    )
    assert client.calls == {
        "regular": ["order_book", "forever", "super", "conditional"],
        "forever": ["order_book", "forever", "super", "conditional"],
        "super": ["order_book", "forever", "super", "conditional"],
    }[family]


@pytest.mark.asyncio
async def test_dhan_regular_safety_order_preserves_disclosed_quantity(bind_adapter) -> None:
    client = _DhanClient()
    _dhan_rows(client)
    client.responses["order_book"]["data"][0]["disclosedQuantity"] = 0
    bound = bind_adapter("dhan", DhanAdapter(client_factory=lambda _session: client), client)

    result = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR))

    assert isinstance(result, BrokerReadSuccess)
    assert result.value[0].disclosed_quantity == "0"
    assert client.calls == ["order_book", "forever", "super", "conditional"]


def _dhan_greek_resolver():
    return build_security_resolver([
        {
            "SEM_EXM_EXCH_ID": "NSE",
            "SEM_SEGMENT": "I",
            "SEM_SMST_SECURITY_ID": "13",
            "SEM_TRADING_SYMBOL": "NIFTY",
        },
        {
            "SEM_EXM_EXCH_ID": "NSE",
            "SEM_SEGMENT": "D",
            "SEM_SMST_SECURITY_ID": "49081",
            "SEM_TRADING_SYMBOL": "NIFTY-Jul2026-25000-CE",
            "SEM_OPTION_TYPE": "CE",
            "SEM_EXPIRY_DATE": "2026-07-30",
            "SEM_STRIKE_PRICE": "25000",
            "UNDERLYING_SYMBOL": "NIFTY",
        },
    ])


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["missing", "conflicting", "incomplete", "nonfinite_ltp", "malformed_oi"])
async def test_dhan_portfolio_greek_response_defects_are_malformed(bind_adapter, defect: str) -> None:
    leg: dict[str, object] = {
        "security_id": "49081",
        "last_price": 120.5,
        "implied_volatility": 13.2,
        "oi": 30000,
        "greeks": {"delta": 0.55, "gamma": 0.002, "theta": -8.1, "vega": 6.4},
    }
    strikes: dict[str, object] = {"25000.000000": {"ce": leg}}
    if defect == "missing":
        strikes = {}
    elif defect == "conflicting":
        leg["security_id"] = "OTHER"
    elif defect == "incomplete":
        leg["greeks"].pop("delta")
    elif defect == "nonfinite_ltp":
        leg["last_price"] = "nan"
    else:
        leg["oi"] = object()
    client = _DhanClient()
    client.responses["option_chain"] = {"status": "success", "data": {"oc": strikes}}
    adapter = DhanAdapter(
        client_factory=lambda _session: client,
        security_resolver=_dhan_greek_resolver(),
    )
    bound = bind_adapter("dhan", adapter, client)
    request = PortfolioGreeksRequest((
        PortfolioPositionRef(
            "NIFTY-Jul2026-25000-CE",
            "NFO",
            "75",
            "CE",
            "49081",
            "2026-07-30",
            25000.0,
            "NIFTY",
        ),
    ))

    assert await bound.port.portfolio_greeks(request) == BrokerReadFailure(
        BrokerReadErrorCode.MALFORMED_RESPONSE
    )
    assert client.calls == ["option_chain"]


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["positions", "holdings", "trades", "orders", "forever", "super"])
@pytest.mark.parametrize(
    "payload",
    [[], {"status": "success", "data": {}}, {"status": "success", "data": ["bad-row"]}],
)
async def test_dhan_fixed_surfaces_reject_malformed_envelopes_containers_and_rows(
    bind_adapter,
    surface: str,
    payload: object,
) -> None:
    client = _DhanClient()
    _dhan_rows(client)
    client.responses[{"orders": "order_book", "trades": "trade_book"}.get(surface, surface)] = payload
    bound = bind_adapter("dhan", DhanAdapter(client_factory=lambda _session: client), client)

    assert await _dhan_surface(bound, surface) == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert client.calls == {
        "positions": ["positions"],
        "holdings": ["holdings"],
        "trades": ["trade_book"],
        "orders": ["order_book"],
        "forever": ["forever"],
        "super": ["super"],
    }[surface]


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["positions", "holdings", "trades", "orders", "forever", "super"])
async def test_dhan_fixed_surfaces_reject_missing_required_evidence(bind_adapter, surface: str) -> None:
    client = _DhanClient()
    _dhan_rows(client)
    if surface == "positions":
        client.responses["positions"]["data"][0].pop("netQty")
    elif surface == "holdings":
        client.responses["holdings"]["data"][0].pop("totalQty")
    elif surface == "trades":
        client.responses["trade_book"]["data"][0].pop("tradedQuantity")
    elif surface == "orders":
        client.responses["order_book"]["data"][0].pop("transactionType")
    elif surface == "forever":
        row = _dhan_forever_row()
        row.pop("transactionType")
        client.responses["forever"] = {"status": "success", "data": [row]}
    else:
        row = _dhan_super_row()
        row.pop("transactionType")
        client.responses["super"] = {"status": "success", "data": [row]}
    bound = bind_adapter("dhan", DhanAdapter(client_factory=lambda _session: client), client)

    assert await _dhan_surface(bound, surface) == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert client.calls == {
        "positions": ["positions"],
        "holdings": ["holdings"],
        "trades": ["trade_book"],
        "orders": ["order_book", "forever", "super", "conditional"],
        "forever": ["forever"],
        "super": ["super"],
    }[surface]


@pytest.mark.asyncio
async def test_dhan_present_malformed_primary_trade_alias_does_not_fall_through(bind_adapter) -> None:
    client = _DhanClient()
    _dhan_rows(client)
    row = client.responses["trade_book"]["data"][0]
    row["tradedQuantity"] = "bad"
    row["quantity"] = 0
    bound = bind_adapter("dhan", DhanAdapter(client_factory=lambda _session: client), client)

    assert await bound.port.trades() == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert client.calls == ["trade_book"]


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [False, True])
async def test_dhan_provider_failures_remain_provider_failure_with_one_fixed_call(bind_adapter, declared: bool) -> None:
    client = _DhanClient()
    _dhan_rows(client)
    if declared:
        client.responses["positions"] = {"status": "failure", "remarks": {"error_message": "synthetic"}}
    else:
        client.errors.add("positions")
    bound = bind_adapter("dhan", DhanAdapter(client_factory=lambda _session: client), client)

    assert await bound.port.positions() == BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
    assert client.calls == ["positions"]


@pytest.mark.asyncio
async def test_dhan_declared_holdings_failure_is_not_empty_success(bind_adapter) -> None:
    client = _DhanClient()
    _dhan_rows(client)
    client.responses["holdings"] = {
        "status": "failure",
        "remarks": {"error_message": "No holdings available"},
    }
    bound = bind_adapter("dhan", DhanAdapter(client_factory=lambda _session: client), client)

    assert await bound.port.holdings() == BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
    assert client.calls == ["holdings"]


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [False, True])
@pytest.mark.parametrize(
    ("surface", "source"),
    [("holdings", "holdings"), ("trades", "trade_book"), ("forever", "forever"), ("super", "super")],
)
async def test_dhan_each_direct_surface_preserves_provider_failure_and_ledger(
    bind_adapter,
    declared: bool,
    surface: str,
    source: str,
) -> None:
    client = _DhanClient()
    _dhan_rows(client)
    if declared:
        client.responses[source] = {"status": "failure", "remarks": {"error_message": "synthetic"}}
    else:
        client.errors.add(source)
    bound = bind_adapter("dhan", DhanAdapter(client_factory=lambda _session: client), client)

    assert await _dhan_surface(bound, surface) == BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
    assert client.calls == [source]


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [False, True])
@pytest.mark.parametrize("source", ["order_book", "forever", "super", "conditional"])
async def test_dhan_regular_safety_provider_failure_stops_at_exact_source_prefix(
    bind_adapter,
    declared: bool,
    source: str,
) -> None:
    client = _DhanClient()
    _dhan_rows(client)
    if declared:
        client.responses[source] = {"status": "failure", "remarks": {"error_message": "synthetic"}}
    else:
        client.errors.add(source)
    bound = bind_adapter("dhan", DhanAdapter(client_factory=lambda _session: client), client)

    assert await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR)) == BrokerReadFailure(
        BrokerReadErrorCode.PROVIDER_FAILURE
    )
    sources = ["order_book", "forever", "super", "conditional"]
    assert client.calls == sources[: sources.index(source) + 1]


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["trades", "forever", "super"])
async def test_dhan_direct_optional_order_evidence_remains_absent(bind_adapter, surface: str) -> None:
    client = _DhanClient()
    _dhan_rows(client)
    if surface == "trades":
        client.responses["trade_book"]["data"][0].pop("orderId")
    elif surface == "forever":
        row = _dhan_forever_row()
        for field in ("filledQty", "price", "triggerPrice"):
            row.pop(field)
        client.responses["forever"] = {"status": "success", "data": [row]}
    else:
        row = _dhan_super_row()
        row["orderStatus"] = "CANCELLED"
        for field in ("filledQty", "price"):
            row.pop(field)
        client.responses["super"] = {"status": "success", "data": [row]}
    bound = bind_adapter("dhan", DhanAdapter(client_factory=lambda _session: client), client)

    outcome = await _dhan_surface(bound, surface)

    assert isinstance(outcome, BrokerReadSuccess)
    if surface == "trades":
        assert outcome.value[0].orderid is None
        assert client.calls == ["trade_book"]
    else:
        assert outcome.value[0].filled_quantity is outcome.value[0].price is None
        assert client.calls == [surface]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("surface", "source", "primary", "secondary"),
    [
        ("positions", "positions", "costPrice", "buyAvg"),
        ("holdings", "holdings", "unrealizedProfit", "pnl"),
        ("trades", "trade_book", "tradedPrice", "price"),
    ],
)
async def test_dhan_present_malformed_primary_data_alias_never_falls_through(
    bind_adapter,
    surface: str,
    source: str,
    primary: str,
    secondary: str,
) -> None:
    client = _DhanClient()
    _dhan_rows(client)
    row = client.responses[source]["data"][0]
    row[primary] = "bad"
    row[secondary] = 0
    bound = bind_adapter("dhan", DhanAdapter(client_factory=lambda _session: client), client)

    assert await _dhan_surface(bound, surface) == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert client.calls == [source]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("surface", "source", "primary", "secondary"),
    [
        ("orders", "order_book", "filledQty", "tradedQty"),
        ("orders", "order_book", "disclosedQuantity", "disclosed_quantity"),
        ("forever", "forever", "filledQty", "tradedQty"),
        ("super", "super", "filledQty", "tradedQty"),
    ],
)
async def test_dhan_present_malformed_primary_order_alias_never_falls_through(
    bind_adapter,
    surface: str,
    source: str,
    primary: str,
    secondary: str,
) -> None:
    client = _DhanClient()
    _dhan_rows(client)
    if source == "forever":
        client.responses[source] = {"status": "success", "data": [_dhan_forever_row()]}
    elif source == "super":
        client.responses[source] = {"status": "success", "data": [_dhan_super_row()]}
    row = client.responses[source]["data"][0]
    row[primary] = "bad"
    row[secondary] = 0
    bound = bind_adapter("dhan", DhanAdapter(client_factory=lambda _session: client), client)

    assert await _dhan_surface(bound, surface) == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert client.calls == [source]


@pytest.mark.asyncio
async def test_dhan_position_pnl_sums_decimal_evidence_before_string_projection(bind_adapter) -> None:
    client = _DhanClient()
    _dhan_rows(client)
    row = client.responses["positions"]["data"][0]
    row["realizedProfit"] = "0.1"
    row["unrealizedProfit"] = "0.2"
    bound = bind_adapter("dhan", DhanAdapter(client_factory=lambda _session: client), client)

    outcome = await bound.port.positions()

    assert isinstance(outcome, BrokerReadSuccess)
    assert outcome.value[0].pnl == "0.3"
    assert client.calls == ["positions"]


@pytest.mark.asyncio
async def test_dhan_terminal_conditional_rejects_a_malformed_child_with_full_ledger(bind_adapter) -> None:
    client = _DhanClient()
    _dhan_rows(client)
    client.responses["conditional"] = {
        "status": "success",
        "data": [{"alertId": "ALERT-1", "alertStatus": "CANCELLED", "orders": ["bad-row"]}],
    }
    bound = bind_adapter("dhan", DhanAdapter(client_factory=lambda _session: client), client)

    assert await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR)) == BrokerReadFailure(
        BrokerReadErrorCode.MALFORMED_RESPONSE
    )
    assert client.calls == ["order_book", "forever", "super", "conditional"]


class _UpstoxClient:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.responses: dict[str, object] = {}
        self.errors: set[str] = set()

    def _read(self, name: str) -> object:
        self.calls.append(name)
        if name in self.errors:
            raise RuntimeError("synthetic Upstox SDK failure")
        return copy.deepcopy(self.responses[name])

    def order_book(self) -> object:
        return self._read("order_book")

    def trade_book(self) -> object:
        return self._read("trade_book")

    def positions(self) -> object:
        return self._read("positions")

    def holdings(self) -> object:
        return self._read("holdings")

    def gtt_order_details(self, _order_id: str | None = None) -> object:
        return self._read("forever")

    def option_greeks_v3(self, _instrument_keys: str) -> object:
        return self._read("option_greeks")


def _upstox_rows(client: _UpstoxClient) -> None:
    client.responses.update({
        "positions": {"status": "success", "data": [{
            "trading_symbol": "TCS",
            "instrument_token": "NSE_EQ|INE467B01029",
            "exchange": "NSE",
            "product": "D",
            "quantity": 0,
        }]},
        "holdings": {"status": "success", "data": [{
            "trading_symbol": "TCS",
            "instrument_token": "NSE_EQ|INE467B01029",
            "exchange": "NSE",
            "product": "D",
            "quantity": 0,
        }]},
        "trade_book": {"status": "success", "data": [{
            "order_id": "UT1",
            "trading_symbol": "TCS",
            "instrument_token": "NSE_EQ|INE467B01029",
            "exchange": "NSE",
            "transaction_type": "BUY",
            "product": "D",
            "quantity": 0,
            "average_price": 0,
            "exchange_timestamp": "2026-09-07T09:20:00+05:30",
        }]},
        "order_book": {"status": "success", "data": [{
            "order_id": "UO1",
            "status": "open",
            "trading_symbol": "TCS",
            "instrument_token": "NSE_EQ|INE467B01029",
            "exchange": "NSE",
            "transaction_type": "BUY",
            "order_type": "LIMIT",
            "product": "D",
            "quantity": 0,
            "filled_quantity": 0,
            "price": 0,
        }]},
        "forever": {"status": "success", "data": [{
            "gtt_order_id": "UG1",
            "status": "PENDING",
            "type": "SINGLE",
            "trading_symbol": "TCS",
            "instrument_token": "NSE_EQ|INE467B01029",
            "exchange": "NSE",
            "product": "D",
            "quantity": 0,
            "rules": [{
                "strategy": "ENTRY",
                "status": "PENDING",
                "trigger_price": 0,
                "transaction_type": "BUY",
                "order_id": "",
            }],
        }]},
    })


async def _upstox_surface(bound: _BoundAdapter, surface: str):
    if surface == "positions":
        return await bound.port.positions()
    if surface == "holdings":
        return await bound.port.holdings()
    if surface == "trades":
        return await bound.port.trades()
    family = BrokerOrderFamily.REGULAR if surface == "orders" else BrokerOrderFamily.FOREVER
    return await bound.port.order_states(OrderStateRequest(family))


@pytest.mark.asyncio
async def test_upstox_supported_surfaces_preserve_zero_optional_absence_and_exact_ledgers(bind_adapter) -> None:
    client = _UpstoxClient()
    _upstox_rows(client)
    bound = bind_adapter("upstox", UpstoxAdapter(client_factory=lambda _session: client), client)

    for surface, expected in (
        ("positions", ["positions"]),
        ("holdings", ["holdings"]),
        ("trades", ["trade_book"]),
        ("orders", ["order_book"]),
        ("forever", ["forever"]),
    ):
        start = len(client.calls)
        outcome = await _upstox_surface(bound, surface)
        assert isinstance(outcome, BrokerReadSuccess)
        assert outcome.value[0].quantity == "0"
        assert client.calls[start:] == expected
    assert (await bound.port.positions()).value[0].average_price is None
    assert (await bound.port.holdings()).value[0].average_price is None
    start = len(client.calls)
    assert await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.SUPER)) == BrokerReadFailure(
        BrokerReadErrorCode.UNSUPPORTED
    )
    assert client.calls[start:] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["positions", "holdings", "trades", "orders", "forever"])
@pytest.mark.parametrize(
    "payload",
    [[], {"status": "success", "data": {}}, {"status": "success", "data": ["bad-row"]}],
)
async def test_upstox_fixed_surfaces_reject_malformed_envelopes_containers_and_rows(
    bind_adapter,
    surface: str,
    payload: object,
) -> None:
    client = _UpstoxClient()
    _upstox_rows(client)
    client.responses[{"orders": "order_book", "trades": "trade_book"}.get(surface, surface)] = payload
    bound = bind_adapter("upstox", UpstoxAdapter(client_factory=lambda _session: client), client)

    assert await _upstox_surface(bound, surface) == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert client.calls == [{"orders": "order_book", "trades": "trade_book"}.get(surface, surface)]


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["positions", "holdings", "trades", "orders", "forever"])
async def test_upstox_fixed_surfaces_reject_missing_required_evidence(bind_adapter, surface: str) -> None:
    client = _UpstoxClient()
    _upstox_rows(client)
    key = {"orders": "order_book", "trades": "trade_book"}.get(surface, surface)
    row = client.responses[key]["data"][0]
    field = {
        "positions": "quantity",
        "holdings": "quantity",
        "trades": "transaction_type",
        "orders": "transaction_type",
        "forever": "trading_symbol",
    }[surface]
    row.pop(field)
    bound = bind_adapter("upstox", UpstoxAdapter(client_factory=lambda _session: client), client)

    assert await _upstox_surface(bound, surface) == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert client.calls == [{"orders": "order_book", "trades": "trade_book"}.get(surface, surface)]


@pytest.mark.asyncio
async def test_upstox_present_malformed_primary_trade_alias_does_not_fall_through(bind_adapter) -> None:
    client = _UpstoxClient()
    _upstox_rows(client)
    row = client.responses["trade_book"]["data"][0]
    row["average_price"] = "bad"
    row["price"] = 0
    bound = bind_adapter("upstox", UpstoxAdapter(client_factory=lambda _session: client), client)

    assert await bound.port.trades() == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert client.calls == ["trade_book"]


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [False, True])
async def test_upstox_provider_failures_remain_provider_failure_with_one_fixed_call(bind_adapter, declared: bool) -> None:
    client = _UpstoxClient()
    _upstox_rows(client)
    if declared:
        client.responses["positions"] = {"status": "error", "errors": [{"message": "synthetic"}]}
    else:
        client.errors.add("positions")
    bound = bind_adapter("upstox", UpstoxAdapter(client_factory=lambda _session: client), client)

    assert await bound.port.positions() == BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
    assert client.calls == ["positions"]


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [False, True])
@pytest.mark.parametrize("surface", ["holdings", "trades", "orders", "forever"])
async def test_upstox_each_remaining_surface_preserves_provider_failure_and_ledger(
    bind_adapter,
    declared: bool,
    surface: str,
) -> None:
    client = _UpstoxClient()
    _upstox_rows(client)
    source = {"orders": "order_book", "trades": "trade_book"}.get(surface, surface)
    if declared:
        client.responses[source] = {"status": "error", "errors": [{"message": "synthetic"}]}
    else:
        client.errors.add(source)
    bound = bind_adapter("upstox", UpstoxAdapter(client_factory=lambda _session: client), client)

    assert await _upstox_surface(bound, surface) == BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
    assert client.calls == [source]


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["holdings", "trades", "orders", "forever"])
async def test_upstox_optional_identity_and_order_numerics_remain_absent(bind_adapter, surface: str) -> None:
    client = _UpstoxClient()
    _upstox_rows(client)
    source = {"orders": "order_book", "trades": "trade_book"}.get(surface, surface)
    row = client.responses[source]["data"][0]
    if surface == "holdings":
        row.pop("instrument_token")
    elif surface == "trades":
        row.pop("instrument_token")
        row.pop("order_id")
    elif surface == "orders":
        row["disclosed_quantity"] = 0
        row.pop("disclosed_quantity")
        row.pop("price")
    else:
        row["rules"][0]["order_id"] = "UFILL"
        row["rules"][0].pop("order_id")
    bound = bind_adapter("upstox", UpstoxAdapter(client_factory=lambda _session: client), client)

    outcome = await _upstox_surface(bound, surface)

    assert isinstance(outcome, BrokerReadSuccess)
    item = outcome.value[0]
    if surface in {"holdings", "trades"}:
        assert item.instrument_id is None
    if surface == "trades":
        assert item.orderid is None
    elif surface == "orders":
        assert item.price is item.disclosed_quantity is None
    elif surface == "forever":
        assert item.filled_quantity is None
    assert client.calls == [source]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("surface", "primary", "secondary"),
    [
        ("positions", "average_price", "buy_price"),
        ("holdings", "trading_symbol", "tradingsymbol"),
        ("orders", "disclosed_quantity", "disclosedQuantity"),
        ("forever", "trading_symbol", "tradingsymbol"),
    ],
)
async def test_upstox_present_malformed_primary_alias_never_falls_through(
    bind_adapter,
    surface: str,
    primary: str,
    secondary: str,
) -> None:
    client = _UpstoxClient()
    _upstox_rows(client)
    source = {"orders": "order_book", "trades": "trade_book"}.get(surface, surface)
    row = client.responses[source]["data"][0]
    row[primary] = object() if "symbol" in primary else "bad"
    row[secondary] = "TCS" if "symbol" in secondary else 0
    bound = bind_adapter("upstox", UpstoxAdapter(client_factory=lambda _session: client), client)

    assert await _upstox_surface(bound, surface) == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert client.calls == [source]


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["missing", "extra", "duplicate", "incomplete"])
async def test_upstox_portfolio_greek_response_identity_defects_are_malformed(bind_adapter, defect: str) -> None:
    key = "NSE_FO|54452"
    row = {
        "instrument_token": key,
        "last_price": 120.5,
        "iv": 13.2,
        "delta": 0.55,
        "gamma": 0.002,
        "theta": -8.1,
        "vega": 6.4,
        "oi": 30000,
        "volume": 5000,
    }
    data: dict[str, object] = {key: row}
    if defect == "missing":
        data = {}
    elif defect == "extra":
        data["NSE_FO|EXTRA"] = {**row, "instrument_token": "NSE_FO|EXTRA"}
    elif defect == "duplicate":
        data["duplicate-container-key"] = dict(row)
    else:
        row.pop("delta")
    client = _UpstoxClient()
    client.responses["option_greeks"] = {"status": "success", "data": data}
    adapter = UpstoxAdapter(
        client_factory=lambda _session: client,
        instrument_resolver=lambda _symbol, _exchange: key,
    )
    bound = bind_adapter("upstox", adapter, client)
    request = PortfolioGreeksRequest((
        PortfolioPositionRef("NIFTY 30 JUL 26 25000 CE", "NFO", "75", "CE", key, None, None, None),
    ))

    assert await bound.port.portfolio_greeks(request) == BrokerReadFailure(
        BrokerReadErrorCode.MALFORMED_RESPONSE
    )
    assert client.calls == ["option_greeks"]


class _GrowwTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.payloads: dict[tuple[str, str | None], object] = {}
        self.raw_responses: dict[tuple[str, str | None], tuple[int, object]] = {}
        self.errors: set[tuple[str, str | None]] = set()

    def __call__(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, Any] | None = None,
        json_body: Any = None,
    ) -> tuple[int, object]:
        del headers, json_body
        path = url.removeprefix(GROWW_BASE_URL)
        copied_params = dict(params or {})
        segment = copied_params.get("segment")
        key = (path, segment if type(segment) is str else None)
        self.calls.append((method, path, copied_params))
        if key in self.errors:
            raise RuntimeError("synthetic Groww transport failure")
        if key in self.raw_responses:
            return self.raw_responses[key]
        payload = copy.deepcopy(self.payloads.get(key, {}))
        return 200, {"status": "SUCCESS", "payload": payload}


def _groww_rows(transport: _GrowwTransport) -> None:
    transport.payloads[("/v1/positions/user", None)] = {
        "positions": [{
            "trading_symbol": "TCS",
            "exchange": "NSE",
            "segment": "CASH",
            "product": "CNC",
            "quantity": 0,
        }]
    }
    transport.payloads[("/v1/holdings/user", None)] = {
        "holdings": [{"isin": "INE467B01029", "trading_symbol": "TCS", "quantity": 0}]
    }
    for segment in ("CASH", "FNO", "COMMODITY"):
        rows: list[dict[str, Any]] = []
        if segment == "CASH":
            rows = [{
                "groww_order_id": "G1",
                "trading_symbol": "TCS",
                "exchange": "NSE",
                "segment": "CASH",
                "transaction_type": "BUY",
                "order_type": "LIMIT",
                "product": "CNC",
                "quantity": 0,
                "filled_quantity": 0,
                "price": 0,
                "order_status": "OPEN",
            }]
        transport.payloads[("/v1/order/list", segment)] = {"order_list": rows}
    transport.payloads[("/v1/order/trades/G1", "CASH")] = {
        "trade_list": [{
            "groww_order_id": "G1",
            "groww_trade_id": "",
            "exchange_trade_id": "EX-T1",
            "trading_symbol": "TCS",
            "exchange": "NSE",
            "segment": "CASH",
            "transaction_type": "BUY",
            "product": "CNC",
            "quantity": 0,
            "price": 0,
            "trade_date_time": "2026-09-07T09:20:00+05:30",
        }]
    }


def _groww_list_calls(count: int = 3) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        ("GET", "/v1/order/list", {"segment": segment, "page": 0, "page_size": 100})
        for segment in ("CASH", "FNO", "COMMODITY")[:count]
    ]


def _groww_surface_calls(surface: str) -> list[tuple[str, str, dict[str, Any]]]:
    if surface == "positions":
        return [("GET", "/v1/positions/user", {})]
    if surface == "holdings":
        return [("GET", "/v1/holdings/user", {})]
    if surface == "orders":
        return _groww_list_calls(1)
    return [
        *_groww_list_calls(),
        ("GET", "/v1/order/trades/G1", {"segment": "CASH", "page": 0, "page_size": 50}),
    ]


@pytest.mark.asyncio
async def test_groww_supported_surfaces_preserve_zero_optional_absence_and_exact_ledgers(bind_adapter) -> None:
    transport = _GrowwTransport()
    _groww_rows(transport)
    bound = bind_adapter("groww", GrowwAdapter(http_factory=lambda: transport), transport)

    start = len(transport.calls)
    positions = await bound.port.positions()
    assert isinstance(positions, BrokerReadSuccess)
    assert positions.value[0].quantity == "0"
    assert positions.value[0].average_price is None
    assert [call[1] for call in transport.calls[start:]] == ["/v1/positions/user"]

    start = len(transport.calls)
    holdings = await bound.port.holdings()
    assert holdings == BrokerReadFailure(BrokerReadErrorCode.UNSUPPORTED)
    assert transport.calls[start:] == []

    start = len(transport.calls)
    orders = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR))
    assert isinstance(orders, BrokerReadSuccess)
    assert orders.value[0].quantity == "0"
    assert [call[2]["segment"] for call in transport.calls[start:]] == ["CASH", "FNO", "COMMODITY"]

    start = len(transport.calls)
    trade_row = transport.payloads[("/v1/order/trades/G1", "CASH")]["trade_list"][0]
    assert from_groww_trade(trade_row)["tradeid"] == "EX-T1"
    trades = await bound.port.trades()
    assert isinstance(trades, BrokerReadSuccess)
    assert trades.value[0].quantity == trades.value[0].price == "0"
    assert [call[1] for call in transport.calls[start:]] == [
        "/v1/order/list",
        "/v1/order/list",
        "/v1/order/list",
        "/v1/order/trades/G1",
    ]

    start = len(transport.calls)
    forever = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER))
    super_orders = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.SUPER))
    assert forever == BrokerReadFailure(BrokerReadErrorCode.UNSUPPORTED)
    assert super_orders == BrokerReadFailure(BrokerReadErrorCode.UNSUPPORTED)
    assert transport.calls[start:] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("surface", "payload"),
    [
        ("positions", []),
        ("positions", {"positions": {}}),
        ("positions", {"positions": ["bad-row"]}),
        ("orders", []),
        ("orders", {"order_list": {}}),
        ("orders", {"order_list": ["bad-row"]}),
        ("trades", []),
        ("trades", {"trade_list": {}}),
        ("trades", {"trade_list": ["bad-row"]}),
    ],
)
async def test_groww_fixed_surfaces_reject_malformed_envelopes_containers_and_rows(
    bind_adapter,
    surface: str,
    payload: object,
) -> None:
    transport = _GrowwTransport()
    _groww_rows(transport)
    if surface == "positions":
        transport.payloads[("/v1/positions/user", None)] = payload
    elif surface == "holdings":
        transport.payloads[("/v1/holdings/user", None)] = payload
    elif surface == "orders":
        transport.payloads[("/v1/order/list", "CASH")] = payload
    else:
        transport.payloads[("/v1/order/trades/G1", "CASH")] = payload
    bound = bind_adapter("groww", GrowwAdapter(http_factory=lambda: transport), transport)

    if surface == "positions":
        outcome = await bound.port.positions()
    elif surface == "holdings":
        outcome = await bound.port.holdings()
    elif surface == "orders":
        outcome = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR))
    else:
        outcome = await bound.port.trades()
    assert outcome == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert transport.calls == _groww_surface_calls(surface)


@pytest.mark.asyncio
@pytest.mark.parametrize("outer", [{"payload": None}, {"status": 1, "payload": None}])
@pytest.mark.parametrize("surface", ["positions", "orders", "trades"])
async def test_groww_fixed_surfaces_reject_malformed_outer_envelopes(
    bind_adapter,
    surface: str,
    outer: dict[str, object],
) -> None:
    transport = _GrowwTransport()
    _groww_rows(transport)
    if surface == "positions":
        key = ("/v1/positions/user", None)
    elif surface == "holdings":
        key = ("/v1/holdings/user", None)
    elif surface == "orders":
        key = ("/v1/order/list", "CASH")
    else:
        key = ("/v1/order/trades/G1", "CASH")
    payload = copy.deepcopy(transport.payloads[key])
    response = dict(outer)
    response["payload"] = payload
    transport.raw_responses[key] = (200, response)
    bound = bind_adapter("groww", GrowwAdapter(http_factory=lambda: transport), transport)

    if surface == "positions":
        outcome = await bound.port.positions()
    elif surface == "holdings":
        outcome = await bound.port.holdings()
    elif surface == "orders":
        outcome = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR))
    else:
        outcome = await bound.port.trades()
    assert outcome == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert transport.calls == _groww_surface_calls(surface)


@pytest.mark.asyncio
async def test_groww_declared_outer_failure_remains_provider_failure(bind_adapter) -> None:
    transport = _GrowwTransport()
    _groww_rows(transport)
    transport.raw_responses[("/v1/positions/user", None)] = (
        200,
        {"status": "FAILURE", "payload": transport.payloads[("/v1/positions/user", None)]},
    )
    bound = bind_adapter("groww", GrowwAdapter(http_factory=lambda: transport), transport)

    assert await bound.port.positions() == BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
    assert [call[1] for call in transport.calls] == ["/v1/positions/user"]


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["positions", "orders", "trades"])
async def test_groww_fixed_surfaces_reject_missing_or_corrupt_required_evidence(bind_adapter, surface: str) -> None:
    transport = _GrowwTransport()
    _groww_rows(transport)
    if surface == "positions":
        row = transport.payloads[("/v1/positions/user", None)]["positions"][0]
        row.pop("quantity")
        row["credit_quantity"] = "bad"
        row["debit_quantity"] = 0
    elif surface == "holdings":
        transport.payloads[("/v1/holdings/user", None)]["holdings"][0].pop("quantity")
    elif surface == "orders":
        transport.payloads[("/v1/order/list", "CASH")]["order_list"][0].pop("transaction_type")
    else:
        row = transport.payloads[("/v1/order/trades/G1", "CASH")]["trade_list"][0]
        row["price"] = "bad"
        row["average_price"] = 1
    bound = bind_adapter("groww", GrowwAdapter(http_factory=lambda: transport), transport)

    if surface == "positions":
        outcome = await bound.port.positions()
    elif surface == "holdings":
        outcome = await bound.port.holdings()
    elif surface == "orders":
        outcome = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR))
    else:
        outcome = await bound.port.trades()
    assert outcome == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert transport.calls == (_groww_list_calls() if surface == "orders" else _groww_surface_calls(surface))


@pytest.mark.asyncio
async def test_groww_transport_failure_remains_provider_failure_with_one_fixed_call(bind_adapter) -> None:
    transport = _GrowwTransport()
    _groww_rows(transport)
    transport.errors.add(("/v1/positions/user", None))
    bound = bind_adapter("groww", GrowwAdapter(http_factory=lambda: transport), transport)

    outcome = await bound.port.positions()

    assert outcome == BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
    assert [call[1] for call in transport.calls] == ["/v1/positions/user"]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload_kind", ["string_subclass", "non_string", "trap", "cycle"])
async def test_groww_lot_sizes_require_an_exact_string_asset_response_without_hooks(
    bind_adapter,
    payload_kind: str,
) -> None:
    class PayloadTrap:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def __bool__(self) -> bool:
            self.calls.append("bool")
            raise AssertionError("untrusted Groww asset bool hook must not run")

        def __str__(self) -> str:
            self.calls.append("str")
            raise AssertionError("untrusted Groww asset string hook must not run")

        def __format__(self, _format_spec: str) -> str:
            self.calls.append("format")
            raise AssertionError("untrusted Groww asset format hook must not run")

        def __repr__(self) -> str:
            self.calls.append("repr")
            raise AssertionError("untrusted Groww asset repr hook must not run")

    class CsvSubclass(str):
        pass

    trap = PayloadTrap()
    csv_text = "trading_symbol,exchange,lot_size,instrument_token\nTCS,NSE,1,101\n"
    if payload_kind == "string_subclass":
        payload: object = CsvSubclass(csv_text)
    elif payload_kind == "non_string":
        payload = [1]
    elif payload_kind == "trap":
        payload = trap
    else:
        cycle: dict[str, object] = {"trap": trap}
        cycle["self"] = cycle
        payload = cycle

    transport = _GrowwTransport()
    transport.raw_responses[(GROWW_INSTRUMENTS_URL, None)] = (200, payload)
    bound = bind_adapter("groww", GrowwAdapter(http_factory=lambda: transport), transport)

    assert await bound.port.lot_sizes(LotSizeRequest("NSE", ("TCS",))) == BrokerReadFailure(
        BrokerReadErrorCode.MALFORMED_RESPONSE
    )
    assert trap.calls == []
    assert transport.calls == [("GET", GROWW_INSTRUMENTS_URL, {})]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 500])
@pytest.mark.parametrize(
    "field",
    ["message", "code", "error_code", "error", "nested_message", "nested_code", "top_level"],
)
async def test_groww_lot_size_http_errors_do_not_execute_payload_hooks(
    bind_adapter,
    field: str,
    status: int,
) -> None:
    class ErrorTrap:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def __bool__(self) -> bool:
            self.calls.append("bool")
            raise AssertionError("untrusted Groww asset-error bool hook must not run")

        def __str__(self) -> str:
            self.calls.append("str")
            raise AssertionError("untrusted Groww asset-error string hook must not run")

        def __format__(self, _format_spec: str) -> str:
            self.calls.append("format")
            raise AssertionError("untrusted Groww asset-error format hook must not run")

        def __repr__(self) -> str:
            self.calls.append("repr")
            raise AssertionError("untrusted Groww asset-error repr hook must not run")

    trap = ErrorTrap()
    if field == "top_level":
        payload: object = trap
    elif field == "nested_message":
        payload = {"error": {"message": trap}}
    elif field == "nested_code":
        payload = {"error": {"code": trap}, "message": "synthetic"}
    else:
        payload = {"message": "synthetic", field: trap}

    transport = _GrowwTransport()
    transport.raw_responses[(GROWW_INSTRUMENTS_URL, None)] = (status, payload)
    bound = bind_adapter("groww", GrowwAdapter(http_factory=lambda: transport), transport)

    assert await bound.port.lot_sizes(LotSizeRequest("NSE", ("TCS",))) == BrokerReadFailure(
        BrokerReadErrorCode.PROVIDER_FAILURE
    )
    assert trap.calls == []
    assert transport.calls == [("GET", GROWW_INSTRUMENTS_URL, {})]


@pytest.mark.asyncio
async def test_groww_lot_size_strict_csv_parse_failure_is_malformed(
    bind_adapter,
    monkeypatch,
) -> None:
    def fail_parse(_payload: str) -> list[dict[str, str]]:
        raise ValueError("synthetic strict Groww CSV parse failure")

    monkeypatch.setattr("flinttrade_gateway.brokers.groww.M.parse_instruments_csv", fail_parse)
    transport = _GrowwTransport()
    transport.raw_responses[(GROWW_INSTRUMENTS_URL, None)] = (200, "header\nvalue\n")
    bound = bind_adapter("groww", GrowwAdapter(http_factory=lambda: transport), transport)

    assert await bound.port.lot_sizes(LotSizeRequest("NSE", ("TCS",))) == BrokerReadFailure(
        BrokerReadErrorCode.MALFORMED_RESPONSE
    )
    assert transport.calls == [("GET", GROWW_INSTRUMENTS_URL, {})]


@pytest.mark.asyncio
async def test_groww_lot_size_exact_string_success_has_one_asset_call(bind_adapter) -> None:
    transport = _GrowwTransport()
    transport.raw_responses[(GROWW_INSTRUMENTS_URL, None)] = (
        200,
        "trading_symbol,exchange,lot_size,instrument_token\nTCS,NSE,1,101\n",
    )
    bound = bind_adapter("groww", GrowwAdapter(http_factory=lambda: transport), transport)

    outcome = await bound.port.lot_sizes(LotSizeRequest("NSE", ("TCS",)))

    assert isinstance(outcome, BrokerReadSuccess)
    assert [(row.symbol, row.exchange, row.lot_size, row.instrument_id) for row in outcome.value] == [
        ("TCS", "NSE", 1, "101")
    ]
    assert transport.calls == [("GET", GROWW_INSTRUMENTS_URL, {})]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("segment", None),
        ("segment", "COMMODITY"),
        ("exchange", "MCX"),
    ],
)
async def test_groww_position_requires_an_exact_consistent_exchange_segment_pair(
    bind_adapter,
    field: str,
    value: str | None,
) -> None:
    transport = _GrowwTransport()
    _groww_rows(transport)
    row = transport.payloads[("/v1/positions/user", None)]["positions"][0]
    if value is None:
        row.pop(field)
    else:
        row[field] = value
    bound = bind_adapter("groww", GrowwAdapter(http_factory=lambda: transport), transport)

    assert await bound.port.positions() == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert transport.calls == [("GET", "/v1/positions/user", {})]


@pytest.mark.asyncio
async def test_groww_trade_book_rejects_order_without_provider_id(bind_adapter) -> None:
    transport = _GrowwTransport()
    _groww_rows(transport)
    transport.payloads[("/v1/order/list", "CASH")]["order_list"][0].pop("groww_order_id")
    bound = bind_adapter("groww", GrowwAdapter(http_factory=lambda: transport), transport)

    assert await bound.port.trades() == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert [call[2]["segment"] for call in transport.calls] == ["CASH", "FNO", "COMMODITY"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [("segment", None), ("segment", "FNO"), ("exchange", None), ("exchange", "MCX")],
)
async def test_groww_trade_routing_rejects_unproved_list_identity_before_detail(
    bind_adapter,
    field: str,
    value: str | None,
) -> None:
    transport = _GrowwTransport()
    _groww_rows(transport)
    order = transport.payloads[("/v1/order/list", "CASH")]["order_list"][0]
    if value is None:
        order.pop(field)
    else:
        order[field] = value
    bound = bind_adapter("groww", GrowwAdapter(http_factory=lambda: transport), transport)

    assert await bound.port.trades() == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert transport.calls == [
        ("GET", "/v1/order/list", {"segment": "CASH", "page": 0, "page_size": 100}),
        ("GET", "/v1/order/list", {"segment": "FNO", "page": 0, "page_size": 100}),
        ("GET", "/v1/order/list", {"segment": "COMMODITY", "page": 0, "page_size": 100}),
    ]


def _groww_segmented_trade_rows(transport: _GrowwTransport) -> dict[str, tuple[str, str, str]]:
    rows = {
        "CASH": ("GC", "NSE", "CNC"),
        "FNO": ("GF", "NSE", "NRML"),
        "COMMODITY": ("GM", "MCX", "NRML"),
    }
    for segment, (order_id, exchange, product) in rows.items():
        transport.payloads[("/v1/order/list", segment)] = {"order_list": [{
            "groww_order_id": order_id,
            "trading_symbol": f"{segment}-SYMBOL",
            "exchange": exchange,
            "segment": segment,
            "transaction_type": "BUY",
            "order_type": "LIMIT",
            "product": product,
            "quantity": 1,
            "filled_quantity": 1,
            "price": 10,
            "order_status": "EXECUTED",
        }]}
        transport.payloads[(f"/v1/order/trades/{order_id}", segment)] = {"trade_list": [{
            "groww_order_id": order_id,
            "groww_trade_id": f"T-{order_id}",
            "trading_symbol": f"{segment}-SYMBOL",
            "exchange": exchange,
            "transaction_type": "BUY",
            "product": product,
            "quantity": 1,
            "price": 10,
            "trade_date_time": "2026-09-07T09:20:00+05:30",
        }]}
    return rows


@pytest.mark.asyncio
async def test_groww_trade_routing_binds_all_three_enumerated_segments_when_details_omit_them(bind_adapter) -> None:
    transport = _GrowwTransport()
    _groww_rows(transport)
    _groww_segmented_trade_rows(transport)
    bound = bind_adapter("groww", GrowwAdapter(http_factory=lambda: transport), transport)

    outcome = await bound.port.trades()

    assert isinstance(outcome, BrokerReadSuccess)
    assert len(outcome.value) == 3
    assert [row.exchange for row in outcome.value] == ["NSE", "NFO", "MCX"]
    assert transport.calls == [
        ("GET", "/v1/order/list", {"segment": "CASH", "page": 0, "page_size": 100}),
        ("GET", "/v1/order/list", {"segment": "FNO", "page": 0, "page_size": 100}),
        ("GET", "/v1/order/list", {"segment": "COMMODITY", "page": 0, "page_size": 100}),
        ("GET", "/v1/order/trades/GC", {"segment": "CASH", "page": 0, "page_size": 50}),
        ("GET", "/v1/order/trades/GF", {"segment": "FNO", "page": 0, "page_size": 50}),
        ("GET", "/v1/order/trades/GM", {"segment": "COMMODITY", "page": 0, "page_size": 50}),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route_segment", "field", "bad_value", "detail_count"),
    [
        ("CASH", "segment", "FNO", 1),
        ("FNO", "segment", "CASH", 2),
        ("COMMODITY", "segment", "FNO", 3),
        ("CASH", "exchange", "MCX", 1),
        ("FNO", "exchange", "MCX", 2),
        ("COMMODITY", "exchange", "NSE", 3),
    ],
)
async def test_groww_trade_routing_rejects_detail_identity_that_conflicts_with_bound_segment(
    bind_adapter,
    route_segment: str,
    field: str,
    bad_value: str,
    detail_count: int,
) -> None:
    transport = _GrowwTransport()
    _groww_rows(transport)
    rows = _groww_segmented_trade_rows(transport)
    order_id = rows[route_segment][0]
    transport.payloads[(f"/v1/order/trades/{order_id}", route_segment)]["trade_list"][0][field] = bad_value
    bound = bind_adapter("groww", GrowwAdapter(http_factory=lambda: transport), transport)

    assert await bound.port.trades() == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert transport.calls == [
        ("GET", "/v1/order/list", {"segment": "CASH", "page": 0, "page_size": 100}),
        ("GET", "/v1/order/list", {"segment": "FNO", "page": 0, "page_size": 100}),
        ("GET", "/v1/order/list", {"segment": "COMMODITY", "page": 0, "page_size": 100}),
        *[
            (
                "GET",
                f"/v1/order/trades/{rows[segment][0]}",
                {"segment": segment, "page": 0, "page_size": 50},
            )
            for segment in ("CASH", "FNO", "COMMODITY")[:detail_count]
        ],
    ]


@pytest.mark.asyncio
async def test_groww_trade_detail_must_match_the_exact_listed_order_id(bind_adapter) -> None:
    transport = _GrowwTransport()
    _groww_rows(transport)
    transport.payloads[("/v1/order/trades/G1", "CASH")]["trade_list"][0]["groww_order_id"] = "OTHER"
    bound = bind_adapter("groww", GrowwAdapter(http_factory=lambda: transport), transport)

    assert await bound.port.trades() == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert transport.calls == _groww_surface_calls("trades")


@pytest.mark.asyncio
async def test_groww_trade_optional_order_id_remains_absent(bind_adapter) -> None:
    transport = _GrowwTransport()
    _groww_rows(transport)
    transport.payloads[("/v1/order/trades/G1", "CASH")]["trade_list"][0].pop("groww_order_id")
    bound = bind_adapter("groww", GrowwAdapter(http_factory=lambda: transport), transport)

    outcome = await bound.port.trades()

    assert isinstance(outcome, BrokerReadSuccess)
    assert outcome.value[0].orderid is None
    assert len(transport.calls) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed_primary", ["   ", object()])
async def test_groww_trade_id_malformed_primary_never_falls_through_to_exchange_id(
    bind_adapter,
    malformed_primary: object,
) -> None:
    transport = _GrowwTransport()
    _groww_rows(transport)
    row = transport.payloads[("/v1/order/trades/G1", "CASH")]["trade_list"][0]
    row["groww_trade_id"] = malformed_primary
    row["exchange_trade_id"] = "EX-T1"
    bound = bind_adapter("groww", GrowwAdapter(http_factory=lambda: transport), transport)

    assert await bound.port.trades() == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert transport.calls == _groww_surface_calls("trades")


@pytest.mark.asyncio
async def test_groww_holdings_is_authority_first_static_unsupported_with_zero_work(bind_adapter) -> None:
    transport = _GrowwTransport()
    _groww_rows(transport)
    bound = bind_adapter("groww", GrowwAdapter(http_factory=lambda: transport), transport)

    assert await bound.port.holdings() == BrokerReadFailure(BrokerReadErrorCode.UNSUPPORTED)
    assert bound.verifier_calls == ["verify"]
    assert bound.limiter.calls == []
    assert transport.calls == []
    assert bound.owner._active == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stale_case", "expected"),
    [
        ("closed", BrokerReadErrorCode.REVOKED),
        ("revoked", BrokerReadErrorCode.REVOKED),
        ("unauthorised", BrokerReadErrorCode.UNAUTHORISED),
        ("broker-mutated", BrokerReadErrorCode.TARGET_STALE),
        ("disconnected", BrokerReadErrorCode.DISCONNECTED),
    ],
)
async def test_groww_holdings_lifecycle_failures_outrank_static_unsupported(
    bind_adapter,
    stale_case: str,
    expected: BrokerReadErrorCode,
) -> None:
    transport = _GrowwTransport()
    _groww_rows(transport)
    bound = bind_adapter("groww", GrowwAdapter(http_factory=lambda: transport), transport)
    if stale_case == "closed":
        assert bound.owner.close(timeout=1.0)
    elif stale_case == "revoked":
        assert bound.owner.revoke(bound.port)
    elif stale_case == "unauthorised":
        bound.authority_context[0] = None
    elif stale_case == "broker-mutated":
        snapshot = read_workspace_snapshot(bound.workspace_path)

        def mutate(config: dict[str, Any]) -> None:
            config["brokers"]["failover"]["enabled"] = not config["brokers"]["failover"]["enabled"]

        compare_and_swap_workspace(bound.workspace_path, snapshot.version, mutate)
    else:
        bound.registry_owner.remove_session_for_exact(
            bound.selector,
            expected_registry=bound.registry.snapshot_selector(bound.selector),
        )

    assert await bound.port.holdings() == BrokerReadFailure(expected)
    assert bound.limiter.calls == []
    assert transport.calls == []
    assert bound.owner._active == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [False, True])
@pytest.mark.parametrize("operation", ["orders", "trades"])
@pytest.mark.parametrize("segment_index", [0, 1, 2])
async def test_groww_list_failure_stops_at_exact_segment_prefix(
    bind_adapter,
    declared: bool,
    operation: str,
    segment_index: int,
) -> None:
    transport = _GrowwTransport()
    _groww_rows(transport)
    segment = ("CASH", "FNO", "COMMODITY")[segment_index]
    key = ("/v1/order/list", segment)
    if declared:
        transport.raw_responses[key] = (200, {"status": "FAILURE", "payload": transport.payloads[key]})
    else:
        transport.errors.add(key)
    bound = bind_adapter("groww", GrowwAdapter(http_factory=lambda: transport), transport)

    if operation == "orders":
        outcome = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR))
    else:
        outcome = await bound.port.trades()

    assert outcome == BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
    assert transport.calls == _groww_list_calls(segment_index + 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [False, True])
async def test_groww_trade_detail_failure_preserves_three_lists_plus_detail(
    bind_adapter,
    declared: bool,
) -> None:
    transport = _GrowwTransport()
    _groww_rows(transport)
    key = ("/v1/order/trades/G1", "CASH")
    if declared:
        transport.raw_responses[key] = (200, {"status": "FAILURE", "payload": transport.payloads[key]})
    else:
        transport.errors.add(key)
    bound = bind_adapter("groww", GrowwAdapter(http_factory=lambda: transport), transport)

    assert await bound.port.trades() == BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
    assert transport.calls == _groww_surface_calls("trades")


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["positions", "orders"])
async def test_groww_optional_numeric_evidence_remains_absent(bind_adapter, surface: str) -> None:
    transport = _GrowwTransport()
    _groww_rows(transport)
    if surface == "positions":
        row = transport.payloads[("/v1/positions/user", None)]["positions"][0]
        row["average_price"] = 1
        row.pop("average_price")
    elif surface == "holdings":
        row = transport.payloads[("/v1/holdings/user", None)]["holdings"][0]
        row["ltp"] = 1
        row.pop("ltp")
    else:
        row = transport.payloads[("/v1/order/list", "CASH")]["order_list"][0]
        row["trigger_price"] = 1
        row.pop("price")
        row.pop("trigger_price")
    bound = bind_adapter("groww", GrowwAdapter(http_factory=lambda: transport), transport)

    if surface == "positions":
        outcome = await bound.port.positions()
        assert isinstance(outcome, BrokerReadSuccess)
        assert outcome.value[0].average_price is None
    elif surface == "holdings":
        outcome = await bound.port.holdings()
        assert isinstance(outcome, BrokerReadSuccess)
        assert outcome.value[0].ltp is None
    else:
        outcome = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR))
        assert isinstance(outcome, BrokerReadSuccess)
        assert outcome.value[0].price is outcome.value[0].trigger_price is None
    assert transport.calls == {
        "positions": [("GET", "/v1/positions/user", {})],
        "holdings": [("GET", "/v1/holdings/user", {})],
        "orders": _groww_list_calls(),
    }[surface]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("surface", "primary", "secondary"),
    [
        ("positions", "average_price", "net_price"),
        ("orders", "order_status", "status"),
    ],
)
async def test_groww_present_malformed_primary_alias_never_falls_through(
    bind_adapter,
    surface: str,
    primary: str,
    secondary: str,
) -> None:
    transport = _GrowwTransport()
    _groww_rows(transport)
    if surface == "positions":
        row = transport.payloads[("/v1/positions/user", None)]["positions"][0]
    elif surface == "holdings":
        row = transport.payloads[("/v1/holdings/user", None)]["holdings"][0]
    else:
        row = transport.payloads[("/v1/order/list", "CASH")]["order_list"][0]
    row[primary] = object() if surface == "orders" else "bad"
    row[secondary] = "OPEN" if surface == "orders" else 0
    bound = bind_adapter("groww", GrowwAdapter(http_factory=lambda: transport), transport)

    if surface == "positions":
        outcome = await bound.port.positions()
    elif surface == "holdings":
        outcome = await bound.port.holdings()
    else:
        outcome = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR))
    assert outcome == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert transport.calls == _groww_surface_calls(surface)


@pytest.mark.asyncio
async def test_groww_position_optional_blank_is_malformed(bind_adapter) -> None:
    transport = _GrowwTransport()
    _groww_rows(transport)
    row = transport.payloads[("/v1/positions/user", None)]["positions"][0]
    row["average_price"] = "  "
    bound = bind_adapter("groww", GrowwAdapter(http_factory=lambda: transport), transport)

    outcome = await bound.port.positions()

    assert outcome == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert transport.calls == _groww_surface_calls("positions")


class _IndMoneyTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.payloads: dict[object, object] = {}
        self.raw_responses: dict[str, tuple[int, object]] = {}
        self.errors: set[str] = set()

    def __call__(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, Any] | None = None,
        json_body: Any = None,
    ) -> tuple[int, object]:
        del headers, json_body
        path = url.removeprefix(INDMONEY_BASE_URL)
        copied_params = dict(params or {})
        self.calls.append((method, path, copied_params))
        if path in self.errors:
            raise RuntimeError("synthetic INDmoney transport failure")
        if path in self.raw_responses:
            return self.raw_responses[path]
        scoped_key = (path, copied_params.get("segment"), copied_params.get("product"))
        payload = self.payloads.get(scoped_key, self.payloads.get(path, {}))
        return 200, {"status": "success", "data": copy.deepcopy(payload)}


def _indmoney_rows(transport: _IndMoneyTransport) -> None:
    scoped_rows = {
        ("derivative", "margin"): ("101", "NIFTY", "NSE_FNO"),
        ("derivative", "intraday"): ("102", "SENSEX", "BSE_FNO"),
        ("equity", "cnc"): ("103", "TCS", "NSE_EQ"),
        ("equity", "intraday"): ("104", "IDEA", "BSE_EQ"),
    }
    for scope, (security_id, symbol, exchange_segment) in scoped_rows.items():
        transport.payloads[("/portfolio/positions", *scope)] = {
            "net_positions": [{
                "security_id": security_id,
                "trading_symbol": symbol,
                "exchange_segment": exchange_segment,
                "net_quantity": 0,
            }],
            "day_positions": [],
        }
    transport.payloads["/portfolio/positions"] = transport.payloads[
        ("/portfolio/positions", "derivative", "margin")
    ]
    transport.payloads["/portfolio/holdings"] = [{
        "security_id": "101",
        "trading_symbol": "TCS",
        "exchange_segment": "NSE_EQ",
        "quantity": 0,
    }]
    transport.payloads["/order-book"] = [{
        "id": "I1",
        "status": "OPEN",
        "name": "TCS",
        "security_id": "101",
        "txn_type": "BUY",
        "exchange": "NSE",
        "segment": "EQUITY",
        "product": "CNC",
        "order_type": "LIMIT",
        "requested_qty": 0,
        "traded_qty": 0,
    }]


def _indmoney_position_calls(count: int = 4) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        ("GET", "/portfolio/positions", {"segment": segment, "product": product})
        for segment, product in (
            ("derivative", "margin"),
            ("derivative", "intraday"),
            ("equity", "cnc"),
            ("equity", "intraday"),
        )[:count]
    ]


async def _invoke_indmoney_public_read(port: object, operation: str) -> object:
    instrument = InstrumentRef("TCS", "NSE", "101")
    if operation == "quote":
        return await port.quote(QuoteRequest(instrument))
    if operation == "batch_quotes":
        return await port.batch_quotes(BatchQuoteRequest((instrument,)))
    if operation == "historical":
        return await port.historical(HistoricalRequest(instrument, "1m", "2026-09-01", "2026-09-02"))
    if operation == "lot_sizes":
        return await port.lot_sizes(LotSizeRequest("NSE", ("TCS",)))
    if operation == "balance":
        return await port.balance()
    if operation == "margin":
        return await port.margin(MarginRequest("TCS", "NSE", "BUY", "1", "CNC", "LIMIT", "1", "0"))
    raise AssertionError(f"unknown INDmoney public read {operation}")


async def _invoke_indmoney_forced_instrument_read(port: object, operation: str) -> object:
    instrument = InstrumentRef("TCS", "NSE")
    if operation == "quote":
        return await port.quote(QuoteRequest(instrument))
    if operation == "batch_quotes":
        return await port.batch_quotes(BatchQuoteRequest((instrument,)))
    if operation == "historical":
        return await port.historical(HistoricalRequest(instrument, "1m", "2026-09-01", "2026-09-02"))
    if operation == "lot_sizes":
        return await port.lot_sizes(LotSizeRequest("NSE", ("TCS",)))
    if operation == "margin":
        return await port.margin(MarginRequest("TCS", "NSE", "BUY", "1", "CNC", "LIMIT", "1", "0"))
    raise AssertionError(f"unknown forced INDmoney instrument read {operation}")


def _indmoney_public_read_calls(operation: str) -> list[tuple[str, str, dict[str, Any]]]:
    if operation in {"quote", "batch_quotes"}:
        return [("GET", "/market/quotes/full", {"scrip-codes": "NSE_101"})]
    if operation == "historical":
        return [("GET", "/market/historical/1minute", {
            "scrip-codes": "NSE_101",
            "start_time": indmoney_epoch_ms("2026-09-01"),
            "end_time": indmoney_epoch_ms("2026-09-02"),
        })]
    if operation == "lot_sizes":
        return [("GET", "/market/instruments", {"source": "equity"})]
    if operation == "balance":
        return [("GET", "/funds", {})]
    if operation == "margin":
        return [("GET", "/margin", {})]
    raise AssertionError(f"unknown INDmoney public read {operation}")


@pytest.mark.asyncio
async def test_indmoney_supported_surfaces_preserve_zero_optional_absence_and_exact_ledgers(bind_adapter) -> None:
    transport = _IndMoneyTransport()
    _indmoney_rows(transport)
    bound = bind_adapter("indmoney", IndMoneyAdapter(http_factory=lambda: transport), transport)

    start = len(transport.calls)
    positions = await bound.port.positions()
    assert isinstance(positions, BrokerReadSuccess)
    assert [(row.exchange, row.product, row.instrument_id) for row in positions.value] == [
        ("NFO", "NRML", "101"),
        ("BFO", "MIS", "102"),
        ("NSE", "CNC", "103"),
        ("BSE", "MIS", "104"),
    ]
    assert all(row.quantity == "0" and row.average_price is None for row in positions.value)
    assert [call[1] for call in transport.calls[start:]] == ["/portfolio/positions"] * 4

    start = len(transport.calls)
    holdings = await bound.port.holdings()
    assert isinstance(holdings, BrokerReadSuccess)
    assert holdings.value[0].quantity == "0"
    assert holdings.value[0].instrument_id == "101"
    assert holdings.value[0].average_price is None
    assert [call[1] for call in transport.calls[start:]] == ["/portfolio/holdings"]

    start = len(transport.calls)
    orders = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR))
    assert isinstance(orders, BrokerReadSuccess)
    assert orders.value[0].quantity == orders.value[0].filled_quantity == "0"
    assert orders.value[0].instrument_id == "101"
    assert [call[1] for call in transport.calls[start:]] == ["/order-book"]

    start = len(transport.calls)
    trades = await bound.port.trades()
    forever = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER))
    super_orders = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.SUPER))
    assert trades == forever == super_orders == BrokerReadFailure(BrokerReadErrorCode.UNSUPPORTED)
    assert transport.calls[start:] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("surface", "payload"),
    [
        ("positions", []),
        ("positions", {"net_positions": {}, "day_positions": []}),
        ("positions", {"net_positions": ["bad-row"], "day_positions": []}),
        ("holdings", {}),
        ("holdings", ["bad-row"]),
        ("orders", {}),
        ("orders", ["bad-row"]),
    ],
)
async def test_indmoney_fixed_surfaces_reject_malformed_envelopes_containers_and_rows(
    bind_adapter,
    surface: str,
    payload: object,
) -> None:
    transport = _IndMoneyTransport()
    _indmoney_rows(transport)
    path = {
        "positions": "/portfolio/positions",
        "holdings": "/portfolio/holdings",
        "orders": "/order-book",
    }[surface]
    if surface == "positions":
        transport.payloads[(path, "derivative", "margin")] = payload
    else:
        transport.payloads[path] = payload
    bound = bind_adapter("indmoney", IndMoneyAdapter(http_factory=lambda: transport), transport)

    if surface == "positions":
        outcome = await bound.port.positions()
    elif surface == "holdings":
        outcome = await bound.port.holdings()
    else:
        outcome = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR))
    assert outcome == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert transport.calls == (
        _indmoney_position_calls(1)
        if surface == "positions"
        else [("GET", path, {})]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("outer", [{"data": None}, {"status": 1, "data": None}])
@pytest.mark.parametrize("surface", ["positions", "holdings", "orders"])
async def test_indmoney_fixed_surfaces_reject_malformed_outer_envelopes(
    bind_adapter,
    surface: str,
    outer: dict[str, object],
) -> None:
    transport = _IndMoneyTransport()
    _indmoney_rows(transport)
    path = {
        "positions": "/portfolio/positions",
        "holdings": "/portfolio/holdings",
        "orders": "/order-book",
    }[surface]
    response = dict(outer)
    response["data"] = copy.deepcopy(transport.payloads[path])
    transport.raw_responses[path] = (200, response)
    bound = bind_adapter("indmoney", IndMoneyAdapter(http_factory=lambda: transport), transport)

    if surface == "positions":
        outcome = await bound.port.positions()
    elif surface == "holdings":
        outcome = await bound.port.holdings()
    else:
        outcome = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR))
    assert outcome == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert transport.calls == (
        _indmoney_position_calls(1)
        if surface == "positions"
        else [("GET", path, {})]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["positions", "holdings", "orders"])
async def test_indmoney_fixed_status_rejects_string_hook_without_execution(
    bind_adapter,
    surface: str,
) -> None:
    class StringTrap:
        def __init__(self) -> None:
            self.calls = 0

        def __str__(self) -> str:
            self.calls += 1
            raise AssertionError("untrusted fixed status string hook must not run")

    transport = _IndMoneyTransport()
    _indmoney_rows(transport)
    path = {
        "positions": "/portfolio/positions",
        "holdings": "/portfolio/holdings",
        "orders": "/order-book",
    }[surface]
    trap = StringTrap()
    transport.raw_responses[path] = (200, {"status": trap, "data": copy.deepcopy(transport.payloads[path])})
    bound = bind_adapter("indmoney", IndMoneyAdapter(http_factory=lambda: transport), transport)

    if surface == "positions":
        outcome = await bound.port.positions()
    elif surface == "holdings":
        outcome = await bound.port.holdings()
    else:
        outcome = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR))

    assert (outcome, trap.calls) == (
        BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE),
        0,
    )
    assert transport.calls == (
        _indmoney_position_calls(1)
        if surface == "positions"
        else [("GET", path, {})]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "path"),
    [
        ("quote", "/market/quotes/full"),
        ("batch_quotes", "/market/quotes/full"),
        ("historical", "/market/historical/1minute"),
        ("lot_sizes", "/market/instruments"),
        ("balance", "/funds"),
        ("margin", "/margin"),
    ],
)
async def test_indmoney_every_supported_public_read_rejects_response_hooks_without_execution(
    bind_adapter,
    operation: str,
    path: str,
) -> None:
    class ResponseTrap:
        def __init__(self) -> None:
            self.calls = 0

        def __str__(self) -> str:
            self.calls += 1
            raise AssertionError("untrusted INDmoney response string hook must not run")

    transport = _IndMoneyTransport()
    _indmoney_rows(transport)
    trap = ResponseTrap()
    payload: object = trap if operation == "lot_sizes" else {"status": trap, "data": {}}
    transport.raw_responses[path] = (200, payload)
    adapter = IndMoneyAdapter(
        http_factory=lambda: transport,
        security_resolver=lambda _symbol, _exchange: "101",
    )
    bound = bind_adapter("indmoney", adapter, transport)

    outcome = await _invoke_indmoney_public_read(bound.port, operation)

    assert (outcome, trap.calls) == (
        BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE),
        0,
    )
    assert transport.calls == _indmoney_public_read_calls(operation)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["quote", "historical", "margin"])
async def test_indmoney_forced_instrument_resolution_rejects_payload_hook_before_downstream_read(
    bind_adapter,
    operation: str,
) -> None:
    class PayloadTrap:
        def __init__(self) -> None:
            self.calls = 0

        def __str__(self) -> str:
            self.calls += 1
            raise AssertionError("untrusted INDmoney instruments payload string hook must not run")

    transport = _IndMoneyTransport()
    _indmoney_rows(transport)
    trap = PayloadTrap()
    transport.raw_responses["/market/instruments"] = (200, trap)
    bound = bind_adapter("indmoney", IndMoneyAdapter(http_factory=lambda: transport), transport)

    outcome = await _invoke_indmoney_public_read(bound.port, operation)

    assert (outcome, trap.calls) == (
        BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE),
        0,
    )
    assert transport.calls == [("GET", "/market/instruments", {"source": "equity"})]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["lot_sizes", "quote", "batch_quotes", "historical", "margin"])
async def test_indmoney_strict_instruments_parse_failure_is_malformed_before_downstream_read(
    bind_adapter,
    operation: str,
) -> None:
    oversized_field = "X" * (csv.field_size_limit() + 1)
    csv_text = (
        "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,SYMBOL_NAME,LOT_UNITS\n"
        f"NSE,E,101,TCS,{oversized_field},1\n"
    )
    transport = _IndMoneyTransport()
    transport.raw_responses["/market/instruments"] = (200, csv_text)
    bound = bind_adapter("indmoney", IndMoneyAdapter(http_factory=lambda: transport), transport)
    instrument = InstrumentRef("TCS", "NSE")

    if operation == "lot_sizes":
        outcome = await bound.port.lot_sizes(LotSizeRequest("NSE", ("TCS",)))
    elif operation == "quote":
        outcome = await bound.port.quote(QuoteRequest(instrument))
    elif operation == "batch_quotes":
        outcome = await bound.port.batch_quotes(BatchQuoteRequest((instrument,)))
    elif operation == "historical":
        outcome = await bound.port.historical(HistoricalRequest(instrument, "1m", "2026-09-01", "2026-09-02"))
    else:
        outcome = await bound.port.margin(MarginRequest("TCS", "NSE", "BUY", "1", "CNC", "LIMIT", "1", "0"))

    assert outcome == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert transport.calls == [("GET", "/market/instruments", {"source": "equity"})]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["lot_sizes", "quote", "batch_quotes", "historical", "margin"])
@pytest.mark.parametrize(
    "csv_text",
    [
        "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,SYMBOL_NAME,LOT_UNITS\nNSE,E,101,TCS,TCS,1,OVERFLOW\n",
        "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,SYMBOL_NAME,LOT_UNITS,OPTIONAL\nNSE,E,101,TCS,TCS,1\n",
        "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,EXCH,LOT_UNITS\nNSE,E,101,TCS,NSE,1\n",
        "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL, exch ,LOT_UNITS\nNSE,E,101,TCS,NSE,1\n",
        "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,,LOT_UNITS\nNSE,E,101,TCS,optional,1\n",
        "EXCH, SEGMENT,SECURITY_ID,TRADING_SYMBOL,LOT_UNITS\nNSE,E,101,TCS,1\n",
        "",
        "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,LOT_UNITS\n",
        "EXCH,SEGMENT,TRADING_SYMBOL,LOT_UNITS\nNSE,E,TCS,1\n",
        "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,LOT_UNITS\n,E,101,TCS,1\n",
        "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,LOT_UNITS\nNSE,,101,TCS,1\n",
        "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,LOT_UNITS\nNSE,E,,TCS,1\n",
        "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,LOT_UNITS\nNSE,E,101,,1\n",
    ],
    ids=[
        "overflow-cell",
        "missing-cell",
        "duplicate-header",
        "duplicate-case-whitespace-header",
        "blank-header",
        "whitespace-header",
        "empty",
        "header-only",
        "missing-security-id-header",
        "blank-exchange",
        "blank-segment",
        "blank-security-id",
        "blank-trading-symbol",
    ],
)
async def test_indmoney_strict_instrument_schema_rejects_malformed_csv_before_every_downstream_read(
    bind_adapter,
    operation: str,
    csv_text: str,
) -> None:
    transport = _IndMoneyTransport()
    transport.raw_responses["/market/instruments"] = (200, csv_text)
    bound = bind_adapter("indmoney", IndMoneyAdapter(http_factory=lambda: transport), transport)

    outcome = await _invoke_indmoney_forced_instrument_read(bound.port, operation)

    assert outcome == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert transport.calls == [("GET", "/market/instruments", {"source": "equity"})]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "csv_text",
    [
        "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,LOT_UNITS\nNSE,E,101,TCS,1,OVERFLOW\n",
        "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,LOT_UNITS,OPTIONAL\nNSE,E,101,TCS,1\n",
        "EXCH,SEGMENT,SECURITY_ID,EXCH,LOT_UNITS\nNSE,E,101,NSE,1\n",
        "EXCH,SEGMENT,SECURITY_ID, exch ,LOT_UNITS\nNSE,E,101,NSE,1\n",
        "EXCH,SEGMENT,SECURITY_ID,,LOT_UNITS\nNSE,E,101,TCS,1\n",
        "EXCH, SEGMENT,SECURITY_ID,TRADING_SYMBOL,LOT_UNITS\nNSE,E,101,TCS,1\n",
        "",
        "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,LOT_UNITS\n",
        "EXCH,SEGMENT,TRADING_SYMBOL,LOT_UNITS\nNSE,E,TCS,1\n",
    ],
    ids=[
        "overflow-cell",
        "optional-underflow",
        "duplicate-header",
        "duplicate-case-whitespace-header",
        "blank-header",
        "whitespace-header",
        "empty",
        "header-only",
        "missing-security-id-header",
    ],
)
async def test_indmoney_strict_instrument_structure_failure_preserves_seeded_cache(csv_text: str) -> None:
    transport = _IndMoneyTransport()
    transport.raw_responses["/market/instruments"] = (200, csv_text)
    adapter = IndMoneyAdapter(http_factory=lambda: transport)
    session = Session("synthetic-token", time.time() + 3600, "Synthetic", "indmoney")
    sentinel = {"SENTINEL": [({"EXCH": "NSE"}, "999")]}
    seeded_cache = {"equity": sentinel}
    session.extra["indmoney_instrument_index"] = seeded_cache

    with pytest.raises(BrokerReadResponseInvalid):
        await adapter._strict_instruments(session, "equity")

    assert session.extra["indmoney_instrument_index"] is seeded_cache
    assert session.extra["indmoney_instrument_index"] == {"equity": sentinel}
    assert transport.calls == [("GET", "/market/instruments", {"source": "equity"})]


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [True, "EQUITY", " equity", "equity ", "crypto", "index\n"])
async def test_indmoney_strict_instruments_rejects_non_exact_or_unsupported_source_without_request(
    source: object,
) -> None:
    transport = _IndMoneyTransport()
    adapter = IndMoneyAdapter(http_factory=lambda: transport)
    session = Session("synthetic-token", time.time() + 3600, "Synthetic", "indmoney")

    with pytest.raises(BrokerReadResponseInvalid):
        await adapter._strict_instruments(session, source)  # type: ignore[arg-type]

    assert transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source", "csv_text"),
    [
        (
            "equity",
            "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,OPTIONAL,EMPTY\nNSE,E,101,TCS,value,\n",
        ),
        (
            "fno",
            "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,SYMBOL_NAME,EXTRA\n"
            "NSE,FNO,201,NIFTY26SEP,NIFTY,\n",
        ),
        ("index", "EXCH,SEGMENT,SECURITY_ID,OPTIONAL\nNSE,NIFTY 50,301,\n"),
    ],
)
async def test_indmoney_strict_instruments_accepts_documented_sources_and_labelled_optional_columns(
    source: str,
    csv_text: str,
) -> None:
    transport = _IndMoneyTransport()
    transport.raw_responses["/market/instruments"] = (200, csv_text)
    adapter = IndMoneyAdapter(http_factory=lambda: transport)
    session = Session("synthetic-token", time.time() + 3600, "Synthetic", "indmoney")

    rows = await adapter._strict_instruments(session, source)

    assert len(rows) == 1
    assert all(type(key) is str and type(value) is str for key, value in rows[0].items())
    assert transport.calls == [("GET", "/market/instruments", {"source": source})]


@pytest.mark.asyncio
async def test_indmoney_strict_instrument_index_deduplicates_identical_rows_and_feeds_legacy_cache() -> None:
    csv_text = (
        "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,SYMBOL_NAME,CUSTOM_SYMBOL\n"
        "NSE,E,101,TCS,Tata Consultancy,TCS-EQ\n"
        "NSE,E,101,TCS,Tata Consultancy,TCS-EQ\n"
    )
    transport = _IndMoneyTransport()
    transport.raw_responses["/market/instruments"] = (200, csv_text)
    adapter = IndMoneyAdapter(http_factory=lambda: transport)
    session = Session("synthetic-token", time.time() + 3600, "Synthetic", "indmoney")

    assert await adapter._resolve_security_for_session(session, "TCS", "NSE", strict_read=True) == "101"
    index = session.extra["indmoney_instrument_index"]
    assert len(index[("strict-read", "equity")]["TCS"]) == 1
    assert index["equity"] is index[("strict-read", "equity")]
    assert await adapter._resolve_security_for_session(session, "TCS", "NSE") == "101"
    assert transport.calls == [("GET", "/market/instruments", {"source": "equity"})]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("csv_text", "symbol", "exchange"),
    [
        (
            "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,SYMBOL_NAME\n"
            "NSE,E,101,TCS,Tata Consultancy\nNSE,E,102,TCS,TCS Limited\n",
            "TCS",
            "NSE",
        ),
        (
            "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,SYMBOL_NAME\n"
            "NSE,FNO,201,NIFTY26SEP25000CE,NIFTY\nNSE,FNO,202,NIFTY26SEP25100CE,NIFTY\n",
            "NIFTY",
            "NFO",
        ),
    ],
    ids=["conflicting-trading-symbol", "ambiguous-fno-description"],
)
async def test_indmoney_strict_resolution_rejects_ambiguous_identity_without_publishing_cache(
    csv_text: str,
    symbol: str,
    exchange: str,
) -> None:
    transport = _IndMoneyTransport()
    transport.raw_responses["/market/instruments"] = (200, csv_text)
    adapter = IndMoneyAdapter(http_factory=lambda: transport)
    session = Session("synthetic-token", time.time() + 3600, "Synthetic", "indmoney")
    sentinel = {"SENTINEL": [({"EXCH": "NSE"}, "999")]}
    session.extra["indmoney_instrument_index"] = {"equity": sentinel}

    with pytest.raises(BrokerReadResponseInvalid):
        await adapter._resolve_security_for_session(session, symbol, exchange, strict_read=True)

    assert session.extra["indmoney_instrument_index"] == {"equity": sentinel}
    assert transport.calls == [("GET", "/market/instruments", {"source": adapter._instrument_source_for_exchange(exchange)})]


@pytest.mark.asyncio
async def test_indmoney_strict_resolution_prioritises_exact_trading_symbol_over_descriptive_alias() -> None:
    csv_text = (
        "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,SYMBOL_NAME\n"
        "NSE,E,101,TCS,Tata Consultancy\n"
        "NSE,E,102,OTHER,TCS\n"
    )
    transport = _IndMoneyTransport()
    transport.raw_responses["/market/instruments"] = (200, csv_text)
    adapter = IndMoneyAdapter(http_factory=lambda: transport)
    session = Session("synthetic-token", time.time() + 3600, "Synthetic", "indmoney")

    assert await adapter._resolve_security_for_session(session, "TCS", "NSE", strict_read=True) == "101"


@pytest.mark.asyncio
async def test_indmoney_batch_resolution_failure_restores_entire_seeded_instrument_cache() -> None:
    csv_text = (
        "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,SYMBOL_NAME\n"
        "NSE,E,101,TCS,Tata Consultancy\n"
        "NSE,E,201,ONE,AMBIGUOUS\n"
        "NSE,E,202,TWO,AMBIGUOUS\n"
    )
    transport = _IndMoneyTransport()
    transport.raw_responses["/market/instruments"] = (200, csv_text)
    adapter = IndMoneyAdapter(http_factory=lambda: transport)
    session = Session("synthetic-token", time.time() + 3600, "Synthetic", "indmoney")
    sentinel = {"SENTINEL": [({"EXCH": "NSE"}, "999")]}
    seeded_cache = {"equity": sentinel}
    session.extra["indmoney_instrument_index"] = seeded_cache

    with pytest.raises(BrokerReadResponseInvalid):
        await adapter.quotes(session, ["NSE:TCS", "NSE:AMBIGUOUS"])

    assert session.extra["indmoney_instrument_index"] is seeded_cache
    assert session.extra["indmoney_instrument_index"] == {"equity": sentinel}
    assert transport.calls == [("GET", "/market/instruments", {"source": "equity"})]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["quote", "batch_quotes"])
async def test_indmoney_missing_requested_quote_rows_fail_before_seeded_cache_publication(
    bind_adapter,
    operation: str,
) -> None:
    csv_text = (
        "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,SYMBOL_NAME\n"
        "NSE,E,101,TCS,TCS\n"
        "NSE,E,102,INFY,INFY\n"
    )
    transport = _IndMoneyTransport()
    transport.raw_responses["/market/instruments"] = (200, csv_text)
    quote_data = {} if operation == "quote" else {"NSE_101": {}}
    transport.raw_responses["/market/quotes/full"] = (200, {"status": "success", "data": quote_data})
    sentinel = {"SENTINEL": [({"EXCH": "NSE"}, "999")]}
    seeded_cache = {"equity": sentinel}
    observed_sessions: list[object] = []

    class SeededCacheAdapter(IndMoneyAdapter):
        async def quotes(self, session, symbols):
            session.extra["indmoney_instrument_index"] = seeded_cache
            observed_sessions.append(session)
            return await super().quotes(session, symbols)

    bound = bind_adapter("indmoney", SeededCacheAdapter(http_factory=lambda: transport), transport)

    if operation == "quote":
        outcome = await bound.port.quote(QuoteRequest(InstrumentRef("TCS", "NSE")))
        scrip_codes = "NSE_101"
    else:
        outcome = await bound.port.batch_quotes(
            BatchQuoteRequest((InstrumentRef("TCS", "NSE"), InstrumentRef("INFY", "NSE")))
        )
        scrip_codes = "NSE_101,NSE_102"

    assert outcome == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert len(observed_sessions) == 1
    session = observed_sessions[0]
    assert session.extra["indmoney_instrument_index"] is seeded_cache
    assert session.extra["indmoney_instrument_index"] == {"equity": sentinel}
    assert transport.calls == [
        ("GET", "/market/instruments", {"source": "equity"}),
        ("GET", "/market/quotes/full", {"scrip-codes": scrip_codes}),
    ]


@pytest.mark.asyncio
async def test_indmoney_mixed_source_batch_never_exposes_partially_staged_cache() -> None:
    equity_csv = "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,SYMBOL_NAME\nNSE,E,101,TCS,TCS\n"
    fno_csv = (
        "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,SYMBOL_NAME\n"
        "NSE,FNO,201,ONE,AMBIGUOUS\n"
        "NSE,FNO,202,TWO,AMBIGUOUS\n"
    )
    session_ref: list[Session] = []
    observed_seed_identity: list[bool] = []

    class MixedSourceTransport(_IndMoneyTransport):
        def __call__(self, method, url, *, headers, params=None, json_body=None):
            path = url.removeprefix(INDMONEY_BASE_URL)
            if path != "/market/instruments":
                return super().__call__(method, url, headers=headers, params=params, json_body=json_body)
            copied_params = dict(params or {})
            self.calls.append((method, path, copied_params))
            observed_seed_identity.append(session_ref[0].extra["indmoney_instrument_index"] is seeded_cache)
            return 200, equity_csv if copied_params["source"] == "equity" else fno_csv

    transport = MixedSourceTransport()
    adapter = IndMoneyAdapter(http_factory=lambda: transport)
    session = Session("synthetic-token", time.time() + 3600, "Synthetic", "indmoney")
    session_ref.append(session)
    sentinel = {"SENTINEL": [({"EXCH": "NSE"}, "999")]}
    seeded_cache = {"equity": sentinel}
    session.extra["indmoney_instrument_index"] = seeded_cache

    with pytest.raises(BrokerReadResponseInvalid):
        await adapter.quotes(session, ["NSE:TCS", "NFO:AMBIGUOUS"])

    assert observed_seed_identity == [True, True]
    assert session.extra["indmoney_instrument_index"] is seeded_cache
    assert transport.calls == [
        ("GET", "/market/instruments", {"source": "equity"}),
        ("GET", "/market/instruments", {"source": "fno"}),
    ]


@pytest.mark.asyncio
async def test_indmoney_strict_index_uses_index_segment_as_source_aware_identity() -> None:
    transport = _IndMoneyTransport()
    transport.raw_responses["/market/instruments"] = (
        200,
        "EXCH,SEGMENT,SECURITY_ID,OPTIONAL\nNSE,NIFTY 50,301,\n",
    )
    adapter = IndMoneyAdapter(http_factory=lambda: transport)
    session = Session("synthetic-token", time.time() + 3600, "Synthetic", "indmoney")

    assert await adapter._resolve_security_for_session(session, "NIFTY 50", "NSE_INDEX", strict_read=True) == "301"


@pytest.mark.asyncio
async def test_indmoney_strict_index_rejects_unrequested_conflicting_segment_before_cache_publication() -> None:
    transport = _IndMoneyTransport()
    transport.raw_responses["/market/instruments"] = (
        200,
        "EXCH,SEGMENT,SECURITY_ID\n"
        "NSE,NIFTY 50,301\n"
        "NSE,NIFTY BANK,302\n"
        "NSE,NIFTY BANK,303\n",
    )
    adapter = IndMoneyAdapter(http_factory=lambda: transport)
    session = Session("synthetic-token", time.time() + 3600, "Synthetic", "indmoney")
    sentinel = {"SENTINEL": [({"EXCH": "NSE"}, "999")]}
    seeded_cache = {"index": sentinel}
    session.extra["indmoney_instrument_index"] = seeded_cache

    with pytest.raises(BrokerReadResponseInvalid):
        await adapter._resolve_security_for_session(session, "NIFTY 50", "NSE_INDEX", strict_read=True)

    assert session.extra["indmoney_instrument_index"] is seeded_cache
    assert session.extra["indmoney_instrument_index"] == {"index": sentinel}
    assert transport.calls == [("GET", "/market/instruments", {"source": "index"})]


@pytest.mark.asyncio
async def test_indmoney_lot_sizes_allows_blank_unrelated_cells_but_requires_selected_canonical_evidence(
    bind_adapter,
) -> None:
    csv_text = (
        "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,LOT_UNITS,OPTIONAL\n"
        "NSE,E,,OTHER, ,\n"
        "NSE,E,101,TCS,1,\n"
    )
    transport = _IndMoneyTransport()
    transport.raw_responses["/market/instruments"] = (200, csv_text)
    bound = bind_adapter("indmoney", IndMoneyAdapter(http_factory=lambda: transport), transport)

    outcome = await bound.port.lot_sizes(LotSizeRequest("NSE", ("TCS",)))

    assert isinstance(outcome, BrokerReadSuccess)
    assert [(row.symbol, row.exchange, row.lot_size, row.instrument_id) for row in outcome.value] == [
        ("TCS", "NSE", 1, "101")
    ]


@pytest.mark.asyncio
async def test_indmoney_lot_sizes_skips_fixed_width_all_blank_row_without_hiding_selected_row() -> None:
    csv_text = (
        "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,LOT_UNITS,OPTIONAL\n"
        ",,,,,\n"
        "NSE,E,101,TCS,1,\n"
    )
    transport = _IndMoneyTransport()
    transport.raw_responses["/market/instruments"] = (200, csv_text)
    adapter = IndMoneyAdapter(http_factory=lambda: transport)
    session = Session("synthetic-token", time.time() + 3600, "Synthetic", "indmoney")

    rows = await adapter.instrument_lot_sizes(session, LotSizeRequest("NSE", ("TCS",)))

    assert rows == [{"symbol": "TCS", "exchange": "NSE", "lot_size": 1, "instrument_id": "101"}]
    assert "indmoney_instrument_index" not in session.extra
    assert transport.calls == [("GET", "/market/instruments", {"source": "equity"})]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row",
    [
        ",E,101,TCS,1",
        "NSE,E,101,,1",
        "NSE,E,,TCS,1",
        "NSE,E,101,TCS,0",
        "NSE,E,101,TCS,01",
        "NSE,E,101,TCS, 1 ",
    ],
    ids=[
        "blank-exchange",
        "blank-trading-symbol",
        "blank-security-id",
        "zero-lot",
        "noncanonical-lot",
        "whitespace-lot",
    ],
)
async def test_indmoney_lot_sizes_rejects_incomplete_selected_row_evidence(
    bind_adapter,
    row: str,
) -> None:
    transport = _IndMoneyTransport()
    transport.raw_responses["/market/instruments"] = (
        200,
        f"EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,LOT_UNITS\n{row}\n",
    )
    bound = bind_adapter("indmoney", IndMoneyAdapter(http_factory=lambda: transport), transport)

    assert await bound.port.lot_sizes(LotSizeRequest("NSE", ("TCS",))) == BrokerReadFailure(
        BrokerReadErrorCode.MALFORMED_RESPONSE
    )
    assert transport.calls == [("GET", "/market/instruments", {"source": "equity"})]


@pytest.mark.asyncio
async def test_indmoney_lot_sizes_rejects_selected_blank_segment_without_mutating_seeded_cache() -> None:
    transport = _IndMoneyTransport()
    transport.raw_responses["/market/instruments"] = (
        200,
        "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,LOT_UNITS\nNSE,,101,TCS,1\n",
    )
    adapter = IndMoneyAdapter(http_factory=lambda: transport)
    session = Session("synthetic-token", time.time() + 3600, "Synthetic", "indmoney")
    sentinel = {"SENTINEL": [({"EXCH": "NSE"}, "999")]}
    session.extra["indmoney_instrument_index"] = {"equity": sentinel}

    with pytest.raises(BrokerLotSizeResponseInvalid):
        await adapter.instrument_lot_sizes(session, LotSizeRequest("NSE", ("TCS",)))

    assert session.extra["indmoney_instrument_index"] == {"equity": sentinel}
    assert transport.calls == [("GET", "/market/instruments", {"source": "equity"})]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_value", [None, object()])
async def test_indmoney_strict_instruments_rejects_non_string_parser_cells(
    monkeypatch,
    bad_value: object,
) -> None:
    transport = _IndMoneyTransport()
    csv_text = "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL\nNSE,E,101,TCS\n"
    transport.raw_responses["/market/instruments"] = (200, csv_text)
    adapter = IndMoneyAdapter(http_factory=lambda: transport)
    session = Session("synthetic-token", time.time() + 3600, "Synthetic", "indmoney")
    monkeypatch.setattr(
        "flinttrade_gateway.brokers.indmoney.M.parse_instruments_csv",
        lambda _payload: [{"EXCH": "NSE", "SEGMENT": "E", "SECURITY_ID": "101", "TRADING_SYMBOL": bad_value}],
    )

    with pytest.raises(BrokerReadResponseInvalid):
        await adapter._strict_instruments(session, "equity")


@pytest.mark.asyncio
async def test_indmoney_strict_read_resolution_never_reuses_legacy_permissive_cache() -> None:
    csv_text = "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,SYMBOL_NAME\nNSE,E,101,TCS,TCS\n"

    class LegacyText:
        def __init__(self) -> None:
            self.calls = 0

        def __str__(self) -> str:
            self.calls += 1
            return csv_text

    class StrictTrap:
        def __init__(self) -> None:
            self.calls = 0

        def __str__(self) -> str:
            self.calls += 1
            raise AssertionError("strict INDmoney instrument resolution must not coerce the payload")

    transport = _IndMoneyTransport()
    legacy = LegacyText()
    transport.raw_responses["/market/instruments"] = (200, legacy)
    adapter = IndMoneyAdapter(http_factory=lambda: transport)
    session = Session("synthetic-token", time.time() + 3600, "Synthetic", "indmoney")

    assert await adapter.ltp(session, ["NSE:TCS"]) == {}
    trap = StrictTrap()
    transport.raw_responses["/market/instruments"] = (200, trap)

    with pytest.raises(BrokerReadResponseInvalid):
        await adapter.quotes(session, ["NSE:TCS"])

    assert (legacy.calls, trap.calls) == (1, 0)
    assert transport.calls == [
        ("GET", "/market/instruments", {"source": "equity"}),
        ("GET", "/market/quotes/ltp", {"scrip-codes": "NSE_101"}),
        ("GET", "/market/instruments", {"source": "equity"}),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "path", "payload_factory"),
    [
        ("quote", "/market/quotes/full", lambda trap: trap),
        ("batch_quotes", "/market/quotes/full", lambda trap: trap),
        ("quote", "/market/quotes/full", lambda trap: {"NSE_101": {"live_price": trap}}),
        (
            "quote",
            "/market/quotes/full",
            lambda trap: {"NSE_101": {"live_price": 1, "market_depth": {"depth": trap}}},
        ),
        ("historical", "/market/historical/1minute", lambda trap: trap),
        ("historical", "/market/historical/1minute", lambda trap: {"candles": trap}),
        ("historical", "/market/historical/1minute", lambda trap: {"candles": [[trap, 1, 1, 1, 1, 1]]}),
        ("historical", "/market/historical/1minute", lambda trap: {"candles": [trap]}),
        ("margin", "/margin", lambda trap: {"total_margin": trap}),
        ("margin", "/margin", lambda trap: {"charges": trap}),
    ],
)
async def test_indmoney_strict_success_data_rejects_inner_hooks_without_execution(
    bind_adapter,
    operation: str,
    path: str,
    payload_factory,
) -> None:
    class InnerTrap:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def __bool__(self) -> bool:
            self.calls.append("bool")
            raise AssertionError("untrusted INDmoney response bool hook must not run")

        def __iter__(self):
            self.calls.append("iter")
            raise AssertionError("untrusted INDmoney response iter hook must not run")

        def __float__(self) -> float:
            self.calls.append("float")
            raise AssertionError("untrusted INDmoney response float hook must not run")

        def __str__(self) -> str:
            self.calls.append("str")
            raise AssertionError("untrusted INDmoney response string hook must not run")

    transport = _IndMoneyTransport()
    _indmoney_rows(transport)
    trap = InnerTrap()
    transport.raw_responses[path] = (200, {"status": "success", "data": payload_factory(trap)})
    adapter = IndMoneyAdapter(
        http_factory=lambda: transport,
        security_resolver=lambda _symbol, _exchange: "101",
    )
    bound = bind_adapter("indmoney", adapter, transport)

    outcome = await _invoke_indmoney_public_read(bound.port, operation)

    assert (outcome, trap.calls) == (
        BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE),
        [],
    )
    assert transport.calls == _indmoney_public_read_calls(operation)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_value", [True, float("inf"), "", "not-a-number"])
@pytest.mark.parametrize(
    ("operation", "path", "payload_factory"),
    [
        ("quote", "/market/quotes/full", lambda value: {"NSE_101": {"live_price": value}}),
        (
            "historical",
            "/market/historical/1minute",
            lambda value: {"candles": [[1, value, 1, 1, 1, 1]]},
        ),
        ("margin", "/margin", lambda value: {"total_margin": value}),
    ],
)
async def test_indmoney_strict_success_data_rejects_malformed_numeric_evidence(
    bind_adapter,
    operation: str,
    path: str,
    payload_factory,
    bad_value: object,
) -> None:
    transport = _IndMoneyTransport()
    _indmoney_rows(transport)
    transport.raw_responses[path] = (200, {"status": "success", "data": payload_factory(bad_value)})
    adapter = IndMoneyAdapter(
        http_factory=lambda: transport,
        security_resolver=lambda _symbol, _exchange: "101",
    )
    bound = bind_adapter("indmoney", adapter, transport)

    assert await _invoke_indmoney_public_read(bound.port, operation) == BrokerReadFailure(
        BrokerReadErrorCode.MALFORMED_RESPONSE
    )
    assert transport.calls == _indmoney_public_read_calls(operation)


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["cycle", "deep"])
async def test_indmoney_strict_success_data_rejects_recursive_quote_graphs(
    bind_adapter,
    shape: str,
) -> None:
    if shape == "cycle":
        quote: dict[str, object] = {}
        quote["nested"] = quote
    else:
        quote = {}
        cursor = quote
        for _ in range(1_200):
            child: dict[str, object] = {}
            cursor["nested"] = child
            cursor = child

    transport = _IndMoneyTransport()
    _indmoney_rows(transport)
    transport.raw_responses["/market/quotes/full"] = (
        200,
        {"status": "success", "data": {"NSE_101": quote}},
    )
    adapter = IndMoneyAdapter(
        http_factory=lambda: transport,
        security_resolver=lambda _symbol, _exchange: "101",
    )
    bound = bind_adapter("indmoney", adapter, transport)

    assert await _invoke_indmoney_public_read(bound.port, "quote") == BrokerReadFailure(
        BrokerReadErrorCode.MALFORMED_RESPONSE
    )
    assert transport.calls == [("GET", "/market/quotes/full", {"scrip-codes": "NSE_101"})]


@pytest.mark.asyncio
async def test_indmoney_declared_failure_message_does_not_execute_hooks(bind_adapter) -> None:
    class MessageTrap:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def __bool__(self) -> bool:
            self.calls.append("bool")
            raise AssertionError("untrusted INDmoney error-message bool hook must not run")

        def __str__(self) -> str:
            self.calls.append("str")
            raise AssertionError("untrusted INDmoney error-message string hook must not run")

        def __format__(self, _format_spec: str) -> str:
            self.calls.append("format")
            raise AssertionError("untrusted INDmoney error-message format hook must not run")

    transport = _IndMoneyTransport()
    _indmoney_rows(transport)
    trap = MessageTrap()
    transport.raw_responses["/portfolio/holdings"] = (
        200,
        {"status": "error", "data": [], "message": trap},
    )
    bound = bind_adapter("indmoney", IndMoneyAdapter(http_factory=lambda: transport), transport)

    assert await bound.port.holdings() == BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
    assert trap.calls == []
    assert transport.calls == [("GET", "/portfolio/holdings", {})]


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["message", "error_type", "error_code"])
async def test_indmoney_strict_http_error_fields_do_not_execute_hooks(
    bind_adapter,
    field: str,
) -> None:
    class ErrorFieldTrap:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def __bool__(self) -> bool:
            self.calls.append("bool")
            raise AssertionError("untrusted INDmoney HTTP-error bool hook must not run")

        def __str__(self) -> str:
            self.calls.append("str")
            raise AssertionError("untrusted INDmoney HTTP-error string hook must not run")

        def __format__(self, _format_spec: str) -> str:
            self.calls.append("format")
            raise AssertionError("untrusted INDmoney HTTP-error format hook must not run")

        def __repr__(self) -> str:
            self.calls.append("repr")
            raise AssertionError("untrusted INDmoney HTTP-error repr hook must not run")

    transport = _IndMoneyTransport()
    _indmoney_rows(transport)
    trap = ErrorFieldTrap()
    payload: dict[str, object] = {"message": "synthetic", field: trap}
    transport.raw_responses["/portfolio/holdings"] = (400, payload)
    bound = bind_adapter("indmoney", IndMoneyAdapter(http_factory=lambda: transport), transport)

    assert await bound.port.holdings() == BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
    assert trap.calls == []
    assert transport.calls == [("GET", "/portfolio/holdings", {})]


@pytest.mark.asyncio
async def test_indmoney_declared_outer_failure_remains_provider_failure(bind_adapter) -> None:
    transport = _IndMoneyTransport()
    _indmoney_rows(transport)
    transport.raw_responses["/portfolio/holdings"] = (
        200,
        {"status": "error", "data": transport.payloads["/portfolio/holdings"], "message": "synthetic"},
    )
    bound = bind_adapter("indmoney", IndMoneyAdapter(http_factory=lambda: transport), transport)

    assert await bound.port.holdings() == BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
    assert [call[1] for call in transport.calls] == ["/portfolio/holdings"]


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["positions", "holdings", "orders"])
async def test_indmoney_fixed_surfaces_reject_missing_required_evidence(bind_adapter, surface: str) -> None:
    transport = _IndMoneyTransport()
    _indmoney_rows(transport)
    if surface == "positions":
        transport.payloads[("/portfolio/positions", "derivative", "margin")]["net_positions"][0].pop(
            "net_quantity"
        )
    elif surface == "holdings":
        transport.payloads["/portfolio/holdings"][0].pop("quantity")
    else:
        transport.payloads["/order-book"][0].pop("txn_type")
    bound = bind_adapter("indmoney", IndMoneyAdapter(http_factory=lambda: transport), transport)

    if surface == "positions":
        outcome = await bound.port.positions()
    elif surface == "holdings":
        outcome = await bound.port.holdings()
    else:
        outcome = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR))
    assert outcome == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    path = {
        "positions": "/portfolio/positions",
        "holdings": "/portfolio/holdings",
        "orders": "/order-book",
    }[surface]
    assert transport.calls == (
        _indmoney_position_calls(1)
        if surface == "positions"
        else [("GET", path, {})]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_index", [0, 1, 2, 3])
async def test_indmoney_position_rejects_cross_scope_exchange_segment_with_exact_prefix(
    bind_adapter,
    failure_index: int,
) -> None:
    transport = _IndMoneyTransport()
    _indmoney_rows(transport)
    segment, product = (
        ("derivative", "margin"),
        ("derivative", "intraday"),
        ("equity", "cnc"),
        ("equity", "intraday"),
    )[failure_index]
    row = transport.payloads[("/portfolio/positions", segment, product)]["net_positions"][0]
    row["exchange_segment"] = "NSE_EQ" if segment == "derivative" else "NSE_FNO"
    bound = bind_adapter("indmoney", IndMoneyAdapter(http_factory=lambda: transport), transport)

    assert await bound.port.positions() == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert transport.calls == _indmoney_position_calls(failure_index + 1)


@pytest.mark.asyncio
async def test_indmoney_transport_failure_remains_provider_failure_with_one_fixed_call(bind_adapter) -> None:
    transport = _IndMoneyTransport()
    _indmoney_rows(transport)
    transport.errors.add("/portfolio/holdings")
    bound = bind_adapter("indmoney", IndMoneyAdapter(http_factory=lambda: transport), transport)

    outcome = await bound.port.holdings()

    assert outcome == BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
    assert [call[1] for call in transport.calls] == ["/portfolio/holdings"]


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [False, True])
@pytest.mark.parametrize("failure_index", [0, 1, 2, 3])
async def test_indmoney_position_failure_stops_at_exact_combo_prefix(
    bind_adapter,
    declared: bool,
    failure_index: int,
) -> None:
    class FailingPositionTransport(_IndMoneyTransport):
        def __init__(self) -> None:
            super().__init__()
            self.position_calls = 0

        def __call__(self, method, url, *, headers, params=None, json_body=None):
            path = url.removeprefix(INDMONEY_BASE_URL)
            if path == "/portfolio/positions":
                current = self.position_calls
                self.position_calls += 1
                if current == failure_index:
                    if declared:
                        self.raw_responses[path] = (
                            200,
                            {"status": "error", "data": self.payloads[path], "message": "synthetic"},
                        )
                    else:
                        self.errors.add(path)
            return super().__call__(
                method,
                url,
                headers=headers,
                params=params,
                json_body=json_body,
            )

    transport = FailingPositionTransport()
    _indmoney_rows(transport)
    bound = bind_adapter("indmoney", IndMoneyAdapter(http_factory=lambda: transport), transport)

    assert await bound.port.positions() == BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
    assert transport.calls == _indmoney_position_calls(failure_index + 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [False, True])
async def test_indmoney_order_failure_preserves_one_call(bind_adapter, declared: bool) -> None:
    transport = _IndMoneyTransport()
    _indmoney_rows(transport)
    if declared:
        transport.raw_responses["/order-book"] = (
            200,
            {"status": "error", "data": transport.payloads["/order-book"], "message": "synthetic"},
        )
    else:
        transport.errors.add("/order-book")
    bound = bind_adapter("indmoney", IndMoneyAdapter(http_factory=lambda: transport), transport)

    assert await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR)) == BrokerReadFailure(
        BrokerReadErrorCode.PROVIDER_FAILURE
    )
    assert transport.calls == [("GET", "/order-book", {})]


@pytest.mark.asyncio
async def test_indmoney_optional_order_price_remains_absent_without_alias_inference(bind_adapter) -> None:
    transport = _IndMoneyTransport()
    _indmoney_rows(transport)
    row = transport.payloads["/order-book"][0]
    row["price"] = 0
    row.pop("price")
    bound = bind_adapter("indmoney", IndMoneyAdapter(http_factory=lambda: transport), transport)

    outcome = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR))

    assert isinstance(outcome, BrokerReadSuccess)
    assert outcome.value[0].price is None
    assert transport.calls == [("GET", "/order-book", {})]


class _KotakNeoClient:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.responses: dict[str, object] = {}
        self.errors: set[str] = set()

    def _read(self, name: str) -> object:
        self.calls.append(name)
        if name in self.errors:
            raise RuntimeError("synthetic Kotak Neo SDK failure")
        return copy.deepcopy(self.responses[name])

    def order_book(self) -> object:
        return self._read("order_book")

    def trade_book(self) -> object:
        return self._read("trade_book")

    def positions(self) -> object:
        return self._read("positions")

    def holdings(self) -> object:
        return self._read("holdings")


def _kotakneo_rows(client: _KotakNeoClient) -> None:
    client.responses["order_book"] = {"stat": "Ok", "stCode": 200, "data": [{
        "nOrdNo": "K1",
        "ordSt": "open",
        "trdSym": "TCS-EQ",
        "exSeg": "nse_cm",
        "trnsTp": "B",
        "prcTp": "L",
        "prod": "CNC",
        "qty": 0,
        "fldQty": 0,
        "prc": 0,
    }]}
    client.responses["trade_book"] = {"stat": "Ok", "stCode": 200, "data": [{
        "nOrdNo": "K1",
        "trdSym": "TCS-EQ",
        "exSeg": "nse_cm",
        "trnsTp": "B",
        "fldQty": 0,
        "avgPrc": 0,
        "prod": "CNC",
        "flDtTm": "07-Sep-2026 09:20:00",
    }]}
    client.responses["positions"] = {"stat": "Ok", "stCode": 200, "data": [{
        "trdSym": "TCS-EQ",
        "exSeg": "nse_cm",
        "prod": "CNC",
        "cfBuyQty": 0,
        "flBuyQty": 0,
        "cfSellQty": 0,
        "flSellQty": 0,
        "cfBuyAmt": 0,
        "buyAmt": 0,
        "cfSellAmt": 0,
        "sellAmt": 0,
        "genNum": 1,
        "genDen": 1,
        "prcNum": 1,
        "prcDen": 1,
        "multiplier": 1,
        "precision": 2,
    }]}
    client.responses["holdings"] = {"data": [{
        "displaySymbol": "TCS",
        "exchangeSegment": "nse_cm",
        "quantity": 0,
        "closingPrice": 0,
        "unrealisedGainLoss": 0,
    }]}


@pytest.mark.asyncio
async def test_kotakneo_supported_surfaces_preserve_zero_optional_absence_and_exact_ledgers(bind_adapter) -> None:
    client = _KotakNeoClient()
    _kotakneo_rows(client)
    bound = bind_adapter("kotakneo", KotakNeoAdapter(client_factory=lambda _session: client), client)

    start = len(client.calls)
    positions = await bound.port.positions()
    assert isinstance(positions, BrokerReadSuccess)
    assert positions.value[0].quantity == "0"
    assert positions.value[0].average_price == positions.value[0].pnl == "0.00"
    assert positions.value[0].ltp is None
    assert positions.value[0].accounting_complete is True
    assert client.calls[start:] == ["positions"]

    start = len(client.calls)
    holdings = await bound.port.holdings()
    assert isinstance(holdings, BrokerReadSuccess)
    assert holdings.value[0].quantity == "0"
    assert holdings.value[0].average_price is None
    assert holdings.value[0].ltp is None
    assert holdings.value[0].close_price == 0.0
    assert holdings.value[0].pnl == "0"
    assert client.calls[start:] == ["holdings"]

    start = len(client.calls)
    orders = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR))
    assert isinstance(orders, BrokerReadSuccess)
    assert orders.value[0].quantity == orders.value[0].filled_quantity == "0"
    assert orders.value[0].disclosed_quantity is None
    assert client.calls[start:] == ["order_book"]

    start = len(client.calls)
    trades = await bound.port.trades()
    assert isinstance(trades, BrokerReadSuccess)
    assert trades.value[0].quantity == trades.value[0].price == "0"
    assert client.calls[start:] == ["trade_book"]

    start = len(client.calls)
    forever = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER))
    super_orders = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.SUPER))
    assert forever == super_orders == BrokerReadFailure(BrokerReadErrorCode.UNSUPPORTED)
    assert client.calls[start:] == []


@pytest.mark.asyncio
async def test_kotakneo_incomplete_optional_position_amounts_are_omitted(bind_adapter) -> None:
    client = _KotakNeoClient()
    _kotakneo_rows(client)
    row = client.responses["positions"]["data"][0]
    for name in ("cfBuyAmt", "buyAmt", "cfSellAmt", "sellAmt"):
        row.pop(name)
    bound = bind_adapter("kotakneo", KotakNeoAdapter(client_factory=lambda _session: client), client)

    outcome = await bound.port.positions()

    assert isinstance(outcome, BrokerReadSuccess)
    assert outcome.value[0].quantity == "0"
    assert outcome.value[0].average_price is None
    assert outcome.value[0].pnl is None
    assert outcome.value[0].accounting_complete is None


@pytest.mark.asyncio
async def test_kotakneo_documented_data_only_holdings_envelope_is_strict_success(bind_adapter) -> None:
    client = _KotakNeoClient()
    _kotakneo_rows(client)
    bound = bind_adapter("kotakneo", KotakNeoAdapter(client_factory=lambda _session: client), client)

    outcome = await bound.port.holdings()

    assert isinstance(outcome, BrokerReadSuccess)
    assert outcome.value[0].pnl == "0"
    assert client.calls == ["holdings"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("surface", "payload"),
    [
        ("positions", []),
        ("positions", {"Error": object()}),
        ("positions", {"status": 1, "data": []}),
        ("positions", {"stat": "Ok", "stCode": 200, "data": {}}),
        ("positions", {"stat": "Ok", "stCode": 200, "data": ["bad-row"]}),
        ("holdings", []),
        ("holdings", {"stat": "Ok", "stCode": 200, "data": {}}),
        ("holdings", {"stat": "Ok", "stCode": 200, "data": ["bad-row"]}),
        ("orders", []),
        ("orders", {"stat": "Ok", "stCode": 200, "data": {}}),
        ("orders", {"stat": "Ok", "stCode": 200, "data": ["bad-row"]}),
        ("trades", []),
        ("trades", {"stat": "Ok", "stCode": 200, "data": {}}),
        ("trades", {"stat": "Ok", "stCode": 200, "data": ["bad-row"]}),
    ],
)
async def test_kotakneo_fixed_surfaces_reject_malformed_envelopes_containers_and_rows(
    bind_adapter,
    surface: str,
    payload: object,
) -> None:
    client = _KotakNeoClient()
    _kotakneo_rows(client)
    client.responses[{"orders": "order_book", "trades": "trade_book"}.get(surface, surface)] = payload
    bound = bind_adapter("kotakneo", KotakNeoAdapter(client_factory=lambda _session: client), client)

    if surface == "positions":
        outcome = await bound.port.positions()
    elif surface == "holdings":
        outcome = await bound.port.holdings()
    elif surface == "orders":
        outcome = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR))
    else:
        outcome = await bound.port.trades()
    assert outcome == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert client.calls == [{"orders": "order_book", "trades": "trade_book"}.get(surface, surface)]


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["positions", "holdings", "orders", "trades"])
async def test_kotakneo_fixed_surfaces_reject_missing_or_corrupt_required_evidence(bind_adapter, surface: str) -> None:
    client = _KotakNeoClient()
    _kotakneo_rows(client)
    if surface == "positions":
        client.responses["positions"]["data"][0].pop("flSellQty")
    elif surface == "holdings":
        client.responses["holdings"]["data"][0].pop("quantity")
    elif surface == "orders":
        client.responses["order_book"]["data"][0].pop("trnsTp")
    else:
        row = client.responses["trade_book"]["data"][0]
        row["avgPrc"] = "bad"
        row["flPrc"] = 1
    bound = bind_adapter("kotakneo", KotakNeoAdapter(client_factory=lambda _session: client), client)

    if surface == "positions":
        outcome = await bound.port.positions()
    elif surface == "holdings":
        outcome = await bound.port.holdings()
    elif surface == "orders":
        outcome = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR))
    else:
        outcome = await bound.port.trades()
    assert outcome == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert client.calls == [{"orders": "order_book", "trades": "trade_book"}.get(surface, surface)]


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [False, True])
async def test_kotakneo_provider_failures_remain_provider_failure_with_one_fixed_call(
    bind_adapter,
    declared: bool,
) -> None:
    client = _KotakNeoClient()
    _kotakneo_rows(client)
    if declared:
        client.responses["positions"] = {"stat": "Not_Ok", "errMsg": "synthetic rejection"}
    else:
        client.errors.add("positions")
    bound = bind_adapter("kotakneo", KotakNeoAdapter(client_factory=lambda _session: client), client)

    outcome = await bound.port.positions()

    assert outcome == BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
    assert client.calls == ["positions"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "envelope",
    [
        {"Error": "synthetic rejection"},
        {"Error": RuntimeError("synthetic rejection")},
        {"Error Message": "synthetic rejection"},
        {"error": ["synthetic rejection"]},
        {"status": "error", "message": "synthetic rejection"},
    ],
)
@pytest.mark.parametrize("surface", ["positions", "holdings", "orders", "trades"])
async def test_kotakneo_missing_stat_declared_errors_remain_provider_failures_with_one_call(
    bind_adapter,
    envelope: dict[str, object],
    surface: str,
) -> None:
    client = _KotakNeoClient()
    _kotakneo_rows(client)
    source = {"orders": "order_book", "trades": "trade_book"}.get(surface, surface)
    client.responses[source] = envelope
    bound = bind_adapter("kotakneo", KotakNeoAdapter(client_factory=lambda _session: client), client)

    if surface == "positions":
        outcome = await bound.port.positions()
    elif surface == "holdings":
        outcome = await bound.port.holdings()
    elif surface == "orders":
        outcome = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR))
    else:
        outcome = await bound.port.trades()
    assert outcome == BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
    assert client.calls == [source]


@pytest.mark.asyncio
async def test_kotakneo_arbitrary_error_value_is_malformed_without_truthiness_hook(bind_adapter) -> None:
    class TruthinessTrap:
        def __init__(self) -> None:
            self.calls = 0

        def __bool__(self) -> bool:
            self.calls += 1
            raise AssertionError("truthiness hook must not run")

        def __deepcopy__(self, _memo):
            return self

    trap = TruthinessTrap()
    client = _KotakNeoClient()
    _kotakneo_rows(client)
    client.responses["positions"] = {"Error": trap}
    bound = bind_adapter("kotakneo", KotakNeoAdapter(client_factory=lambda _session: client), client)

    assert await bound.port.positions() == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert trap.calls == 0
    assert client.calls == ["positions"]


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [False, True])
@pytest.mark.parametrize("surface", ["holdings", "orders", "trades"])
async def test_kotakneo_each_remaining_surface_preserves_provider_failure_and_ledger(
    bind_adapter,
    declared: bool,
    surface: str,
) -> None:
    client = _KotakNeoClient()
    _kotakneo_rows(client)
    source = {"orders": "order_book", "trades": "trade_book"}.get(surface, surface)
    if declared:
        client.responses[source] = {"stat": "Not_Ok", "errMsg": "synthetic rejection"}
    else:
        client.errors.add(source)
    bound = bind_adapter("kotakneo", KotakNeoAdapter(client_factory=lambda _session: client), client)

    if surface == "holdings":
        outcome = await bound.port.holdings()
    elif surface == "orders":
        outcome = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR))
    else:
        outcome = await bound.port.trades()
    assert outcome == BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
    assert client.calls == [source]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("surface", "primary", "secondary", "valid_secondary"),
    [
        ("positions", "trdSym", "sym", "TCS-EQ"),
        ("holdings", "quantity", "sellableQuantity", 0),
        ("holdings", "unrealisedGainLoss", "pnl", 0),
        ("orders", "ordSt", "stat", "open"),
        ("orders", "dscQty", "dclQty", 0),
    ],
)
async def test_kotakneo_present_malformed_primary_alias_never_falls_through(
    bind_adapter,
    surface: str,
    primary: str,
    secondary: str,
    valid_secondary: object,
) -> None:
    client = _KotakNeoClient()
    _kotakneo_rows(client)
    source = {"orders": "order_book"}.get(surface, surface)
    row = client.responses[source]["data"][0]
    row[primary] = object() if primary in {"trdSym", "ordSt"} else "bad"
    row[secondary] = valid_secondary
    bound = bind_adapter("kotakneo", KotakNeoAdapter(client_factory=lambda _session: client), client)

    if surface == "positions":
        outcome = await bound.port.positions()
    elif surface == "holdings":
        outcome = await bound.port.holdings()
    else:
        outcome = await bound.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR))
    assert outcome == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert client.calls == [source]


@pytest.mark.asyncio
async def test_kotakneo_trade_optional_order_id_remains_absent(bind_adapter) -> None:
    client = _KotakNeoClient()
    _kotakneo_rows(client)
    client.responses["trade_book"]["data"][0].pop("nOrdNo")
    bound = bind_adapter("kotakneo", KotakNeoAdapter(client_factory=lambda _session: client), client)

    outcome = await bound.port.trades()

    assert isinstance(outcome, BrokerReadSuccess)
    assert outcome.value[0].orderid is None
    assert client.calls == ["trade_book"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"cfBuyQty": 0, "cfBuyAmt": 100, "flBuyQty": 1, "buyAmt": 0},
        {"cfBuyQty": 1, "cfBuyAmt": -1},
        {"flSellQty": 0, "sellAmt": 100, "cfSellQty": 1, "cfSellAmt": 0},
        {"flSellQty": 1, "sellAmt": -1},
    ],
)
async def test_kotakneo_position_rejects_invalid_component_amount_pairs(
    bind_adapter,
    changes: dict[str, int],
) -> None:
    client = _KotakNeoClient()
    _kotakneo_rows(client)
    client.responses["positions"]["data"][0].update(changes)
    bound = bind_adapter("kotakneo", KotakNeoAdapter(client_factory=lambda _session: client), client)

    assert await bound.port.positions() == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert client.calls == ["positions"]


class _MarketEvidenceTrap:
    """Provider value whose Python conversion hooks must never execute."""

    def __init__(self) -> None:
        self.calls = 0

    def _called(self) -> None:
        self.calls += 1
        raise AssertionError("provider conversion hook must not run")

    def __bool__(self) -> bool:
        self._called()

    def __eq__(self, _other: object) -> bool:
        self._called()

    def __float__(self) -> float:
        self._called()

    def __str__(self) -> str:
        self._called()

    def __deepcopy__(self, _memo: object) -> _MarketEvidenceTrap:
        return self


class _DhanMarketClient(_DhanClient):
    def __init__(self) -> None:
        super().__init__()
        self.quote_requests: list[dict[str, list[object]]] = []
        self.history_requests: list[tuple[object, ...]] = []

    def quote_data(self, securities: dict[str, list[object]]) -> object:
        self.quote_requests.append(copy.deepcopy(securities))
        return self._read("quote")

    def intraday_minute_data(self, *args: object) -> object:
        self.history_requests.append(args)
        return self._read("historical")


class _UpstoxMarketClient(_UpstoxClient):
    def __init__(self) -> None:
        super().__init__()
        self.quote_requests: list[str] = []
        self.history_requests: list[tuple[object, ...]] = []

    def full_quote(self, instrument_keys: str) -> object:
        self.quote_requests.append(instrument_keys)
        return self._read("quote")

    def historical(self, *args: object) -> object:
        self.history_requests.append(args)
        return self._read("historical")


class _KotakNeoQuoteClient(_KotakNeoClient):
    def __init__(self) -> None:
        super().__init__()
        self.quote_requests: list[tuple[list[dict[str, str]], str]] = []

    def quotes(self, tokens: list[dict[str, str]], quote_type: str = "all") -> object:
        self.quote_requests.append((copy.deepcopy(tokens), quote_type))
        return self._read("quote")


def _quote_record(provider: str, value: object = 1) -> dict[str, object]:
    if provider == "dhan":
        return {"last_price": value}
    if provider == "upstox":
        return {"symbol": "TCS", "instrument_token": "NSE_EQ|101", "last_price": value}
    if provider == "groww":
        return {"last_price": value}
    if provider == "indmoney":
        return {"live_price": value}
    if provider == "kotakneo":
        return {
            "instrument_token": "101",
            "trading_symbol": "TCS",
            "exchange_segment": "nse_cm",
            "last_traded_price": value,
        }
    raise AssertionError(f"unknown quote provider {provider}")


def _identity_only_quote_record(provider: str) -> dict[str, object]:
    row = _quote_record(provider)
    for field in ("last_price", "live_price", "last_traded_price"):
        row.pop(field, None)
    return row


async def _native_quote_outcome(bind_adapter, provider: str, row: dict[str, object]) -> object:
    if provider == "dhan":
        client = _DhanMarketClient()
        client.responses["quote"] = {"status": "success", "data": {"NSE_EQ": {"101": row}}}
        adapter = DhanAdapter(
            client_factory=lambda _session: client,
            security_resolver=lambda _symbol, _exchange: "101",
        )
        bound = bind_adapter(provider, adapter, client)
        outcome = await bound.port.quote(QuoteRequest(InstrumentRef("TCS", "NSE")))
        assert client.calls == ["quote"]
        assert client.quote_requests == [{"NSE_EQ": [101]}]
        return outcome
    if provider == "upstox":
        client = _UpstoxMarketClient()
        client.responses["quote"] = {"status": "success", "data": {"NSE_EQ:TCS": row}}
        adapter = UpstoxAdapter(
            client_factory=lambda _session: client,
            instrument_resolver=lambda _symbol, _exchange: "NSE_EQ|101",
        )
        bound = bind_adapter(provider, adapter, client)
        outcome = await bound.port.quote(QuoteRequest(InstrumentRef("TCS", "NSE")))
        assert client.calls == ["quote"]
        assert client.quote_requests == ["NSE_EQ|101"]
        return outcome
    if provider == "groww":
        transport = _GrowwTransport()
        transport.raw_responses[("/v1/live-data/quote", "CASH")] = (
            200,
            {"status": "SUCCESS", "payload": row},
        )
        bound = bind_adapter(provider, GrowwAdapter(http_factory=lambda: transport), transport)
        outcome = await bound.port.quote(QuoteRequest(InstrumentRef("TCS", "NSE")))
        assert transport.calls == [(
            "GET",
            "/v1/live-data/quote",
            {"exchange": "NSE", "segment": "CASH", "trading_symbol": "TCS"},
        )]
        return outcome
    if provider == "indmoney":
        transport = _IndMoneyTransport()
        transport.raw_responses["/market/quotes/full"] = (
            200,
            {"status": "success", "data": {"NSE_101": row}},
        )

        class ResolvedIndMoneyAdapter(IndMoneyAdapter):
            async def _resolve_security_for_session(self, *_args, **_kwargs):
                return "101"

        bound = bind_adapter(provider, ResolvedIndMoneyAdapter(http_factory=lambda: transport), transport)
        outcome = await bound.port.quote(QuoteRequest(InstrumentRef("TCS", "NSE")))
        assert transport.calls == [("GET", "/market/quotes/full", {"scrip-codes": "NSE_101"})]
        return outcome
    if provider == "kotakneo":
        client = _KotakNeoQuoteClient()
        client.responses["quote"] = {"stat": "Ok", "stCode": 200, "data": [row]}
        adapter = KotakNeoAdapter(
            client_factory=lambda _session: client,
            token_resolver=lambda _symbol, _exchange: "101",
        )
        bound = bind_adapter(provider, adapter, client)
        outcome = await bound.port.quote(QuoteRequest(InstrumentRef("TCS", "NSE")))
        assert client.calls == ["quote"]
        assert client.quote_requests == [([{"instrument_token": "101", "exchange_segment": "nse_cm"}], "all")]
        return outcome
    raise AssertionError(f"unknown quote provider {provider}")


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["dhan", "upstox", "groww", "indmoney", "kotakneo"])
async def test_native_quote_identity_without_numeric_evidence_fails_closed(bind_adapter, provider: str) -> None:
    outcome = await _native_quote_outcome(bind_adapter, provider, _identity_only_quote_record(provider))

    assert outcome == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [1, 0])
@pytest.mark.parametrize("provider", ["dhan", "upstox", "groww", "indmoney", "kotakneo"])
async def test_native_quote_preserves_present_numeric_and_omits_absent_fields(
    bind_adapter,
    provider: str,
    value: int,
) -> None:
    outcome = await _native_quote_outcome(bind_adapter, provider, _quote_record(provider, value))

    assert isinstance(outcome, BrokerReadSuccess)
    assert outcome.value.ltp == value
    assert outcome.value.open is None
    assert outcome.value.high is None
    assert outcome.value.low is None
    assert outcome.value.close is None
    assert outcome.value.volume is None
    assert outcome.value.bid is None
    assert outcome.value.ask is None
    assert outcome.value.oi is None


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["dhan", "upstox", "groww", "indmoney", "kotakneo"])
async def test_native_quote_rejects_malformed_present_primary_without_hooks_or_alias_fallback(
    bind_adapter,
    provider: str,
) -> None:
    trap = _MarketEvidenceTrap()
    row = _quote_record(provider, trap)
    if provider == "dhan":
        row["ltp"] = 0
    elif provider == "groww":
        row["ltp"] = 0
    elif provider == "kotakneo":
        row["ltp"] = 0
    else:
        row["day_open" if provider == "indmoney" else "ohlc"] = 0 if provider == "indmoney" else {"open": 0}

    outcome = await _native_quote_outcome(bind_adapter, provider, row)

    assert outcome == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert trap.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["dhan", "groww", "kotakneo"])
async def test_native_quote_present_zero_primary_never_falls_through_to_alias(
    bind_adapter,
    provider: str,
) -> None:
    row = _quote_record(provider, 0)
    row["ltp"] = 99

    outcome = await _native_quote_outcome(bind_adapter, provider, row)

    assert isinstance(outcome, BrokerReadSuccess)
    assert outcome.value.ltp == 0


@pytest.mark.asyncio
async def test_kotakneo_quote_rejects_positional_row_with_wrong_resolved_token(bind_adapter) -> None:
    row = _quote_record("kotakneo", 0)
    row["instrument_token"] = "999"

    outcome = await _native_quote_outcome(bind_adapter, "kotakneo", row)

    assert outcome == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)


@pytest.mark.asyncio
@pytest.mark.parametrize("reverse_rows", [False, True])
async def test_kotakneo_quote_rejects_ambiguous_identity_independent_of_response_order(
    bind_adapter,
    reverse_rows: bool,
) -> None:
    client = _KotakNeoQuoteClient()
    rows = [
        {
            "instrument_token": "101",
            "exchange_segment": "nse_cm",
            "last_traded_price": 1,
        },
        {
            "instrument_token": "101",
            "last_traded_price": 999,
        },
    ]
    if reverse_rows:
        rows.reverse()
    client.responses["quote"] = {"stat": "Ok", "stCode": 200, "data": rows}
    adapter = KotakNeoAdapter(
        client_factory=lambda _session: client,
        token_resolver=lambda _symbol, _exchange: "101",
    )
    bound = bind_adapter("kotakneo", adapter, client)

    outcome = await bound.port.batch_quotes(
        BatchQuoteRequest((InstrumentRef("A", "NSE"), InstrumentRef("B", "BSE")))
    )

    assert outcome == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert client.calls == ["quote"]
    assert client.quote_requests == [(
        [
            {"instrument_token": "101", "exchange_segment": "nse_cm"},
            {"instrument_token": "101", "exchange_segment": "bse_cm"},
        ],
        "all",
    )]


@pytest.mark.asyncio
async def test_kotakneo_quote_rejects_duplicate_identity_with_a_missing_target(bind_adapter) -> None:
    client = _KotakNeoQuoteClient()
    duplicate = {
        "instrument_token": "101",
        "exchange_segment": "nse_cm",
        "last_traded_price": 1,
    }
    client.responses["quote"] = {"stat": "Ok", "stCode": 200, "data": [duplicate, dict(duplicate)]}
    adapter = KotakNeoAdapter(
        client_factory=lambda _session: client,
        token_resolver=lambda _symbol, _exchange: "101",
    )
    bound = bind_adapter("kotakneo", adapter, client)

    outcome = await bound.port.batch_quotes(
        BatchQuoteRequest((InstrumentRef("A", "NSE"), InstrumentRef("B", "BSE")))
    )

    assert outcome == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert client.calls == ["quote"]


@pytest.mark.asyncio
async def test_kotakneo_quote_reorders_exact_rows_to_the_request_ledger(bind_adapter) -> None:
    client = _KotakNeoQuoteClient()
    client.responses["quote"] = {
        "stat": "Ok",
        "stCode": 200,
        "data": [
            {
                "instrument_token": "202",
                "exchange_segment": "bse_cm",
                "last_traded_price": 2,
            },
            {
                "instrument_token": "101",
                "exchange_segment": "nse_cm",
                "last_traded_price": 1,
            },
        ],
    }
    tokens = {("A", "NSE"): "101", ("B", "BSE"): "202"}
    adapter = KotakNeoAdapter(
        client_factory=lambda _session: client,
        token_resolver=lambda symbol, exchange: tokens[(symbol, exchange)],
    )
    bound = bind_adapter("kotakneo", adapter, client)

    outcome = await bound.port.batch_quotes(
        BatchQuoteRequest((InstrumentRef("A", "NSE"), InstrumentRef("B", "BSE")))
    )

    assert isinstance(outcome, BrokerReadSuccess)
    assert [(quote.instrument.symbol, quote.instrument.exchange, quote.ltp) for quote in outcome.value] == [
        ("A", "NSE", 1.0),
        ("B", "BSE", 2.0),
    ]
    assert client.calls == ["quote"]


@pytest.mark.asyncio
async def test_kotakneo_index_quote_matches_provider_segment_and_preserves_requested_exchange(bind_adapter) -> None:
    client = _KotakNeoQuoteClient()
    client.responses["quote"] = {
        "stat": "Ok",
        "stCode": 200,
        "data": [{
            "instrument_token": "Nifty 50",
            "trading_symbol": "Nifty 50",
            "exchange_segment": "nse_cm",
            "last_traded_price": 25000,
        }],
    }
    adapter = KotakNeoAdapter(client_factory=lambda _session: client)
    bound = bind_adapter("kotakneo", adapter, client)

    outcome = await bound.port.quote(QuoteRequest(InstrumentRef("NIFTY 50", "NSE_INDEX")))

    assert isinstance(outcome, BrokerReadSuccess)
    assert (
        outcome.value.instrument.symbol,
        outcome.value.instrument.exchange,
        outcome.value.ltp,
    ) == ("NIFTY 50", "NSE_INDEX", 25000.0)
    assert client.calls == ["quote"]
    assert client.quote_requests == [(
        [{"instrument_token": "Nifty 50", "exchange_segment": "nse_cm"}],
        "all",
    )]


async def _native_history_outcome(bind_adapter, provider: str, payload: object) -> object:
    request = HistoricalRequest(InstrumentRef("TCS", "NSE"), "1m", "2026-09-01", "2026-09-02")
    if provider == "dhan":
        client = _DhanMarketClient()
        client.responses["historical"] = {"status": "success", "data": payload}
        adapter = DhanAdapter(
            client_factory=lambda _session: client,
            security_resolver=lambda _symbol, _exchange: "101",
        )
        bound = bind_adapter(provider, adapter, client)
        outcome = await bound.port.historical(request)
        assert client.calls == ["historical"]
        assert len(client.history_requests) == 1
        return outcome
    if provider == "upstox":
        client = _UpstoxMarketClient()
        client.responses["historical"] = {"status": "success", "data": {"candles": payload}}
        adapter = UpstoxAdapter(
            client_factory=lambda _session: client,
            instrument_resolver=lambda _symbol, _exchange: "NSE_EQ|101",
        )
        bound = bind_adapter(provider, adapter, client)
        outcome = await bound.port.historical(request)
        assert client.calls == ["historical"]
        assert len(client.history_requests) == 1
        return outcome
    if provider == "groww":
        transport = _GrowwTransport()
        transport.raw_responses[("/v1/historical/candle/range", "CASH")] = (
            200,
            {"status": "SUCCESS", "payload": {"candles": payload}},
        )
        bound = bind_adapter(provider, GrowwAdapter(http_factory=lambda: transport), transport)
        outcome = await bound.port.historical(request)
        assert len(transport.calls) == 1
        assert transport.calls[0][0:2] == ("GET", "/v1/historical/candle/range")
        return outcome
    raise AssertionError(f"unknown history provider {provider}")


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["dhan", "upstox", "groww"])
async def test_native_history_omits_genuinely_absent_volume(bind_adapter, provider: str) -> None:
    timestamp = "2026-09-01T09:15:00+05:30"
    payload: object
    if provider == "dhan":
        payload = {"timestamp": [timestamp], "open": [1], "high": [1], "low": [1], "close": [1]}
    else:
        payload = [[timestamp, 1, 1, 1, 1]]

    outcome = await _native_history_outcome(bind_adapter, provider, payload)

    assert isinstance(outcome, BrokerReadSuccess)
    assert len(outcome.value.bars) == 1
    assert outcome.value.bars[0].volume is None


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["dhan", "upstox", "groww"])
async def test_native_history_rejects_mismatched_or_truncated_required_evidence(
    bind_adapter,
    provider: str,
) -> None:
    timestamp = "2026-09-01T09:15:00+05:30"
    if provider == "dhan":
        payload: object = {
            "timestamp": [timestamp, timestamp],
            "open": [1, 1],
            "high": [1],
            "low": [1, 1],
            "close": [1, 1],
        }
    elif provider == "upstox":
        payload = [[timestamp, 1, 1, 1]]
    else:
        payload = [[timestamp]]

    outcome = await _native_history_outcome(bind_adapter, provider, payload)

    assert outcome == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["dhan", "upstox", "groww"])
async def test_native_history_rejects_malformed_present_numeric_without_conversion_hooks(
    bind_adapter,
    provider: str,
) -> None:
    trap = _MarketEvidenceTrap()
    timestamp = "2026-09-01T09:15:00+05:30"
    if provider == "dhan":
        payload: object = {
            "timestamp": [timestamp],
            "open": [trap],
            "high": [1],
            "low": [1],
            "close": [1],
        }
    else:
        payload = [[timestamp, trap, 1, 1, 1]]

    outcome = await _native_history_outcome(bind_adapter, provider, payload)

    assert outcome == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert trap.calls == 0
