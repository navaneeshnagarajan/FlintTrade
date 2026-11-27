"""Synthetic observation bridge controls; not broker/payment qualification.

The registry, ACL, read owner and durable lifecycle owner are real. Generic
bridge controls use labelled synthetic adapter outputs; concrete controls use
real adapters, mappers and installed SDKs with inert synthetic transports.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from flinttrade_core.broker_identity import BrokerSelector
from flinttrade_core.broker_read_port import BrokerReadFailure, BrokerReadSuccess, ExactReadTarget
from flinttrade_core.models import Trade
from flinttrade_core.secure_file import harden_directory
from flinttrade_core.workspace_migrations import broker_workspace_version, compare_and_swap_workspace
from flinttrade_engine.request_context import RequestContext
from flinttrade_gateway import registry as registry_api
from flinttrade_gateway.broker_read_service import create_broker_read_owner
from flinttrade_gateway.brokers._base import AdapterSessionView, Session
from flinttrade_gateway.session_provider import AuthenticatingSessionProvider
from flinttrade_gateway.credentials import CredentialStore

pytestmark = pytest.mark.unit


def richer_trade(**changes: object) -> dict[str, Any]:
    """Build independently labelled synthetic native trade observations.

    Args:
        changes: Explicit synthetic native-field replacements.

    Returns:
        A detached synthetic raw trade mapping.
    """
    return {
        "orderid": "OrderAa",
        "symbol": "SYNTHETIC-OPTION",
        "instrument_id": "TokenAa",
        "exchange": "NFO",
        "action": "BUY",
        "quantity": "1",
        "price": "12.50",
        "product": "NRML",
        "timestamp": "2026-10-23T10:01:00+05:30",
        "fill_id": "FillAa",
        "fill_leg": "1",
        "exchange_order_id": "ExchangeAa",
        "broker_account_id": "NativeCase",
        "broker_exchange_segment": "NSE_FNO",
        "broker_product_type": "MARGIN",
        "trade_date": "2026-10-23",
        "created_at": "created",
        "updated_at": "updated",
        "exchange_time": "exchange",
        "fill_time": "fill",
        "broker_fields": {
            "exchangeTradeId": "FillAa",
            "tradedQuantity": 1,
            "quantity": "1",
            "tradedPrice": "12.50",
            "securityId": "TokenAa",
            "drvOptionType": "CALL",
        },
        **changes,
    }


class SyntheticAdapter:
    """Return labelled synthetic observations without external broker I/O."""

    def __init__(self, rows: object) -> None:
        self.rows: object = rows
        self.calls: list[tuple[object, ...]] = []

    async def trade_book(self, session: AdapterSessionView) -> object:
        """Return the deliberately synthetic result and record its native account.

        Args:
            session: Exact registry-owned adapter session.

        Returns:
            The configured synthetic payload, not provider qualification.
        """
        self.calls.append(("trades", session.account_id))
        return self.rows


@pytest.fixture
def bound(tmp_path: Path) -> Iterator[Callable[..., SimpleNamespace]]:
    """Yield real isolated read owners and drain every acquired owner.

    Args:
        tmp_path: Disposable workspace and ledger directory.

    Yields:
        A binder returning a real registry, port, owner and disposable storage.
    """
    owners = []
    stores = []

    def bind(adapter, broker="dhan", native_account="NativeCase", client=None):
        path = tmp_path / f"workspace-{len(owners)}"
        path.mkdir()
        harden_directory(path)
        selector = BrokerSelector(broker, "AliasCase")

        def initialise(config):
            config["brokers"]["account_acls"] = {broker: {"AliasCase": ["actor"]}}

        workspace = compare_and_swap_workspace(path, None, initialise)
        store = CredentialStore(path / "credentials.db", "synthetic-password")
        stores.append(store)
        store.put_credentials(
            selector, broker, "Synthetic", {"token": "synthetic-token"}, expected=store.selector_state(selector).version
        )
        credential = store.selector_state(selector).version
        authority = registry_api.ManagedSessionAuthority(
            credential, workspace.version, broker_workspace_version(workspace)
        )
        registry, publisher = registry_api.create_owned_registry()
        session = Session("synthetic-token", time.time() + 3600, native_account, broker)
        if client is not None:
            session.extra["client"] = client
        receipt = publisher.prepare_session_candidate(
            selector,
            session,
            expected_registry=registry.snapshot_selector(selector),
            authority=authority,
            broker=broker,
            label="Synthetic",
            client=object() if client is None else client,
        )
        publisher.publish_prepared_candidate(receipt, current_authority=authority)
        provider = AuthenticatingSessionProvider(
            registry,
            {broker: {"AliasCase": ["actor"]}},
            workspace_snapshot=workspace,
            workspace_path=path,
            credential_version_for=lambda target: store.selector_state(target).version if target == selector else None,
        )
        context = [RequestContext("jti", "human", "actor", "practice", selector=f"{broker}:AliasCase")]

        class Limiter:
            def __init__(self):
                self.calls = []

            async def acquire(self, adapter_id, kind, *, before_retry=None):
                self.calls.append((adapter_id, kind))

        limiter = Limiter()
        owner = create_broker_read_owner(
            registry=registry,
            session_provider=provider,
            adapters={broker: adapter},
            workspace_path=path,
            rate_limiter=limiter,
            runtime_accepting_requests=lambda: True,
        )
        owners.append(owner)
        port = owner.bind(target=ExactReadTarget(selector), verify_current_authority=lambda: context[0])
        assert not isinstance(port, BrokerReadFailure)
        return SimpleNamespace(
            owner=owner,
            port=port,
            selector=selector,
            publisher=publisher,
            registry=registry,
            context=context,
            limiter=limiter,
            session=session,
            store=store,
            workspace_path=path,
        )

    yield bind
    for owner in owners:
        assert owner.close(timeout=1.0)
    for store in stores:
        store.close()


@pytest.mark.parametrize("model", [False, True])
def test_native_fill_identity_and_independent_raw_observations_survive(
    bound: Callable[..., SimpleNamespace],
    model: bool,
) -> None:
    """Verify native fill identity and independent raw observations survive.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
        model: Use the validated Trade model rather than a dictionary.
    """
    raw = richer_trade()
    adapter = SyntheticAdapter([Trade(**raw) if model else raw])
    handle = bound(adapter)
    result = asyncio.run(handle.port.trades())
    assert isinstance(result, BrokerReadSuccess)
    trade = result.value[0]
    assert getattr(trade, "fill_id", None) == "FillAa"
    assert trade.fill_leg == "1"
    assert trade.broker_account_id == "NativeCase"  # not the public alias
    assert trade.exchange_order_id == "ExchangeAa"
    assert (trade.created_at, trade.updated_at, trade.exchange_time, trade.fill_time) == (
        "created",
        "updated",
        "exchange",
        "fill",
    )
    observed = json.loads(trade.raw_observation_json)
    assert observed["broker_fields"] == raw["broker_fields"]
    raw["broker_fields"]["securityId"] = "changed"
    assert json.loads(trade.raw_observation_json)["broker_fields"]["securityId"] == "TokenAa"


@pytest.mark.parametrize("account", ["AliasCase", "nativecase", "Foreign"])
def test_foreign_native_account_is_not_the_public_alias(bound: Callable[..., SimpleNamespace], account: str) -> None:
    """Verify foreign native account is not the public alias.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
        account: Native account spelling under test.
    """
    handle = bound(SyntheticAdapter([richer_trade(broker_account_id=account)]))
    result = asyncio.run(handle.port.trades())
    assert isinstance(result, BrokerReadFailure)
    assert result.code.value == "malformed_response"


@pytest.mark.parametrize(
    "native",
    [
        {"tradedQuantity": 1, "quantity": 2},
        {"tradedQuantity": 2, "quantity": 2},
        {"tradedPrice": "12.50", "price": "13.50"},
        {"dhanClientId": "Foreign"},
        {"exchangeTradeId": "fillaA"},
    ],
)
def test_same_meaning_native_conflicts_are_not_hidden(
    bound: Callable[..., SimpleNamespace],
    native: dict[str, object],
) -> None:
    """Verify same meaning native conflicts are not hidden.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
        native: Independent native observations under test.
    """
    handle = bound(SyntheticAdapter([richer_trade(broker_fields=native)]))
    result = asyncio.run(handle.port.trades())
    assert isinstance(result, BrokerReadFailure)
    assert result.code.value == "malformed_response"


def test_kotak_independent_quantities_and_empty_token_are_preserved(bound: Callable[..., SimpleNamespace]) -> None:
    """Verify kotak independent quantities and empty token are preserved.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
    """
    row = richer_trade(
        instrument_id="",
        broker_exchange_segment="nse_fo",
        broker_fields={"flId": "FillAa", "qty": "0", "fldQty": "1", "tok": "", "flTm": "10:02", "exTm": "10:01"},
    )
    handle = bound(SyntheticAdapter([row]), broker="kotakneo")
    result = asyncio.run(handle.port.trades())
    assert isinstance(result, BrokerReadSuccess)
    assert result.value[0].instrument_id is None
    assert result.value[0].quantity == "1"
    assert json.loads(result.value[0].raw_observation_json)["broker_fields"] == row["broker_fields"]


def test_raw_evidence_is_hook_free_and_secrets_are_not_projected(bound: Callable[..., SimpleNamespace]) -> None:
    """Verify raw evidence is hook free and secrets are not projected.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
    """
    class Trap:
        def __deepcopy__(self, _memo):
            pytest.fail("deepcopy hook invoked")

        def __str__(self):
            pytest.fail("string hook invoked")

    row = richer_trade(broker_fields={"securityId": Trap()})
    handle = bound(SyntheticAdapter([row]))
    assert isinstance(asyncio.run(handle.port.trades()), BrokerReadFailure)
    row["broker_fields"] = {"access_token": "not-evidence", "securityId": "TokenAa"}
    result = asyncio.run(handle.port.trades())
    assert isinstance(result, BrokerReadSuccess)
    assert "not-evidence" not in result.value[0].raw_observation_json


def test_canonical_refresh_persists_fills_and_available_empty_is_not_lifetime_empty(
    bound: Callable[..., SimpleNamespace],
    tmp_path: Path,
) -> None:
    """Verify canonical refresh persists fills and available empty is not lifetime empty.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
        tmp_path: Disposable workspace and ledger directory.
    """
    from flinttrade_engine.local_state_provider import OrderLifecycleLedger

    adapter = SyntheticAdapter([richer_trade()])
    handle = bound(adapter)
    path = tmp_path / "canonical.sqlite3"
    ledger = OrderLifecycleLedger(ledger_path=path)
    assert callable(getattr(ledger, "refresh_observations", None))
    captured = asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    assert captured.generation > 0
    assert len(captured.fills) == 1
    assert captured.fills[0].trade.fill_id == "FillAa"
    assert captured.fills[0].owner_attempt_id is None
    assert captured.fills[0].namespace[1] == "NativeCase"
    coverage = next(c for c in captured.coverage if c.resource == "trades.daily")
    assert coverage.availability == "available"
    assert coverage.observed_count == 1
    assert coverage.completeness == "window_only"
    assert coverage.atomic is False
    assert not captured.admission_available
    adapter.rows = []
    empty = asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    assert len(empty.fills) == 1
    assert next(c for c in empty.coverage if c.resource == "trades.daily").observed_count == 0
    restarted = OrderLifecycleLedger(ledger_path=path)
    retained = restarted.observation_snapshot(handle.selector)
    assert retained.fills == empty.fills
    assert retained.generation == empty.generation
    assert not retained.source_current
    before = len(adapter.calls)
    assert restarted.observation_snapshot(handle.selector).fills == retained.fills
    assert len(adapter.calls) == before  # inspection never fetches or logs in


@pytest.fixture
def scoped_canonical(bound: Any, backend_lease_factory: Any, monkeypatch: Any, tmp_path: Path) -> Any:
    """Issue independent synthetic native scope through real writer/read owners."""
    from flinttrade_engine.local_state_provider import OrderLifecycleLedger
    from flinttrade_engine.safety import SafetyContext
    from flinttrade_gateway.native_scope_primitives import SyntheticNativeScopeSource
    from packages.integrations.gateway.tests.test_native_scope_correspondence import ScopedTransport, resource
    from packages.integrations.gateway.tests.test_writer_native_provenance import _provider, _writer, _submit

    adapter = ScopedTransport()
    adapter.resources = [resource(date="2026-10-23")]
    handle = bound(adapter)
    adapter.primitive_source = SyntheticNativeScopeSource(adapter=adapter, transport=adapter.transport,
        reader=adapter.native_scope_read, workspace_path=handle.workspace_path, label="synthetic-canonical-positive")
    owner = create_broker_read_owner(registry=handle.registry, session_provider=_provider(handle),
        adapters={"dhan": adapter}, workspace_path=handle.workspace_path, runtime_accepting_requests=lambda: True,
        native_scope_source=adapter.primitive_source)
    port = owner.bind(target=ExactReadTarget(handle.selector), verify_current_authority=lambda: handle.context[0])
    ledger = OrderLifecycleLedger(ledger_path=tmp_path/"canonical.sqlite3")
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(handle.workspace_path))
    proof = backend_lease_factory()
    router, context, order, _ = _writer(handle, adapter, ledger, proof)
    order = order.model_copy(update={"quantity": "10"})
    signed = SafetyContext.mint(order, mode="live", user_jti=context.jti, actor_type="human",
        adapter_id="dhan", account_id="AliasCase", backend_lease_proof=proof)
    try:
        asyncio.run(_submit(router, context, order, signed))
        attempt = ledger.list_dispatch_attempts()[0]["attempt_id"]
        row = adapter.native_records[0]["resources"][0]
        row["filled_quantity"] = "1"
        row["executions"] = [{"fill_id": "FillAa", "execution_date": "2026-10-23", "fill_leg": "1"}]
        yield SimpleNamespace(adapter=adapter, handle=SimpleNamespace(owner=owner, port=port, selector=handle.selector),
                              ledger=ledger, attempt=attempt)
    finally:
        assert router.revoke_and_drain(timeout=1)
        assert owner.close(timeout=1)


def test_canonical_attribution_dedup_and_conflict_survive_restart(
    scoped_canonical: Any,
) -> None:
    """Verify canonical attribution dedup and conflict survive restart.

    Args:
        scoped_canonical: Genuine writer-issued synthetic resource fixture.
    """
    from flinttrade_engine.local_state_provider import OrderLifecycleLedger

    desk = scoped_canonical
    adapter, handle, ledger = desk.adapter, desk.handle, desk.ledger
    path, attempt = ledger._path(), desk.attempt
    first = asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    assert first.fills[0].owner_attempt_id == attempt
    adapter.rows = [richer_trade(updated_at="newer", broker_fields={"exchangeTradeId": "FillAa", "stt": "0.20"})]
    second = asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    assert len(second.fills) == 1
    assert not second.conflicts  # fee/time enrichment is not a second execution
    adapter.rows = [richer_trade(price="13", broker_fields={})]
    conflict = asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    assert len(conflict.fills) == 1
    assert conflict.fills[0].trade.price == "12.50"
    assert any(item.startswith("immutable_fill_conflict:") for item in conflict.conflicts)
    assert OrderLifecycleLedger(ledger_path=path).observation_snapshot(handle.selector).conflicts == conflict.conflicts


def test_current_source_is_owner_resolved_and_retirement_keeps_obligations(
    bound: Callable[..., SimpleNamespace],
    tmp_path: Path,
) -> None:
    """Verify current source is owner resolved and retirement keeps obligations.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
        tmp_path: Disposable workspace and ledger directory.
    """
    from flinttrade_engine.local_state_provider import OrderLifecycleLedger, LifecycleStateError

    adapter = SyntheticAdapter([richer_trade()])
    handle = bound(adapter)
    ledger = OrderLifecycleLedger(ledger_path=tmp_path / "canonical.sqlite3")
    asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    current = ledger.observation_snapshot(
        handle.selector, read_owner=handle.owner, port=handle.port, max_age_seconds=30
    )
    assert current.source_current
    handle.owner.revoke(handle.port)
    retired = ledger.observation_snapshot(
        handle.selector, read_owner=handle.owner, port=handle.port, max_age_seconds=30
    )
    assert not retired.source_current
    assert retired.fills == current.fills
    with pytest.raises(LifecycleStateError):
        asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    assert ledger.observation_snapshot(handle.selector).fills == current.fills


def test_bounded_history_captures_overlap_without_inventing_terminal_pages(
    bound: Callable[..., SimpleNamespace],
    tmp_path: Path,
) -> None:
    """Verify bounded history captures overlap without inventing terminal pages.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
        tmp_path: Disposable workspace and ledger directory.
    """
    import flinttrade_core.broker_read_port as contracts
    from flinttrade_engine.local_state_provider import OrderLifecycleLedger

    assert hasattr(contracts, "TradeHistoryRequest")

    class HistoryAdapter(SyntheticAdapter):
        async def trade_history(self, session, from_date, to_date, page=0):
            self.calls.append(("history", page, from_date, to_date))
            return [richer_trade()] if page in (0, 1) else []

    adapter = HistoryAdapter([richer_trade()])
    handle = bound(adapter)
    request = contracts.TradeHistoryRequest("2026-10-23", "2026-10-24", max_pages=4)
    ledger = OrderLifecycleLedger(ledger_path=tmp_path / "canonical.sqlite3")
    snapshot = asyncio.run(ledger.refresh_observations(handle.owner, handle.port, history=request))
    assert len(snapshot.fills) == 1
    history = next(c for c in snapshot.coverage if c.resource == "trades.history")
    assert history.pages == (0, 1)
    assert "repeated_page" in history.issues
    assert history.completeness == "partial"
    assert history.terminal_evidence is None
    assert len([c for c in adapter.calls if c[0] == "history"]) == 2


@pytest.mark.parametrize(
    "payload,availability", [([], "available"), (None, "malformed_response"), ([None], "malformed_response")]
)
def test_empty_and_malformed_daily_coverage_are_distinct(
    bound: Callable[..., SimpleNamespace],
    tmp_path: Path,
    payload: object,
    availability: str,
) -> None:
    """Verify empty and malformed daily coverage are distinct.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
        tmp_path: Disposable workspace and ledger directory.
        payload: Synthetic collection payload or malformed variant.
        availability: Expected explicit availability state.
    """
    from flinttrade_engine.local_state_provider import OrderLifecycleLedger

    handle = bound(SyntheticAdapter(payload))
    ledger = OrderLifecycleLedger(ledger_path=tmp_path / "canonical.sqlite3")
    snapshot = asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    assert snapshot.coverage[0].availability == availability
    assert snapshot.coverage[0].observed_count == 0
    assert not snapshot.admission_available


def test_kotak_history_is_explicitly_unavailable_not_a_synthetic_empty_book(
    bound: Callable[..., SimpleNamespace],
    tmp_path: Path,
) -> None:
    """Verify kotak history is explicitly unavailable not a synthetic empty book.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
        tmp_path: Disposable workspace and ledger directory.
    """
    import flinttrade_core.broker_read_port as contracts
    from flinttrade_engine.local_state_provider import OrderLifecycleLedger

    assert hasattr(contracts, "TradeHistoryRequest")
    adapter = SyntheticAdapter([])
    handle = bound(adapter, broker="kotakneo")
    request = contracts.TradeHistoryRequest("2026-10-23", "2026-10-24", max_pages=2)
    snapshot = asyncio.run(
        OrderLifecycleLedger(ledger_path=tmp_path / "canonical.sqlite3").refresh_observations(
            handle.owner, handle.port, history=request
        )
    )
    history = next(c for c in snapshot.coverage if c.resource == "trades.history")
    assert history.availability == "unsupported"
    assert history.completeness == "unknown"
    assert history.pages == ()


def test_observed_charges_remain_payment_unknown_and_survive_outage(
    bound: Callable[..., SimpleNamespace],
    tmp_path: Path,
) -> None:
    """Verify observed charges remain payment unknown and survive outage.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
        tmp_path: Disposable workspace and ledger directory.
    """
    from flinttrade_engine.local_state_provider import OrderLifecycleLedger

    adapter = SyntheticAdapter(
        [
            richer_trade(
                broker_fields={
                    "stt": "0.20",
                    "brokerageCharges": "2.00",
                    "paid": True,
                    "payment_reference": "caller-upload",
                    "timestamp": "paid-at",
                }
            )
        ]
    )
    handle = bound(adapter)
    path = tmp_path / "canonical.sqlite3"
    ledger = OrderLifecycleLedger(ledger_path=path)
    snapshot = asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    assert hasattr(snapshot, "fees")
    assert {(f.component, f.amount, f.state.value) for f in snapshot.fees} == {
        ("stt", "0.20", "payment_unknown"),
        ("brokerageCharges", "2.00", "payment_unknown"),
    }
    assert all(f.payment_reference is None and f.policy_reference is None for f in snapshot.fees)
    adapter.rows = None
    unavailable = asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    assert unavailable.fees == snapshot.fees
    assert OrderLifecycleLedger(ledger_path=path).observation_snapshot(handle.selector).fees == snapshot.fees


@pytest.mark.parametrize("claimed", ["broker_hold", "accrued_unpaid", "observed_paid", "adjustment", "reversed"])
def test_unreviewed_fee_state_never_creates_payment_attestation(
    bound: Callable[..., SimpleNamespace],
    tmp_path: Path,
    claimed: str,
) -> None:
    """Verify unreviewed fee state never creates payment attestation.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
        tmp_path: Disposable workspace and ledger directory.
        claimed: Untrusted payment disposition to refuse.
    """
    from flinttrade_engine.local_state_provider import OrderLifecycleLedger

    handle = bound(
        SyntheticAdapter([richer_trade(broker_fields={"brokerageCharges": "2", "state": claimed, "paid": True})])
    )
    snapshot = asyncio.run(
        OrderLifecycleLedger(ledger_path=tmp_path / "canonical.sqlite3").refresh_observations(handle.owner, handle.port)
    )
    assert hasattr(snapshot, "fees")
    assert snapshot.fees[0].state.value == "payment_unknown"
    assert "paid_allocation_producer_unavailable" in snapshot.missing_evidence


def test_contract_revision_raw_tick_units_and_margin_meanings_survive(
    bound: Callable[..., SimpleNamespace],
    tmp_path: Path,
) -> None:
    """Verify contract revision raw tick units and margin meanings survive.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
        tmp_path: Disposable workspace and ledger directory.
    """
    from flinttrade_core.broker_read_port import LotSizeRequest, MarginRequest
    from flinttrade_engine.local_state_provider import OrderLifecycleLedger

    class ContractAdapter(SyntheticAdapter):
        async def instrument_lot_sizes(self, session, request):
            return [
                {
                    "symbol": "SYNTHETIC-OPTION",
                    "exchange": "NFO",
                    "instrument_id": "TokenAa",
                    "lot_size": 1,
                    "underlying": "SYNTHETIC",
                    "expiry": "2026-10-29",
                    "option_type": "CE",
                    "strike_price": "100",
                    "tick_size": "0.05",
                    "tick_unit": "INR",
                    "raw_tick_size": "5",
                    "raw_tick_unit": "unknown",
                    "source_revision": "synthetic-v1",
                    "source_digest": "a" * 64,
                    "observed_at": "2020-01-01T00:00:00+00:00",
                    "valid_until": "2020-01-02T00:00:00+00:00",
                }
            ]

        async def margin_calculator(self, session, order):
            return {
                "required_margin": "100",
                "provider_additional_margin": "25",
                "rms_validated": "NOT_OK",
                "brokerage": "2.5",
            }

    handle = bound(ContractAdapter([]))
    lot_request = LotSizeRequest("NFO", ("SYNTHETIC-OPTION",))
    lots = asyncio.run(handle.port.lot_sizes(lot_request))
    assert isinstance(lots, BrokerReadSuccess)
    assert getattr(lots.value[0], "source_revision", None) == "synthetic-v1"
    assert lots.value[0].raw_tick_size == "5"
    assert lots.value[0].raw_tick_unit == "unknown"
    margin_request = MarginRequest("SYNTHETIC-OPTION", "NFO", "SELL", "1", "NRML", "LIMIT", "12.5", "0")
    margin = asyncio.run(handle.port.margin(margin_request))
    assert isinstance(margin, BrokerReadSuccess)
    assert margin.value.provider_additional_margin == "25"
    assert margin.value.rms_validated == "NOT_OK"
    assert margin.value.request == margin_request
    ledger = OrderLifecycleLedger(ledger_path=tmp_path / "canonical.sqlite3")
    snapshot = asyncio.run(
        ledger.refresh_observations(handle.owner, handle.port, lots=lot_request, margin=margin_request)
    )
    assert snapshot.contracts[0].source_revision == "synthetic-v1"
    assert "contract_stale" in snapshot.missing_evidence
    assert snapshot.margins[0].required_margin == 100.0
    assert any(f.state.value == "estimated" for f in snapshot.fees)


def test_unique_fills_and_cumulative_high_water_are_not_added_twice(
    scoped_canonical: Any,
) -> None:
    """Verify unique fills and cumulative high water are not added twice.

    Args:
        scoped_canonical: Genuine writer-issued synthetic resource fixture.
    """
    desk = scoped_canonical
    adapter, handle, ledger = desk.adapter, desk.handle, desk.ledger
    adapter.rows = [richer_trade(fill_id="FillAa", broker_fields={}), richer_trade(fill_id="FillBb", broker_fields={})]
    resource = adapter.native_records[0]["resources"][0]
    order = {
        "orderid": "OrderAa",
        "symbol": "SYNTHETIC-OPTION",
        "exchange": "NFO",
        "product": "NRML",
        "action": "BUY",
        "status": "PARTIALLY_FILLED",
        "quantity": "10",
        "filled_quantity": "3",
        "price": "12.5",
    }
    resource["filled_quantity"] = "3.0"
    resource["executions"] = [{"fill_id": fill, "execution_date": "2026-10-23", "fill_leg": "1"}
                              for fill in ("FillAa", "FillBb")]
    snapshot = asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    assert hasattr(snapshot, "order_fills")
    assert snapshot.order_fills[0].unique_quantity == "2"
    assert snapshot.order_fills[0].cumulative_high_water == "3.0"
    assert snapshot.order_fills[0].unexplained_quantity == "1.0"
    order.update(status="CANCELLED", filled_quantity="0")
    resource["filled_quantity"] = order["filled_quantity"]
    adapter.rows = []
    after = asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    assert after.order_fills == snapshot.order_fills
    assert len(after.fills) == 2


def test_actual_base_adapter_history_and_ledger_are_observations_not_paid_allocations(
    bound: Callable[..., SimpleNamespace],
    tmp_path: Path,
) -> None:
    """Verify actual base adapter history and ledger are observations not paid allocations.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
        tmp_path: Disposable workspace and ledger directory.
    """
    import flinttrade_core.broker_read_port as contracts
    from flinttrade_engine.local_state_provider import OrderLifecycleLedger
    from flinttrade_gateway.brokers.dhan import DhanAdapter
    from flinttrade_gateway.brokers.dhan_mapping import from_dhan_trade

    native = {
        "dhanClientId": "NativeCase",
        "orderId": "OrderAa",
        "exchangeOrderId": "ExchangeAa",
        "exchangeTradeId": "FillAa",
        "tradingSymbol": "SYNTHETIC-OPTION",
        "securityId": "TokenAa",
        "exchangeSegment": "NSE_FNO",
        "productType": "MARGIN",
        "transactionType": "BUY",
        "tradedQuantity": 1,
        "tradedPrice": 12.5,
        "exchangeTime": "2026-10-23 10:01:00",
        "stt": "0.2",
    }

    class InertClient:
        def get_trade_book(self):
            return {"status": "success", "data": [native]}

        def get_trade_history(self, start, end, page):
            return {"status": "success", "data": [native] if page == 0 else []}

        def ledger_report(self, start, end):
            return {
                "status": "success",
                "data": [
                    {
                        "dhanClientId": "NativeCase",
                        "voucherdate": "2026-10-24",
                        "vouchernumber": "VoucherAa",
                        "debit": "10",
                        "credit": "0",
                        "runbal": "100",
                        "narration": "account posting",
                    }
                ],
            }

    client = InertClient()
    handle = bound(DhanAdapter(client_factory=lambda session: client))
    daily = asyncio.run(handle.port.trades())
    assert isinstance(daily, BrokerReadSuccess)
    # Verify the actual baseline mapper path without inventing metadata it lost.
    assert daily.value[0].fill_id == from_dhan_trade(native).get("fill_id")
    history = asyncio.run(handle.port.trade_history(contracts.TradeHistoryRequest("2026-10-23", "2026-10-24", 2)))
    assert isinstance(history, BrokerReadSuccess)
    assert history.value.coverage.availability == "available"
    assert history.value.trades[0].fill_id == "FillAa"
    assert hasattr(contracts, "LedgerRequest")
    ledger = OrderLifecycleLedger(ledger_path=tmp_path / "canonical.sqlite3")
    snapshot = asyncio.run(
        ledger.refresh_observations(
            handle.owner, handle.port, ledger=contracts.LedgerRequest("2026-10-23", "2026-10-24")
        )
    )
    assert snapshot.account_postings[0].voucher_number == "VoucherAa"
    assert snapshot.account_postings[0].debit == "10"
    assert not any(f.state.value == "observed_paid" for f in snapshot.fees)


def test_invalid_collection_is_refused_before_any_provider_read(
    bound: Callable[..., SimpleNamespace],
    tmp_path: Path,
) -> None:
    """Verify invalid collection is refused before any provider read.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
        tmp_path: Disposable workspace and ledger directory.
    """
    from flinttrade_engine.local_state_provider import OrderLifecycleLedger, LifecycleStateError

    adapter = SyntheticAdapter([])
    handle = bound(adapter)
    ledger = OrderLifecycleLedger(ledger_path=tmp_path / "canonical.sqlite3")
    with pytest.raises(LifecycleStateError):
        asyncio.run(ledger.refresh_observations(handle.owner, handle.port, history={"max_pages": 999999}))
    assert adapter.calls == []


def test_rollover_during_collection_is_not_a_single_day_complete_read(
    bound: Callable[..., SimpleNamespace],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify rollover during collection is not a single day complete read.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
        monkeypatch: Scoped clock or inert transport injection.
    """
    from datetime import datetime, UTC
    import flinttrade_gateway.broker_read_service as service

    class Clock:
        calls = 0

        @classmethod
        def now(cls, tz):
            cls.calls += 1
            return datetime(2026, 10, 23 if cls.calls == 1 else 24, 18, 29, tzinfo=UTC)

    handle = bound(SyntheticAdapter([]))
    monkeypatch.setattr(service, "datetime", Clock)
    result = asyncio.run(handle.owner.capture_observations(handle.port))
    coverage = result.coverage[0]
    assert coverage.trading_date is None
    assert coverage.completeness == "partial"
    assert "collection_crossed_trading_day" in coverage.issues


