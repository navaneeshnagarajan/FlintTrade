"""Exact listing and observation boundaries with the real SDK and inert I/O."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
import threading
from typing import Any

import httpx
import pytest

from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
from flinttrade_core.exceptions import BrokerError, UnsupportedCapabilityError
from flinttrade_core.models import Order
from flinttrade_gateway.brokers._base import ROUTER_TOKEN, Session
from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter

from .test_kotakneo_options_prerequisites import listed_resolver, margin_body, master_row
from .test_kotakneo_options_prerequisites import sdk_runtime as sdk_runtime
from flinttrade_gateway.brokers.kotakneo_sdk import KotakNeoSdkSession

pytestmark = pytest.mark.unit
SdkFactory = Callable[[dict[str, Any]], tuple[KotakNeoSdkSession, list[httpx.Request]]]


def _order(row: dict[str, Any], **changes: Any) -> Order:
    """Build a synthetic exact-listing order without resolving an underlying."""
    return Order(**{
        "symbol": row["pTrdSymbol"], "exchange": "NFO", "action": "BUY", "quantity": row["lLotSize"],
        "product": "NRML", "pricetype": "LIMIT", "price": "9.40", **changes,
    })


@pytest.mark.parametrize("operation", ["place", "amo", "modify", "margin"])
@pytest.mark.parametrize("replace", [False, True])
async def test_final_preflight_replacement_cannot_reach_installed_sdk(
    sdk_runtime: SdkFactory, monkeypatch: pytest.MonkeyPatch, operation: str, replace: bool,
) -> None:
    """Reject publication after executor preflight while retaining every positive resource call."""
    row = master_row()
    response = margin_body()["data"] if operation == "margin" else {
        "stat": "Ok", "stCode": 200, "nOrdNo": "synthetic-order",
    }
    facade, calls = sdk_runtime(response)
    adapter = KotakNeoAdapter(client_factory=lambda _: facade, contract_resolver=listed_resolver([row]))
    entered, release = threading.Event(), threading.Event()
    original_preflight = adapter.preflight_order
    method = {"place": "place_order", "amo": "place_order", "modify": "modify_order", "margin": "margin_required"}
    original_sdk = getattr(facade._neo, method[operation])
    invocations = []

    def observe_sdk(*args: Any, **kwargs: Any) -> Any:
        invocations.append((adapter._contract_resolver.revision, dict(kwargs)))
        return original_sdk(*args, **kwargs)

    def hold_preflight(order: Order) -> dict[str, Any] | None:
        evidence = original_preflight(order)
        if threading.current_thread() is not threading.main_thread():
            entered.set()
            assert release.wait(3)
        return evidence

    monkeypatch.setattr(facade._neo, method[operation], observe_sdk)
    monkeypatch.setattr(adapter, "preflight_order", hold_preflight)
    session = Session("synthetic", 9e9, "synthetic", "kotakneo")
    order = _order(row, variety="amo" if operation == "amo" else "regular")
    if operation == "modify":
        action = adapter.modify_order(session, "synthetic-order", {
            "symbol": order.symbol, "exchange": "NFO", "action": "BUY", "product": "NRML",
            "pricetype": "LIMIT", "quantity": "65", "price": "9.40",
        }, _router_token=ROUTER_TOKEN)
    elif operation == "margin":
        action = adapter.margin_calculator(session, order)
    else:
        action = adapter.place_order(session, order, _router_token=ROUTER_TOKEN)
    task = asyncio.create_task(action)
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        assert calls == [] and invocations == []
        if replace:
            adapter.replace_contract_resolver(
                listed_resolver([row | {"pSymbol": "999", "lLotSize": "25"}], revision="synthetic-v2"),
                expected_revision="synthetic-v1",
            )
    finally:
        release.set()
        result = (await asyncio.gather(task, return_exceptions=True))[0]
    if replace:
        assert isinstance(result, UnsupportedCapabilityError)
        assert calls == [] and invocations == []
    else:
        assert not isinstance(result, BaseException)
        assert len(calls) == len(invocations) == 1
        assert invocations[0][0] == "synthetic-v1"
        assert invocations[0][1]["quantity"] == "65"


@pytest.mark.parametrize("late_error", [False, True])
async def test_inflight_invocation_keeps_revision_and_nonblocking_refresh_custody(
    sdk_runtime: SdkFactory, monkeypatch: pytest.MonkeyPatch, late_error: bool,
) -> None:
    """A live old attempt retains its identity; refresh retries only after it releases custody."""
    row = master_row()
    facade, calls = sdk_runtime({"stat": "Ok", "stCode": 200, "nOrdNo": "synthetic-order"})
    first = listed_resolver([row])
    second = listed_resolver([row | {"pSymbol": "999"}], revision="synthetic-v2")
    adapter = KotakNeoAdapter(client_factory=lambda _: facade, contract_resolver=first)
    entered, release = threading.Event(), threading.Event()
    original_sdk = facade._neo.place_order
    revisions = []

    def hold_after_write(*args: Any, **kwargs: Any) -> Any:
        revisions.append(adapter._contract_resolver.revision)
        result = original_sdk(*args, **kwargs)
        entered.set()
        assert release.wait(3)
        revisions.append(adapter._contract_resolver.revision)
        if late_error:
            raise httpx.ReadTimeout("synthetic response loss after possible write")
        return result

    monkeypatch.setattr(facade._neo, "place_order", hold_after_write)
    task = asyncio.create_task(adapter.place_order(
        Session("synthetic", 9e9, "synthetic", "kotakneo"), _order(row), _router_token=ROUTER_TOKEN,
    ))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        assert len(calls) == 1
        with pytest.raises(BrokerReadResponseInvalid):
            adapter.replace_contract_resolver(second, expected_revision="synthetic-v1")
        assert adapter._contract_resolver is first
    finally:
        release.set()
        result = (await asyncio.gather(task, return_exceptions=True))[0]
    assert revisions == ["synthetic-v1", "synthetic-v1"]
    assert len(calls) == 1
    if late_error:
        assert isinstance(result, BrokerError)
        assert not isinstance(result, UnsupportedCapabilityError)
    else:
        assert result == "synthetic-order"
    adapter.replace_contract_resolver(second, expected_revision="synthetic-v1")
    assert adapter._contract_resolver is second


@pytest.mark.parametrize("surface", ["trade", "join"])
@pytest.mark.parametrize("alias", ["actId", "usrId"])
@pytest.mark.parametrize("account", [None, "", " ", "foreign", "Synthetic", "synthetic", True, {}])
async def test_supplied_native_account_is_validated_before_optional_projection(
    sdk_runtime: SdkFactory, surface: str, alias: str, account: Any,
) -> None:
    """Every supplied native account alias is exact, canonical and bound before joining."""
    from .test_kotakneo_options_prerequisites import trade_row

    row = trade_row(**({alias: account} if surface == "trade" else {}))
    evidence = {
        "nOrdNo": "synthetic-order", "trdSym": "IDEA-EQ", "exSeg": "nse_cm", "tok": "14366",
        **({alias: account} if surface == "join" else {}),
    }
    facade, calls = sdk_runtime({"stat": "ok", "data": [row]})
    adapter = KotakNeoAdapter(client_factory=lambda _: facade)
    session = Session("synthetic", 9e9, "synthetic", "kotakneo")
    if account != "synthetic":
        with pytest.raises(BrokerReadResponseInvalid):
            await adapter.trade_book_observation(session, order_evidence=[evidence])
    else:
        result = await adapter.trade_book_observation(session, order_evidence=[evidence])
        trade = result.rows[0]
        assert trade["instrument_id"] == "14366" and trade["broker_fields"]["tok"] == ""
        assert ("broker_account_id" in trade) == (surface == "trade")
        if surface == "trade":
            assert trade["broker_account_id"] == "synthetic"
            assert trade["broker_fields"][alias] == account
        else:
            assert trade["instrument_resolution"]["broker_fields"][alias] == account
    assert len(calls) == 1


@pytest.mark.parametrize("surface", ["trade", "join"])
@pytest.mark.parametrize("secondary", [None, "", "foreign", "Synthetic", "synthetic"])
async def test_account_aliases_cannot_hide_behind_a_valid_first_value(
    sdk_runtime: SdkFactory, surface: str, secondary: Any,
) -> None:
    """Validate both supplied identities rather than selecting the first usable alias."""
    from .test_kotakneo_options_prerequisites import trade_row

    identities = {"actId": "synthetic", "usrId": secondary}
    row = trade_row(**(identities if surface == "trade" else {}))
    evidence = {
        "nOrdNo": "synthetic-order", "trdSym": "IDEA-EQ", "exSeg": "nse_cm", "tok": "14366",
        **(identities if surface == "join" else {}),
    }
    facade, calls = sdk_runtime({"stat": "ok", "data": [row]})
    adapter = KotakNeoAdapter(client_factory=lambda _: facade)
    if secondary == "synthetic":
        result = await adapter.trade_book_observation(
            Session("synthetic", 9e9, "synthetic", "kotakneo"), order_evidence=[evidence],
        )
        assert result.rows[0]["instrument_id"] == "14366"
    else:
        with pytest.raises(BrokerReadResponseInvalid):
            await adapter.trade_book_observation(
                Session("synthetic", 9e9, "synthetic", "kotakneo"), order_evidence=[evidence],
            )
    assert len(calls) == 1


@pytest.mark.parametrize("join", [None, "same", "case-distinct"])
async def test_omitted_provider_account_is_not_synthesised_from_session_or_join(
    sdk_runtime: SdkFactory, join: str | None,
) -> None:
    """Omission stays incomplete and case-distinct order identifiers never supply tokens."""
    from .test_kotakneo_options_prerequisites import trade_row

    row = trade_row()
    evidence = None if join is None else [{
        "nOrdNo": "synthetic-order" if join == "same" else "SYNTHETIC-ORDER", "trdSym": "IDEA-EQ",
        "exSeg": "nse_cm", "tok": "14366", "actId": "synthetic",
    }]
    facade, calls = sdk_runtime({"stat": "ok", "data": [row]})
    result = await KotakNeoAdapter(client_factory=lambda _: facade).trade_book_observation(
        Session("synthetic", 9e9, "synthetic", "kotakneo"), order_evidence=evidence,
    )
    trade = result.rows[0]
    assert "broker_account_id" not in trade and "actId" not in trade["broker_fields"]
    assert trade["broker_fields"]["tok"] == ""
    assert ("instrument_id" in trade) == (join == "same")
    assert ("instrument_resolution" in trade) == (join == "same")
    assert result.coverage["lifetime_complete"] is False and len(calls) == 1


@pytest.mark.parametrize("right", ["CE", "PE"])
@pytest.mark.parametrize("exchange,kind,allowed", [
    ("NFO", "OPTIDX", True), ("BFO", "IO", True),
    ("NFO", "IO", False), ("BFO", "OPTIDX", False),
    ("NFO", "FUTIDX", False), ("BFO", "IF", False),
    ("NFO", "EQUITY", False), ("BFO", "EQUITY", False),
    ("NFO", "OPTSTK", False), ("BFO", "SO", False),
    ("NFO", "unqualified", False), ("BFO", "unqualified", False),
])
async def test_listing_class_is_venue_and_underlying_specific(
    sdk_runtime: SdkFactory, exchange: str, kind: str, allowed: bool, right: str,
) -> None:
    """Only the selected venue's index-option class can qualify either listed option right."""
    row = master_row(exchange=exchange, pInstType=kind, pOptionType=right)
    row["pTrdSymbol"] = row["pTrdSymbol"][:-2] + right
    facade, calls = sdk_runtime({"stat": "Ok", "stCode": 200, "nOrdNo": "synthetic-order"})
    if not allowed:
        with pytest.raises(BrokerReadResponseInvalid):
            listed_resolver([row])
        assert calls == []
        return
    adapter = KotakNeoAdapter(client_factory=lambda _: facade, contract_resolver=listed_resolver([row]))
    evidence = adapter.preflight_order(_order(row, exchange=exchange))
    assert evidence["instrument_type"] == kind and evidence["option_type"] == right
    assert evidence["underlying"] == ("NIFTY" if exchange == "NFO" else "SENSEX")
    assert await adapter.place_order(
        Session("synthetic", 9e9, "synthetic", "kotakneo"), _order(row, exchange=exchange),
        _router_token=ROUTER_TOKEN,
    ) == "synthetic-order"
    assert len(calls) == 1


