"""Identity and lifecycle tests for the broker read capability owner."""

from __future__ import annotations

import asyncio
import copy
import gc
import importlib.util
import pickle
import threading
import time
import weakref
from dataclasses import dataclass, fields, is_dataclass
from functools import partial
from types import CoroutineType, FrameType, FunctionType, MethodType, ModuleType, TracebackType

import pytest

from flinttrade_core.broker_identity import BrokerSelector
from flinttrade_core.broker_read_port import (
    BalanceEvidence,
    BalanceSnapshot,
    BatchQuoteRequest,
    BrokerBalanceResponseInvalid,
    BrokerDataRole,
    BrokerOrderFamily,
    BrokerReadErrorCode,
    BrokerReadFailure,
    BrokerReadResponseInvalid,
    BrokerReadSuccess,
    DataRoleReadTarget,
    ExactReadTarget,
    HistoricalRequest,
    InstrumentRef,
    LotSizeRequest,
    MarginRequest,
    OptionChainRequest,
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
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.credentials import CredentialStore
from flinttrade_gateway.session_provider import AuthenticatingSessionProvider


class _QuoteAdapter:
    def __init__(self, result: object) -> None:
        self.calls = 0
        self.result = result
        self.started: asyncio.Event | None = None
        self.release: asyncio.Event | None = None

    async def quotes(self, session, symbols):
        self.calls += 1
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            await self.release.wait()
        if len(symbols) > 1:
            return [
                {
                    "symbol": symbol.partition(":")[2],
                    "exchange": symbol.partition(":")[0],
                    "ltp": 100.0 + index,
                    "available": True,
                }
                for index, symbol in enumerate(symbols)
            ]
        return self.result

    async def depth(self, session, request):
        return {
            "symbol": request.instrument.symbol,
            "exchange": request.instrument.exchange,
            "bids": [{"price": 99.0, "quantity": 3, "orders": 1}],
            "asks": [{"price": 101.0, "quantity": 4, "orders": 2}],
        }

    async def historical(self, session, request):
        return {
            "symbol": request["symbol"],
            "exchange": request["exchange"],
            "interval": request["interval"],
            "bars": [{"timestamp": "2026-09-05", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10}],
        }

    async def option_chain(self, session, request):
        return {
            "underlying": request["symbol"],
            "underlying_key": "underlying-1",
            "exchange": request["exchange"],
            "expiry": request["expiry"],
            "spot_price": 25000,
            "strikes": [{"strike_price": 25000, "ce_delta": 0.5, "ce_vega": 1.2, "pe_delta": -0.5, "pe_vega": 1.1}],
        }

    async def instrument_lot_sizes(self, session, request):
        return [{"symbol": symbol, "exchange": request.exchange, "lot_size": 75} for symbol in request.symbols]

    async def balance_snapshot(self, session):
        return BalanceSnapshot(
            100.0,
            BalanceEvidence.DIRECT,
            20.0,
            BalanceEvidence.DIRECT,
            120.0,
            BalanceEvidence.DERIVED_FROM_DIRECT_COMPONENTS,
            125.0,
            BalanceEvidence.DIRECT,
        )

    async def portfolio_greeks(self, session, positions):
        return [
            {
                "symbol": row["symbol"],
                "exchange": row["exchange"],
                "instrument_id": row["instrument_id"],
                "delta": 0.5,
                "vega": 1.2,
            }
            for row in positions
        ]

    async def positions(self, session):
        return [{"symbol": "NIFTY", "instrument_id": "P1", "exchange": "NFO", "product": "NRML", "quantity": "75"}]

    async def holdings(self, session):
        return [{"symbol": "INFY", "instrument_id": "H1", "exchange": "NSE", "quantity": "10"}]

    async def margin_calculator(self, session, order):
        return {"required_margin": 1234.5}

    async def safety_order_book(self, session):
        return [{
            "orderid": "O1",
            "status": "open",
            "symbol": "NIFTY",
            "exchange": "NFO",
            "action": "BUY",
            "product": "NRML",
            "quantity": "75",
            "filled_quantity": "0",
        }]

    async def order_book(self, session):
        return await self.safety_order_book(session)

    async def forever_orders(self, session):
        return [{"orderid": "G1", "status": "pending", "quantity": "75", "order_flag": "SINGLE"}]

    async def super_orders(self, session):
        return [{"orderid": "S1", "status": "open", "legs": [{"leg_name": "ENTRY_LEG", "status": "complete"}]}]

    async def trade_book(self, session):
        return [{"orderid": "O1", "symbol": "NIFTY", "exchange": "NFO", "action": "BUY", "quantity": "75", "price": "100", "product": "NRML", "timestamp": "2026-09-06T09:20:00+05:30"}]


class _Limiter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def acquire(self, adapter_id: str, kind: str) -> None:
        self.calls.append((adapter_id, kind))


class _OptionalBalanceAdapter:
    def __init__(self) -> None:
        self.quote_calls = 0
        self.fallback_calls = 0

    async def quotes(self, _session, symbols):
        self.quote_calls += 1
        return [
            {
                "symbol": symbol.partition(":")[2],
                "exchange": symbol.partition(":")[0],
                "ltp": 100.0,
                "available": True,
            }
            for symbol in symbols
        ]

    async def funds(self, _session):
        self.fallback_calls += 1
        raise AssertionError("balance must not fall back to funds")


class _PrimitiveHookTrap:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def _called(self, name: str):
        self.calls.append(name)
        raise AssertionError(f"provider primitive hook executed: {name}")

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


class _CollidingKeyTrap:
    def __init__(self, target: str) -> None:
        self.target = target
        self.calls: list[str] = []

    def __hash__(self) -> int:
        self.calls.append("hash")
        return hash(self.target)

    def __eq__(self, _other: object) -> bool:
        self.calls.append("eq")
        raise AssertionError("provider mapping key comparison executed")


class _LotIterableTrap:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def _called(self, name: str):
        self.calls.append(name)
        raise AssertionError(f"provider lot container hook executed: {name}")

    def __iter__(self):
        return self._called("iter")

    def __len__(self):
        return self._called("len")

    def __bool__(self):
        return self._called("bool")

    def __repr__(self):
        return self._called("repr")


class _LotListSubclassTrap(list):
    def __init__(self, rows: list[dict[str, object]]) -> None:
        super().__init__(rows)
        self.calls: list[str] = []

    def _called(self, name: str):
        self.calls.append(name)
        raise AssertionError(f"provider lot list-subclass hook executed: {name}")

    def __iter__(self):
        return self._called("iter")

    def __len__(self):
        return self._called("len")

    def __bool__(self):
        return self._called("bool")

    def __repr__(self):
        return self._called("repr")


class _RoleValueTrap:
    def __init__(self) -> None:
        self.calls: list[str] = []

    @property
    def value(self) -> str:
        self.calls.append("value")
        raise AssertionError("invalid role value was accessed")


@dataclass
class _Harness:
    workspace_path: object
    selector: BrokerSelector
    registry: object
    registry_owner: object
    raw_session: Session
    raw_client: object
    provider: AuthenticatingSessionProvider
    adapter: _QuoteAdapter
    limiter: _Limiter
    context: RequestContext
    store: CredentialStore

    def close(self) -> None:
        self.store.close()


@pytest.fixture
def harness(tmp_path):
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    harden_directory(workspace_path)
    selector = BrokerSelector("dhan", "Synthetic")

    def initialise(config):
        config["brokers"]["account_acls"] = {"dhan": {"Synthetic": ["actor"]}}
        config["brokers"]["data"].update(
            {
                "quote": "dhan:Synthetic",
                "historical": "dhan:Synthetic",
                "option_chains": "dhan:Synthetic",
                "global_indices": "dhan:Synthetic",
            }
        )

    workspace = compare_and_swap_workspace(workspace_path, None, initialise)
    store = CredentialStore(workspace_path / "dhan.db", "synthetic-password")
    state = store.selector_state(selector)
    store.put_credentials(
        selector,
        "dhan",
        "Synthetic",
        {"token": "synthetic-credential-token-7b"},
        expected=state.version,
    )
    version = store.selector_state(selector).version
    authority = registry_api.ManagedSessionAuthority(
        version, workspace.version, broker_workspace_version(workspace)
    )
    registry, owner = registry_api.create_owned_registry()
    raw_session = Session("synthetic-secret-token-7b", time.time() + 3600, "Synthetic", "dhan")
    raw_client = object()
    receipt = owner.prepare_session_candidate(
        selector,
        raw_session,
        expected_registry=registry.snapshot_selector(selector),
        authority=authority,
        broker="dhan",
        label="Synthetic",
        client=raw_client,
    )
    owner.publish_prepared_candidate(receipt, current_authority=authority)
    provider = AuthenticatingSessionProvider(
        registry,
        {"dhan": {"Synthetic": ["actor"]}},
        workspace_snapshot=workspace,
        workspace_path=workspace_path,
        credential_version_for=lambda target: store.selector_state(target).version,
    )
    adapter = _QuoteAdapter(
        [{"symbol": "NIFTY", "exchange": "NSE", "ltp": 25000.0, "available": True}]
    )
    item = _Harness(
        workspace_path,
        selector,
        registry,
        owner,
        raw_session,
        raw_client,
        provider,
        adapter,
        _Limiter(),
        RequestContext("jti", "human", "actor", "practice", selector="dhan:Synthetic"),
        store,
    )
    yield item
    item.close()


def test_broker_read_service_module_exists() -> None:
    assert importlib.util.find_spec("flinttrade_gateway.broker_read_service") is not None


def _owner(harness, *, runtime=lambda: True, adapters=None, limiter=None):
    from flinttrade_gateway.broker_read_service import create_broker_read_owner

    return create_broker_read_owner(
        registry=harness.registry,
        session_provider=harness.provider,
        adapters={"dhan": harness.adapter} if adapters is None else adapters,
        workspace_path=harness.workspace_path,
        rate_limiter=harness.limiter if limiter is None else limiter,
        runtime_accepting_requests=runtime,
    )


def _concrete_lot_adapter(monkeypatch, kind: str, result: object, error: Exception | None, calls: list[str]):
    async def source(*_args):
        calls.append(kind)
        if error is not None:
            raise error
        return result

    if kind == "openalgo":
        from flinttrade_gateway.brokers.openalgo import OpenAlgoAdapter

        class Client:
            async def instruments(self, exchange):
                return await source(exchange)

        adapter = object.__new__(OpenAlgoAdapter)
        client = Client()
        monkeypatch.setattr(adapter, "_client", lambda _session: client)
        return adapter
    if kind == "groww":
        from flinttrade_gateway.brokers.groww import GrowwAdapter

        adapter = GrowwAdapter()
        monkeypatch.setattr(adapter, "_strict_lot_size_instruments", source)
        return adapter
    if kind == "indmoney":
        from flinttrade_gateway.brokers.indmoney import IndMoneyAdapter

        adapter = IndMoneyAdapter()
        monkeypatch.setattr(adapter, "_strict_instruments", source)
        return adapter
    raise AssertionError(f"unexpected lot adapter kind: {kind}")


def _read_concrete_lot(harness, monkeypatch, kind: str, result: object, *, error: Exception | None = None):
    calls: list[str] = []
    adapter = _concrete_lot_adapter(monkeypatch, kind, result, error, calls)
    owner = _owner(harness, adapters={"dhan": adapter})
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)
    outcome = asyncio.run(port.lot_sizes(LotSizeRequest("NSE", ("NIFTY",))))
    return outcome, calls


def test_facade_is_identity_only_and_forged_copied_cross_owner_grants_fail(harness) -> None:
    first = _owner(harness)
    second = _owner(harness)
    port = first.bind(target=ExactReadTarget(harness.selector), verify_current_authority=lambda: harness.context)
    assert not isinstance(port, BrokerReadFailure)
    assert type(port).__slots__ == ("__weakref__",)
    assert not hasattr(port, "__dict__")

    copied = copy.copy(port)
    result = asyncio.run(copied.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE"))))
    assert result == BrokerReadFailure(BrokerReadErrorCode.REVOKED)
    assert not second.revoke(port)
    assert first.revoke(port)
    assert first.revoke(port)
    assert not second.revoke(copied)
    assert harness.adapter.calls == 0


def test_forged_deepcopied_deserialised_and_owner_replaced_facades_fail(harness) -> None:
    import flinttrade_gateway.broker_read_service as service

    first = _owner(harness)
    second = _owner(harness)
    port = first.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)
    forged = service._BrokerReadFacade()
    variants = (forged, copy.deepcopy(port), pickle.loads(pickle.dumps(port)))
    request = QuoteRequest(InstrumentRef("NIFTY", "NSE"))

    for variant in variants:
        assert asyncio.run(variant.quote(request)) == BrokerReadFailure(BrokerReadErrorCode.REVOKED)

    with service._FACADE_LOCK:
        service._FACADE_OWNERS[port] = weakref.ref(second)
    assert asyncio.run(port.quote(request)) == BrokerReadFailure(BrokerReadErrorCode.REVOKED)
    assert harness.adapter.calls == 0
    assert first.revoke(port)