def test_unallocated_fee_amount_is_retained_even_when_fill_identity_is_missing(
    bound: Callable[..., SimpleNamespace],
    tmp_path: Path,
) -> None:
    """Verify unallocated fee amount is retained even when fill identity is missing.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
        tmp_path: Disposable workspace and ledger directory.
    """
    from flinttrade_engine.local_state_provider import OrderLifecycleLedger

    adapter = SyntheticAdapter([richer_trade(fill_id=None, broker_fields={"stt": "0.2"})])
    handle = bound(adapter)
    ledger = OrderLifecycleLedger(ledger_path=tmp_path / "canonical.sqlite3")
    first = asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    assert len(first.fees) == 1
    assert "fill_identity_unavailable" in first.missing_evidence
    adapter.rows = []
    assert asyncio.run(ledger.refresh_observations(handle.owner, handle.port)).fees == first.fees


def test_empty_new_day_does_not_resolve_previous_possible_write(
    bound: Callable[..., SimpleNamespace],
    tmp_path: Path,
) -> None:
    """Verify empty new day does not resolve previous possible write.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
        tmp_path: Disposable workspace and ledger directory.
    """
    from datetime import datetime, UTC
    from flinttrade_engine.local_state_provider import OrderLifecycleLedger

    handle = bound(SyntheticAdapter([]))
    path = tmp_path / "canonical.sqlite3"
    ledger = OrderLifecycleLedger(ledger_path=path)
    stamp = datetime(2026, 10, 22, tzinfo=UTC)
    attempt = ledger.prepare_dispatch(
        adapter_id="dhan",
        account_id="AliasCase",
        operation="place_order",
        request_context=handle.context[0],
        payload={
            "symbol": "SYNTHETIC-OPTION",
            "exchange": "NFO",
            "product": "NRML",
            "action": "BUY",
            "quantity": 2,
            "price": 12.5,
        },
        observed_at=stamp,
    )
    ledger.mark_invoked(attempt, observed_at=stamp)
    ledger.mark_outcome_unknown(attempt, error_kind="synthetic_timeout", observed_at=stamp)
    asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    assert ledger.list_unresolved_outcomes()[0]["attempt_id"] == attempt
    restarted = OrderLifecycleLedger(ledger_path=path)
    assert restarted.list_unresolved_outcomes()[0]["attempt_id"] == attempt