async def _dispatch_listing(adapter: KotakNeoAdapter, row: dict[str, Any], operation: str, exchange: str) -> Any:
    """Exercise the real placement, replacement or margin path with exact synthetic context."""
    session = Session("synthetic", 9e9, "synthetic", "kotakneo")
    order = _order(row, exchange=exchange, variety="amo" if operation == "amo" else "regular")
    if operation == "modify":
        return await adapter.modify_order(session, "synthetic-order", {
            "symbol": order.symbol, "exchange": exchange, "action": "BUY", "product": "NRML",
            "pricetype": "LIMIT", "quantity": order.quantity, "price": "9.40",
        }, _router_token=ROUTER_TOKEN)
    if operation == "margin":
        return await adapter.margin_calculator(session, order)
    return await adapter.place_order(session, order, _router_token=ROUTER_TOKEN)


@pytest.mark.parametrize("operation", ["place", "amo", "modify", "margin"])
@pytest.mark.parametrize("exchange", ["NFO", "BFO"])
@pytest.mark.parametrize("instant,allowed", [
    ("2099-06-22T18:29:59+00:00", True),
    ("2099-06-22T18:30:00+00:00", False),
    ("2099-06-23T18:00:00+00:00", False),
])
async def test_date_only_expiry_never_qualifies_an_expiry_session(
    sdk_runtime: SdkFactory, monkeypatch: pytest.MonkeyPatch,
    operation: str, exchange: str, instant: str, allowed: bool,
) -> None:
    """Snapshot freshness does not qualify any part of an unknown expiry-day session."""
    from datetime import UTC, datetime
    import flinttrade_gateway.brokers.kotakneo as adapter_module

    fixed = datetime.fromisoformat(instant)

    class Clock:
        @staticmethod
        def now(tz: Any = None) -> datetime:
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

    row = master_row(exchange=exchange)
    resolver = listed_resolver([row], observed_at=datetime(2099, 6, 21, tzinfo=UTC),
                               valid_until=datetime(2099, 6, 25, tzinfo=UTC))
    response = margin_body()["data"] if operation == "margin" else {
        "stat": "Ok", "stCode": 200, "nOrdNo": "synthetic-order",
    }
    facade, calls = sdk_runtime(response)
    adapter = KotakNeoAdapter(client_factory=lambda _: facade, contract_resolver=resolver)
    monkeypatch.setattr(adapter_module, "datetime", Clock)
    if allowed:
        await _dispatch_listing(adapter, row, operation, exchange)
        assert len(calls) == 1
    else:
        with pytest.raises(UnsupportedCapabilityError):
            await _dispatch_listing(adapter, row, operation, exchange)
        assert calls == []