def test_same_selector_in_a_new_registry_incarnation_cannot_claim_an_old_facade(harness) -> None:
    from flinttrade_core.workspace_migrations import read_workspace_snapshot
    from flinttrade_gateway.broker_read_service import create_broker_read_owner

    first = _owner(harness)
    first_port = first.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(first_port, BrokerReadFailure)
    workspace = read_workspace_snapshot(harness.workspace_path)
    credential_version = harness.store.selector_state(harness.selector).version
    authority = registry_api.ManagedSessionAuthority(
        credential_version,
        workspace.version,
        broker_workspace_version(workspace),
    )
    registry, publication_owner = registry_api.create_owned_registry()
    receipt = publication_owner.prepare_session_candidate(
        harness.selector,
        Session("new-incarnation-token-7b", time.time() + 3600, "Synthetic", "dhan"),
        expected_registry=registry.snapshot_selector(harness.selector),
        authority=authority,
        broker="dhan",
        label="Synthetic",
    )
    publication_owner.publish_prepared_candidate(receipt, current_authority=authority)
    provider = AuthenticatingSessionProvider(
        registry,
        {"dhan": {"Synthetic": ["actor"]}},
        workspace_snapshot=workspace,
        workspace_path=harness.workspace_path,
        credential_version_for=lambda _target: credential_version,
    )
    second = create_broker_read_owner(
        registry=registry,
        session_provider=provider,
        adapters={"dhan": harness.adapter},
        workspace_path=harness.workspace_path,
        rate_limiter=harness.limiter,
        runtime_accepting_requests=lambda: True,
    )
    second_port = second.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(second_port, BrokerReadFailure)

    assert (
        first._grants[first_port].binding.registry_version.registry_incarnation
        != second._grants[second_port].binding.registry_version.registry_incarnation
    )
    assert not second.revoke(first_port)
    assert not first.revoke(second_port)
    assert first.revoke(first_port)
    assert second.revoke(second_port)
    assert harness.adapter.calls == 0


def test_role_permissions_are_closed_and_early_refusal_calls_nothing(harness) -> None:
    owner = _owner(harness)
    port = owner.bind(target=DataRoleReadTarget(BrokerDataRole.QUOTE), verify_current_authority=lambda: harness.context)
    assert not isinstance(port, BrokerReadFailure)

    assert asyncio.run(port.balance()) == BrokerReadFailure(BrokerReadErrorCode.UNAUTHORISED)
    assert harness.adapter.calls == 0
    assert harness.limiter.calls == []


def test_missing_optional_balance_seam_refuses_before_provider_or_fallback(harness, monkeypatch) -> None:
    from flinttrade_gateway.broker_read_service import create_broker_read_owner

    provider_calls: list[str] = []
    current_authority_for = AuthenticatingSessionProvider.current_authority_for
    resolve_session = AuthenticatingSessionProvider.__call__

    def current(provider, selector):
        provider_calls.append("current_authority_for")
        return current_authority_for(provider, selector)

    def resolve(provider, context, adapter_id, account_id):
        provider_calls.append("resolve")
        return resolve_session(provider, context, adapter_id, account_id)

    monkeypatch.setattr(AuthenticatingSessionProvider, "current_authority_for", current)
    monkeypatch.setattr(AuthenticatingSessionProvider, "__call__", resolve)
    adapter = _OptionalBalanceAdapter()
    owner = create_broker_read_owner(
        registry=harness.registry,
        session_provider=harness.provider,
        adapters={"dhan": adapter},
        workspace_path=harness.workspace_path,
        rate_limiter=harness.limiter,
        runtime_accepting_requests=lambda: True,
    )
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)

    quote = asyncio.run(port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE"))))
    assert isinstance(quote, BrokerReadSuccess)
    assert adapter.quote_calls == 1

    provider_calls.clear()
    harness.limiter.calls.clear()
    assert asyncio.run(port.balance()) == BrokerReadFailure(BrokerReadErrorCode.UNSUPPORTED)
    assert provider_calls == ["current_authority_for", "resolve", "current_authority_for"]
    assert harness.limiter.calls == []
    assert adapter.fallback_calls == 0


def test_limiter_precedes_provider_and_authority_is_checked_on_both_sides(harness) -> None:
    owner = _owner(harness)
    checks = 0

    def verify():
        nonlocal checks
        checks += 1
        return None if checks == 3 else harness.context

    port = owner.bind(target=ExactReadTarget(harness.selector), verify_current_authority=verify)
    result = asyncio.run(port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE"))))
    assert result == BrokerReadFailure(BrokerReadErrorCode.UNAUTHORISED)
    assert harness.limiter.calls == [("dhan", "data")]
    assert harness.adapter.calls == 0


@pytest.mark.parametrize(
    ("mode", "expected_verifier", "expected_current", "expected_resolve", "expected_limiter", "expected_endpoint"),
    [
        ("success", 3, 6, 3, 1, 1),
        ("provider-failure", 2, 4, 2, 1, 1),
        ("response-signal-failure", 2, 4, 2, 1, 1),
        ("conversion-failure", 2, 4, 2, 1, 1),
        ("unsupported", 1, 2, 1, 0, 0),
        ("begin-refusal", 0, 0, 0, 0, 0),
    ],
)
def test_fixed_operation_revalidation_limiter_and_endpoint_ledgers(
    harness,
    monkeypatch,
    mode,
    expected_verifier,
    expected_current,
    expected_resolve,
    expected_limiter,
    expected_endpoint,
) -> None:
    current_calls: list[str] = []
    resolve_calls: list[str] = []
    verifier_calls: list[str] = []
    endpoint_calls: list[str] = []
    real_current = AuthenticatingSessionProvider.current_authority_for
    real_resolve = AuthenticatingSessionProvider.__call__

    def current(provider, *args, **kwargs):
        current_calls.append("current")
        return real_current(provider, *args, **kwargs)

    def resolve(provider, *args, **kwargs):
        resolve_calls.append("resolve")
        return real_resolve(provider, *args, **kwargs)

    class Adapter:
        async def quotes(self, _session, _symbols):
            endpoint_calls.append("quotes")
            if mode == "provider-failure":
                raise RuntimeError("provider-private")
            if mode == "response-signal-failure":
                raise BrokerReadResponseInvalid
            if mode == "conversion-failure":
                return [{"symbol": "NIFTY", "exchange": "NSE", "ltp": object()}]
            return [{"symbol": "NIFTY", "exchange": "NSE", "ltp": 1}]

    monkeypatch.setattr(AuthenticatingSessionProvider, "current_authority_for", current)
    monkeypatch.setattr(AuthenticatingSessionProvider, "__call__", resolve)
    adapter = object() if mode == "unsupported" else Adapter()
    owner = _owner(harness, adapters={"dhan": adapter})

    def verify():
        verifier_calls.append("verify")
        return harness.context

    target = (
        DataRoleReadTarget(BrokerDataRole.QUOTE)
        if mode == "begin-refusal"
        else ExactReadTarget(harness.selector)
    )
    port = owner.bind(target=target, verify_current_authority=verify)
    assert not isinstance(port, BrokerReadFailure)
    current_calls.clear()
    resolve_calls.clear()
    verifier_calls.clear()
    harness.limiter.calls.clear()

    result = asyncio.run(
        port.balance()
        if mode == "begin-refusal"
        else port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE")))
    )

    if mode == "success":
        assert isinstance(result, BrokerReadSuccess)
    else:
        expected = {
            "provider-failure": BrokerReadErrorCode.PROVIDER_FAILURE,
            "response-signal-failure": BrokerReadErrorCode.MALFORMED_RESPONSE,
            "conversion-failure": BrokerReadErrorCode.MALFORMED_RESPONSE,
            "unsupported": BrokerReadErrorCode.UNSUPPORTED,
            "begin-refusal": BrokerReadErrorCode.UNAUTHORISED,
        }[mode]
        assert result == BrokerReadFailure(expected)
    assert len(verifier_calls) == expected_verifier
    assert len(current_calls) == expected_current
    assert len(resolve_calls) == expected_resolve
    assert len(harness.limiter.calls) == expected_limiter
    assert len(endpoint_calls) == expected_endpoint
    assert owner._active == 0


def test_bind_proves_acl_before_issuing_a_facade_and_calls_no_adapter_or_limiter(harness) -> None:
    owner = _owner(harness)
    unauthorised = RequestContext(
        "jti-intruder",
        "human",
        "intruder",
        "practice",
        selector="dhan:Synthetic",
    )

    result = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: unauthorised,
    )

    assert result == BrokerReadFailure(BrokerReadErrorCode.UNAUTHORISED)
    assert harness.adapter.calls == 0
    assert harness.limiter.calls == []


def test_bind_rejects_a_session_handle_that_does_not_match_the_live_binding(harness, monkeypatch) -> None:
    calls = 0

    def mismatched_handle(_provider, _context, _adapter_id, _account_id):
        nonlocal calls
        calls += 1
        return object()

    monkeypatch.setattr(AuthenticatingSessionProvider, "__call__", mismatched_handle)
    owner = _owner(harness)

    result = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )

    assert result == BrokerReadFailure(BrokerReadErrorCode.TARGET_STALE)
    assert calls == 1
    assert harness.adapter.calls == 0
    assert harness.limiter.calls == []


def test_bind_redacts_ordinary_workspace_dependency_failures(harness, monkeypatch) -> None:
    import flinttrade_gateway.broker_read_service as service

    owner = _owner(harness)
    monkeypatch.setattr(service, "read_workspace_snapshot", lambda _path: (_ for _ in ()).throw(OSError("private")))

    result = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )

    assert result == BrokerReadFailure(BrokerReadErrorCode.TARGET_UNAVAILABLE)
    assert harness.adapter.calls == 0
    assert harness.limiter.calls == []


@pytest.mark.parametrize("target_kind", ["exact", "role", "forged_role"])
def test_bind_validates_mutated_public_target_values_before_provider_work(harness, monkeypatch, target_kind) -> None:
    provider_calls: list[str] = []

    def forbidden_provider(*_args, **_kwargs):
        provider_calls.append("provider")
        raise AssertionError("session provider executed")

    owner = _owner(harness)
    if target_kind == "exact":
        trap = _PrimitiveHookTrap()
        selector = BrokerSelector("dhan", "Synthetic")
        selector.__dict__["account_id"] = trap
        target = ExactReadTarget.__new__(ExactReadTarget)
        object.__setattr__(target, "selector", selector)
    else:
        trap = _RoleValueTrap() if target_kind == "role" else None
        target = DataRoleReadTarget(BrokerDataRole.QUOTE)
        if trap is not None:
            object.__setattr__(target, "role", trap)
        else:
            forged = str.__new__(BrokerDataRole, "quote")
            forged._name_ = "FORGED"
            forged._value_ = "quote"
            object.__setattr__(target, "role", forged)
    monkeypatch.setattr(AuthenticatingSessionProvider, "current_authority_for", forbidden_provider)
    monkeypatch.setattr(AuthenticatingSessionProvider, "__call__", forbidden_provider)

    result = owner.bind(target=target, verify_current_authority=lambda: harness.context)

    assert result == BrokerReadFailure(BrokerReadErrorCode.TARGET_UNAVAILABLE)
    assert trap is None or trap.calls == []
    assert provider_calls == []
    assert harness.adapter.calls == 0
    assert harness.limiter.calls == []


def test_role_bind_rejects_a_target_resolved_before_a_new_workspace_binding(harness, monkeypatch) -> None:
    import flinttrade_gateway.broker_read_service as service

    initial = service.read_workspace_snapshot(harness.workspace_path)
    real_read = service.read_workspace_snapshot
    interleaved = False

    def read_with_one_refresh(workspace_path):
        nonlocal interleaved
        snapshot = real_read(workspace_path)
        if interleaved:
            return snapshot
        interleaved = True

        def change_broker_authority(config):
            config["brokers"]["failover"]["enabled"] = True

        refreshed = compare_and_swap_workspace(harness.workspace_path, snapshot.version, change_broker_authority)
        credential_version = harness.store.selector_state(harness.selector).version
        authority = registry_api.ManagedSessionAuthority(
            credential_version,
            refreshed.version,
            broker_workspace_version(refreshed),
        )
        receipt = harness.registry_owner.prepare_session_candidate(
            harness.selector,
            Session("role-race-token-7b", time.time() + 3600, "Synthetic", "dhan"),
            expected_registry=harness.registry.snapshot_selector(harness.selector),
            authority=authority,
            broker="dhan",
            label="Synthetic",
        )
        harness.registry_owner.publish_prepared_candidate(receipt, current_authority=authority)
        harness.provider.workspace_version = refreshed.version
        harness.provider.broker_workspace_version = broker_workspace_version(refreshed)
        return snapshot

    monkeypatch.setattr(service, "read_workspace_snapshot", read_with_one_refresh)
    owner = _owner(harness)

    role_result = owner.bind(
        target=DataRoleReadTarget(BrokerDataRole.QUOTE),
        verify_current_authority=lambda: harness.context,
    )
    if not isinstance(role_result, BrokerReadFailure):
        owner.revoke(role_result)
    assert role_result == BrokerReadFailure(BrokerReadErrorCode.TARGET_STALE)

    exact_result = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(exact_result, BrokerReadFailure)
    assert owner.revoke(exact_result)
    assert interleaved is True
    assert initial.version != harness.provider.workspace_version
    assert harness.adapter.calls == 0
    assert harness.limiter.calls == []


@pytest.mark.parametrize(
    ("failed_resolution", "expected"),
    [(1, BrokerReadErrorCode.TARGET_UNAVAILABLE), (2, BrokerReadErrorCode.TARGET_STALE)],
    ids=("initial", "final"),
)
def test_role_bind_classifies_initial_and_final_resolution_failures(
    harness,
    monkeypatch,
    failed_resolution,
    expected,
) -> None:
    owner = _owner(harness)
    owner_type = type(owner)
    real_resolve = owner_type._resolve_target
    calls = 0

    def resolve(self, target):
        nonlocal calls
        if self is not owner:
            return real_resolve(self, target)
        calls += 1
        if calls == failed_resolution:
            raise LookupError("synthetic role resolution failure")
        return real_resolve(self, target)

    monkeypatch.setattr(owner_type, "_resolve_target", resolve)

    result = owner.bind(
        target=DataRoleReadTarget(BrokerDataRole.QUOTE),
        verify_current_authority=lambda: harness.context,
    )

    assert result == BrokerReadFailure(expected)
    assert calls == failed_resolution
    assert harness.adapter.calls == 0
    assert harness.limiter.calls == []