@pytest.mark.parametrize("kind", ["workspace", "registry", "credential"])
def test_generation_retirement_during_read_refuses_publication(
    bound: Callable[..., SimpleNamespace],
    tmp_path: Path,
    kind: str,
) -> None:
    """Verify generation retirement during read refuses publication.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
        tmp_path: Disposable workspace and ledger directory.
        kind: Owner generation to retire.
    """
    from flinttrade_engine.local_state_provider import OrderLifecycleLedger, LifecycleStateError

    class HeldAdapter(SyntheticAdapter):
        async def trade_book(self, session):
            self.started.set()
            await self.release.wait()
            return self.rows

    adapter = HeldAdapter([richer_trade()])
    handle = bound(adapter)
    ledger = OrderLifecycleLedger(ledger_path=tmp_path / "canonical.sqlite3")

    async def run():
        adapter.started, adapter.release = asyncio.Event(), asyncio.Event()
        task = asyncio.create_task(ledger.refresh_observations(handle.owner, handle.port))
        await adapter.started.wait()
        try:
            if kind == "workspace":
                from flinttrade_core.workspace_migrations import read_workspace_snapshot

                snapshot = read_workspace_snapshot(handle.workspace_path)
                compare_and_swap_workspace(
                    handle.workspace_path, snapshot.version, lambda config: config["brokers"]["account_acls"].clear()
                )
            elif kind == "registry":
                handle.publisher.remove_session_for_exact(
                    handle.selector, expected_registry=handle.registry.snapshot_selector(handle.selector)
                )
            else:
                handle.store.put_credentials(
                    handle.selector,
                    "dhan",
                    "Synthetic",
                    {"token": "new-synthetic-token"},
                    expected=handle.store.selector_state(handle.selector).version,
                )
            adapter.release.set()
            with pytest.raises(LifecycleStateError):
                await task
            assert ledger.observation_snapshot(handle.selector).generation == 0
        finally:
            adapter.release.set()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