@pytest.mark.parametrize("operation", ["place", "amo", "modify", "margin"])
@pytest.mark.parametrize("advance", [False, True])
async def test_expiry_day_transition_after_preflight_is_checked_at_invocation(
    sdk_runtime: SdkFactory, monkeypatch: pytest.MonkeyPatch, operation: str, advance: bool,
) -> None:
    """Even a fresh unchanged revision loses execution qualification on the expiry date."""
    from datetime import UTC, datetime
    import flinttrade_gateway.brokers.kotakneo as adapter_module

    fixed = [datetime(2099, 6, 22, 18, tzinfo=UTC)]

    class Clock:
        @staticmethod
        def now(tz: Any = None) -> datetime:
            return fixed[0].astimezone(tz) if tz else fixed[0].replace(tzinfo=None)

    row = master_row()
    resolver = listed_resolver([row], observed_at=datetime(2099, 6, 21, tzinfo=UTC),
                               valid_until=datetime(2099, 6, 25, tzinfo=UTC))
    response = margin_body()["data"] if operation == "margin" else {
        "stat": "Ok", "stCode": 200, "nOrdNo": "synthetic-order",
    }
    facade, calls = sdk_runtime(response)
    adapter = KotakNeoAdapter(client_factory=lambda _: facade, contract_resolver=resolver)
    original = adapter.preflight_order
    entered, release = threading.Event(), threading.Event()

    def hold_preflight(order: Order) -> dict[str, Any] | None:
        result = original(order)
        if threading.current_thread() is not threading.main_thread():
            entered.set()
            assert release.wait(3)
        return result

    monkeypatch.setattr(adapter_module, "datetime", Clock)
    monkeypatch.setattr(adapter, "preflight_order", hold_preflight)
    task = asyncio.create_task(_dispatch_listing(adapter, row, operation, "NFO"))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        assert calls == []
        if advance:
            fixed[0] = datetime(2099, 6, 22, 18, 30, tzinfo=UTC)
    finally:
        release.set()
        result = (await asyncio.gather(task, return_exceptions=True))[0]
    if advance:
        assert isinstance(result, UnsupportedCapabilityError)
        assert calls == []
    else:
        assert not isinstance(result, BaseException) and len(calls) == 1