@pytest.mark.parametrize(
    ("target", "invoke"),
    [
        (
            ExactReadTarget(BrokerSelector("dhan", "Synthetic")),
            lambda port: port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE"))),
        ),
        (
            DataRoleReadTarget(BrokerDataRole.QUOTE),
            lambda port: port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE"))),
        ),
        (
            DataRoleReadTarget(BrokerDataRole.HISTORICAL),
            lambda port: port.historical(
                HistoricalRequest(InstrumentRef("NIFTY", "NSE"), "D", "2026-09-01", "2026-09-05")
            ),
        ),
        (
            DataRoleReadTarget(BrokerDataRole.OPTION_CHAINS),
            lambda port: port.option_chain(
                OptionChainRequest(InstrumentRef("NIFTY", "NSE"), "2026-09-24")
            ),
        ),
        (
            DataRoleReadTarget(BrokerDataRole.GLOBAL_INDICES),
            lambda port: port.batch_quotes(BatchQuoteRequest((InstrumentRef("NIFTY", "NSE"),))),
        ),
    ],
    ids=("exact", "quote-role", "historical-role", "option-chain-role", "global-indices-role"),
)
def test_telegram_only_workspace_change_preserves_existing_and_new_broker_ports(
    harness,
    target,
    invoke,
) -> None:
    owner = _owner(harness)
    existing = owner.bind(target=target, verify_current_authority=lambda: harness.context)
    assert not isinstance(existing, BrokerReadFailure)
    original = read_workspace_snapshot(harness.workspace_path)
    original_binding = owner._grants[existing].binding

    def update_telegram(config):
        config["openalgo"]["telegram_username"] = "linked-trader"

    updated = compare_and_swap_workspace(harness.workspace_path, original.version, update_telegram)
    assert updated.version != original.version
    assert updated.version != original_binding.workspace_version
    assert broker_workspace_version(updated) == broker_workspace_version(original)

    newly_bound = owner.bind(target=target, verify_current_authority=lambda: harness.context)
    assert not isinstance(newly_bound, BrokerReadFailure)
    for port in (existing, newly_bound):
        result = asyncio.run(invoke(port))
        assert isinstance(result, BrokerReadSuccess)
        assert result.provenance.workspace_version == original_binding.workspace_version
        assert result.provenance.broker_workspace_version == original_binding.broker_workspace_version


@pytest.mark.parametrize(
    "target",
    [ExactReadTarget(BrokerSelector("dhan", "Synthetic")), DataRoleReadTarget(BrokerDataRole.QUOTE)],
    ids=("exact", "role"),
)
def test_real_broker_workspace_mutation_stales_existing_ports_before_provider_work(harness, target) -> None:
    owner = _owner(harness)
    port = owner.bind(target=target, verify_current_authority=lambda: harness.context)
    assert not isinstance(port, BrokerReadFailure)
    snapshot = read_workspace_snapshot(harness.workspace_path)

    def mutate_broker(config):
        config["brokers"]["failover"]["enabled"] = True

    changed = compare_and_swap_workspace(harness.workspace_path, snapshot.version, mutate_broker)
    assert broker_workspace_version(changed) != broker_workspace_version(snapshot)
    harness.limiter.calls.clear()

    result = asyncio.run(port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE"))))

    assert result == BrokerReadFailure(BrokerReadErrorCode.TARGET_STALE)
    assert harness.limiter.calls == []
    assert harness.adapter.calls == 0


def test_bound_context_is_a_fresh_primitive_snapshot_and_selector_is_revalidated(harness) -> None:
    context = RequestContext("jti", "human", "actor", "practice", selector="dhan:Synthetic")
    owner = _owner(harness)
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: context,
    )
    assert not isinstance(port, BrokerReadFailure)

    context.__dict__["selector"] = "dhan:Other"
    result = asyncio.run(port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE"))))

    assert result == BrokerReadFailure(BrokerReadErrorCode.UNAUTHORISED)
    assert harness.adapter.calls == 0
    assert harness.limiter.calls == []


def test_context_copy_uses_one_validated_snapshot_and_later_mutation_fails_closed(harness, monkeypatch) -> None:
    import flinttrade_gateway.broker_read_service as service

    source = RequestContext("jti", "human", "actor", "practice", selector="dhan:Synthetic")
    real_parse = service.parse_broker_selector
    mutated = False

    def mutate_after_selector_snapshot(raw: str):
        nonlocal mutated
        parsed = real_parse(raw)
        if not mutated:
            mutated = True
            source.__dict__["actor_id"] = "intruder"
            source.__dict__["selector"] = "dhan:Other"
        return parsed

    monkeypatch.setattr(service, "parse_broker_selector", mutate_after_selector_snapshot)
    owner = _owner(harness)

    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: source,
    )

    assert not isinstance(port, BrokerReadFailure)
    assert owner._grants[port].context == RequestContext(
        "jti",
        "human",
        "actor",
        "practice",
        selector="dhan:Synthetic",
    )
    assert asyncio.run(port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE")))) == BrokerReadFailure(
        BrokerReadErrorCode.UNAUTHORISED
    )
    assert harness.adapter.calls == 0
    assert harness.limiter.calls == []


@pytest.mark.parametrize(
    "operation",
    [
        "quote",
        "depth",
        "historical",
        "batch",
        "option",
        "lot",
        "greeks",
        "margin",
        "orders",
        "forged_orders",
    ],
)
def test_every_request_is_recursively_reconstructed_before_admission(harness, monkeypatch, operation) -> None:
    class ForbiddenAdapter:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def __getattr__(self, name: str):
            self.calls.append(name)
            raise AssertionError("adapter lookup executed")

    adapter = ForbiddenAdapter()
    owner = _owner(harness, adapters={"dhan": adapter})
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)
    provider_calls: list[str] = []

    def forbidden_provider(*_args, **_kwargs):
        provider_calls.append("provider")
        raise AssertionError("session provider executed")

    monkeypatch.setattr(AuthenticatingSessionProvider, "current_authority_for", forbidden_provider)
    monkeypatch.setattr(AuthenticatingSessionProvider, "__call__", forbidden_provider)
    harness.limiter.calls.clear()

    instrument = InstrumentRef("NIFTY", "NSE")
    if operation == "quote":
        request = QuoteRequest(instrument)
        object.__setattr__(instrument, "symbol", "")
        invoke = port.quote(request)
    elif operation == "depth":
        request = QuoteRequest(instrument)
        object.__setattr__(instrument, "exchange", object())
        invoke = port.depth(request)
    elif operation == "historical":
        request = HistoricalRequest(instrument, "D", "2026-09-01", "2026-09-05")
        object.__setattr__(request, "interval", "")
        invoke = port.historical(request)
    elif operation == "batch":
        request = BatchQuoteRequest((instrument,))
        object.__setattr__(request, "instruments", [instrument])
        invoke = port.batch_quotes(request)
    elif operation == "option":
        request = OptionChainRequest(instrument, "2026-09-24")
        object.__setattr__(instrument, "instrument_id", object())
        invoke = port.option_chain(request)
    elif operation == "lot":
        request = LotSizeRequest("NSE", ("NIFTY",))
        object.__setattr__(request, "symbols", ["NIFTY"])
        invoke = port.lot_sizes(request)
    elif operation == "greeks":
        position = PortfolioPositionRef("NIFTY", "NFO", "75", "CE", "P1", None, None, None)
        request = PortfolioGreeksRequest((position,))
        object.__setattr__(position, "quantity", "")
        invoke = port.portfolio_greeks(request)
    elif operation == "margin":
        request = MarginRequest("NIFTY", "NFO", "BUY", "75", "NRML", "MARKET", "0", "0")
        object.__setattr__(request, "action", "buy")
        invoke = port.margin(request)
    elif operation == "orders":
        request = OrderStateRequest(BrokerOrderFamily.REGULAR)
        object.__setattr__(request, "family", "regular")
        invoke = port.order_states(request)
    else:
        forged = str.__new__(BrokerOrderFamily, "regular")
        forged._name_ = "FORGED"
        forged._value_ = "regular"
        request = OrderStateRequest(forged)
        invoke = port.order_states(request)

    result = asyncio.run(invoke)

    assert result == BrokerReadFailure(BrokerReadErrorCode.INVALID_REQUEST)
    assert provider_calls == []
    assert harness.limiter.calls == []
    assert adapter.calls == []
    assert owner._active == 0


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [("exchange", "INVALID_EXCHANGE"), ("product", "INVALID_PRODUCT"), ("pricetype", "INVALID_PRICETYPE")],
)
def test_margin_order_projection_is_validated_before_admission(
    harness,
    monkeypatch,
    field,
    invalid_value,
) -> None:
    provider_calls: list[str] = []
    adapter_calls: list[str] = []
    real_current = AuthenticatingSessionProvider.current_authority_for
    real_resolve = AuthenticatingSessionProvider.__call__

    def current_authority_for(provider, *args, **kwargs):
        provider_calls.append("current")
        return real_current(provider, *args, **kwargs)

    def resolve_session(provider, *args, **kwargs):
        provider_calls.append("resolve")
        return real_resolve(provider, *args, **kwargs)

    async def margin_calculator(*_args):
        adapter_calls.append("margin")
        return {"required_margin": 1}

    monkeypatch.setattr(AuthenticatingSessionProvider, "current_authority_for", current_authority_for)
    monkeypatch.setattr(AuthenticatingSessionProvider, "__call__", resolve_session)
    harness.adapter.margin_calculator = margin_calculator
    owner = _owner(harness)
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)
    provider_calls.clear()
    harness.limiter.calls.clear()
    values = {
        "symbol": "NIFTY",
        "exchange": "NFO",
        "action": "BUY",
        "quantity": "75",
        "product": "NRML",
        "pricetype": "MARKET",
        "price": "0",
        "trigger_price": "0",
    }
    values[field] = invalid_value

    result = asyncio.run(port.margin(MarginRequest(**values)))

    assert result == BrokerReadFailure(BrokerReadErrorCode.INVALID_REQUEST)
    assert provider_calls == []
    assert harness.limiter.calls == []
    assert adapter_calls == []


def test_each_success_has_fresh_provenance_children_and_cannot_mutate_binding(harness) -> None:
    owner = _owner(harness)
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)
    binding = owner._grants[port].binding

    first = asyncio.run(port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE"))))
    assert isinstance(first, BrokerReadSuccess)
    original_generation = binding.registry_version.generation
    first.provenance.registry_version.__dict__["generation"] = original_generation + 100
    first.provenance.selector.__dict__["account_id"] = "Mutated"

    second = asyncio.run(port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE"))))
    assert isinstance(second, BrokerReadSuccess)
    assert binding.registry_version.generation == original_generation
    assert binding.selector == harness.selector
    assert second.provenance.registry_version.generation == original_generation
    assert second.provenance.selector == harness.selector

    first_children = (
        first.provenance.selector,
        first.provenance.registry_version,
        first.provenance.credential_version,
        first.provenance.workspace_version,
        first.provenance.broker_workspace_version,
    )
    second_children = (
        second.provenance.selector,
        second.provenance.registry_version,
        second.provenance.credential_version,
        second.provenance.workspace_version,
        second.provenance.broker_workspace_version,
    )
    binding_children = (
        binding.selector,
        binding.registry_version,
        binding.credential_version,
        binding.workspace_version,
        binding.broker_workspace_version,
    )
    assert first.provenance is not second.provenance
    assert all(left is not right for left, right in zip(first_children, second_children, strict=True))
    assert all(public is not internal for public, internal in zip(second_children, binding_children, strict=True))
    assert second.provenance.registry_version.registry_incarnation is not binding.registry_version.registry_incarnation
    assert second.provenance.credential_version.vault_incarnation is not binding.credential_version.vault_incarnation
    assert second.provenance.workspace_version.instance_id is not binding.workspace_version.instance_id
    assert second.provenance.broker_workspace_version.instance_id is not binding.broker_workspace_version.instance_id


@pytest.mark.parametrize(
    ("attribute", "invoke"),
    [
        ("quotes", lambda port: port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE")))),
        ("depth", lambda port: port.depth(QuoteRequest(InstrumentRef("NIFTY", "NSE")))),
        (
            "historical",
            lambda port: port.historical(
                HistoricalRequest(InstrumentRef("NIFTY", "NSE"), "D", "2026-09-01", "2026-09-05")
            ),
        ),
        (
            "quotes",
            lambda port: port.batch_quotes(
                BatchQuoteRequest((InstrumentRef("NIFTY", "NSE"), InstrumentRef("BANKNIFTY", "NSE")))
            ),
        ),
        (
            "option_chain",
            lambda port: port.option_chain(OptionChainRequest(InstrumentRef("NIFTY", "NSE"), "2026-09-24")),
        ),
        ("instrument_lot_sizes", lambda port: port.lot_sizes(LotSizeRequest("NSE", ("NIFTY",)))),
        ("balance_snapshot", lambda port: port.balance()),
        (
                "portfolio_greeks",
                lambda port: port.portfolio_greeks(
                    PortfolioGreeksRequest(
                        (PortfolioPositionRef("NIFTY", "NFO", "75", "CE", "P1", None, None, None),)
                    )
                ),
        ),
        ("positions", lambda port: port.positions()),
        ("holdings", lambda port: port.holdings()),
        (
            "margin_calculator",
            lambda port: port.margin(MarginRequest("NIFTY", "NFO", "BUY", "75", "NRML", "MARKET", "0", "0")),
        ),
        (
            "safety_order_book",
            lambda port: port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR)),
        ),
        (
            "forever_orders",
            lambda port: port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER)),
        ),
        (
            "super_orders",
            lambda port: port.order_states(OrderStateRequest(BrokerOrderFamily.SUPER)),
        ),
        ("trade_book", lambda port: port.trades()),
    ],
)
@pytest.mark.parametrize("provider_error", [ValueError, RuntimeError])
def test_every_provider_call_exception_is_redacted_as_provider_failure(
    harness,
    attribute,
    invoke,
    provider_error,
) -> None:
    async def raises_private_error(*_args):
        raise provider_error("provider-private")

    setattr(harness.adapter, attribute, raises_private_error)
    owner = _owner(harness)
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)

    assert asyncio.run(invoke(port)) == BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)