@pytest.mark.parametrize(
    "field,value",
    [
        ("fill_id", 7),
        ("fill_id", type("TextSubclass", (str,), {})("FillAa")),
        ("broker_fields", type("DictSubclass", (dict,), {})({"stt": "1"})),
    ],
)
def test_trade_model_does_not_coerce_native_evidence(field: str, value: object) -> None:
    """Verify trade model does not coerce native evidence.

    Args:
        field: Native evidence field to challenge.
        value: Malformed primitive or subclass to refuse.
    """
    with pytest.raises(ValueError):
        Trade(**richer_trade(**{field: value}))


@pytest.mark.parametrize("quantity", ["0", "-1", "1.5", "1e999999"])
def test_non_execution_quantities_never_enter_canonical_unique_fills(
    bound: Callable[..., SimpleNamespace],
    tmp_path: Path,
    quantity: object,
) -> None:
    """Verify non execution quantities never enter canonical unique fills.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
        tmp_path: Disposable workspace and ledger directory.
        quantity: Non-execution quantity that must remain unallocated.
    """
    from flinttrade_engine.local_state_provider import OrderLifecycleLedger

    handle = bound(SyntheticAdapter([richer_trade(quantity=quantity, broker_fields={})]))
    snapshot = asyncio.run(
        OrderLifecycleLedger(ledger_path=tmp_path / "canonical.sqlite3").refresh_observations(handle.owner, handle.port)
    )
    assert snapshot.fills == ()
    assert "fill_quantity_unavailable" in snapshot.missing_evidence


