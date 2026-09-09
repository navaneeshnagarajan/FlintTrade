"""Gateway-owned exact broker-read capability and grant lifecycle."""

from __future__ import annotations

import inspect
import math
import threading
import time
import weakref
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Callable
from uuid import UUID

from flinttrade_core.account_mutation_contracts import (
    RegistrySelectorVersion,
    RegistrySessionUnavailable,
    SessionVersion,
)
from flinttrade_core.broker_identity import BrokerSelector, CredentialVersion, parse_broker_selector
from flinttrade_core.broker_read_port import (
    BalanceSnapshot,
    BatchQuoteRequest,
    BrokerDataRole,
    BrokerOrderFamily,
    BrokerOrderSourceFamily,
    BrokerReadErrorCode,
    BrokerReadFailure,
    BrokerReadPort,
    BrokerReadProvenance,
    BrokerReadResponseInvalid,
    BrokerReadSuccess,
    CandleSnapshot,
    DataRoleReadTarget,
    DepthLevelSnapshot,
    DepthSnapshot,
    ExactReadTarget,
    HistoricalRequest,
    HistoricalSnapshot,
    HoldingSnapshot,
    InstrumentLotSizeSnapshot,
    InstrumentRef,
    LotSizeRequest,
    MarginRequest,
    MarginSnapshot,
    OptionChainRequest,
    OptionChainSnapshot,
    OptionChainStrikeSnapshot,
    OrderLegStateSnapshot,
    OrderStateRequest,
    OrderStateSnapshot,
    PortfolioGreekSnapshot,
    PortfolioGreeksRequest,
    PortfolioPositionRef,
    PositionSnapshot,
    QuoteRequest,
    QuoteSnapshot,
    TradeSnapshot,
)
from flinttrade_core.exceptions import SafetyBypassError
from flinttrade_core.models import (
    OHLCV,
    Candles,
    Depth,
    GttTrigger,
    Holding,
    OptionChain,
    Order,
    OrderStatus,
    Position,
    Quote,
    Trade,
)
from flinttrade_core.workspace_migrations import (
    BrokerWorkspaceVersion,
    WorkspaceVersion,
    broker_workspace_version,
    read_workspace_snapshot,
)
from flinttrade_engine.request_context import RequestContext

from .registry import (
    BrokerRegistry,
    ConnectedRegistrySession,
    OpenAlgoDefaultCompatibilitySessionVersion,
)
from .session_provider import AuthenticatingSessionProvider


class _Operation(StrEnum):
    QUOTE = "quote"
    DEPTH = "depth"
    HISTORICAL = "historical"
    BATCH_QUOTES = "batch_quotes"
    OPTION_CHAIN = "option_chain"
    LOT_SIZES = "lot_sizes"
    BALANCE = "balance"
    PORTFOLIO_GREEKS = "portfolio_greeks"
    POSITIONS = "positions"
    HOLDINGS = "holdings"
    MARGIN = "margin"
    ORDER_STATES = "order_states"
    TRADES = "trades"


_ALL_OPERATIONS = frozenset(_Operation)
_TERMINAL_ORDER_STATUSES = frozenset(
    {
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
    }
)
_FOREVER_PRE_TRIGGER_STATUSES = frozenset(
    {"CONFIRM", "PENDING", "SCHEDULED", "TRIGGER PENDING", "TRIGGER_PENDING"}
)
_ROLE_OPERATIONS = {
    BrokerDataRole.QUOTE: frozenset(
        {_Operation.QUOTE, _Operation.DEPTH, _Operation.BATCH_QUOTES, _Operation.LOT_SIZES}
    ),
    BrokerDataRole.HISTORICAL: frozenset({_Operation.HISTORICAL}),
    BrokerDataRole.OPTION_CHAINS: frozenset({_Operation.OPTION_CHAIN}),
    BrokerDataRole.GLOBAL_INDICES: frozenset({_Operation.BATCH_QUOTES}),
}


@dataclass(slots=True)
class _Grant:
    selector: BrokerSelector
    role: BrokerDataRole | None
    binding: SessionVersion | OpenAlgoDefaultCompatibilitySessionVersion
    context: RequestContext
    verify_current_authority: Callable[[], RequestContext | None] | None
    allowed: frozenset[_Operation]
    active: int = 0
    revoked: bool = False


@dataclass(frozen=True, slots=True)
class _ProviderCall:
    handle: ConnectedRegistrySession
    method: Callable[..., object]


_FACADE_LOCK = threading.RLock()
_FACADE_OWNERS: weakref.WeakKeyDictionary[_BrokerReadFacade, weakref.ReferenceType[BrokerReadOwner]] = (
    weakref.WeakKeyDictionary()
)


class _BrokerReadFacade:
    """Identity-only public facade; all authority remains in owner side tables."""

    __slots__ = ("__weakref__",)

    def __copy__(self) -> _BrokerReadFacade:
        return _BrokerReadFacade()

    def __deepcopy__(self, memo: dict[int, object]) -> _BrokerReadFacade:
        return _BrokerReadFacade()

    def __repr__(self) -> str:
        return "<BrokerReadPort>"

    async def quote(self, request: QuoteRequest):
        owner = _facade_owner(self)
        return BrokerReadFailure(BrokerReadErrorCode.REVOKED) if owner is None else await owner._quote(self, request)

    async def depth(self, request: QuoteRequest):
        owner = _facade_owner(self)
        return BrokerReadFailure(BrokerReadErrorCode.REVOKED) if owner is None else await owner._depth(self, request)

    async def historical(self, request: HistoricalRequest):
        owner = _facade_owner(self)
        return (
            BrokerReadFailure(BrokerReadErrorCode.REVOKED) if owner is None else await owner._historical(self, request)
        )

    async def batch_quotes(self, request: BatchQuoteRequest):
        owner = _facade_owner(self)
        return (
            BrokerReadFailure(BrokerReadErrorCode.REVOKED)
            if owner is None
            else await owner._batch_quotes(self, request)
        )

    async def option_chain(self, request: OptionChainRequest):
        owner = _facade_owner(self)
        return (
            BrokerReadFailure(BrokerReadErrorCode.REVOKED)
            if owner is None
            else await owner._option_chain(self, request)
        )

    async def lot_sizes(self, request: LotSizeRequest):
        owner = _facade_owner(self)
        return (
            BrokerReadFailure(BrokerReadErrorCode.REVOKED) if owner is None else await owner._lot_sizes(self, request)
        )

    async def balance(self):
        owner = _facade_owner(self)
        return BrokerReadFailure(BrokerReadErrorCode.REVOKED) if owner is None else await owner._balance(self)

    async def portfolio_greeks(self, request: PortfolioGreeksRequest):
        owner = _facade_owner(self)
        return (
            BrokerReadFailure(BrokerReadErrorCode.REVOKED)
            if owner is None
            else await owner._portfolio_greeks(self, request)
        )

    async def positions(self):
        owner = _facade_owner(self)
        return BrokerReadFailure(BrokerReadErrorCode.REVOKED) if owner is None else await owner._positions(self)

    async def holdings(self):
        owner = _facade_owner(self)
        return BrokerReadFailure(BrokerReadErrorCode.REVOKED) if owner is None else await owner._holdings(self)

    async def margin(self, request: MarginRequest):
        owner = _facade_owner(self)
        return BrokerReadFailure(BrokerReadErrorCode.REVOKED) if owner is None else await owner._margin(self, request)

    async def order_states(self, request: OrderStateRequest):
        owner = _facade_owner(self)
        return (
            BrokerReadFailure(BrokerReadErrorCode.REVOKED)
            if owner is None
            else await owner._order_states(self, request)
        )

    async def trades(self):
        owner = _facade_owner(self)
        return BrokerReadFailure(BrokerReadErrorCode.REVOKED) if owner is None else await owner._trades(self)