@pytest.mark.parametrize(
    ("attribute", "invoke"),
    [
        ("quotes", lambda port: port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE")))),
        ("depth", lambda port: port.depth(QuoteRequest(InstrumentRef("NIFTY", "NSE")))),
        (
            "historical",
            lambda port: port.historical(
                HistoricalRequest(InstrumentRef("NIFTY", "NSE"), "D", "2026-09-01", "2026-09-05")
            ),
        ),
        (
            "quotes",
            lambda port: port.batch_quotes(BatchQuoteRequest((InstrumentRef("NIFTY", "NSE"),))),
        ),
        (
            "option_chain",
            lambda port: port.option_chain(
                OptionChainRequest(InstrumentRef("NIFTY", "NSE"), "2026-09-24")
            ),
        ),
        ("instrument_lot_sizes", lambda port: port.lot_sizes(LotSizeRequest("NSE", ("NIFTY",)))),
        ("balance_snapshot", lambda port: port.balance()),
        (
            "portfolio_greeks",
            lambda port: port.portfolio_greeks(
                PortfolioGreeksRequest(
                    (PortfolioPositionRef("NIFTY", "NFO", "75", "CE", "P1", None, None, None),)
                )
            ),
        ),
        ("positions", lambda port: port.positions()),
        ("holdings", lambda port: port.holdings()),
        (
            "margin_calculator",
            lambda port: port.margin(
                MarginRequest("NIFTY", "NFO", "BUY", "75", "NRML", "MARKET", "0", "0")
            ),
        ),
        (
            "safety_order_book",
            lambda port: port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR)),
        ),
        (
            "forever_orders",
            lambda port: port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER)),
        ),
        (
            "super_orders",
            lambda port: port.order_states(OrderStateRequest(BrokerOrderFamily.SUPER)),
        ),
        ("trade_book", lambda port: port.trades()),
    ],
)
def test_shared_response_projection_signal_is_malformed_at_every_fixed_provider_boundary(
    harness,
    attribute,
    invoke,
) -> None:
    async def invalid_response(*_args):
        raise BrokerReadResponseInvalid

    setattr(harness.adapter, attribute, invalid_response)
    owner = _owner(harness)
    port = owner.bind(target=ExactReadTarget(harness.selector), verify_current_authority=lambda: harness.context)
    assert not isinstance(port, BrokerReadFailure)

    assert asyncio.run(invoke(port)) == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)


def test_provider_base_exception_propagates_and_releases_the_read_lease(harness) -> None:
    class FatalProviderSignal(BaseException):
        pass

    async def fatal_response(_session):
        raise FatalProviderSignal

    harness.adapter.positions = fatal_response
    owner = _owner(harness)
    port = owner.bind(target=ExactReadTarget(harness.selector), verify_current_authority=lambda: harness.context)
    assert not isinstance(port, BrokerReadFailure)

    with pytest.raises(FatalProviderSignal):
        asyncio.run(port.positions())
    assert owner._active == 0
    assert owner.close(timeout=0.0) is True


def test_balance_conversion_signal_is_malformed_but_provider_value_error_is_provider_failure(harness) -> None:
    async def conversion_failure(_session):
        raise BrokerBalanceResponseInvalid

    owner = _owner(harness)
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)
    harness.adapter.balance_snapshot = conversion_failure
    assert asyncio.run(port.balance()) == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)

    async def provider_failure(_session):
        raise ValueError("provider-private")

    harness.adapter.balance_snapshot = provider_failure
    assert asyncio.run(port.balance()) == BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        ("openalgo", {"data": [{"symbol": "NIFTY", "exchange": "NSE", "lot_size": "bad"}]}),
        ("groww", [{"trading_symbol": "NIFTY", "exchange": "NSE", "lot_size": "bad"}]),
        ("indmoney", [{"TRADING_SYMBOL": "NIFTY", "EXCH": "NSE", "LOT_UNITS": "bad"}]),
    ],
)
def test_concrete_lot_converter_failures_are_malformed(harness, monkeypatch, kind, payload) -> None:
    outcome, calls = _read_concrete_lot(harness, monkeypatch, kind, payload)

    assert outcome == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert calls == [kind]


@pytest.mark.parametrize("kind", ["openalgo", "groww", "indmoney"])
def test_concrete_lot_provider_failures_remain_provider_failure(harness, monkeypatch, kind) -> None:
    outcome, calls = _read_concrete_lot(
        harness,
        monkeypatch,
        kind,
        [],
        error=RuntimeError("provider-private"),
    )

    assert outcome == BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
    assert calls == [kind]


def test_openalgo_lot_requires_provider_exchange_identity(harness, monkeypatch) -> None:
    outcome, calls = _read_concrete_lot(
        harness,
        monkeypatch,
        "openalgo",
        {"data": [{"symbol": "NIFTY", "lot_size": 75}]},
    )

    assert outcome == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert calls == ["openalgo"]


@pytest.mark.parametrize("layer", ["outer", "nested", "row"])
def test_openalgo_lot_rejects_non_string_keys_without_hooks(harness, monkeypatch, layer) -> None:
    target = "data" if layer != "row" else "symbol"
    trap = _CollidingKeyTrap(target)
    row = {"symbol": "NIFTY", "exchange": "NSE", "lot_size": 75}
    if layer == "outer":
        payload = {trap: [row]}
    elif layer == "nested":
        payload = {"data": {trap: [row]}}
    else:
        payload = {"data": [{trap: "NIFTY", "exchange": "NSE", "lot_size": 75}]}
    trap.calls.clear()

    outcome, calls = _read_concrete_lot(harness, monkeypatch, "openalgo", payload)

    assert outcome == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert calls == ["openalgo"]
    assert trap.calls == []


@pytest.mark.parametrize("kind", ["groww", "indmoney"])
def test_native_lot_rows_reject_non_string_keys_without_hooks(harness, monkeypatch, kind) -> None:
    target = "symbol" if kind == "groww" else "TRADING_SYMBOL"
    trap = _CollidingKeyTrap(target)
    if kind == "groww":
        payload = [{trap: "NIFTY", "exchange": "NSE", "lot_size": 75}]
    else:
        payload = [{trap: "NIFTY", "EXCH": "NSE", "LOT_UNITS": 75}]
    trap.calls.clear()

    outcome, calls = _read_concrete_lot(harness, monkeypatch, kind, payload)

    assert outcome == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert calls == [kind]
    assert trap.calls == []


@pytest.mark.parametrize("kind", ["groww", "indmoney"])
@pytest.mark.parametrize("container_kind", ["tuple", "list-subclass", "arbitrary-iterable"])
def test_native_lot_non_list_containers_fail_before_hooks_or_fallback(
    harness,
    monkeypatch,
    kind,
    container_kind,
) -> None:
    if kind == "groww":
        row = {"trading_symbol": "NIFTY", "exchange": "NSE", "lot_size": 75}
    else:
        row = {"TRADING_SYMBOL": "NIFTY", "EXCH": "NSE", "LOT_UNITS": 75}
    trap: _LotIterableTrap | _LotListSubclassTrap | None = None
    if container_kind == "tuple":
        rows: object = (row,)
    elif container_kind == "list-subclass":
        trap = _LotListSubclassTrap([row])
        rows = trap
    else:
        trap = _LotIterableTrap()
        rows = trap

    outcome, calls = _read_concrete_lot(harness, monkeypatch, kind, rows)

    assert outcome == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert calls == [kind]
    if trap is not None:
        assert trap.calls == []


@pytest.mark.parametrize(
    ("positions", "rows"),
    [
        (
            (PortfolioPositionRef("NIFTY", "NFO", "75", "CE", None, None, None, None),),
            [{"symbol": "NIFTY", "exchange": "NFO", "delta": 0.5, "vega": 1.0}],
        ),
        (
            (PortfolioPositionRef("NIFTY", "NFO", "75", "CE", "P1", None, None, None),),
            [{"symbol": "NIFTY", "exchange": "NFO", "delta": 0.5, "vega": 1.0}],
        ),
        (
            (
                PortfolioPositionRef("NIFTY", "NFO", "75", "CE", None, None, None, None),
                PortfolioPositionRef("BANKNIFTY", "NFO", "30", "PE", None, None, None, None),
            ),
            [
                {"symbol": "NIFTY", "exchange": "NFO", "instrument_id": "DUP", "delta": 0.5, "vega": 1.0},
                {"symbol": "BANKNIFTY", "exchange": "NFO", "instrument_id": "DUP", "delta": -0.4, "vega": 0.9},
            ],
        ),
        (
            (PortfolioPositionRef("NIFTY", "NFO", "75", "CE", "P1", None, None, None),),
            [
                {"symbol": "NIFTY", "exchange": "NFO", "instrument_id": "P1", "delta": 0.5, "vega": 1.0},
                {"symbol": "EXTRA", "exchange": "NFO", "instrument_id": "P2", "delta": 0.1, "vega": 0.2},
            ],
        ),
        (
            (
                PortfolioPositionRef("NIFTY", "NFO", "75", "CE", "P1", None, None, None),
                PortfolioPositionRef("BANKNIFTY", "NFO", "30", "PE", "P2", None, None, None),
            ),
            [{"symbol": "NIFTY", "exchange": "NFO", "instrument_id": "P1", "delta": 0.5, "vega": 1.0}],
        ),
    ],
    ids=[
        "native-both-missing-id",
        "requested-id-returned-id-missing",
        "duplicate-returned-id",
        "extra-returned-row",
        "incomplete-requested-coverage",
    ],
)
def test_native_portfolio_greek_identity_matrix_fails_closed(harness, positions, rows) -> None:
    provider_calls: list[list[dict[str, object]]] = []

    async def portfolio_greeks(_session, projected):
        provider_calls.append(projected)
        return rows

    harness.adapter.portfolio_greeks = portfolio_greeks
    owner = _owner(harness)
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)
    harness.limiter.calls.clear()

    outcome = asyncio.run(port.portfolio_greeks(PortfolioGreeksRequest(positions)))

    assert outcome == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert len(provider_calls) == 1
    assert harness.limiter.calls == [("dhan", "data")]


def test_missing_fixed_adapter_attribute_is_classified_without_invoking_getattribute(harness) -> None:
    lookups: list[str] = []

    class ExplodingAdapter:
        def __getattribute__(self, name):
            if name == "quotes":
                lookups.append(name)
                raise RuntimeError("provider-private")
            return object.__getattribute__(self, name)

    owner = _owner(harness, adapters={"dhan": ExplodingAdapter()})
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)

    result = asyncio.run(port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE"))))

    assert result == BrokerReadFailure(BrokerReadErrorCode.UNSUPPORTED)
    assert lookups == []
    assert harness.limiter.calls == []


def test_post_admission_active_descriptor_lookup_failure_is_provider_failure(harness) -> None:
    lookups: list[str] = []

    class ExplodingAdapter:
        async def quotes(self, _session, _symbols):
            raise AssertionError("declared provider method must be resolved first")

        def __getattribute__(self, name):
            if name == "quotes":
                lookups.append(name)
                raise RuntimeError("provider-private")
            return object.__getattribute__(self, name)

    owner = _owner(harness, adapters={"dhan": ExplodingAdapter()})
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)
    harness.limiter.calls.clear()

    result = asyncio.run(port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE"))))

    assert result == BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
    assert lookups == ["quotes"]
    assert harness.limiter.calls == [("dhan", "data")]


def test_post_admission_real_descriptor_getter_failure_is_provider_failure(harness) -> None:
    getter_calls: list[str] = []

    class ExplodingDescriptor:
        def __call__(self, *_args):
            raise AssertionError("static descriptor must never be invoked")

        def __get__(self, _instance, _owner):
            getter_calls.append("quotes")
            raise RuntimeError("provider-private descriptor failure")

    class DescriptorAdapter:
        quotes = ExplodingDescriptor()

    owner = _owner(harness, adapters={"dhan": DescriptorAdapter()})
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)
    harness.limiter.calls.clear()

    result = asyncio.run(port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE"))))

    assert result == BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
    assert getter_calls == ["quotes"]
    assert harness.limiter.calls == [("dhan", "data")]
    assert owner._active == 0


@pytest.mark.parametrize(
    ("attribute", "result", "invoke"),
    [
        (
            "quotes",
            lambda trap: [{"symbol": trap, "exchange": "NSE", "ltp": 1}],
            lambda port: port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE"))),
        ),
        (
            "depth",
            lambda trap: {
                "symbol": "NIFTY",
                "exchange": "NSE",
                "bids": [{"price": trap, "quantity": 1}],
                "asks": [],
            },
            lambda port: port.depth(QuoteRequest(InstrumentRef("NIFTY", "NSE"))),
        ),
        (
            "historical",
            lambda trap: {
                "symbol": "NIFTY",
                "exchange": trap,
                "interval": "D",
                "bars": [],
            },
            lambda port: port.historical(
                HistoricalRequest(InstrumentRef("NIFTY", "NSE"), "D", "2026-09-01", "2026-09-05")
            ),
        ),
        (
            "quotes",
            lambda trap: [
                {"symbol": trap, "exchange": "NSE", "ltp": 1},
                {"symbol": "BANKNIFTY", "exchange": "NSE", "ltp": 2},
            ],
            lambda port: port.batch_quotes(
                BatchQuoteRequest((InstrumentRef("NIFTY", "NSE"), InstrumentRef("BANKNIFTY", "NSE")))
            ),
        ),
        (
            "option_chain",
            lambda trap: {
                "underlying": "NIFTY",
                "exchange": "NSE",
                "expiry": trap,
                "strikes": [],
            },
            lambda port: port.option_chain(OptionChainRequest(InstrumentRef("NIFTY", "NSE"), "2026-09-24")),
        ),
        (
            "margin_calculator",
            lambda trap: {"required_margin": trap},
            lambda port: port.margin(MarginRequest("NIFTY", "NFO", "BUY", "75", "NRML", "MARKET", "0", "0")),
        ),
        (
            "safety_order_book",
            lambda trap: [{"orderid": trap, "status": "complete"}],
            lambda port: port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR)),
        ),
    ],
)
def test_untrusted_primitive_hooks_never_execute(harness, attribute, result, invoke) -> None:
    trap = _PrimitiveHookTrap()

    async def replacement(*_args):
        return result(trap)

    setattr(harness.adapter, attribute, replacement)
    owner = _owner(harness)
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)

    assert asyncio.run(invoke(port)) == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert trap.calls == []