def test_partial_page_failure_retains_prior_fills_and_latches_incompleteness(
    bound: Callable[..., SimpleNamespace],
    tmp_path: Path,
) -> None:
    """Verify partial page failure retains prior fills and latches incompleteness.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
        tmp_path: Disposable workspace and ledger directory.
    """
    from flinttrade_core.broker_read_port import TradeHistoryRequest
    from flinttrade_engine.local_state_provider import OrderLifecycleLedger

    class BrokenPage(SyntheticAdapter):
        async def trade_history(self, session, start, end, page=0):
            if page == 0:
                return [richer_trade()]
            raise RuntimeError("synthetic source outage")

    handle = bound(BrokenPage([]))
    result = asyncio.run(
        OrderLifecycleLedger(ledger_path=tmp_path / "canonical.sqlite3").refresh_observations(
            handle.owner, handle.port, history=TradeHistoryRequest("2026-10-23", "2026-10-24", 3)
        )
    )
    assert len(result.fills) == 1
    coverage = next(c for c in result.coverage if c.resource == "trades.history")
    assert coverage.availability == "provider_failure"
    assert coverage.completeness == "partial"
    assert coverage.pages == (0,)


def test_manifest_corruption_is_not_silently_recreated(bound: Callable[..., SimpleNamespace], tmp_path: Path) -> None:
    """Verify manifest corruption is not silently recreated.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
        tmp_path: Disposable workspace and ledger directory.
    """
    import sqlite3
    from flinttrade_engine.local_state_provider import OrderLifecycleLedger, LifecycleStateError

    handle = bound(SyntheticAdapter([richer_trade()]))
    path = tmp_path / "canonical.sqlite3"
    ledger = OrderLifecycleLedger(ledger_path=path)
    result = asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE snapshot_generation_manifests SET content_digest=? WHERE generation=?",
            ("0" * 64, result.generation),
        )
    with pytest.raises(LifecycleStateError, match="integrity"):
        OrderLifecycleLedger(ledger_path=path).observation_snapshot(handle.selector)