def _facade_owner(facade: _BrokerReadFacade) -> BrokerReadOwner | None:
    with _FACADE_LOCK:
        reference = _FACADE_OWNERS.get(facade)
    return None if reference is None else reference()


class BrokerReadOwner:
    """Trusted owner for exact read grants and admitted-read drainage."""

    __slots__ = (
        "_registry",
        "_provider",
        "_adapters",
        "_workspace_path",
        "_rate_limiter",
        "_runtime_accepting_requests",
        "_lock",
        "_drained",
        "_grants",
        "_active",
        "_revoked",
        "_closed",
        "__weakref__",
    )

    def __init__(
        self,
        *,
        registry: BrokerRegistry,
        session_provider: AuthenticatingSessionProvider,
        adapters: dict[str, object],
        workspace_path: Path,
        rate_limiter: object | None,
        runtime_accepting_requests: Callable[[], bool],
    ) -> None:
        self._registry = registry
        self._provider = session_provider
        self._adapters = adapters
        self._workspace_path = workspace_path
        self._rate_limiter = rate_limiter
        self._runtime_accepting_requests = runtime_accepting_requests
        self._lock = threading.RLock()
        self._drained = threading.Condition(self._lock)
        self._grants: weakref.WeakKeyDictionary[_BrokerReadFacade, _Grant] = weakref.WeakKeyDictionary()
        self._active = 0
        self._revoked: weakref.WeakSet[_BrokerReadFacade] = weakref.WeakSet()
        self._closed = False

    def _resolve_target(
        self,
        target: ExactReadTarget | DataRoleReadTarget,
    ) -> tuple[BrokerSelector, BrokerDataRole | None, BrokerWorkspaceVersion | None]:
        if type(target) is ExactReadTarget:
            selector = target.selector
            return self._copy_selector(selector), None, None
        if type(target) is not DataRoleReadTarget:
            raise ValueError
        role = target.role
        if role is BrokerDataRole.QUOTE:
            canonical_role = BrokerDataRole.QUOTE
            role_name = "quote"
        elif role is BrokerDataRole.HISTORICAL:
            canonical_role = BrokerDataRole.HISTORICAL
            role_name = "historical"
        elif role is BrokerDataRole.OPTION_CHAINS:
            canonical_role = BrokerDataRole.OPTION_CHAINS
            role_name = "option_chains"
        elif role is BrokerDataRole.GLOBAL_INDICES:
            canonical_role = BrokerDataRole.GLOBAL_INDICES
            role_name = "global_indices"
        else:
            raise ValueError
        snapshot = read_workspace_snapshot(self._workspace_path)
        if type(snapshot.version) is not WorkspaceVersion:
            raise LookupError
        brokers = snapshot.config.get("brokers")
        data = brokers.get("data") if isinstance(brokers, Mapping) else None
        raw = data.get(role_name) if isinstance(data, Mapping) else None
        if type(raw) is not str or not raw:
            raise LookupError
        return parse_broker_selector(raw), canonical_role, broker_workspace_version(snapshot)

    def _verified_context(
        self, verifier: Callable[[], RequestContext | None], expected: RequestContext | None = None
    ) -> RequestContext:
        try:
            context = self._copy_context(verifier())
        except Exception:
            raise PermissionError from None
        if expected is not None and context != expected:
            raise PermissionError
        return context

    @staticmethod
    def _copy_context(context: object) -> RequestContext:
        if type(context) is not RequestContext:
            raise PermissionError
        jti = context.jti
        actor_type = context.actor_type
        actor_id = context.actor_id
        mode = context.mode
        intent_source = context.intent_source
        external_nonce_hash = context.external_nonce_hash
        selector = context.selector
        required = (jti, actor_type, actor_id, mode)
        optional = (intent_source, external_nonce_hash, selector)
        if any(type(value) is not str or not value for value in required):
            raise PermissionError
        if actor_type not in {"human", "agent", "external_intent"}:
            raise PermissionError
        if mode not in {"explore", "practice", "live"}:
            raise PermissionError
        if any(value is not None and type(value) is not str for value in optional):
            raise PermissionError
        if selector is None:
            raise PermissionError
        try:
            parse_broker_selector(selector)
        except ValueError:
            raise PermissionError from None
        return RequestContext(
            jti,
            actor_type,
            actor_id,
            mode,
            intent_source,
            external_nonce_hash,
            selector,
        )

    def _current_binding(
        self, selector: BrokerSelector
    ) -> SessionVersion | OpenAlgoDefaultCompatibilitySessionVersion:
        self._provider.current_authority_for(selector)
        state = self._registry.snapshot_exact_state(selector)
        if state is None or state.status != "connected" or state.binding is None:
            raise RegistrySessionUnavailable
        if type(state.binding) not in (SessionVersion, OpenAlgoDefaultCompatibilitySessionVersion):
            raise RegistrySessionUnavailable
        return state.binding

    @staticmethod
    def _copy_selector(selector: object) -> BrokerSelector:
        if type(selector) is not BrokerSelector:
            raise ValueError
        adapter_id = selector.adapter_id
        account_id = selector.account_id
        if type(adapter_id) is not str or not adapter_id or type(account_id) is not str or not account_id:
            raise ValueError
        return BrokerSelector(adapter_id, account_id)

    @staticmethod
    def _copy_instrument(instrument: object) -> InstrumentRef:
        if type(instrument) is not InstrumentRef:
            raise ValueError
        symbol = instrument.symbol
        exchange = instrument.exchange
        instrument_id = instrument.instrument_id
        return InstrumentRef(symbol, exchange, instrument_id)

    @staticmethod
    def _copy_portfolio_position(position: object) -> PortfolioPositionRef:
        if type(position) is not PortfolioPositionRef:
            raise ValueError
        symbol = position.symbol
        exchange = position.exchange
        quantity = position.quantity
        option_type = position.option_type
        instrument_id = position.instrument_id
        expiry = position.expiry
        strike_price = position.strike_price
        underlying = position.underlying
        return PortfolioPositionRef(
            symbol,
            exchange,
            quantity,
            option_type,
            instrument_id,
            expiry,
            strike_price,
            underlying,
        )

    @classmethod
    def _copy_request(cls, request: object, expected: type) -> object:
        if type(request) is not expected:
            raise ValueError
        if expected is QuoteRequest:
            instrument = request.instrument
            return QuoteRequest(cls._copy_instrument(instrument))
        if expected is HistoricalRequest:
            instrument = request.instrument
            interval = request.interval
            start_date = request.start_date
            end_date = request.end_date
            return HistoricalRequest(cls._copy_instrument(instrument), interval, start_date, end_date)
        if expected is BatchQuoteRequest:
            instruments = request.instruments
            if type(instruments) is not tuple:
                raise ValueError
            copied = tuple(cls._copy_instrument(instrument) for instrument in instruments)
            return BatchQuoteRequest(copied)
        if expected is OptionChainRequest:
            underlying = request.underlying
            expiry_date = request.expiry_date
            return OptionChainRequest(cls._copy_instrument(underlying), expiry_date)
        if expected is LotSizeRequest:
            exchange = request.exchange
            symbols = request.symbols
            if type(symbols) is not tuple:
                raise ValueError
            copied_symbols = tuple(symbol for symbol in symbols)
            return LotSizeRequest(exchange, copied_symbols)
        if expected is PortfolioGreeksRequest:
            positions = request.positions
            if type(positions) is not tuple:
                raise ValueError
            copied_positions = tuple(cls._copy_portfolio_position(position) for position in positions)
            return PortfolioGreeksRequest(copied_positions)
        if expected is MarginRequest:
            symbol = request.symbol
            exchange = request.exchange
            action = request.action
            quantity = request.quantity
            product = request.product
            pricetype = request.pricetype
            price = request.price
            trigger_price = request.trigger_price
            return MarginRequest(symbol, exchange, action, quantity, product, pricetype, price, trigger_price)
        if expected is OrderStateRequest:
            family = request.family
            order_id = request.order_id
            if family is BrokerOrderFamily.REGULAR:
                canonical_family = BrokerOrderFamily.REGULAR
            elif family is BrokerOrderFamily.FOREVER:
                canonical_family = BrokerOrderFamily.FOREVER
            elif family is BrokerOrderFamily.SUPER:
                canonical_family = BrokerOrderFamily.SUPER
            else:
                raise ValueError
            return OrderStateRequest(canonical_family, order_id)
        raise ValueError

    @staticmethod
    def _copy_uuid(value: object) -> UUID:
        if type(value) is not UUID:
            raise ValueError
        return UUID(bytes=value.bytes)

    @classmethod
    def _provenance(
        cls,
        binding: SessionVersion | OpenAlgoDefaultCompatibilitySessionVersion, role: BrokerDataRole | None
    ) -> BrokerReadProvenance:
        if type(binding) not in (SessionVersion, OpenAlgoDefaultCompatibilitySessionVersion):
            raise ValueError
        registry = binding.registry_version
        if type(registry) is not RegistrySelectorVersion:
            raise ValueError
        registry_copy = RegistrySelectorVersion(
            cls._copy_selector(registry.selector),
            cls._copy_uuid(registry.registry_incarnation),
            registry.generation,
            registry.present,
        )
        credential = None
        if type(binding) is SessionVersion:
            source_credential = binding.credential_version
            if type(source_credential) is not CredentialVersion:
                raise ValueError
            credential = CredentialVersion(
                cls._copy_selector(source_credential.selector),
                cls._copy_uuid(source_credential.vault_incarnation),
                source_credential.generation,
            )
        workspace = binding.workspace_version
        broker_workspace = binding.broker_workspace_version
        if type(workspace) is not WorkspaceVersion or type(broker_workspace) is not BrokerWorkspaceVersion:
            raise ValueError
        return BrokerReadProvenance(
            cls._copy_selector(binding.selector),
            registry_copy,
            credential,
            WorkspaceVersion(cls._copy_uuid(workspace.instance_id), workspace.generation),
            BrokerWorkspaceVersion(
                cls._copy_uuid(broker_workspace.instance_id),
                broker_workspace.generation,
            ),
            role,
        )

    def bind(
        self,
        *,
        target: ExactReadTarget | DataRoleReadTarget,
        verify_current_authority: Callable[[], RequestContext | None],
    ) -> BrokerReadPort | BrokerReadFailure:
        with self._lock:
            if self._closed:
                return BrokerReadFailure(BrokerReadErrorCode.REVOKED)
        if not callable(verify_current_authority):
            return BrokerReadFailure(BrokerReadErrorCode.UNAUTHORISED)
        try:
            if self._runtime_accepting_requests() is not True:
                return BrokerReadFailure(BrokerReadErrorCode.REVOKED)
            selector, role, resolved_broker_workspace_version = self._resolve_target(target)
            context = self._verified_context(verify_current_authority)
            if parse_broker_selector(context.selector) != selector:
                return BrokerReadFailure(BrokerReadErrorCode.UNAUTHORISED)
            binding = self._current_binding(selector)
            handle = self._provider(context, selector.adapter_id, selector.account_id)
            if type(handle) is not ConnectedRegistrySession or handle.version != binding:
                return BrokerReadFailure(BrokerReadErrorCode.TARGET_STALE)
            if role is not None:
                try:
                    current_selector, _, current_broker_workspace_version = self._resolve_target(
                        DataRoleReadTarget(role)
                    )
                except (LookupError, ValueError):
                    return BrokerReadFailure(BrokerReadErrorCode.TARGET_STALE)
                if (
                    current_selector != selector
                    or current_broker_workspace_version != resolved_broker_workspace_version
                    or current_broker_workspace_version != binding.broker_workspace_version
                ):
                    return BrokerReadFailure(BrokerReadErrorCode.TARGET_STALE)
            else:
                snapshot = read_workspace_snapshot(self._workspace_path)
                if broker_workspace_version(snapshot) != binding.broker_workspace_version:
                    return BrokerReadFailure(BrokerReadErrorCode.TARGET_STALE)
        except (PermissionError, SafetyBypassError):
            return BrokerReadFailure(BrokerReadErrorCode.UNAUTHORISED)
        except (LookupError, ValueError):
            return BrokerReadFailure(BrokerReadErrorCode.TARGET_UNAVAILABLE)
        except RegistrySessionUnavailable:
            return BrokerReadFailure(BrokerReadErrorCode.DISCONNECTED)
        except Exception:
            return BrokerReadFailure(BrokerReadErrorCode.TARGET_UNAVAILABLE)
        facade = _BrokerReadFacade()
        grant = _Grant(
            selector,
            role,
            binding,
            context,
            verify_current_authority,
            _ALL_OPERATIONS if role is None else _ROLE_OPERATIONS[role],
        )
        with self._lock:
            if self._closed:
                return BrokerReadFailure(BrokerReadErrorCode.REVOKED)
            try:
                if self._runtime_accepting_requests() is not True:
                    return BrokerReadFailure(BrokerReadErrorCode.REVOKED)
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.REVOKED)
            self._grants[facade] = grant
            with _FACADE_LOCK:
                _FACADE_OWNERS[facade] = weakref.ref(self)
        return facade

    def revoke(self, port: object) -> bool:
        if type(port) is not _BrokerReadFacade:
            return False
        with self._lock:
            grant = self._grants.pop(port, None)
            if grant is None:
                return port in self._revoked
            grant.revoked = True
            grant.verify_current_authority = None
            self._revoked.add(port)
            with _FACADE_LOCK:
                _FACADE_OWNERS.pop(port, None)
        return True

    def close(self, *, timeout: float = 0.0) -> bool:
        if type(timeout) not in (int, float) or isinstance(timeout, bool) or not math.isfinite(timeout) or timeout < 0:
            return False
        deadline = time.monotonic() + float(timeout)
        with self._lock:
            self._closed = True
            facades = tuple(self._grants)
            grants = tuple(self._grants.values())
            for grant in grants:
                grant.revoked = True
                grant.verify_current_authority = None
            self._grants.clear()
            self._revoked.update(facades)
            while self._active:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._drained.wait(remaining)
            drained = self._active == 0
            with _FACADE_LOCK:
                for facade in facades:
                    _FACADE_OWNERS.pop(facade, None)
        return drained

    def _begin(self, facade: _BrokerReadFacade, operation: _Operation, request: object, expected: type | None) -> _Grant | BrokerReadFailure:
        if expected is not None and type(request) is not expected:
            return BrokerReadFailure(BrokerReadErrorCode.INVALID_REQUEST)
        with self._lock:
            grant = self._grants.get(facade)
            if self._closed or grant is None or grant.revoked:
                return BrokerReadFailure(BrokerReadErrorCode.REVOKED)
            if operation not in grant.allowed:
                return BrokerReadFailure(BrokerReadErrorCode.UNAUTHORISED)
            grant.active += 1
            self._active += 1
            return grant

    def _end(self, grant: _Grant) -> None:
        with self._lock:
            grant.active -= 1
            self._active -= 1
            self._drained.notify_all()

    def _revalidate(self, grant: _Grant) -> ConnectedRegistrySession | BrokerReadFailure:
        with self._lock:
            if self._closed or grant.revoked or grant.verify_current_authority is None:
                return BrokerReadFailure(BrokerReadErrorCode.REVOKED)
            verifier = grant.verify_current_authority
        try:
            if self._runtime_accepting_requests() is not True:
                return BrokerReadFailure(BrokerReadErrorCode.REVOKED)
            context = self._verified_context(verifier, grant.context)
            if parse_broker_selector(context.selector) != grant.selector:
                return BrokerReadFailure(BrokerReadErrorCode.UNAUTHORISED)
            if grant.role is not None:
                try:
                    selector, _, resolved_broker_workspace_version = self._resolve_target(
                        DataRoleReadTarget(grant.role)
                    )
                except (LookupError, ValueError):
                    return BrokerReadFailure(BrokerReadErrorCode.TARGET_STALE)
                if (
                    selector != grant.selector
                    or resolved_broker_workspace_version != grant.binding.broker_workspace_version
                ):
                    return BrokerReadFailure(BrokerReadErrorCode.TARGET_STALE)
            else:
                snapshot = read_workspace_snapshot(self._workspace_path)
                if broker_workspace_version(snapshot) != grant.binding.broker_workspace_version:
                    return BrokerReadFailure(BrokerReadErrorCode.TARGET_STALE)
            if self._current_binding(grant.selector) != grant.binding:
                return BrokerReadFailure(BrokerReadErrorCode.TARGET_STALE)
            handle = self._provider(context, grant.selector.adapter_id, grant.selector.account_id)
            if type(handle) is not ConnectedRegistrySession or handle.version != grant.binding:
                return BrokerReadFailure(BrokerReadErrorCode.TARGET_STALE)
        except (PermissionError, SafetyBypassError):
            return BrokerReadFailure(BrokerReadErrorCode.UNAUTHORISED)
        except RegistrySessionUnavailable:
            return BrokerReadFailure(BrokerReadErrorCode.DISCONNECTED)
        except Exception:
            return BrokerReadFailure(BrokerReadErrorCode.UNAUTHORISED)
        with self._lock:
            if self._closed or grant.revoked or grant.verify_current_authority is not verifier:
                return BrokerReadFailure(BrokerReadErrorCode.REVOKED)
        return handle

    async def _admit_provider(
        self,
        grant: _Grant,
        capability: str | tuple[str, ...],
    ) -> _ProviderCall | BrokerReadFailure:
        first = self._revalidate(grant)
        if type(first) is BrokerReadFailure:
            return first
        adapter = self._adapters.get(grant.selector.adapter_id)
        capabilities = (capability,) if type(capability) is str else capability
        if adapter is None or type(capabilities) is not tuple or not capabilities:
            return BrokerReadFailure(BrokerReadErrorCode.UNSUPPORTED)
        adapter_type = type(adapter)
        marker = frozenset()
        if "_BROKER_READ_UNSUPPORTED" in adapter_type.__dict__:
            candidate_marker = inspect.getattr_static(adapter_type, "_BROKER_READ_UNSUPPORTED")
            if (
                type(candidate_marker) is not frozenset
                or any(type(value) is not str for value in candidate_marker)
            ):
                return BrokerReadFailure(BrokerReadErrorCode.UNSUPPORTED)
            marker = candidate_marker
        selected: str | None = None
        for candidate in capabilities:
            if type(candidate) is not str or not candidate or candidate in marker:
                return BrokerReadFailure(BrokerReadErrorCode.UNSUPPORTED)
            static_method = inspect.getattr_static(adapter, candidate, None)
            if callable(static_method):
                selected = candidate
                break
        if selected is None:
            return BrokerReadFailure(BrokerReadErrorCode.UNSUPPORTED)
        if self._rate_limiter is not None:
            try:
                await self._rate_limiter.acquire(grant.selector.adapter_id, "data")
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
        second = self._revalidate(grant)
        if type(second) is BrokerReadFailure:
            return second
        try:
            method = getattr(adapter, selected)
        except Exception:
            return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
        if not callable(method):
            return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
        return _ProviderCall(second, method)

    @staticmethod
    def _number(value: object) -> float | None:
        if type(value) in (int, float) and not isinstance(value, bool):
            result = float(value)
        elif type(value) is str and value.strip():
            try:
                result = float(value)
            except ValueError:
                return None
        else:
            return None
        return result if math.isfinite(result) else None

    @classmethod
    def _quote_snapshot(cls, raw: object, request: QuoteRequest, *, allow_missing: bool = False) -> QuoteSnapshot:
        raw = cls._record(raw, Quote)
        symbol = cls._text(raw, "symbol")
        exchange = cls._text(raw, "exchange")
        if symbol is not None and symbol != request.instrument.symbol:
            raise ValueError
        if exchange is not None and exchange != request.instrument.exchange:
            raise ValueError
        available = raw.get("available", True)
        if type(available) is not bool:
            raise ValueError
        if not available and not allow_missing:
            raise ValueError
        optional_fields = (
            "ltp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "bid",
            "ask",
            "prev_close",
            "previous_close_trusted",
            "previous_close_as_of",
            "oi",
        )
        if not available:
            if any(name in raw for name in optional_fields):
                raise ValueError
            return QuoteSnapshot(
                request.instrument,
                False,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            )

        def number(name: str) -> float | None:
            value = raw.get(name)
            if value is None:
                return None
            converted = cls._number(value)
            if converted is None:
                raise ValueError
            return converted

        def integer(name: str) -> int | None:
            value = number(name)
            if value is None:
                return None
            if not value.is_integer():
                raise ValueError
            return int(value)

        numeric = (
            number("ltp"),
            number("open"),
            number("high"),
            number("low"),
            number("close"),
            integer("volume"),
            number("bid"),
            number("ask"),
            number("prev_close"),
            integer("oi"),
        )
        if all(value is None for value in numeric):
            raise ValueError
        return QuoteSnapshot(
            request.instrument,
            available,
            *numeric[:9],
            cls._boolean(raw, "previous_close_trusted"),
            cls._text(raw, "previous_close_as_of"),
            numeric[9],
        )

    @staticmethod
    def _record(raw: object, *model_types: type) -> dict[str, object]:
        if type(raw) is dict:
            record = raw
        elif type(raw) in model_types:
            record = raw.model_dump(exclude_unset=True)
        else:
            raise ValueError
        if type(record) is not dict or any(type(key) is not str for key in record):
            raise ValueError
        return record

    @classmethod
    def _text(cls, raw: dict[str, object], name: str, *, required: bool = False) -> str | None:
        value = raw.get(name)
        if value is None:
            if required:
                raise ValueError
            return None
        if type(value) is not str:
            raise ValueError
        if value == "":
            if required:
                raise ValueError
            return None
        return value

    @staticmethod
    def _number_text(
        raw: dict[str, object],
        *names: str,
        required: bool = False,
    ) -> str | None:
        for name in names:
            if name not in raw or raw[name] is None:
                continue
            value = raw[name]
            if type(value) is int:
                text = str(value)
            elif type(value) is float:
                if not math.isfinite(value):
                    raise ValueError
                text = str(value)
            elif type(value) is str:
                if not value or not value.strip():
                    raise ValueError
                text = value.encode("utf-8").decode("utf-8")
            else:
                raise ValueError
            try:
                number = Decimal(text)
            except InvalidOperation:
                raise ValueError from None
            if not number.is_finite():
                raise ValueError
            return text
        if required:
            raise ValueError
        return None

    @classmethod
    def _numeric(cls, raw: dict[str, object], name: str, *, required: bool = False) -> float | None:
        value = raw.get(name)
        if value is None:
            if required:
                raise ValueError
            return None
        if type(value) is str and value == "":
            if required:
                raise ValueError
            return None
        number = cls._number(value)
        if number is None:
            raise ValueError
        return number

    @classmethod
    def _text_alias(cls, raw: dict[str, object], *names: str, required: bool = False) -> str | None:
        values: list[str] = []
        for name in names:
            if name not in raw:
                continue
            value = raw[name]
            if value is None:
                continue
            if type(value) is not str:
                raise ValueError
            if value == "":
                continue
            values.append(value)
        if not values:
            if required:
                raise ValueError
            return None
        selected = values[0]
        if any(value != selected for value in values[1:]):
            raise ValueError
        return selected

    @classmethod
    def _first_text(cls, raw: dict[str, object], *names: str) -> str | None:
        for name in names:
            if name not in raw:
                continue
            value = raw[name]
            if value is None:
                continue
            if type(value) is not str:
                raise ValueError
            if value != "":
                return value
        return None

    @classmethod
    def _integer_field(cls, raw: dict[str, object], name: str, *, required: bool = False) -> int | None:
        number = cls._numeric(raw, name, required=required)
        if number is None:
            return None
        if not number.is_integer():
            raise ValueError
        return int(number)

    @staticmethod
    def _boolean(raw: dict[str, object], name: str) -> bool | None:
        value = raw.get(name)
        if value is None:
            return None
        if type(value) is not bool:
            raise ValueError
        return value

    def _published(self, grant: _Grant, copied: object):
        current = self._revalidate(grant)
        if type(current) is BrokerReadFailure:
            return current
        with self._lock:
            if self._closed or grant.revoked or grant.verify_current_authority is None:
                return BrokerReadFailure(BrokerReadErrorCode.REVOKED)
            try:
                return BrokerReadSuccess(self._provenance(grant.binding, grant.role), copied)
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.TARGET_STALE)

    async def _quote(self, facade: _BrokerReadFacade, request: QuoteRequest):
        try:
            request = self._copy_request(request, QuoteRequest)
        except Exception:
            return BrokerReadFailure(BrokerReadErrorCode.INVALID_REQUEST)
        grant = self._begin(facade, _Operation.QUOTE, request, QuoteRequest)
        if type(grant) is BrokerReadFailure:
            return grant
        try:
            call = await self._admit_provider(grant, "quotes")
            if type(call) is BrokerReadFailure:
                return call
            try:
                raw = await call.method(
                    call.handle,
                    [f"{request.instrument.exchange}:{request.instrument.symbol}"],
                )
            except BrokerReadResponseInvalid:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
            try:
                if type(raw) is not list or len(raw) != 1:
                    raise ValueError
                copied = self._quote_snapshot(raw[0], request)
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            return self._published(grant, copied)
        finally:
            self._end(grant)

    async def _depth(self, facade: _BrokerReadFacade, request: QuoteRequest):
        try:
            request = self._copy_request(request, QuoteRequest)
        except Exception:
            return BrokerReadFailure(BrokerReadErrorCode.INVALID_REQUEST)
        grant = self._begin(facade, _Operation.DEPTH, request, QuoteRequest)
        if type(grant) is BrokerReadFailure:
            return grant
        try:
            call = await self._admit_provider(grant, "depth")
            if type(call) is BrokerReadFailure:
                return call
            try:
                raw_result = await call.method(call.handle, request)
            except BrokerReadResponseInvalid:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
            try:
                raw = self._record(raw_result, Depth)
                symbol = self._text(raw, "symbol")
                exchange = self._text(raw, "exchange")
                if (symbol is not None and symbol != request.instrument.symbol) or (
                    exchange is not None and exchange != request.instrument.exchange
                ):
                    raise ValueError

                def levels(name: str) -> tuple[DepthLevelSnapshot, ...]:
                    rows = raw.get(name)
                    if type(rows) is not list:
                        raise ValueError
                    return tuple(
                        DepthLevelSnapshot(
                            self._numeric(row := self._record(item), "price", required=True),
                            self._integer_field(row, "quantity", required=True),
                            self._integer_field(row, "orders"),
                        )
                        for item in rows
                    )

                copied = DepthSnapshot(request.instrument, levels("bids"), levels("asks"))
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            return self._published(grant, copied)
        finally:
            self._end(grant)

    async def _historical(self, facade: _BrokerReadFacade, request: HistoricalRequest):
        try:
            request = self._copy_request(request, HistoricalRequest)
        except Exception:
            return BrokerReadFailure(BrokerReadErrorCode.INVALID_REQUEST)
        grant = self._begin(facade, _Operation.HISTORICAL, request, HistoricalRequest)
        if type(grant) is BrokerReadFailure:
            return grant
        try:
            call = await self._admit_provider(grant, "historical")
            if type(call) is BrokerReadFailure:
                return call
            provider_request = {
                "symbol": request.instrument.symbol,
                "exchange": request.instrument.exchange,
                "interval": request.interval,
                "start_date": request.start_date,
                "end_date": request.end_date,
            }
            try:
                raw_result = await call.method(call.handle, provider_request)
            except BrokerReadResponseInvalid:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
            try:
                raw = self._record(raw_result, Candles)
                if (
                    self._text(raw, "symbol", required=True) != request.instrument.symbol
                    or self._text(raw, "exchange", required=True) != request.instrument.exchange
                    or self._text(raw, "interval", required=True) != request.interval
                    or type(raw.get("bars")) is not list
                ):
                    raise ValueError
                bars = tuple(
                    CandleSnapshot(
                        self._text(row := self._record(item, OHLCV), "timestamp", required=True),
                        self._numeric(row, "open", required=True),
                        self._numeric(row, "high", required=True),
                        self._numeric(row, "low", required=True),
                        self._numeric(row, "close", required=True),
                        self._integer_field(row, "volume"),
                    )
                    for item in raw["bars"]
                )
                copied = HistoricalSnapshot(request.instrument, request.interval, bars)
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            return self._published(grant, copied)
        finally:
            self._end(grant)

    async def _batch_quotes(self, facade: _BrokerReadFacade, request: BatchQuoteRequest):
        try:
            request = self._copy_request(request, BatchQuoteRequest)
        except Exception:
            return BrokerReadFailure(BrokerReadErrorCode.INVALID_REQUEST)
        grant = self._begin(facade, _Operation.BATCH_QUOTES, request, BatchQuoteRequest)
        if type(grant) is BrokerReadFailure:
            return grant
        try:
            identities = {(item.exchange, item.symbol) for item in request.instruments}
            if len(identities) != len(request.instruments):
                return BrokerReadFailure(BrokerReadErrorCode.INVALID_REQUEST)
            call = await self._admit_provider(grant, "quotes")
            if type(call) is BrokerReadFailure:
                return call
            try:
                raw = await call.method(
                    call.handle,
                    [f"{item.exchange}:{item.symbol}" for item in request.instruments],
                )
            except BrokerReadResponseInvalid:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
            try:
                if type(raw) is not list or len(raw) != len(request.instruments):
                    raise ValueError
                by_identity: dict[tuple[str, str], object] = {}
                for item in raw:
                    row = self._record(item, Quote)
                    identity = (
                        self._text(row, "exchange", required=True),
                        self._text(row, "symbol", required=True),
                    )
                    if identity not in identities or identity in by_identity:
                        raise ValueError
                    by_identity[identity] = item
                copied = tuple(
                    self._quote_snapshot(
                        by_identity[(item.exchange, item.symbol)],
                        QuoteRequest(item),
                        allow_missing=True,
                    )
                    for item in request.instruments
                )
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            return self._published(grant, copied)
        finally:
            self._end(grant)

    async def _option_chain(self, facade: _BrokerReadFacade, request: OptionChainRequest):
        try:
            request = self._copy_request(request, OptionChainRequest)
        except Exception:
            return BrokerReadFailure(BrokerReadErrorCode.INVALID_REQUEST)
        grant = self._begin(facade, _Operation.OPTION_CHAIN, request, OptionChainRequest)
        if type(grant) is BrokerReadFailure:
            return grant
        try:
            call = await self._admit_provider(grant, "option_chain")
            if type(call) is BrokerReadFailure:
                return call
            try:
                raw_result = await call.method(
                    call.handle,
                    {
                        "symbol": request.underlying.symbol,
                        "exchange": request.underlying.exchange,
                        "expiry": request.expiry_date,
                    },
                )
            except BrokerReadResponseInvalid:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
            try:
                raw = self._record(raw_result, OptionChain)
                if (
                    self._text(raw, "underlying", required=True) != request.underlying.symbol
                    or self._text(raw, "exchange", required=True) != request.underlying.exchange
                ):
                    raise ValueError
                expiry = self._text_alias(raw, "expiry", "expiry_date", required=True)
                if expiry != request.expiry_date or type(raw.get("strikes")) is not list:
                    raise ValueError
                underlying_id = self._text(raw, "underlying_key")
                if (
                    request.underlying.instrument_id is not None
                    and underlying_id is not None
                    and underlying_id != request.underlying.instrument_id
                ):
                    raise ValueError
                if underlying_id is None:
                    underlying_id = request.underlying.instrument_id
                strikes = tuple(self._option_strike(item) for item in raw["strikes"])
                if len({strike.strike_price for strike in strikes}) != len(strikes):
                    raise ValueError
                copied = OptionChainSnapshot(
                    InstrumentRef(request.underlying.symbol, request.underlying.exchange, underlying_id),
                    expiry,
                    self._numeric(raw, "spot_price"),
                    strikes,
                )
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            return self._published(grant, copied)
        finally:
            self._end(grant)

    def _option_strike(self, item: object):
        row = self._record(item)
        return OptionChainStrikeSnapshot(
            self._numeric(row, "strike_price", required=True),
            self._text(row, "ce_instrument_id"), self._numeric(row, "ce_ltp"), self._integer_field(row, "ce_oi"),
            self._integer_field(row, "ce_volume"), self._numeric(row, "ce_iv"), self._numeric(row, "ce_delta"),
            self._numeric(row, "ce_gamma"), self._numeric(row, "ce_theta"), self._numeric(row, "ce_vega"),
            self._numeric(row, "ce_bid"), self._numeric(row, "ce_ask"), self._boolean(row, "ce_greeks_complete"),
            self._text(row, "pe_instrument_id"), self._numeric(row, "pe_ltp"), self._integer_field(row, "pe_oi"),
            self._integer_field(row, "pe_volume"), self._numeric(row, "pe_iv"), self._numeric(row, "pe_delta"),
            self._numeric(row, "pe_gamma"), self._numeric(row, "pe_theta"), self._numeric(row, "pe_vega"),
            self._numeric(row, "pe_bid"), self._numeric(row, "pe_ask"), self._boolean(row, "pe_greeks_complete"),
        )

    async def _lot_sizes(self, facade: _BrokerReadFacade, request: LotSizeRequest):
        try:
            request = self._copy_request(request, LotSizeRequest)
        except Exception:
            return BrokerReadFailure(BrokerReadErrorCode.INVALID_REQUEST)
        grant = self._begin(facade, _Operation.LOT_SIZES, request, LotSizeRequest)
        if type(grant) is BrokerReadFailure:
            return grant
        try:
            call = await self._admit_provider(grant, "instrument_lot_sizes")
            if type(call) is BrokerReadFailure:
                return call
            try:
                raw = await call.method(call.handle, request)
            except BrokerReadResponseInvalid:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
            try:
                if type(raw) is not list:
                    raise ValueError
                expected = set(request.symbols)
                seen: dict[str, tuple[int, str | None]] = {}
                copied_rows = []
                for item in raw:
                    row = self._record(item)
                    symbol = self._text(row, "symbol", required=True)
                    exchange = self._text(row, "exchange", required=True)
                    lot_size = self._integer_field(row, "lot_size", required=True)
                    instrument_id = self._text(row, "instrument_id")
                    if exchange != request.exchange or (expected and symbol not in expected):
                        raise ValueError
                    fingerprint = (lot_size, instrument_id)
                    if symbol in seen and seen[symbol] != fingerprint:
                        raise ValueError
                    if symbol in seen:
                        continue
                    seen[symbol] = fingerprint
                    copied_rows.append(InstrumentLotSizeSnapshot(symbol, exchange, lot_size, instrument_id))
                if expected and set(seen) != expected:
                    raise ValueError
                copied = tuple(copied_rows)
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            return self._published(grant, copied)
        finally:
            self._end(grant)

    async def _balance(self, facade: _BrokerReadFacade):
        grant = self._begin(facade, _Operation.BALANCE, None, None)
        if type(grant) is BrokerReadFailure:
            return grant
        try:
            call = await self._admit_provider(grant, "balance_snapshot")
            if type(call) is BrokerReadFailure:
                return call
            try:
                raw = await call.method(call.handle)
            except BrokerReadResponseInvalid:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
            try:
                if type(raw) is not BalanceSnapshot:
                    raise ValueError
                copied = BalanceSnapshot(*(getattr(raw, field) for field in raw.__slots__))
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            return self._published(grant, copied)
        finally:
            self._end(grant)

    async def _portfolio_greeks(self, facade: _BrokerReadFacade, request: PortfolioGreeksRequest):
        try:
            request = self._copy_request(request, PortfolioGreeksRequest)
        except Exception:
            return BrokerReadFailure(BrokerReadErrorCode.INVALID_REQUEST)
        grant = self._begin(facade, _Operation.PORTFOLIO_GREEKS, request, PortfolioGreeksRequest)
        if type(grant) is BrokerReadFailure:
            return grant
        try:
            call = await self._admit_provider(grant, "portfolio_greeks")
            if type(call) is BrokerReadFailure:
                return call
            positions = [
                {
                    "symbol": item.symbol, "exchange": item.exchange, "quantity": item.quantity,
                    "option_type": item.option_type, "instrument_id": item.instrument_id,
                    "expiry": item.expiry, "strike_price": item.strike_price, "underlying": item.underlying,
                }
                for item in request.positions
            ]
            try:
                raw = await call.method(call.handle, positions)
            except BrokerReadResponseInvalid:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
            try:
                if type(raw) is not list or len(raw) != len(request.positions):
                    raise ValueError
                copied = self._portfolio_rows(raw, request.positions, grant.selector.adapter_id == "openalgo")
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            return self._published(grant, copied)
        finally:
            self._end(grant)

    def _portfolio_rows(self, raw: list[object], requested: tuple[PortfolioPositionRef, ...], openalgo: bool):
        expected = {(item.exchange, item.symbol): item for item in requested}
        if len(expected) != len(requested):
            raise ValueError
        seen_ids: set[str] = set()
        copied = []
        for item in raw:
            row = self._record(item)
            symbol = self._text(row, "symbol", required=True)
            exchange = self._text(row, "exchange", required=True)
            expected_row = expected.get((exchange, symbol))
            if expected_row is None:
                raise ValueError
            instrument_id = self._text(row, "instrument_id")
            if expected_row.instrument_id is not None and instrument_id != expected_row.instrument_id:
                raise ValueError
            if expected_row.instrument_id is None and not openalgo and instrument_id is None:
                raise ValueError
            if instrument_id is not None:
                if instrument_id in seen_ids:
                    raise ValueError
                seen_ids.add(instrument_id)
            copied.append(
                PortfolioGreekSnapshot(symbol, exchange, instrument_id, self._numeric(row, "delta", required=True), self._numeric(row, "vega", required=True))
            )
            expected.pop((exchange, symbol))
        if expected:
            raise ValueError
        return tuple(copied)

    async def _positions(self, facade: _BrokerReadFacade):
        grant = self._begin(facade, _Operation.POSITIONS, None, None)
        if type(grant) is BrokerReadFailure:
            return grant
        try:
            call = await self._admit_provider(grant, "positions")
            if type(call) is BrokerReadFailure:
                return call
            try:
                raw = await call.method(call.handle)
            except BrokerReadResponseInvalid:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
            try:
                if type(raw) is not list:
                    raise ValueError
                copied = tuple(self._position(item) for item in raw)
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            return self._published(grant, copied)
        finally:
            self._end(grant)

    def _position(self, item: object) -> PositionSnapshot:
        row = self._record(item, Position)
        return PositionSnapshot(
            self._text(row, "symbol", required=True), self._text(row, "instrument_id"),
            self._text(row, "exchange", required=True), self._text(row, "product", required=True),
            self._number_text(row, "quantity", required=True), self._number_text(row, "average_price"),
            self._number_text(row, "ltp"), self._number_text(row, "pnl"),
            self._number_text(row, "buy_quantity"), self._number_text(row, "sell_quantity"),
            self._number_text(row, "buy_avg"), self._number_text(row, "sell_avg"), self._numeric(row, "multiplier"),
            self._numeric(row, "fx_rate"), self._numeric(row, "close_price"), self._boolean(row, "previous_close_trusted"),
            self._boolean(row, "cross_currency"), self._number_text(row, "overnight_quantity"),
            self._number_text(row, "day_buy_quantity"), self._number_text(row, "day_sell_quantity"),
            self._number_text(row, "carry_forward_buy_quantity"),
            self._number_text(row, "carry_forward_sell_quantity"), self._boolean(row, "accounting_complete"),
            self._text(row, "option_type"), self._text(row, "expiry"), self._numeric(row, "strike_price"),
            self._text(row, "underlying"),
        )

    async def _holdings(self, facade: _BrokerReadFacade):
        grant = self._begin(facade, _Operation.HOLDINGS, None, None)
        if type(grant) is BrokerReadFailure:
            return grant
        try:
            call = await self._admit_provider(grant, "holdings")
            if type(call) is BrokerReadFailure:
                return call
            try:
                raw = await call.method(call.handle)
            except BrokerReadResponseInvalid:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
            try:
                if type(raw) is not list:
                    raise ValueError
                copied = tuple(self._holding(item) for item in raw)
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            return self._published(grant, copied)
        finally:
            self._end(grant)

    def _holding(self, item: object) -> HoldingSnapshot:
        row = self._record(item, Holding)
        return HoldingSnapshot(
            self._text(row, "symbol", required=True), self._text(row, "instrument_id"),
            self._text(row, "exchange", required=True), self._text(row, "product"),
            self._number_text(row, "quantity", required=True), self._number_text(row, "average_price"),
            self._number_text(row, "ltp"), self._number_text(row, "pnl"), self._number_text(row, "pnl_percent"),
            self._numeric(row, "multiplier"),
            self._numeric(row, "fx_rate"), self._numeric(row, "close_price"), self._boolean(row, "previous_close_trusted"),
            self._boolean(row, "cross_currency"), self._number_text(row, "settled_quantity"),
            self._number_text(row, "t1_quantity"),
            self._boolean(row, "accounting_complete"),
        )

    async def _margin(self, facade: _BrokerReadFacade, request: MarginRequest):
        try:
            request = self._copy_request(request, MarginRequest)
            order = Order(
                symbol=request.symbol,
                action=request.action,
                exchange=request.exchange,
                quantity=request.quantity,
                product=request.product,
                pricetype=request.pricetype,
                price=request.price,
                trigger_price=request.trigger_price,
            )
        except Exception:
            return BrokerReadFailure(BrokerReadErrorCode.INVALID_REQUEST)
        grant = self._begin(facade, _Operation.MARGIN, request, MarginRequest)
        if type(grant) is BrokerReadFailure:
            return grant
        try:
            call = await self._admit_provider(grant, "margin_calculator")
            if type(call) is BrokerReadFailure:
                return call
            try:
                raw_result = await call.method(call.handle, order)
            except BrokerReadResponseInvalid:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
            try:
                raw = self._record(raw_result)
                if "data" in raw:
                    raw = self._record(raw["data"])
                selected = None
                for name in ("required_margin", "total_margin_required", "total_margin", "final_margin", "order_margin", "margin"):
                    if name not in raw:
                        continue
                    value = raw[name]
                    if value is None or (type(value) is str and value == ""):
                        continue
                    selected = self._numeric(raw, name, required=True)
                    break
                if selected is None or selected < 0:
                    raise ValueError
                copied = MarginSnapshot(selected)
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            return self._published(grant, copied)
        finally:
            self._end(grant)

    async def _order_states(self, facade: _BrokerReadFacade, request: OrderStateRequest):
        try:
            request = self._copy_request(request, OrderStateRequest)
        except Exception:
            return BrokerReadFailure(BrokerReadErrorCode.INVALID_REQUEST)
        grant = self._begin(facade, _Operation.ORDER_STATES, request, OrderStateRequest)
        if type(grant) is BrokerReadFailure:
            return grant
        try:
            if request.family is BrokerOrderFamily.REGULAR:
                capability: str | tuple[str, ...] = ("safety_order_book", "order_book")
            elif request.family is BrokerOrderFamily.FOREVER:
                capability = "forever_orders"
            else:
                capability = "super_orders"
            call = await self._admit_provider(grant, capability)
            if type(call) is BrokerReadFailure:
                return call
            try:
                raw = await call.method(call.handle)
            except BrokerReadResponseInvalid:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
            try:
                if type(raw) is not list:
                    raise ValueError
                all_rows = tuple(self._order_state(item, request.family) for item in raw)
                active_rows = [
                    row
                    for row in all_rows
                    if row.status.lower() not in _TERMINAL_ORDER_STATUSES
                ]
                if any(
                    value is None
                    for row in active_rows
                    for value in (row.orderid, row.symbol, row.exchange, row.action, row.product, row.quantity)
                ):
                    raise ValueError
                if any(
                    row.filled_quantity is None
                    and not (
                        (
                            row.family is BrokerOrderFamily.FOREVER
                            or row.order_family is BrokerOrderSourceFamily.FOREVER
                        )
                        and row.status.upper() in _FOREVER_PRE_TRIGGER_STATUSES
                    )
                    for row in active_rows
                ):
                    raise ValueError
                active_ids = [row.orderid for row in active_rows]
                if any(identity is None for identity in active_ids) or len(set(active_ids)) != len(active_ids):
                    raise ValueError
                copied = all_rows
                if request.order_id is not None:
                    copied = tuple(row for row in all_rows if row.orderid == request.order_id)
                    if len(copied) != 1:
                        raise ValueError
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            return self._published(grant, copied)
        finally:
            self._end(grant)

    def _order_state(self, item: object, family: BrokerOrderFamily) -> OrderStateSnapshot:
        row = self._record(item, OrderStatus, GttTrigger)
        if type(item) is GttTrigger:
            row = {
                **row,
                "orderid": self._text(row, "trigger_id"),
                "order_flag": self._text(row, "trigger_type"),
                "trigger_price": self._number_text(row, "triggerprice_tg", "triggerprice_sl"),
            }
        raw_family = self._text(row, "order_family")
        source_family = BrokerOrderSourceFamily(raw_family.lower()) if raw_family is not None else None
        if "legs" in row and "leg_details" in row:
            raise ValueError
        legs_raw = row["legs"] if "legs" in row else row["leg_details"] if "leg_details" in row else []
        if type(legs_raw) is not list:
            raise ValueError
        legs_list = []
        leg_names: set[str] = set()
        for child in legs_raw:
            leg = self._record(child)
            leg_name = self._text_alias(leg, "leg_name", "legName", required=True).upper()
            if leg_name in leg_names:
                raise ValueError
            leg_names.add(leg_name)
            legs_list.append(
                OrderLegStateSnapshot(
                    leg_name,
                    self._text_alias(leg, "status", "orderStatus"),
                    self._text_alias(leg, "order_id", "orderId"),
                    self._text_alias(leg, "exchange_order_id", "exchangeOrderId"),
                    self._number_text(leg, "quantity"),
                    self._number_text(leg, "filled_quantity", "filledQty"),
                    self._number_text(leg, "price"),
                    self._number_text(leg, "trigger_price", "triggerPrice"),
                )
            )
        order_flag = self._text(row, "order_flag")
        if order_flag is not None:
            order_flag = order_flag.upper()
        if family is BrokerOrderFamily.FOREVER and order_flag == "OCO":
            if row.get("oco_leg_complete") is not True:
                raise ValueError
            if "STOP_LOSS_LEG" in leg_names:
                raise ValueError
            leg_names.add("STOP_LOSS_LEG")
            legs_list.append(
                OrderLegStateSnapshot(
                    "STOP_LOSS_LEG",
                    None,
                    None,
                    None,
                    self._number_text(row, "quantity1", required=True),
                    None,
                    self._number_text(row, "price1", required=True),
                    self._number_text(row, "trigger_price1", required=True),
                )
            )
        legs = tuple(legs_list)
        return OrderStateSnapshot(
            family, source_family, self._text_alias(row, "orderid", "order_id"),
            self._text(row, "status", required=True), self._text(row, "symbol"), self._text(row, "instrument_id"),
            self._text(row, "exchange"), self._text(row, "action"), self._text(row, "product"),
            self._number_text(row, "quantity"), self._number_text(row, "filled_quantity"), self._text(row, "pricetype"),
            self._number_text(row, "price"), self._number_text(row, "trigger_price"),
            self._number_text(row, "disclosed_quantity"),
            self._text(row, "option_type"), self._text(row, "expiry"), self._numeric(row, "strike_price"),
            self._text(row, "underlying"), self._text(row, "safety_order_id"), self._text(row, "broker_order_id"),
            self._text(row, "raw_broker_order_id"), self._text(row, "parent_order_id"), self._text(row, "exchange_order_id"),
            self._text(row, "leg_name"), self._boolean(row, "margin_unfunded"), order_flag, legs,
        )

    async def _trades(self, facade: _BrokerReadFacade):
        grant = self._begin(facade, _Operation.TRADES, None, None)
        if type(grant) is BrokerReadFailure:
            return grant
        try:
            call = await self._admit_provider(grant, "trade_book")
            if type(call) is BrokerReadFailure:
                return call
            try:
                raw = await call.method(call.handle)
            except BrokerReadResponseInvalid:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
            try:
                if type(raw) is not list:
                    raise ValueError
                copied = tuple(self._trade(item) for item in raw)
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            return self._published(grant, copied)
        finally:
            self._end(grant)

    def _trade(self, item: object) -> TradeSnapshot:
        row = self._record(item, Trade)
        return TradeSnapshot(
            self._text(row, "orderid"), self._text(row, "symbol", required=True), self._text(row, "instrument_id"),
            self._text(row, "exchange", required=True), self._text(row, "action", required=True),
            self._number_text(row, "quantity", required=True), self._number_text(row, "price", required=True),
            self._text(row, "product", required=True), self._text(row, "timestamp", required=True),
            self._numeric(row, "multiplier"), self._numeric(row, "fx_rate"), self._boolean(row, "cross_currency"),
        )


def create_broker_read_owner(
    *,
    registry: BrokerRegistry,
    session_provider: AuthenticatingSessionProvider,
    adapters: dict[str, object],
    workspace_path: Path,
    rate_limiter: object | None = None,
    runtime_accepting_requests: Callable[[], bool],
) -> BrokerReadOwner:
    """Create an inert owner from one already-prepared app dependency set."""
    if (
        type(registry) is not BrokerRegistry
        or type(session_provider) is not AuthenticatingSessionProvider
        or session_provider._registry is not registry
        or type(adapters) is not dict
        or any(type(key) is not str or not key for key in adapters)
        or not isinstance(workspace_path, Path)
        or not callable(runtime_accepting_requests)
        or (rate_limiter is not None and not callable(getattr(rate_limiter, "acquire", None)))
    ):
        raise RegistrySessionUnavailable
    return BrokerReadOwner(
        registry=registry,
        session_provider=session_provider,
        adapters=adapters,
        workspace_path=workspace_path,
        rate_limiter=rate_limiter,
        runtime_accepting_requests=runtime_accepting_requests,
    )