@pytest.mark.parametrize("case", ["record", "model_dump", "margin_data"])
def test_every_consumed_record_rejects_non_string_keys_without_comparison_hooks(
    harness,
    monkeypatch,
    case,
) -> None:
    from flinttrade_core.models import Quote

    target = "required_margin" if case == "margin_data" else "symbol"
    trap = _CollidingKeyTrap(target)
    mapping = {trap: "untrusted"}
    if case != "margin_data":
        mapping.update({"exchange": "NSE", "ltp": 1})
    trap.calls.clear()

    if case == "record":
        harness.adapter.result = [mapping]
    elif case == "model_dump":
        model = Quote(symbol="NIFTY", exchange="NSE", ltp=1)
        monkeypatch.setattr(Quote, "model_dump", lambda _self, **_kwargs: mapping)
        harness.adapter.result = [model]
    else:
        async def margin_calculator(*_args):
            return {"data": mapping}

        harness.adapter.margin_calculator = margin_calculator

    def invoke(port):
        if case == "margin_data":
            return port.margin(MarginRequest("NIFTY", "NFO", "BUY", "75", "NRML", "MARKET", "0", "0"))
        return port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE")))

    owner = _owner(harness)
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)

    assert asyncio.run(invoke(port)) == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert trap.calls == []


@pytest.mark.parametrize(
    ("available", "optional", "success"),
    [
        (True, {}, False),
        (True, {"ltp": 0}, True),
        (False, {}, True),
        (False, {"ltp": None}, False),
        (False, {"ltp": ""}, False),
    ],
)
def test_batch_quote_presence_contract(harness, available, optional, success) -> None:
    async def quotes(_session, _symbols):
        return [{"symbol": "NIFTY", "exchange": "NSE", "available": available, **optional}]

    harness.adapter.quotes = quotes
    owner = _owner(harness)
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)

    result = asyncio.run(port.batch_quotes(BatchQuoteRequest((InstrumentRef("NIFTY", "NSE"),))))

    assert isinstance(result, BrokerReadSuccess) is success
    if not success:
        assert result == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)


def test_single_quote_requires_numeric_payload_but_accepts_all_zero(harness) -> None:
    owner = _owner(harness)
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)

    harness.adapter.result = [{"symbol": "NIFTY", "exchange": "NSE", "available": True}]
    assert asyncio.run(port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE")))) == BrokerReadFailure(
        BrokerReadErrorCode.MALFORMED_RESPONSE
    )

    harness.adapter.result = [
        {
            "symbol": "NIFTY",
            "exchange": "NSE",
            "available": True,
            "ltp": 0,
            "open": 0,
            "high": 0,
            "low": 0,
            "close": 0,
            "volume": 0,
            "bid": 0,
            "ask": 0,
            "prev_close": 0,
            "oi": 0,
        }
    ]
    result = asyncio.run(port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE"))))
    assert isinstance(result, BrokerReadSuccess)
    assert result.value.ltp == 0.0
    assert result.value.volume == 0


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "0"), (0.0, "0.0"), ("0", "0"), (75, "75"), (-1.25, "-1.25"), ("1e2", "1e2")],
)
def test_numeric_as_text_fields_accept_only_finite_numeric_primitives(harness, value, expected) -> None:
    async def positions(_session):
        return [
            {
                "symbol": "NIFTY",
                "exchange": "NFO",
                "product": "NRML",
                "quantity": value,
                "average_price": value,
            }
        ]

    harness.adapter.positions = positions
    owner = _owner(harness)
    port = owner.bind(target=ExactReadTarget(harness.selector), verify_current_authority=lambda: harness.context)
    assert not isinstance(port, BrokerReadFailure)

    result = asyncio.run(port.positions())

    assert isinstance(result, BrokerReadSuccess)
    assert result.value[0].quantity == expected
    assert result.value[0].average_price == expected


@pytest.mark.parametrize(
    "value",
    [True, float("nan"), float("inf"), float("-inf"), "", "   ", "NaN", "Infinity", "not-a-number"],
)
def test_numeric_as_text_fields_reject_non_numeric_or_non_finite_values(harness, value) -> None:
    async def positions(_session):
        return [{"symbol": "NIFTY", "exchange": "NFO", "product": "NRML", "quantity": value}]

    harness.adapter.positions = positions
    owner = _owner(harness)
    port = owner.bind(target=ExactReadTarget(harness.selector), verify_current_authority=lambda: harness.context)
    assert not isinstance(port, BrokerReadFailure)

    assert asyncio.run(port.positions()) == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)


def test_numeric_as_text_fields_reject_arbitrary_coercion_without_hooks(harness) -> None:
    trap = _PrimitiveHookTrap()

    async def positions(_session):
        return [{"symbol": "NIFTY", "exchange": "NFO", "product": "NRML", "quantity": trap}]

    harness.adapter.positions = positions
    owner = _owner(harness)
    port = owner.bind(target=ExactReadTarget(harness.selector), verify_current_authority=lambda: harness.context)
    assert not isinstance(port, BrokerReadFailure)

    assert asyncio.run(port.positions()) == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert trap.calls == []


def test_number_text_distinguishes_absence_rejects_subclasses_and_detaches_strings(harness) -> None:
    class IntSubclass(int):
        pass

    class FloatSubclass(float):
        pass

    class StringSubclass(str):
        pass

    owner = _owner(harness)
    assert owner._number_text({}, "value") is None
    assert owner._number_text({"value": None}, "value") is None
    for raw in ({}, {"value": None}):
        with pytest.raises(ValueError):
            owner._number_text(raw, "value", required=True)
    for value in (IntSubclass(1), FloatSubclass(1.0), StringSubclass("1")):
        with pytest.raises(ValueError):
            owner._number_text({"value": value}, "value")

    source = "".join(("1234567890", ".", "1234567890"))
    detached = owner._number_text({"value": source}, "value")
    assert detached == source
    assert detached is not source


def test_numeric_as_text_aliases_are_presence_first_and_identifiers_remain_strict(harness) -> None:
    owner = _owner(harness)

    assert owner._number_text({"primary": None, "secondary": 0}, "primary", "secondary") == "0"
    assert owner._number_text({"primary": 1, "secondary": "bad"}, "primary", "secondary") == "1"
    assert owner._number_text({"primary": 1, "secondary": 2}, "primary", "secondary") == "1"
    with pytest.raises(ValueError):
        owner._number_text({"primary": "bad", "secondary": 1}, "primary", "secondary")

    async def positions(_session):
        return [{"symbol": 123, "exchange": "NFO", "product": "NRML", "quantity": 1}]

    harness.adapter.positions = positions
    port = owner.bind(target=ExactReadTarget(harness.selector), verify_current_authority=lambda: harness.context)
    assert not isinstance(port, BrokerReadFailure)
    assert asyncio.run(port.positions()) == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)


def test_option_expiry_aliases_reject_conflict(harness) -> None:
    async def option_chain(_session, _request):
        return {
            "underlying": "NIFTY",
            "exchange": "NSE",
            "expiry": "2026-09-24",
            "expiry_date": "2026-10-01",
            "strikes": [],
        }

    harness.adapter.option_chain = option_chain
    owner = _owner(harness)
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)

    assert asyncio.run(
        port.option_chain(OptionChainRequest(InstrumentRef("NIFTY", "NSE"), "2026-09-24"))
    ) == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)


def test_option_chain_rejects_a_conflicting_requested_underlying_identity(harness) -> None:
    async def option_chain(_session, _request):
        return {
            "underlying": "NIFTY",
            "underlying_key": "WRONG",
            "exchange": "NSE",
            "expiry": "2026-09-24",
            "strikes": [],
        }

    harness.adapter.option_chain = option_chain
    owner = _owner(harness)
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)

    result = asyncio.run(
        port.option_chain(
            OptionChainRequest(InstrumentRef("NIFTY", "NSE", "REQUESTED"), "2026-09-24")
        )
    )

    assert result == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)


def test_supported_models_publish_only_recursively_explicit_fields(harness) -> None:
    from flinttrade_core.models import (
        Candles,
        Depth,
        DepthLevel,
        Holding,
        OHLCV,
        OptionChain,
        OptionChainStrike,
        Position,
        Quote,
        Trade,
    )

    async def quotes(_session, _symbols):
        return [Quote(symbol="NIFTY", exchange="NSE", ltp=1)]

    async def depth(_session, _request):
        return Depth(
            symbol="NIFTY",
            exchange="NSE",
            bids=[DepthLevel(price=1, quantity=2)],
            asks=[],
        )

    async def historical(_session, _request):
        return Candles(
            symbol="NIFTY",
            exchange="NSE",
            interval="D",
            bars=[OHLCV(timestamp="2026-09-05", open=1, high=2, low=0.5, close=1.5)],
        )

    async def option_chain(_session, _request):
        return OptionChain(
            underlying="NIFTY",
            exchange="NSE",
            expiry="2026-09-24",
            strikes=[OptionChainStrike(strike_price=25000)],
        )

    async def positions(_session):
        return [Position(symbol="NIFTY", exchange="NFO", product="NRML", quantity="75")]

    async def holdings(_session):
        return [Holding(symbol="INFY", exchange="NSE", quantity="10")]

    async def trade_book(_session):
        return [
            Trade(
                orderid="O1",
                symbol="NIFTY",
                exchange="NFO",
                action="BUY",
                quantity="75",
                price="100",
                product="NRML",
                timestamp="2026-09-06T09:20:00+05:30",
            )
        ]

    harness.adapter.quotes = quotes
    harness.adapter.depth = depth
    harness.adapter.historical = historical
    harness.adapter.option_chain = option_chain
    harness.adapter.positions = positions
    harness.adapter.holdings = holdings
    harness.adapter.trade_book = trade_book
    owner = _owner(harness)
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)

    quote_result = asyncio.run(port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE"))))
    depth_result = asyncio.run(port.depth(QuoteRequest(InstrumentRef("NIFTY", "NSE"))))
    history_result = asyncio.run(
        port.historical(HistoricalRequest(InstrumentRef("NIFTY", "NSE"), "D", "2026-09-01", "2026-09-05"))
    )
    option_result = asyncio.run(
        port.option_chain(OptionChainRequest(InstrumentRef("NIFTY", "NSE"), "2026-09-24"))
    )
    positions_result = asyncio.run(port.positions())
    holdings_result = asyncio.run(port.holdings())
    trades_result = asyncio.run(port.trades())

    assert quote_result.value.open is None
    assert quote_result.value.volume is None
    assert depth_result.value.bids[0].orders is None
    assert history_result.value.bars[0].volume is None
    assert option_result.value.spot_price is None
    assert option_result.value.strikes[0].ce_ltp is None
    assert positions_result.value[0].previous_close_trusted is None
    assert positions_result.value[0].accounting_complete is None
    assert holdings_result.value[0].previous_close_trusted is None
    assert holdings_result.value[0].accounting_complete is None
    assert trades_result.value[0].multiplier is None
    assert trades_result.value[0].cross_currency is None


def _all_operation_invocations(port):
    instrument = InstrumentRef("NIFTY", "NSE")
    return (
        lambda: port.quote(QuoteRequest(instrument)),
        lambda: port.depth(QuoteRequest(instrument)),
        lambda: port.historical(HistoricalRequest(instrument, "D", "2026-09-01", "2026-09-05")),
        lambda: port.batch_quotes(
            BatchQuoteRequest((InstrumentRef("NIFTY", "NSE"), InstrumentRef("BANKNIFTY", "NSE")))
        ),
        lambda: port.option_chain(OptionChainRequest(instrument, "2026-09-24")),
        lambda: port.lot_sizes(LotSizeRequest("NSE", ("NIFTY", "BANKNIFTY"))),
        lambda: port.balance(),
        lambda: port.portfolio_greeks(
            PortfolioGreeksRequest(
                (PortfolioPositionRef("NIFTY", "NFO", "75", "CE", "P1", None, None, None),)
            )
        ),
        lambda: port.positions(),
        lambda: port.holdings(),
        lambda: port.margin(MarginRequest("NIFTY", "NFO", "BUY", "75", "NRML", "MARKET", "0", "0")),
        lambda: port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR)),
        lambda: port.trades(),
    )