def test_coverage_history_keeps_outage_window_across_rollover_and_restart(
    bound: Callable[..., SimpleNamespace],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify coverage history keeps outage window across rollover and restart.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
        tmp_path: Disposable workspace and ledger directory.
        monkeypatch: Scoped clock or inert transport injection.
    """
    from datetime import datetime, UTC
    import flinttrade_gateway.broker_read_service as service
    from flinttrade_engine.local_state_provider import OrderLifecycleLedger

    class Clock:
        day = 22

        @classmethod
        def now(cls, tz):
            return datetime(2026, 10, cls.day, 9, 30, tzinfo=UTC)

    adapter = SyntheticAdapter([richer_trade(trade_date="2026-10-22")])
    handle = bound(adapter)
    monkeypatch.setattr(service, "datetime", Clock)
    path = tmp_path / "canonical.sqlite3"
    ledger = OrderLifecycleLedger(ledger_path=path)
    asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    Clock.day = 23
    adapter.rows = None
    asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    Clock.day = 24
    adapter.rows = []
    snapshot = asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    assert hasattr(snapshot, "coverage_history")
    daily = [c for c in snapshot.coverage_history if c.resource == "trades.daily"]
    assert [c.trading_date for c in daily] == ["2026-10-22", "2026-10-23", "2026-10-24"]
    assert all(c.provider_account_id == "NativeCase" and c.generation > 0 for c in daily)
    assert daily[1].availability == "malformed_response"
    assert "2026-10-23/2026-10-23" in daily[1].missing_intervals
    restarted = OrderLifecycleLedger(ledger_path=path).observation_snapshot(handle.selector)
    assert restarted.coverage_history == snapshot.coverage_history
    assert len(restarted.fills) == 1


def test_native_instrument_and_margin_fields_are_presence_sensitive(bound: Callable[..., SimpleNamespace]) -> None:
    """Verify native instrument and margin fields are presence sensitive.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
    """
    from flinttrade_core.broker_read_port import LotSizeRequest, MarginRequest

    class NativeMetadata(SyntheticAdapter):
        async def instrument_lot_sizes(self, session, request):
            return [
                {
                    "symbol": "S",
                    "exchange": "NFO",
                    "lot_size": 1,
                    "instrument_id": "Ta",
                    "broker_exchange_segment": "nse_fo",
                    "broker_fields": {"pSymbol": "Ta", "dTickSize": "5", "lPrecision": "2", "pExpiryDate": None},
                }
            ]

        async def margin_calculator(self, session, order):
            return {
                "required_margin": 100,
                "broker_fields": {"ordMrgn": "100", "reqdMrgn": "25", "rmsVldtd": "NOT_OK", "stat": "Ok"},
            }

    handle = bound(NativeMetadata([]), broker="kotakneo")
    lots = asyncio.run(handle.port.lot_sizes(LotSizeRequest("NFO", ("S",))))
    assert isinstance(lots, BrokerReadSuccess)
    raw = json.loads(lots.value[0].raw_observation_json)
    assert raw["broker_fields"]["pExpiryDate"] is None
    assert raw["broker_exchange_segment"] == "nse_fo"
    margin = asyncio.run(handle.port.margin(MarginRequest("S", "NFO", "SELL", "1", "NRML", "LIMIT", "1", "0")))
    assert isinstance(margin, BrokerReadSuccess)
    assert json.loads(margin.value.raw_observation_json)["broker_fields"]["rmsVldtd"] == "NOT_OK"
    assert margin.value.rms_validated is None  # raw state is not silently reinterpreted


def test_foreign_native_margin_account_is_refused(bound: Callable[..., SimpleNamespace]) -> None:
    """Verify foreign native margin account is refused.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
    """
    from flinttrade_core.broker_read_port import MarginRequest

    class ForeignMargin(SyntheticAdapter):
        async def margin_calculator(self, session, order):
            return {
                "required_margin": 100,
                "broker_account_id": "Foreign",
                "broker_fields": {"dhanClientId": "Foreign"},
            }

    handle = bound(ForeignMargin([]))
    result = asyncio.run(handle.port.margin(MarginRequest("S", "NFO", "BUY", "1", "NRML", "LIMIT", "1", "0")))
    assert isinstance(result, BrokerReadFailure)


def test_changed_native_contract_on_same_fill_is_a_retained_conflict(
    bound: Callable[..., SimpleNamespace],
    tmp_path: Path,
) -> None:
    """Verify changed native contract on same fill is a retained conflict.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
        tmp_path: Disposable workspace and ledger directory.
    """
    from flinttrade_engine.local_state_provider import OrderLifecycleLedger

    adapter = SyntheticAdapter([richer_trade(broker_fields={"drvExpiryDate": "2026-10-29", "drvOptionType": "CALL"})])
    handle = bound(adapter)
    ledger = OrderLifecycleLedger(ledger_path=tmp_path / "canonical.sqlite3")
    asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    adapter.rows = [richer_trade(broker_fields={"drvExpiryDate": "2026-11-26", "drvOptionType": "CALL"})]
    snapshot = asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    assert any(c.startswith("immutable_fill_conflict:") for c in snapshot.conflicts)
    assert len(snapshot.fills) == 1


def test_same_alias_rebound_to_case_distinct_native_account_is_not_a_join(
    bound: Callable[..., SimpleNamespace],
    tmp_path: Path,
) -> None:
    """Verify same alias rebound to case distinct native account is not a join.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
        tmp_path: Disposable workspace and ledger directory.
    """
    from flinttrade_engine.local_state_provider import OrderLifecycleLedger

    ledger = OrderLifecycleLedger(ledger_path=tmp_path / "canonical.sqlite3")
    first = bound(SyntheticAdapter([richer_trade()]))
    asyncio.run(ledger.refresh_observations(first.owner, first.port))
    second = bound(SyntheticAdapter([richer_trade(broker_account_id="nativecase")]), native_account="nativecase")
    snapshot = asyncio.run(ledger.refresh_observations(second.owner, second.port))
    assert len(snapshot.fills) == 2
    assert {f.namespace[1] for f in snapshot.fills} == {"NativeCase", "nativecase"}
    assert "provider_account_rebound" in snapshot.conflicts


def test_canonical_refresh_has_one_bounded_read_deadline(bound: Callable[..., SimpleNamespace], tmp_path: Path) -> None:
    """Verify canonical refresh has one bounded read deadline.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
        tmp_path: Disposable workspace and ledger directory.
    """
    from flinttrade_engine.local_state_provider import OrderLifecycleLedger

    class SlowSource(SyntheticAdapter):
        async def trade_book(self, session):
            await asyncio.Event().wait()

    handle = bound(SlowSource([]))
    ledger = OrderLifecycleLedger(ledger_path=tmp_path / "canonical.sqlite3")

    async def run():
        return await asyncio.wait_for(ledger.refresh_observations(handle.owner, handle.port, timeout_seconds=0.05), 1.0)

    snapshot = asyncio.run(run())
    assert snapshot.coverage[0].availability == "provider_failure"
    assert "read_deadline_exceeded" in snapshot.coverage[0].issues
    assert snapshot.generation > 0


def test_repaired_dhan_sdk_statement_coverage_reaches_canonical_owner(
    bound: Callable[..., SimpleNamespace],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify repaired dhan sdk statement coverage reaches canonical owner.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
        tmp_path: Disposable workspace and ledger directory.
        monkeypatch: Scoped clock or inert transport injection.
    """
    from dhanhq import DhanContext, dhanhq
    from flinttrade_gateway.brokers.dhan import DhanAdapter
    from flinttrade_core.broker_read_port import TradeHistoryRequest, LedgerRequest
    from flinttrade_engine.local_state_provider import OrderLifecycleLedger

    native = {
        "dhanClientId": "NativeCase",
        "orderId": "OrderAa",
        "exchangeTradeId": "FillAa",
        "exchangeOrderId": "ExchangeAa",
        "tradingSymbol": "SYNTHETIC-OPTION",
        "securityId": "TokenAa",
        "exchangeSegment": "NSE_FNO",
        "productType": "MARGIN",
        "transactionType": "BUY",
        "tradedQuantity": "1",
        "tradedPrice": "12.50",
        "exchangeTime": "2026-10-23 10:00:00",
        "stt": "0.20",
    }
    client = dhanhq(DhanContext("NativeCase", "synthetic-token"))
    calls = []

    def transport(method, url, **kwargs):
        calls.append((method, url))
        payload = (
            {
                "dhanClientId": "NativeCase",
                "vouchernumber": "V1",
                "voucherdate": "2026-10-24",
                "debit": "1",
                "credit": "0",
            }
            if "/ledger" in url
            else []
            if url.endswith("/1")
            else [native]
        )
        return SimpleNamespace(status_code=200, content=json.dumps(payload).encode())

    monkeypatch.setattr(client.dhan_http.session, "request", transport)
    try:
        handle = bound(DhanAdapter(client_factory=lambda _: client))
        ledger = OrderLifecycleLedger(ledger_path=tmp_path / "canonical.sqlite3")
        snapshot = asyncio.run(
            ledger.refresh_observations(
                handle.owner,
                handle.port,
                history=TradeHistoryRequest("2026-10-23", "2026-10-24", 2),
                ledger=LedgerRequest("2026-10-23", "2026-10-24"),
            )
        )
        history = next(c for c in snapshot.coverage if c.resource == "trades.history")
        assert history.availability == "available"
        assert history.pages == (0, 1)
        assert json.loads(history.provider_coverage_json)[0]["complete"] is False
        assert json.loads(history.provider_coverage_json)[1]["terminal"] == "undocumented"
        assert snapshot.account_postings[0].voucher_number == "V1"
        assert snapshot.fees[0].state.value == "payment_unknown"
        assert [item.trade.fill_id for item in snapshot.unallocated_trades] == ["FillAa"]
        reopened = OrderLifecycleLedger(ledger_path=tmp_path / "canonical.sqlite3").observation_snapshot(
            handle.selector
        )
        assert reopened.unallocated_trades == snapshot.unallocated_trades
        assert len(calls) == 4
    finally:
        client.dhan_http.session.close()


def test_repaired_kotak_sdk_day_coverage_and_empty_token_reach_canonical_owner(
    bound: Callable[..., SimpleNamespace],
    tmp_path: Path,
) -> None:
    """Verify repaired kotak sdk day coverage and empty token reach canonical owner.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
        tmp_path: Disposable workspace and ledger directory.
    """
    import httpx
    from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
    from flinttrade_gateway.brokers.kotakneo_sdk import KotakNeoSdkSession, _sdk_class
    from flinttrade_engine.local_state_provider import OrderLifecycleLedger

    row = {
        "nOrdNo": "OrderAa",
        "flId": "FillAa",
        "flLeg": 1,
        "exOrdId": "ExchangeAa",
        "actId": "NativeCase",
        "exSeg": "nse_fo",
        "trdSym": "SYNTHETIC-OPTION",
        "trnsTp": "B",
        "prod": "NRML",
        "rptTp": "fill",
        "avgPrc": "12.50",
        "fldQty": 1,
        "qty": 0,
        "tok": "",
        "flDt": "23-Oct-2026",
        "flTm": "10:01:00",
        "exTm": "23-Oct-2026 10:00:00",
        "hsUpTm": "2026/10/23 10:01:00",
        "ordDtTm": "23-Oct-2026 09:59:00",
        "lotSz": 3,
        "optTp": "CE",
        "expDt": "29-Oct-2026",
        "stkPrc": "10000",
    }
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(200, json={"stat": "Ok", "stCode": 200, "data": [row, row]})

    neo = _sdk_class()(consumer_key="synthetic", transport=httpx.MockTransport(transport))
    neo.configuration.edit_token = "synthetic"
    neo.configuration.edit_sid = "synthetic"
    neo.configuration.base_url = "https://example.invalid"
    client = KotakNeoSdkSession.__new__(KotakNeoSdkSession)
    client._neo, client._closed = neo, False
    try:
        handle = bound(KotakNeoAdapter(client_factory=lambda _: client), broker="kotakneo")
        snapshot = asyncio.run(
            OrderLifecycleLedger(ledger_path=tmp_path / "canonical.sqlite3").refresh_observations(
                handle.owner, handle.port
            )
        )
        assert len(snapshot.fills) == 1
        assert snapshot.fills[0].trade.instrument_id is None
        assert json.loads(snapshot.fills[0].trade.raw_observation_json)["broker_fields"]["qty"] == 0
        fields = json.loads(snapshot.fills[0].trade.raw_observation_json)["broker_fields"]
        assert {key: fields[key] for key in ("ordDtTm", "lotSz", "optTp", "expDt", "stkPrc")} == {
            key: row[key] for key in ("ordDtTm", "lotSz", "optTp", "expDt", "stkPrc")
        }
        coverage = snapshot.coverage[0]
        assert coverage.generation == snapshot.generation
        assert coverage.provider_account_id == "NativeCase"
        native = json.loads(coverage.provider_coverage_json)
        assert native["received_count"] == 2 and native["returned_count"] == 1
        assert native["lifetime_complete"] is False
        assert len(calls) == 1
    finally:
        client.close()


@pytest.mark.parametrize("broker", ["dhan", "kotakneo"])
def test_repaired_versioned_resolvers_cross_actual_lot_bridge(
    bound: Callable[..., SimpleNamespace],
    broker: str,
) -> None:
    """Verify repaired versioned resolvers cross actual lot bridge.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
        broker: Concrete broker adapter under test.
    """
    from datetime import datetime, UTC, timedelta
    from flinttrade_core.broker_read_port import LotSizeRequest

    now = datetime.now(UTC)
    if broker == "dhan":
        from flinttrade_gateway.brokers.dhan import DhanAdapter
        from flinttrade_gateway.brokers.dhan_mapping import build_security_resolver

        records = [
            {
                "SEM_SMST_SECURITY_ID": "111",
                "SEM_TRADING_SYMBOL": "SYNTH2099CE",
                "SEM_EXM_EXCH_ID": "NSE",
                "SEM_SEGMENT": "D",
                "SEM_INSTRUMENT_NAME": "OPTIDX",
                "SEM_EXPIRY_DATE": "2099-01-29",
                "SEM_OPTION_TYPE": "CE",
                "SEM_STRIKE_PRICE": "100",
                "SEM_LOT_UNITS": "3",
                "SEM_TICK_SIZE": "5",
                "SM_SYMBOL_NAME": "NIFTY",
            }
        ]
        resolver = build_security_resolver(
            records,
            source_revision="synthetic-revision",
            observed_at=now.timestamp(),
            valid_until=(now + timedelta(minutes=1)).timestamp(),
        )
        adapter = DhanAdapter(security_resolver=resolver)
    else:
        from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
        from flinttrade_gateway.brokers.kotakneo_contracts import KotakContractResolver

        epoch = int(datetime(2099, 1, 29, tzinfo=UTC).timestamp()) - 315511200
        resolver = KotakContractResolver.from_records(
            [
                {
                    "pSymbol": "111",
                    "pTrdSymbol": "SYNTH2099CE",
                    "pExchSeg": "nse_fo",
                    "pSymbolName": "NIFTY",
                    "pOptionType": "CE",
                    "pInstType": "OPTIDX",
                    "lExpiryDate": str(epoch),
                    "dStrikePrice;": "10000",
                    "lLotSize": "3",
                    "dTickSize": "5",
                    "lPrecision": "2",
                }
            ],
            source="synthetic-source",
            revision="synthetic-revision",
            observed_at=now,
            valid_until=now + timedelta(minutes=1),
        )
        adapter = KotakNeoAdapter(contract_resolver=resolver)
    handle = bound(adapter, broker=broker)
    result = asyncio.run(handle.port.lot_sizes(LotSizeRequest("NFO", ("SYNTH2099CE",))))
    assert isinstance(result, BrokerReadSuccess)
    assert result.value[0].source_revision == "synthetic-revision"
    assert result.value[0].raw_tick_size == "5"
    assert result.value[0].valid_until is not None
    assert result.value[0].raw_observation_json is not None


def test_contract_and_margin_versions_survive_outage_and_restart(
    bound: Callable[..., SimpleNamespace],
    tmp_path: Path,
) -> None:
    """Verify contract and margin versions survive outage and restart.

    Args:
        bound: Real registry and read-owner fixture with inert adapters.
        tmp_path: Disposable workspace and ledger directory.
    """
    from flinttrade_core.broker_read_port import LotSizeRequest, MarginRequest
    from flinttrade_engine.local_state_provider import OrderLifecycleLedger

    class Source(SyntheticAdapter):
        async def instrument_lot_sizes(self, session, request):
            return [
                {
                    "symbol": "SYNTHETIC-OPTION",
                    "exchange": "NFO",
                    "instrument_id": "TokenAa",
                    "lot_size": 3,
                    "source_revision": "synthetic-v1",
                    "source_digest": "a" * 64,
                    "observed_at": "2026-10-23T00:00:00+00:00",
                    "valid_until": "2026-10-24T00:00:00+00:00",
                }
            ]

        async def margin_calculator(self, session, order):
            return {
                "required_margin": "100",
                "provider_additional_margin": "25",
                "broker_fields": {"ordMrgn": "100", "reqdMrgn": "25"},
            }

    source = Source([])
    handle = bound(source, broker="kotakneo")
    path = tmp_path / "canonical.sqlite3"
    ledger = OrderLifecycleLedger(ledger_path=path)
    first = asyncio.run(
        ledger.refresh_observations(
            handle.owner,
            handle.port,
            lots=LotSizeRequest("NFO", ("SYNTHETIC-OPTION",)),
            margin=MarginRequest("SYNTHETIC-OPTION", "NFO", "SELL", "3", "NRML", "LIMIT", "12.50", "0"),
        )
    )
    assert first.margins[0].estimate_kind == "provider_order_estimate"
    assert "standalone_short_margin_unverified" in first.missing_evidence
    source.rows = RuntimeError("source unavailable")
    asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    reopened = OrderLifecycleLedger(ledger_path=path).observation_snapshot(handle.selector)
    assert reopened.contracts == first.contracts
    assert reopened.margins == first.margins
    assert reopened.contract_history[0].generation == first.generation
    assert reopened.margin_history[0].generation == first.generation
    assert "margin_not_recollected" in reopened.missing_evidence