def test_all_thirteen_missing_capabilities_return_unsupported_without_alternate_dispatch(harness) -> None:
    owner = _owner(harness, adapters={"dhan": object()})
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)
    harness.limiter.calls.clear()

    outcomes = [asyncio.run(invoke()) for invoke in _all_operation_invocations(port)]

    assert outcomes == [BrokerReadFailure(BrokerReadErrorCode.UNSUPPORTED)] * 13
    assert harness.limiter.calls == []
    assert owner._active == 0


@pytest.mark.parametrize(
    ("adapter_type", "invoke", "attribute"),
    [
        (
            "indmoney",
            lambda port: port.option_chain(
                OptionChainRequest(InstrumentRef("NIFTY", "NSE"), "2026-09-24")
            ),
            "option_chain",
        ),
        ("indmoney", lambda port: port.trades(), "trade_book"),
        (
            "kotakneo",
            lambda port: port.historical(
                HistoricalRequest(InstrumentRef("NIFTY", "NSE"), "D", "2026-09-01", "2026-09-05")
            ),
            "historical",
        ),
        (
            "kotakneo",
            lambda port: port.option_chain(
                OptionChainRequest(InstrumentRef("NIFTY", "NSE"), "2026-09-24")
            ),
            "option_chain",
        ),
    ],
)
def test_exact_class_static_unsupported_markers_skip_limiter_and_callable(
    harness,
    monkeypatch,
    adapter_type,
    invoke,
    attribute,
) -> None:
    from flinttrade_gateway.brokers.indmoney import IndMoneyAdapter
    from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter

    adapter = IndMoneyAdapter() if adapter_type == "indmoney" else KotakNeoAdapter()
    endpoint_calls: list[str] = []
    verifier_calls: list[str] = []

    async def forbidden(*_args):
        endpoint_calls.append(attribute)
        raise AssertionError("unsupported callable executed")

    monkeypatch.setattr(adapter, attribute, forbidden)
    owner = _owner(harness, adapters={"dhan": adapter})

    def verify():
        verifier_calls.append("verify")
        return harness.context

    port = owner.bind(target=ExactReadTarget(harness.selector), verify_current_authority=verify)
    assert not isinstance(port, BrokerReadFailure)
    verifier_calls.clear()
    harness.limiter.calls.clear()

    assert asyncio.run(invoke(port)) == BrokerReadFailure(BrokerReadErrorCode.UNSUPPORTED)
    assert verifier_calls == ["verify"]
    assert harness.limiter.calls == []
    assert endpoint_calls == []
    assert owner._active == 0


def test_unmarked_subclass_not_implemented_callable_remains_provider_failure(harness) -> None:
    from flinttrade_gateway.brokers.indmoney import IndMoneyAdapter

    endpoint_calls: list[str] = []

    class UnmarkedIndMoneyAdapter(IndMoneyAdapter):
        async def trade_book(self, _session):
            endpoint_calls.append("trade_book")
            raise NotImplementedError("provider placeholder")

    owner = _owner(harness, adapters={"dhan": UnmarkedIndMoneyAdapter()})
    port = owner.bind(target=ExactReadTarget(harness.selector), verify_current_authority=lambda: harness.context)
    assert not isinstance(port, BrokerReadFailure)
    harness.limiter.calls.clear()

    assert asyncio.run(port.trades()) == BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
    assert endpoint_calls == ["trade_book"]
    assert harness.limiter.calls == [("dhan", "data")]
    assert owner._active == 0


@pytest.mark.parametrize(
    ("stale_case", "expected"),
    [
        ("shutdown", BrokerReadErrorCode.REVOKED),
        ("revoke", BrokerReadErrorCode.REVOKED),
        ("callback", BrokerReadErrorCode.UNAUTHORISED),
        ("role-replaced", BrokerReadErrorCode.TARGET_STALE),
        ("broker-mutated", BrokerReadErrorCode.TARGET_STALE),
        ("disconnected", BrokerReadErrorCode.DISCONNECTED),
    ],
)
def test_lifecycle_failures_outrank_static_unsupported_classification(
    harness,
    monkeypatch,
    stale_case,
    expected,
) -> None:
    from flinttrade_gateway.brokers.indmoney import IndMoneyAdapter

    accepting = [True]
    authority = [harness.context]
    endpoint_calls: list[str] = []
    adapter = IndMoneyAdapter()

    async def forbidden(*_args):
        endpoint_calls.append("option_chain")
        raise AssertionError("unsupported callable executed")

    monkeypatch.setattr(adapter, "option_chain", forbidden)
    owner = _owner(harness, runtime=lambda: accepting[0], adapters={"dhan": adapter})
    port = owner.bind(
        target=DataRoleReadTarget(BrokerDataRole.OPTION_CHAINS),
        verify_current_authority=lambda: authority[0],
    )
    assert not isinstance(port, BrokerReadFailure)
    harness.limiter.calls.clear()

    if stale_case == "shutdown":
        accepting[0] = False
    elif stale_case == "revoke":
        assert owner.revoke(port)
    elif stale_case == "callback":
        authority[0] = None
    elif stale_case in {"role-replaced", "broker-mutated"}:
        snapshot = read_workspace_snapshot(harness.workspace_path)

        def mutate(config):
            if stale_case == "role-replaced":
                config["brokers"]["data"]["option_chains"] = "dhan:Other"
            else:
                config["brokers"]["failover"]["enabled"] = True

        compare_and_swap_workspace(harness.workspace_path, snapshot.version, mutate)
    else:
        harness.registry_owner.remove_session_for_exact(
            harness.selector,
            expected_registry=harness.registry.snapshot_selector(harness.selector),
        )

    outcome = asyncio.run(
        port.option_chain(OptionChainRequest(InstrumentRef("NIFTY", "NSE"), "2026-09-24"))
    )

    assert outcome == BrokerReadFailure(expected)
    assert harness.limiter.calls == []
    assert endpoint_calls == []
    assert owner._active == 0


@pytest.mark.parametrize(
    ("attribute", "raw", "invoke"),
    [
        (
            "quotes",
            [{"symbol": "NIFTY", "exchange": "NSE"}],
            lambda port: port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE"))),
        ),
        (
            "depth",
            {"symbol": "NIFTY", "exchange": "NSE", "bids": []},
            lambda port: port.depth(QuoteRequest(InstrumentRef("NIFTY", "NSE"))),
        ),
        (
            "historical",
            {"symbol": "NIFTY", "exchange": "NSE", "interval": "D", "bars": [{}]},
            lambda port: port.historical(
                HistoricalRequest(InstrumentRef("NIFTY", "NSE"), "D", "2026-09-01", "2026-09-05")
            ),
        ),
        (
            "quotes",
            [
                {"symbol": "NIFTY", "exchange": "NSE", "ltp": 1},
                {"symbol": "NIFTY", "exchange": "NSE", "ltp": 2},
            ],
            lambda port: port.batch_quotes(
                BatchQuoteRequest((InstrumentRef("NIFTY", "NSE"), InstrumentRef("BANKNIFTY", "NSE")))
            ),
        ),
        (
            "option_chain",
            {
                "underlying": "NIFTY",
                "exchange": "NSE",
                "expiry": "2026-09-24",
                "strikes": [{"strike_price": 25000}, {"strike_price": 25000}],
            },
            lambda port: port.option_chain(OptionChainRequest(InstrumentRef("NIFTY", "NSE"), "2026-09-24")),
        ),
        (
            "instrument_lot_sizes",
            [{"symbol": "NIFTY", "exchange": "NSE", "lot_size": 75}],
            lambda port: port.lot_sizes(LotSizeRequest("NSE", ("NIFTY", "BANKNIFTY"))),
        ),
        ("balance_snapshot", object(), lambda port: port.balance()),
        (
            "portfolio_greeks",
            [],
            lambda port: port.portfolio_greeks(
                PortfolioGreeksRequest(
                    (PortfolioPositionRef("NIFTY", "NFO", "75", "CE", "P1", None, None, None),)
                )
            ),
        ),
        (
            "positions",
            [{"symbol": "NIFTY", "exchange": "NFO", "product": "NRML"}],
            lambda port: port.positions(),
        ),
        (
            "holdings",
            [{"symbol": "INFY", "exchange": "NSE"}],
            lambda port: port.holdings(),
        ),
        (
            "margin_calculator",
            {"data": []},
            lambda port: port.margin(MarginRequest("NIFTY", "NFO", "BUY", "75", "NRML", "MARKET", "0", "0")),
        ),
        (
            "safety_order_book",
            [{"orderid": "O1"}],
            lambda port: port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR)),
        ),
        (
            "trade_book",
            [
                {
                    "symbol": "NIFTY",
                    "exchange": "NFO",
                    "action": "BUY",
                    "quantity": "75",
                    "price": "100",
                    "product": "NRML",
                }
            ],
            lambda port: port.trades(),
        ),
    ],
)
def test_all_thirteen_malformed_or_partial_results_have_one_fixed_outcome(harness, attribute, raw, invoke) -> None:
    calls = 0

    async def replacement(*_args):
        nonlocal calls
        calls += 1
        return raw

    setattr(harness.adapter, attribute, replacement)
    if attribute == "safety_order_book":
        async def forbidden_fallback(*_args):
            raise AssertionError("regular order fallback called")

        harness.adapter.order_book = forbidden_fallback
    owner = _owner(harness)
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)

    assert asyncio.run(invoke(port)) == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
    assert calls == 1


@pytest.mark.parametrize(
    ("family", "attribute"),
    [
        (BrokerOrderFamily.REGULAR, "safety_order_book"),
        (BrokerOrderFamily.FOREVER, "forever_orders"),
        (BrokerOrderFamily.SUPER, "super_orders"),
    ],
)
def test_exact_order_id_filters_valid_family_books_but_rejects_duplicates_and_malformed_rows(
    harness,
    family,
    attribute,
) -> None:
    def row(order_id: str) -> dict[str, object]:
        result: dict[str, object] = {
            "orderid": order_id,
            "status": "open",
            "symbol": "NIFTY",
            "exchange": "NFO",
            "action": "BUY",
            "product": "NRML",
            "quantity": "75",
            "filled_quantity": "0",
        }
        if family is BrokerOrderFamily.SUPER:
            result["legs"] = [{"leg_name": "ENTRY_LEG", "status": "open"}]
        return result

    response = [row("REQUESTED"), row("UNRELATED")]

    async def family_book(*_args):
        return response

    setattr(harness.adapter, attribute, family_book)
    owner = _owner(harness)
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)
    request = OrderStateRequest(family, "REQUESTED")

    result = asyncio.run(port.order_states(request))
    assert isinstance(result, BrokerReadSuccess)
    assert [item.orderid for item in result.value] == ["REQUESTED"]

    response[:] = [row("REQUESTED"), row("REQUESTED")]
    assert asyncio.run(port.order_states(request)) == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)

    response[:] = [row("REQUESTED"), {"orderid": "UNRELATED"}]
    assert asyncio.run(port.order_states(request)) == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)


@pytest.mark.parametrize(
    ("family", "attribute"),
    [
        (BrokerOrderFamily.REGULAR, "safety_order_book"),
        (BrokerOrderFamily.FOREVER, "forever_orders"),
        (BrokerOrderFamily.SUPER, "super_orders"),
    ],
)
@pytest.mark.parametrize("invalid_unrelated", ["missing_active_symbol", "duplicate_active_id"])
def test_exact_order_filter_validates_every_unrelated_active_family_row(
    harness,
    family,
    attribute,
    invalid_unrelated,
) -> None:
    def row(order_id: str) -> dict[str, object]:
        result: dict[str, object] = {
            "orderid": order_id,
            "status": "open",
            "symbol": "NIFTY",
            "exchange": "NFO",
            "action": "BUY",
            "product": "NRML",
            "quantity": "75",
        }
        if family is BrokerOrderFamily.SUPER:
            result["legs"] = [{"leg_name": "ENTRY_LEG", "status": "open"}]
        return result

    unrelated = row("UNRELATED")
    if invalid_unrelated == "missing_active_symbol":
        unrelated.pop("symbol")
        response = [row("REQUESTED"), unrelated]
    else:
        response = [row("REQUESTED"), unrelated, row("UNRELATED")]

    async def family_book(*_args):
        return response

    setattr(harness.adapter, attribute, family_book)
    owner = _owner(harness)
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)

    result = asyncio.run(port.order_states(OrderStateRequest(family, "REQUESTED")))
    assert result == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)


@pytest.mark.parametrize(
    "status",
    [
        "canceled",
        "cancelled",
        "closed",
        "complete",
        "completed",
        "deleted",
        "disabled",
        "expired",
        "filled",
        "rejected",
        "traded",
    ],
)
def test_terminal_order_status_matrix_allows_omitted_identity(harness, status) -> None:
    async def order_book(*_args):
        return [{"status": status}]

    harness.adapter.safety_order_book = order_book
    owner = _owner(harness)
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)

    result = asyncio.run(port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR)))

    assert isinstance(result, BrokerReadSuccess)
    assert result.value[0].status == status


@pytest.mark.parametrize(
    ("family", "attribute"),
    [
        (BrokerOrderFamily.REGULAR, "safety_order_book"),
        (BrokerOrderFamily.FOREVER, "forever_orders"),
        (BrokerOrderFamily.SUPER, "super_orders"),
    ],
)
@pytest.mark.parametrize(("filled_quantity", "success"), [(None, False), ("0", True)])
def test_non_terminal_order_rows_require_explicit_fill_for_every_family(
    harness,
    family,
    attribute,
    filled_quantity,
    success,
) -> None:
    row = {
        "orderid": "O1",
        "status": "OPEN",
        "symbol": "NIFTY",
        "exchange": "NFO",
        "action": "BUY",
        "product": "NRML",
        "quantity": "75",
    }
    if filled_quantity is not None:
        row["filled_quantity"] = filled_quantity

    async def order_book(*_args):
        return [row]

    setattr(harness.adapter, attribute, order_book)
    owner = _owner(harness)
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)

    result = asyncio.run(port.order_states(OrderStateRequest(family)))

    assert isinstance(result, BrokerReadSuccess) is success
    if not success:
        assert result == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)


@pytest.mark.parametrize(
    "status",
    ["CONFIRM", "PENDING", "SCHEDULED", "TRIGGER PENDING", "TRIGGER_PENDING"],
)
def test_forever_pre_trigger_rows_preserve_missing_fill_for_task_7c(harness, status) -> None:
    async def forever_orders(*_args):
        return [{
            "orderid": "G1",
            "status": status,
            "symbol": "NIFTY",
            "exchange": "NFO",
            "action": "BUY",
            "product": "NRML",
            "quantity": "75",
        }]

    harness.adapter.forever_orders = forever_orders
    owner = _owner(harness)
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)

    result = asyncio.run(port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER)))

    assert isinstance(result, BrokerReadSuccess)
    assert result.value[0].filled_quantity is None


@pytest.mark.parametrize("leg_name", ["ENTRY_LEG", "TARGET_LEG", "STOP_LOSS_LEG"])
def test_order_rows_reject_duplicate_recognised_nested_leg_names(harness, leg_name) -> None:
    async def super_orders(*_args):
        return [{
            "orderid": "S1",
            "status": "OPEN",
            "symbol": "NIFTY",
            "exchange": "NFO",
            "action": "BUY",
            "product": "NRML",
            "quantity": "75",
            "filled_quantity": "0",
            "legs": [{"leg_name": leg_name}, {"leg_name": leg_name.lower()}],
        }]

    harness.adapter.super_orders = super_orders
    owner = _owner(harness)
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)

    assert asyncio.run(port.order_states(OrderStateRequest(BrokerOrderFamily.SUPER))) == BrokerReadFailure(
        BrokerReadErrorCode.MALFORMED_RESPONSE
    )


def test_dhan_oco_generated_stop_leg_rejects_a_provider_stop_leg_collision(harness) -> None:
    async def forever_orders(*_args):
        return [{
            "orderid": "G1",
            "status": "PENDING",
            "symbol": "NIFTY",
            "exchange": "NFO",
            "action": "BUY",
            "product": "NRML",
            "quantity": "75",
            "filled_quantity": "0",
            "order_flag": "OCO",
            "oco_leg_complete": True,
            "quantity1": "75",
            "price1": "90",
            "trigger_price1": "95",
            "legs": [{"leg_name": "STOP_LOSS_LEG"}],
        }]

    harness.adapter.forever_orders = forever_orders
    owner = _owner(harness)
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)

    assert asyncio.run(port.order_states(OrderStateRequest(BrokerOrderFamily.FOREVER))) == BrokerReadFailure(
        BrokerReadErrorCode.MALFORMED_RESPONSE
    )


@pytest.mark.parametrize(
    ("instrument_ids", "success"),
    [(("I1", "I1"), True), ((None, None), True), (("I1", "I2"), False), ((None, "I2"), False)],
)
def test_lot_size_duplicates_require_identical_size_and_optional_instrument_id(
    harness,
    instrument_ids,
    success,
) -> None:
    rows = [
        {"symbol": "NIFTY", "exchange": "NSE", "lot_size": 75, "instrument_id": instrument_id}
        for instrument_id in instrument_ids
    ]

    async def instrument_lot_sizes(*_args):
        return rows

    harness.adapter.instrument_lot_sizes = instrument_lot_sizes
    owner = _owner(harness)
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)

    result = asyncio.run(port.lot_sizes(LotSizeRequest("NSE", ("NIFTY",))))

    assert isinstance(result, BrokerReadSuccess) is success
    if success:
        assert len(result.value) == 1
        assert result.value[0].instrument_id == instrument_ids[0]
    else:
        assert result == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)


def test_all_thirteen_success_values_are_isolated_from_mutable_provider_sources(harness) -> None:
    owner = _owner(harness)
    port = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )
    assert not isinstance(port, BrokerReadFailure)

    async def publish(attribute, raw, invoke):
        async def replacement(*_args):
            return raw

        setattr(harness.adapter, attribute, replacement)
        result = await invoke()
        assert isinstance(result, BrokerReadSuccess)
        return result

    async def scenario():
        quote_raw = [{"symbol": "NIFTY", "exchange": "NSE", "ltp": 1}]
        quote = await publish("quotes", quote_raw, _all_operation_invocations(port)[0])
        quote_raw[0]["ltp"] = 999
        assert quote.value.ltp == 1.0

        depth_raw = {"bids": [{"price": 1, "quantity": 2}], "asks": []}
        depth = await publish("depth", depth_raw, _all_operation_invocations(port)[1])
        depth_raw["bids"][0]["price"] = 999
        assert depth.value.bids[0].price == 1.0

        history_raw = {
            "symbol": "NIFTY",
            "exchange": "NSE",
            "interval": "D",
            "bars": [{"timestamp": "2026-09-05", "open": 1, "high": 2, "low": 0.5, "close": 1.5}],
        }
        history = await publish("historical", history_raw, _all_operation_invocations(port)[2])
        history_raw["bars"][0]["close"] = 999
        assert history.value.bars[0].close == 1.5

        batch_raw = [
            {"symbol": "NIFTY", "exchange": "NSE", "ltp": 1},
            {"symbol": "BANKNIFTY", "exchange": "NSE", "ltp": 2},
        ]
        batch = await publish("quotes", batch_raw, _all_operation_invocations(port)[3])
        batch_raw[0]["ltp"] = 999
        assert batch.value[0].ltp == 1.0

        option_raw = {
            "underlying": "NIFTY",
            "exchange": "NSE",
            "expiry": "2026-09-24",
            "strikes": [{"strike_price": 25000, "ce_ltp": 1}],
        }
        option = await publish("option_chain", option_raw, _all_operation_invocations(port)[4])
        option_raw["strikes"][0]["ce_ltp"] = 999
        assert option.value.strikes[0].ce_ltp == 1.0

        lots_raw = [
            {"symbol": "NIFTY", "exchange": "NSE", "lot_size": 75},
            {"symbol": "BANKNIFTY", "exchange": "NSE", "lot_size": 30},
        ]
        lots = await publish("instrument_lot_sizes", lots_raw, _all_operation_invocations(port)[5])
        lots_raw[0]["lot_size"] = 999
        assert lots.value[0].lot_size == 75

        balance_raw = BalanceSnapshot(1.0, BalanceEvidence.DIRECT, None, None, None, None, None, None)
        balance = await publish("balance_snapshot", balance_raw, _all_operation_invocations(port)[6])
        object.__setattr__(balance_raw, "available_balance", 999.0)
        assert balance.value.available_balance == 1.0

        greeks_raw = [{"symbol": "NIFTY", "exchange": "NFO", "instrument_id": "P1", "delta": 1, "vega": 2}]
        greeks = await publish("portfolio_greeks", greeks_raw, _all_operation_invocations(port)[7])
        greeks_raw[0]["delta"] = 999
        assert greeks.value[0].delta == 1.0

        positions_raw = [{"symbol": "NIFTY", "exchange": "NFO", "product": "NRML", "quantity": "75"}]
        positions = await publish("positions", positions_raw, _all_operation_invocations(port)[8])
        positions_raw[0]["quantity"] = "999"
        assert positions.value[0].quantity == "75"

        holdings_raw = [{"symbol": "INFY", "exchange": "NSE", "quantity": "10"}]
        holdings = await publish("holdings", holdings_raw, _all_operation_invocations(port)[9])
        holdings_raw[0]["quantity"] = "999"
        assert holdings.value[0].quantity == "10"

        margin_raw = {"required_margin": 1}
        margin = await publish("margin_calculator", margin_raw, _all_operation_invocations(port)[10])
        margin_raw["required_margin"] = 999
        assert margin.value.required_margin == 1.0

        orders_raw = [{
            "orderid": "O1", "status": "open", "symbol": "NIFTY", "exchange": "NFO",
            "action": "BUY", "product": "NRML", "quantity": "75", "filled_quantity": "0",
        }]
        orders = await publish("safety_order_book", orders_raw, _all_operation_invocations(port)[11])
        orders_raw[0]["status"] = "complete"
        assert orders.value[0].status == "open"

        trades_raw = [{
            "orderid": "O1", "symbol": "NIFTY", "exchange": "NFO", "action": "BUY",
            "quantity": "75", "price": "100", "product": "NRML", "timestamp": "09:20",
        }]
        trades = await publish("trade_book", trades_raw, _all_operation_invocations(port)[12])
        trades_raw[0]["price"] = "999"
        assert trades.value[0].price == "100"

    asyncio.run(scenario())


def test_post_provider_revocation_discards_copied_result(harness) -> None:
    owner = _owner(harness)
    checks = 0

    def verify():
        nonlocal checks
        checks += 1
        return None if checks == 4 else harness.context

    port = owner.bind(target=ExactReadTarget(harness.selector), verify_current_authority=verify)
    result = asyncio.run(port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE"))))
    assert result == BrokerReadFailure(BrokerReadErrorCode.UNAUTHORISED)
    assert harness.adapter.calls == 1


@pytest.mark.parametrize("retirement", ["close", "revoke"])
@pytest.mark.parametrize(
    ("boundary", "blocked_verifier_call", "expected_adapter_calls"),
    [("pre_provider", 3, 0), ("post_provider", 4, 1)],
)
def test_close_or_revoke_linearises_final_revalidation_and_publication(
    harness,
    retirement,
    boundary,
    blocked_verifier_call,
    expected_adapter_calls,
) -> None:
    verifier_blocked = threading.Event()
    verifier_release = threading.Event()
    verifier_calls = 0

    def verify():
        nonlocal verifier_calls
        verifier_calls += 1
        if verifier_calls == blocked_verifier_call:
            verifier_blocked.set()
            assert verifier_release.wait(2.0)
        return harness.context

    owner = _owner(harness)
    port = owner.bind(target=ExactReadTarget(harness.selector), verify_current_authority=verify)
    assert not isinstance(port, BrokerReadFailure)
    outcomes: list[object] = []
    errors: list[BaseException] = []

    def run_read() -> None:
        try:
            outcomes.append(asyncio.run(port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE")))))
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    read_thread = threading.Thread(target=run_read, name=f"read-{retirement}-{boundary}")
    read_thread.start()
    assert verifier_blocked.wait(2.0)
    assert owner._active == 1
    if retirement == "close":
        assert owner.close(timeout=0.0) is False
    else:
        assert owner.revoke(port) is True
        assert owner.revoke(port) is True

    verifier_release.set()
    read_thread.join(2.0)

    assert not read_thread.is_alive()
    assert errors == []
    assert outcomes == [BrokerReadFailure(BrokerReadErrorCode.REVOKED)]
    assert harness.adapter.calls == expected_adapter_calls
    assert harness.limiter.calls == [("dhan", "data")]
    assert owner._active == 0
    assert owner.close(timeout=0.0) is True


def test_revoke_and_close_release_callbacks_and_close_is_bounded(harness) -> None:
    owner = _owner(harness)

    class Verifier:
        def __call__(self):
            return harness.context

    verifier = Verifier()
    retained = weakref.ref(verifier)
    port = owner.bind(target=ExactReadTarget(harness.selector), verify_current_authority=verifier)
    del verifier
    assert retained() is not None
    assert owner.revoke(port)
    gc.collect()
    assert retained() is None
    assert owner.close(timeout=0.0)
    assert owner.bind(
        target=ExactReadTarget(harness.selector), verify_current_authority=lambda: harness.context
    ) == BrokerReadFailure(BrokerReadErrorCode.REVOKED)


def test_read_owner_retains_the_exact_prepared_adapter_map(harness) -> None:
    adapters = {"dhan": harness.adapter}

    owner = _owner(harness, adapters=adapters)

    assert owner._adapters is adapters


def test_repeated_close_remains_false_until_the_exact_admitted_read_releases(harness) -> None:
    async def scenario() -> None:
        owner = _owner(harness)
        harness.adapter.started = asyncio.Event()
        harness.adapter.release = asyncio.Event()
        port = owner.bind(
            target=ExactReadTarget(harness.selector),
            verify_current_authority=lambda: harness.context,
        )
        assert not isinstance(port, BrokerReadFailure)
        read = asyncio.create_task(port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE"))))
        await harness.adapter.started.wait()

        assert await asyncio.to_thread(owner.close, timeout=0.0) is False
        assert await asyncio.to_thread(owner.close, timeout=0.0) is False
        harness.adapter.release.set()
        assert await read == BrokerReadFailure(BrokerReadErrorCode.REVOKED)
        assert await asyncio.to_thread(owner.close, timeout=0.0) is True

    asyncio.run(scenario())


def test_revoked_active_read_remains_owned_until_its_exact_lease_releases(harness) -> None:
    async def scenario() -> None:
        owner = _owner(harness)
        harness.adapter.started = asyncio.Event()
        harness.adapter.release = asyncio.Event()
        port = owner.bind(
            target=ExactReadTarget(harness.selector),
            verify_current_authority=lambda: harness.context,
        )
        assert not isinstance(port, BrokerReadFailure)
        read = asyncio.create_task(port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE"))))
        await harness.adapter.started.wait()

        assert owner.revoke(port) is True
        assert await asyncio.to_thread(owner.close, timeout=0.0) is False
        harness.adapter.release.set()
        assert await read == BrokerReadFailure(BrokerReadErrorCode.REVOKED)
        assert await asyncio.to_thread(owner.close, timeout=0.0) is True

    asyncio.run(scenario())


@pytest.mark.parametrize("blocked_at", ["limiter", "provider"])
def test_cancellation_propagates_and_releases_the_exact_admitted_read(harness, blocked_at) -> None:
    class BlockingLimiter:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def acquire(self, _adapter_id, _kind) -> None:
            self.started.set()
            await self.release.wait()

    async def scenario() -> None:
        limiter = BlockingLimiter()
        if blocked_at == "provider":
            harness.adapter.started = asyncio.Event()
            harness.adapter.release = asyncio.Event()
        owner = _owner(harness, limiter=limiter if blocked_at == "limiter" else harness.limiter)
        port = owner.bind(
            target=ExactReadTarget(harness.selector),
            verify_current_authority=lambda: harness.context,
        )
        assert not isinstance(port, BrokerReadFailure)
        read = asyncio.create_task(port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE"))))
        started = limiter.started if blocked_at == "limiter" else harness.adapter.started
        assert started is not None
        await started.wait()

        read.cancel()
        with pytest.raises(asyncio.CancelledError):
            await read
        assert await asyncio.to_thread(owner.close, timeout=0.0) is True

    asyncio.run(scenario())


@pytest.mark.parametrize("shared_facade", [True, False])
def test_owner_count_tracks_two_simultaneous_reads_until_both_release(harness, shared_facade) -> None:
    class TwoReadAdapter:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.releases = (asyncio.Event(), asyncio.Event())
            self.calls = 0

        async def quotes(self, _session, _symbols):
            index = self.calls
            self.calls += 1
            if self.calls == 2:
                self.started.set()
            await self.releases[index].wait()
            return [{"symbol": "NIFTY", "exchange": "NSE", "ltp": 100.0}]

    async def scenario() -> None:
        adapter = TwoReadAdapter()
        owner = _owner(harness, adapters={"dhan": adapter})
        first = owner.bind(
            target=ExactReadTarget(harness.selector),
            verify_current_authority=lambda: harness.context,
        )
        second = first if shared_facade else owner.bind(
            target=ExactReadTarget(harness.selector),
            verify_current_authority=lambda: harness.context,
        )
        assert not isinstance(first, BrokerReadFailure)
        assert not isinstance(second, BrokerReadFailure)
        reads = [
            asyncio.create_task(port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE"))))
            for port in (first, second)
        ]
        await adapter.started.wait()

        assert owner._active == 2
        assert await asyncio.to_thread(owner.close, timeout=0.0) is False
        adapter.releases[0].set()
        assert await reads[0] == BrokerReadFailure(BrokerReadErrorCode.REVOKED)
        assert owner._active == 1
        assert await asyncio.to_thread(owner.close, timeout=0.0) is False
        adapter.releases[1].set()
        assert await reads[1] == BrokerReadFailure(BrokerReadErrorCode.REVOKED)
        assert owner._active == 0
        assert await asyncio.to_thread(owner.close, timeout=0.0) is True

    asyncio.run(scenario())


def test_bind_close_race_never_publishes_a_late_closed_owner_mapping(harness, monkeypatch) -> None:
    import flinttrade_gateway.broker_read_service as service

    binder_waiting = threading.Event()
    closer_waiting = threading.Event()
    closer_done = threading.Event()

    class CloseFirstRaceLock:
        def __enter__(self):
            name = threading.current_thread().name
            if name == "bind-race":
                binder_waiting.set()
                if closer_waiting.wait(0.25):
                    assert closer_done.wait(1.0)
            elif name == "close-race":
                closer_waiting.set()
            return self

        def __exit__(self, _kind, _error, _traceback):
            if threading.current_thread().name == "close-race":
                closer_done.set()

    monkeypatch.setattr(service, "_FACADE_LOCK", CloseFirstRaceLock())
    owner = _owner(harness)
    outcome: list[object] = []
    closed: list[bool] = []
    bind_thread = threading.Thread(
        name="bind-race",
        target=lambda: outcome.append(
            owner.bind(
                target=ExactReadTarget(harness.selector),
                verify_current_authority=lambda: harness.context,
            )
        ),
    )
    bind_thread.start()
    assert binder_waiting.wait(2.0)
    close_thread = threading.Thread(
        name="close-race",
        target=lambda: closed.append(owner.close(timeout=0.0)),
    )
    close_thread.start()
    bind_thread.join(2.0)
    close_thread.join(2.0)

    assert not bind_thread.is_alive()
    assert not close_thread.is_alive()
    assert closed == [True]
    assert len(outcome) == 1
    port = outcome[0]
    assert not isinstance(port, BrokerReadFailure)
    assert service._facade_owner(port) is None
    assert asyncio.run(port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE")))) == BrokerReadFailure(
        BrokerReadErrorCode.REVOKED
    )
    assert harness.adapter.calls == 0


@pytest.mark.parametrize("final_acceptance", [False, RuntimeError("runtime unavailable")])
def test_bind_rechecks_runtime_acceptance_inside_final_publication_section(harness, final_acceptance) -> None:
    import flinttrade_gateway.broker_read_service as service

    calls = 0

    def runtime_acceptance() -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            return True
        if isinstance(final_acceptance, Exception):
            raise final_acceptance
        return final_acceptance

    owner = _owner(harness, runtime=runtime_acceptance)
    with service._FACADE_LOCK:
        before = tuple(service._FACADE_OWNERS)

    result = owner.bind(
        target=ExactReadTarget(harness.selector),
        verify_current_authority=lambda: harness.context,
    )

    assert result == BrokerReadFailure(BrokerReadErrorCode.REVOKED)
    assert calls == 2
    assert len(owner._grants) == 0
    with service._FACADE_LOCK:
        assert tuple(service._FACADE_OWNERS) == before
    assert harness.adapter.calls == 0
    assert harness.limiter.calls == []


def _application_graph(root: object) -> set[int]:
    """Walk application data, including primitives but excluding interpreter machinery.

    Frames, tracebacks, coroutine frames, module globals and function global
    dictionaries are interpreter-owned reachability, not application-data edges.
    Bound receivers, closures, defaults, partials and weak references are walked.
    """
    seen: set[int] = set()
    pending = [root]
    while pending:
        value = pending.pop()
        identity = id(value)
        if identity in seen:
            continue
        seen.add(identity)
        if isinstance(
            value,
            (
                str,
                bytes,
                int,
                float,
                bool,
                type(None),
                type,
                ModuleType,
                FrameType,
                TracebackType,
                CoroutineType,
            ),
        ):
            continue
        if isinstance(value, weakref.ReferenceType):
            referenced = value()
            if referenced is not None:
                pending.append(referenced)
        elif isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, (tuple, list, set, frozenset)):
            pending.extend(value)
        elif isinstance(value, MethodType):
            pending.append(value.__self__)
        elif isinstance(value, partial):
            pending.extend((value.func, value.args, value.keywords))
        elif isinstance(value, FunctionType):
            if value.__closure__:
                pending.extend(cell.cell_contents for cell in value.__closure__)
            if value.__defaults__:
                pending.extend(value.__defaults__)
            if value.__kwdefaults__:
                pending.append(value.__kwdefaults__)
        elif is_dataclass(value) and not isinstance(value, type):
            pending.extend(getattr(value, field.name) for field in fields(value))
        if hasattr(value, "__dict__") and not isinstance(value, (FunctionType, MethodType)):
            pending.append(vars(value))
        for slot in getattr(type(value), "__slots__", ()):
            if slot not in {"__weakref__", "__dict__"} and hasattr(value, slot):
                pending.append(getattr(value, slot))
    return seen


def test_facade_and_result_graphs_expose_no_owner_dependencies_or_callback(harness) -> None:
    from flinttrade_gateway.session_provider import ConnectedSessionClientResolver

    owner = _owner(harness)
    default_sentinel = object()
    closure_sentinel = object()

    class Receiver:
        def verify(self, _default=default_sentinel):
            _ = closure_sentinel
            return harness.context

    receiver = Receiver()
    bound_receiver = receiver.verify
    verifier = partial(bound_receiver)
    weak_receiver = weakref.ref(receiver)
    port = owner.bind(target=ExactReadTarget(harness.selector), verify_current_authority=verifier)
    assert not isinstance(port, BrokerReadFailure)
    handle = harness.provider(harness.context, "dhan", "Synthetic")
    resolver = ConnectedSessionClientResolver(harness.provider, harness.registry)
    router = object()
    raw_success = harness.adapter.result
    success = asyncio.run(port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE"))))
    assert isinstance(success, BrokerReadSuccess)

    raw_malformed = [{"symbol": "OTHER", "exchange": "NSE", "ltp": 1}]
    harness.adapter.result = raw_malformed
    malformed = asyncio.run(port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE"))))
    assert malformed == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)

    async def provider_failure(*_args):
        raise RuntimeError("private-provider-error")

    harness.adapter.quotes = provider_failure
    ordinary_failure = asyncio.run(port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE"))))
    assert ordinary_failure == BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
    graph = _application_graph((port, success, ordinary_failure, malformed))

    forbidden = (
        owner,
        harness.registry,
        harness.registry_owner,
        handle,
        handle._record,
        harness.raw_session,
        harness.raw_session.access_token,
        "synthetic-credential-token-7b",
        harness.provider,
        harness.adapter,
        harness.limiter,
        harness.raw_client,
        raw_success,
        raw_success[0],
        raw_malformed,
        raw_malformed[0],
        resolver,
        router,
        verifier,
        bound_receiver,
        receiver,
        closure_sentinel,
        default_sentinel,
        weak_receiver,
    )
    assert all(id(value) not in graph for value in forbidden)


def test_exact_facade_converts_all_thirteen_fixed_operations(harness) -> None:
    owner = _owner(harness)
    port = owner.bind(target=ExactReadTarget(harness.selector), verify_current_authority=lambda: harness.context)
    assert not isinstance(port, BrokerReadFailure)
    instrument = InstrumentRef("NIFTY", "NSE")

    async def read_all():
        return (
            await port.quote(QuoteRequest(instrument)),
            await port.depth(QuoteRequest(instrument)),
            await port.historical(HistoricalRequest(instrument, "D", "2026-09-01", "2026-09-05")),
            await port.batch_quotes(BatchQuoteRequest((InstrumentRef("A", "NSE"), InstrumentRef("B", "NSE")))),
            await port.option_chain(OptionChainRequest(instrument, "2026-09-24")),
            await port.lot_sizes(LotSizeRequest("NSE", ("A", "B"))),
            await port.balance(),
            await port.portfolio_greeks(
                PortfolioGreeksRequest((PortfolioPositionRef("NIFTY", "NFO", "75", "CE", "P1", "2026-09-24", 25000.0, "NIFTY"),))
            ),
            await port.positions(),
            await port.holdings(),
            await port.margin(MarginRequest("NIFTY", "NFO", "BUY", "75", "NRML", "MARKET", "0", "0")),
            await port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR)),
            await port.trades(),
        )

    results = asyncio.run(read_all())
    assert len(results) == 13
    assert [(index, result) for index, result in enumerate(results) if not isinstance(result, BrokerReadSuccess)] == []
    assert results[3].value[1].instrument.symbol == "B"
    assert results[4].value.underlying.instrument_id == "underlying-1"
    assert results[6].value.opening_risk_capital == 125.0
    assert results[7].value[0].instrument_id == "P1"
    assert results[11].value[0].family is BrokerOrderFamily.REGULAR


@pytest.mark.parametrize(
    ("attribute", "bad_result", "invoke"),
    [
        ("result", [{"symbol": "OTHER", "exchange": "NSE", "ltp": 1}], lambda port: port.quote(QuoteRequest(InstrumentRef("NIFTY", "NSE")))),
        ("instrument_lot_sizes", [{"symbol": "OTHER", "exchange": "NSE", "lot_size": 75}], lambda port: port.lot_sizes(LotSizeRequest("NSE", ("NIFTY",)))),
        ("portfolio_greeks", [{"symbol": "NIFTY", "exchange": "NFO", "instrument_id": "WRONG", "delta": 0.5, "vega": 1.0}], lambda port: port.portfolio_greeks(PortfolioGreeksRequest((PortfolioPositionRef("NIFTY", "NFO", "75", "CE", "P1", None, None, None),)))),
        ("super_orders", [{"orderid": "S1", "status": "open", "legs": [{"leg_name": "ARBITRARY"}]}], lambda port: port.order_states(OrderStateRequest(BrokerOrderFamily.SUPER))),
    ],
)
def test_malformed_or_identity_conflicting_provider_results_fail_closed(harness, attribute, bad_result, invoke) -> None:
    if attribute == "result":
        harness.adapter.result = bad_result
    else:
        async def replacement(*args):
            return bad_result

        setattr(harness.adapter, attribute, replacement)
    owner = _owner(harness)
    port = owner.bind(target=ExactReadTarget(harness.selector), verify_current_authority=lambda: harness.context)
    assert not isinstance(port, BrokerReadFailure)
    assert asyncio.run(invoke(port)) == BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
