"""Gateway-owned exact broker-read capability and grant lifecycle."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import math
import threading
import time
import weakref
from collections.abc import Awaitable, Mapping
from concurrent.futures import Future
from contextvars import ContextVar
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Callable, TypeVar, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from flinttrade_core.account_mutation_contracts import (
    RegistrySelectorVersion,
    RegistrySessionUnavailable,
    SessionVersion,
)
from flinttrade_core.broker_identity import BrokerSelector, CredentialVersion, parse_broker_selector
from flinttrade_core.broker_read_port import (
    AccountPostingSnapshot,
    BalanceSnapshot,
    BatchQuoteRequest,
    BrokerDataRole,
    BrokerObservationSnapshot,
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
    LedgerRequest,
    LedgerSnapshot,
    LotSizeRequest,
    MarginRequest,
    MarginSnapshot,
    ObservationCoverage,
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
    TradeBookSnapshot,
    TradeHistoryRequest,
    TradeHistorySnapshot,
    TradeSnapshot,
)
from flinttrade_core.exceptions import SafetyBypassError, UnsupportedCapabilityError
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

from .brokers._base import BrokerAdapter
from .json_evidence import copy_json_evidence
from .read_frontier import ReadContinuation, read_diagnostics, read_invocation_guard
from .registry import (
    BrokerRegistry,
    ConnectedRegistrySession,
)
from .session_provider import AuthenticatingSessionProvider

_ObservationT = TypeVar("_ObservationT")
_OBSERVATION_DEADLINE: ContextVar[float | None] = ContextVar("broker_observation_deadline", default=None)


def _observation_wait_expired() -> bool:
    deadline = _OBSERVATION_DEADLINE.get()
    return deadline is not None and time.monotonic() >= deadline


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
    TRADE_HISTORY = "trade_history"
    LEDGER = "ledger"


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
    binding: SessionVersion
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


class _ReadAdmissionRefused(Exception):
    """Internal control flow for an authority refusal while awaiting a token."""

    def __init__(self, failure: BrokerReadFailure) -> None:
        super().__init__()
        self.failure = failure


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

    async def trade_history(
        self, request: TradeHistoryRequest
    ) -> BrokerReadSuccess[TradeHistorySnapshot] | BrokerReadFailure:
        """Delegate the bounded request to the exact retained read owner.

        Args:
            request: Explicit date window and collection bounds.

        Returns:
            Copied observations with coverage, or a typed ownership/read refusal.
        """
        owner = _facade_owner(self)
        return (
            BrokerReadFailure(BrokerReadErrorCode.REVOKED)
            if owner is None
            else await owner._trade_history(self, request)
        )

    async def ledger(
        self, request: LedgerRequest
    ) -> BrokerReadSuccess[LedgerSnapshot] | BrokerReadFailure:
        """Delegate the bounded request to the exact retained read owner.

        Args:
            request: Explicit date window and collection bounds.

        Returns:
            Copied observations with coverage, or a typed ownership/read refusal.
        """
        owner = _facade_owner(self)
        return BrokerReadFailure(BrokerReadErrorCode.REVOKED) if owner is None else await owner._ledger(self, request)


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
        "_observation_tasks",
        "_continuation",
        "_native_scope_source",
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
        native_scope_source: object | None = None,
    ) -> None:
        self._native_scope_source = native_scope_source
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
        self._observation_tasks: set[asyncio.Task] = set()
        self._continuation: ReadContinuation | None = None
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
    ) -> SessionVersion:
        self._provider.current_authority_for(selector)
        state = self._registry.snapshot_exact_state(selector)
        if state is None or state.status != "connected" or state.binding is None:
            raise RegistrySessionUnavailable
        if type(state.binding) is not SessionVersion:
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
        binding: SessionVersion, role: BrokerDataRole | None
    ) -> BrokerReadProvenance:
        if type(binding) is not SessionVersion:
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
            continuation = self._continuation
        # Never stop a worker's loop merely because its collector returned.
        # A failed join keeps the same component for the next owner retry.
        return drained and (continuation is None or continuation.close(deadline))

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

    async def _bounded_observation(
        self, factory: Callable[[], Awaitable[_ObservationT]], deadline: float, *, facade: _BrokerReadFacade
    ) -> _ObservationT:
        """Bound the collector wait while retaining actual work in this owner.

        Cancellation requests do not imply completion: the SDK helper can keep
        shielding its worker. Concrete BrokerAdapter tasks run on an owner-held
        continuation, never a disposable caller loop. Async-only injected readers
        keep their caller-loop affinity. Close remains incomplete until the exact
        tasks, executor and continuation exit, through the original factory's drain.

        Args:
            factory: The admitted read operation, not a detached SDK retry.
            deadline: The capture's original absolute monotonic deadline.
            facade: The existing port identifying the actual installed adapter.

        Returns:
            Only an on-time result; late results are retrieved but not published.

        Raises:
            TimeoutError: The collector deadline expired or the owner retired.
        """
        if deadline <= time.monotonic():
            raise TimeoutError
        caller_loop = asyncio.get_running_loop()
        completion: Future[_ObservationT] = Future()
        tasks: list[asyncio.Task[_ObservationT]] = []

        async def run() -> _ObservationT:
            token = _OBSERVATION_DEADLINE.set(deadline)
            try:
                if _observation_wait_expired():
                    raise TimeoutError
                return await factory()
            finally:
                _OBSERVATION_DEADLINE.reset(token)

        def retire(task: asyncio.Task[_ObservationT]) -> None:
            # Completion, not concurrent-future cancellation, retires custody.
            try:
                if task.cancelled():
                    completion.cancel()
                elif (error := task.exception()) is not None:
                    completion.set_exception(error)
                else:
                    completion.set_result(task.result())
            finally:
                with self._lock:
                    self._observation_tasks.remove(task)
                    self._active -= 1
                    self._drained.notify_all()

        def schedule() -> None:
            with read_diagnostics(caller_loop):
                task = asyncio.create_task(run())
                with self._lock:
                    self._observation_tasks.add(task)
                tasks.append(task)
                task.add_done_callback(retire)

        def cancel() -> None:
            # Queued after schedule on the same loop, even if the caller exits
            # before the coroutine's first turn. Its done callback still owns it.
            for task in tasks:
                task.cancel()

        with self._lock:
            grant = self._grants.get(facade)
            if self._closed or grant is None or grant.revoked:
                raise TimeoutError
            if isinstance(self._adapters.get(grant.selector.adapter_id), BrokerAdapter):
                if self._continuation is None:
                    self._continuation = ReadContinuation()
                loop = self._continuation.loop
            else:
                loop = caller_loop
            self._active += 1
            try:
                loop.call_soon_threadsafe(schedule)
            except BaseException:
                self._active -= 1
                self._drained.notify_all()
                raise
        waiter = asyncio.wrap_future(completion)
        # The caller may have stopped waiting when a late exception arrives.
        waiter.add_done_callback(lambda future: None if future.cancelled() else future.exception())
        try:
            done, _ = await asyncio.wait({waiter}, timeout=max(0.0, deadline - time.monotonic()))
            if waiter not in done or time.monotonic() >= deadline:
                raise TimeoutError
            return waiter.result()
        except BaseException:
            # A real SDK task deliberately ignores cancellation until its
            # worker exits; retain its reference and drainage count meanwhile.
            with self._lock:
                # Completion can race a collector timeout and a successful
                # concurrent close. A completed task needs no cancellation.
                if not completion.done():
                    loop.call_soon_threadsafe(cancel)
            raise

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
        *,
        depth_exchange: str | None = None,
    ) -> _ProviderCall | BrokerReadFailure:
        if _observation_wait_expired():
            return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
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
        if selected == "depth":
            # A request outside an adapter's static depth scope makes no provider
            # call, so it must not wait for or consume quote/data quota either.
            missing = object()
            exchanges = inspect.getattr_static(adapter_type, "_BROKER_READ_DEPTH_EXCHANGES", missing)
            if exchanges is not missing and (
                type(exchanges) is not frozenset
                or any(type(exchange) is not str or not exchange for exchange in exchanges)
                or depth_exchange not in exchanges
            ):
                return BrokerReadFailure(BrokerReadErrorCode.UNSUPPORTED)
        from .canonical_read_plan import current_budget

        budget = current_budget()
        if budget is not None and not budget.take(page=selected == "trade_history"):
            return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
        if self._rate_limiter is not None:
            def revalidate_waiter() -> None:
                result = self._revalidate(grant)
                if type(result) is BrokerReadFailure:
                    raise _ReadAdmissionRefused(result)

            try:
                # Single/batch quotes and quote-backed depth share the stricter
                # market-quote cap as well as the generic data budget.
                kind = "quote" if selected in {"quotes", "depth"} else "data"
                await self._rate_limiter.acquire(
                    grant.selector.adapter_id, kind, before_retry=revalidate_waiter
                )
            except _ReadAdmissionRefused as refusal:
                return refusal.failure
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
        from .brokers.dhan import DhanAdapter
        from .brokers.kotakneo import KotakNeoAdapter

        # Concrete native methods repeat this check after their final executor
        # and transport-lock waits. Do not spend the same bounded capture on
        # another full custody read immediately before that mandatory frontier.
        # Async-only and substituted methods retain their pre-call revalidation.
        native_frontier = (type(adapter) in (DhanAdapter, KotakNeoAdapter)
                           and getattr(getattr(adapter, selected, None), "__func__", None)
                           is getattr(type(adapter), selected, None))
        second = first if native_frontier else self._revalidate(grant)
        if type(second) is BrokerReadFailure:
            return second
        try:
            method = getattr(adapter, selected)
        except Exception:
            return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
        if not callable(method):
            return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
        if _observation_wait_expired():
            return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)

        native_calls = 0

        def verify_invocation() -> None:
            nonlocal native_calls
            # Runs on the actual SDK worker after every executor/transport wait.
            # The handle's native account is independent of the public alias.
            current = self._revalidate(grant)
            if type(current) is BrokerReadFailure:
                raise _ReadAdmissionRefused(current)
            if current.version != second.version or current.account_id != second.account_id:
                raise _ReadAdmissionRefused(BrokerReadFailure(BrokerReadErrorCode.TARGET_STALE))
            if _observation_wait_expired():
                raise TimeoutError
            # The first call uses its admitted slot. Aggregate adapter methods
            # must acquire another slot at every subsequent native invocation.
            if budget is not None and native_calls and not budget.take():
                raise _ReadAdmissionRefused(BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE))
            native_calls += 1

        async def guarded_method(*args: object, **kwargs: object) -> object:
            with read_invocation_guard(verify_invocation):
                return await cast(Callable[..., Awaitable[object]], method)(*args, **kwargs)

        return _ProviderCall(second, guarded_method)

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
        if _observation_wait_expired():
            return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
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
            call = await self._admit_provider(grant, "depth", depth_exchange=request.instrument.exchange)
            if type(call) is BrokerReadFailure:
                return call
            try:
                raw_result = await call.method(call.handle, request)
            except UnsupportedCapabilityError:
                return BrokerReadFailure(BrokerReadErrorCode.UNSUPPORTED)
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
                seen: dict[str, InstrumentLotSizeSnapshot] = {}
                copied_rows = []
                for item in raw:
                    row = self._record(item)
                    row, original_row = self._contract_projection(row, grant.selector.adapter_id)
                    symbol = self._text(row, "symbol", required=True)
                    exchange = self._text(row, "exchange", required=True)
                    lot_size = self._integer_field(row, "lot_size", required=True)
                    instrument_id = self._text(row, "instrument_id")
                    if exchange != request.exchange or (expected and symbol not in expected):
                        raise ValueError
                    extras = {
                        key: self._text(row, key)
                        for key in (
                            "underlying",
                            "expiry",
                            "option_type",
                            "tick_unit",
                            "raw_tick_unit",
                            "source_revision",
                            "source_digest",
                            "observed_at",
                            "valid_until",
                        )
                    }
                    extras.update(
                        {key: self._number_text(row, key) for key in ("strike_price", "tick_size", "raw_tick_size")}
                    )
                    observed = {
                        key: row[key]
                        for key in (
                            *extras,
                            "symbol",
                            "exchange",
                            "lot_size",
                            "instrument_id",
                            "broker_exchange_segment",
                            "broker_symbol",
                            "instrument_type",
                            "price_unit",
                            "quantity_unit",
                        )
                        if key in row
                    }
                    native = self._native_fields(
                        row,
                        frozenset(
                            {
                                "SEM_SMST_SECURITY_ID",
                                "SECURITY_ID",
                                "SEM_LOT_UNITS",
                                "LOT_SIZE",
                                "SEM_TICK_SIZE",
                                "TICK_SIZE",
                                "SEM_EXPIRY_DATE",
                                "SM_EXPIRY_DATE",
                                "SEM_STRIKE_PRICE",
                                "STRIKE_PRICE",
                                "SEM_OPTION_TYPE",
                                "OPTION_TYPE",
                                "UNDERLYING_SECURITY_ID",
                                "UNDERLYING_SYMBOL",
                                "pSymbol",
                                "pTrdSymbol",
                                "pSymbolName",
                                "pInstType",
                                "pOptionType",
                                "lExpiryDate",
                                "pExpiryDate",
                                "dStrikePrice;",
                                "lLotSize",
                                "dTickSize",
                                "lPrecision",
                            }
                        ),
                    )
                    if native is not None:
                        observed["broker_fields"] = native
                    for key in (
                        "broker_id",
                        "security_id",
                        "exchange_segment",
                        "instrument",
                        "underlying_security_id",
                        "tick_scale",
                        "tick_source",
                        "contract",
                    ):
                        if key in original_row:
                            observed[key] = copy_json_evidence(original_row[key])
                    for key in ("observed_at", "valid_until"):
                        if key in original_row:
                            observed[key] = original_row[key]
                    extras["raw_observation_json"] = json.dumps(
                        copy_json_evidence(observed), sort_keys=True, separators=(",", ":")
                    )
                    snapshot = InstrumentLotSizeSnapshot(symbol, exchange, lot_size, instrument_id, **extras)
                    fingerprint = snapshot
                    if symbol in seen and seen[symbol] != fingerprint:
                        raise ValueError
                    if symbol in seen:
                        continue
                    seen[symbol] = fingerprint
                    copied_rows.append(snapshot)
                if expected and set(seen) != expected:
                    raise ValueError
                copied = tuple(copied_rows)
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            return self._published(grant, copied)
        finally:
            self._end(grant)

    async def read_safety_source(
        self, facade: BrokerReadPort, name: str, *args: object,
    ) -> BrokerReadSuccess | BrokerReadFailure:
        """Retain native observations for canonical L2/L4's existing strict parser.

        Only an already bound exact-account port can borrow this read-only
        surface. The ordinary provider admission owns budgets, transport-frontier
        revalidation and active-worker drain. A read-only account cannot supply
        write-admission evidence; no arbitrary adapter method is dispatched.

        Args:
            facade: Already bound exact-account read port, not a raw session or new authority.
            name: Supported canonical safety read name mapped to an existing operation.
            args: Arguments forwarded unchanged to that admitted native read method.

        Returns:
            The genuine native observation or a typed unsupported, unauthorised or provider failure.
        """
        operations = {
            "positions": _Operation.POSITIONS, "trade_book": _Operation.TRADES,
            "holdings": _Operation.HOLDINGS, "safety_order_book": _Operation.ORDER_STATES,
            "order_book": _Operation.ORDER_STATES, "funds": _Operation.BALANCE,
            "quotes": _Operation.BATCH_QUOTES, "margin_calculator": _Operation.MARGIN,
        }
        if type(name) is not str or name not in operations:
            return BrokerReadFailure(BrokerReadErrorCode.UNSUPPORTED)
        grant = self._begin(facade, operations[name], None, None)
        if type(grant) is BrokerReadFailure:
            return grant
        try:
            if grant.role is not None or grant.context.mode != "live":
                return BrokerReadFailure(BrokerReadErrorCode.UNAUTHORISED)
            call = await self._admit_provider(grant, name)
            if type(call) is BrokerReadFailure:
                return call
            if call.handle.is_read_only:
                return BrokerReadFailure(BrokerReadErrorCode.UNAUTHORISED)
            try:
                raw = await cast(Callable[..., Awaitable[object]], call.method)(call.handle, *args)
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
            return self._published(grant, raw)
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
                copied = self._portfolio_rows(raw, request.positions)
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            return self._published(grant, copied)
        finally:
            self._end(grant)

    def _portfolio_rows(self, raw: list[object], requested: tuple[PortfolioPositionRef, ...]):
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
            if expected_row.instrument_id is None and instrument_id is None:
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
                for name in (
                    "required_margin",
                    "total_margin_required",
                    "total_margin",
                    "final_margin",
                    "order_margin",
                    "margin",
                ):
                    if name not in raw:
                        continue
                    value = raw[name]
                    if value is None or (type(value) is str and value == ""):
                        continue
                    selected = self._numeric(raw, name, required=True)
                    break
                if selected is None or selected < 0:
                    raise ValueError
                observations = {
                    key: raw[key]
                    for key in (
                        "required_margin",
                        "provider_additional_margin",
                        "rms_validated",
                        "available_balance",
                        "available_cash",
                        "available_margin",
                        "used_margin",
                        "span_margin",
                        "exposure_margin",
                        "variable_margin",
                        "insufficient_balance",
                        "brokerage",
                        "leverage",
                        "broker_account_id",
                    )
                    if key in raw
                }
                native = self._native_fields(
                    raw,
                    frozenset(
                        {
                            "dhanClientId",
                            "actId",
                            "accountId",
                            "totalMargin",
                            "spanMargin",
                            "exposureMargin",
                            "availableBalance",
                            "variableMargin",
                            "insufficientBalance",
                            "brokerage",
                            "leverage",
                            "ordMrgn",
                            "reqdMrgn",
                            "avlCash",
                            "avlMrgn",
                            "mrgnUsd",
                            "totMrgnUsd",
                            "insufFund",
                            "rmsVldtd",
                            "stat",
                            "stCode",
                        }
                    ),
                )
                if native is not None:
                    observations["broker_fields"] = native
                account = self._text(raw, "broker_account_id")
                if account is not None and account != call.handle.account_id:
                    raise ValueError
                for name in ("dhanClientId",) if grant.selector.adapter_id == "dhan" else ("actId", "accountId"):
                    if (
                        native is not None
                        and name in native
                        and (type(native[name]) is not str or native[name] != call.handle.account_id)
                    ):
                        raise ValueError
                copied = MarginSnapshot(
                    selected,
                    request=request,
                    provider_additional_margin=self._number_text(raw, "provider_additional_margin"),
                    rms_validated=self._text(raw, "rms_validated"),
                    raw_observation_json=json.dumps(
                        copy_json_evidence(observations), sort_keys=True, separators=(",", ":")
                    ),
                )
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
                for row in all_rows:
                    if row.broker_account_id is not None and row.broker_account_id != call.handle.account_id:
                        raise ValueError
                    native = json.loads(row.raw_observation_json or "{}").get("broker_fields", {})
                    account_fields = (("dhanClientId",) if grant.selector.adapter_id == "dhan" else
                                      ("actId", "accountId") if grant.selector.adapter_id == "kotakneo" else ())
                    if any(name in native and (type(native[name]) is not str or native[name] != call.handle.account_id)
                           for name in account_fields):
                        raise ValueError
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

    @classmethod
    def _order_number_text(cls, raw: dict[str, object], *names: str) -> str | None:
        """Copy every supplied numeric alias; refuse conflicts, never infer."""
        values: list[str] = []
        for name in names:
            value = raw.get(name)
            if value is None or (type(value) is str and not value.strip()):
                continue
            text = cls._number_text(raw, name)
            if text is None:
                raise ValueError
            values.append(text)
        if not values:
            return None
        if any(Decimal(value) != Decimal(values[0]) for value in values[1:]):
            raise ValueError
        return values[0]

    @staticmethod
    def _order_observation_json(raw: dict[str, object]) -> str:
        """Detach exact JSON evidence without conversion/deepcopy hooks."""
        return json.dumps(copy_json_evidence(raw), allow_nan=False, separators=(",", ":"))

    def _native_order_observation_json(self, row: dict[str, object]) -> str | None:
        if not any(name in row for name in ("gtt_order_id", "resource_status", "entry_status", "rules")):
            native = self._native_fields(row, frozenset({
                "dhanClientId", "orderId", "exchangeOrderId", "correlationId", "exchangeSegment", "legName",
                "createTime", "updateTime", "exchangeTime", "afterMarketOrder", "amoTime", "quantity",
                "filledQty", "tradedQty", "remainingQuantity", "productType", "orderType", "securityId",
                "nOrdNo", "exOrdId", "exchOrdId", "actId", "accountId", "usrId", "brkClnt", "GuiOrdId", "exSeg",
                "ordDtTm", "ordEntTm", "exCfmTm", "exchTmstp", "flDtTm", "flDt", "flTm", "exTm",
                "hsUpTm", "updRecvTm", "boeSec", "uSec", "ordGenTp", "qty", "fldQty", "prod", "prcTp", "tok",
            }))
            return None if native is None else self._order_observation_json({"broker_fields": native})
        # Reuse the same exact-JSON validator as native Dhan leg observations.
        # Validate before inspecting aliases, so opaque hooks never run here.
        encoded = self._order_observation_json(row)
        views = [row]
        if "broker_fields" in row:
            views.append(self._record(row["broker_fields"]))
        rule_observations = []
        for view in views:
            self._text_alias(view, "gtt_order_id", "gttOrderId")
            self._text_alias(view, "resource_status", "resourceStatus")
            self._text_alias(view, "entry_status", "entryStatus")
            self._text_alias(view, "status")
            self._text_alias(view, "type")
            self._order_number_text(view, "stop_loss_trailing_gap", "stopLossTrailingGap")
            self._order_number_text(view, "expires_at", "expiresAt")
            rules = view.get("rules")
            if type(rules) is not list:
                raise ValueError
            strategies: set[str] = set()
            observed_rules = {}
            for child in rules:
                rule = self._record(child)
                strategy = self._text_alias(rule, "strategy", required=True)
                if strategy is None:
                    raise ValueError
                strategy = strategy.upper()
                if strategy not in {"ENTRY", "TARGET", "STOPLOSS"} or strategy in strategies:
                    raise ValueError
                strategies.add(strategy)
                values = {}
                for names in (
                    ("status", "order_status", "orderStatus"), ("message",), ("trigger_type", "triggerType"),
                    ("transaction_type", "transactionType", "action"), ("order_id", "orderId"),
                    ("exchange_order_id", "exchangeOrderId"), ("parent_order_id", "parentOrderId"),
                ):
                    text = self._text_alias(rule, *names)
                    values[names[0]] = text if text is not None and text.strip() else None
                for names in (
                    ("trigger_price", "triggerPrice"), ("trailing_gap", "trailingGap"),
                    ("market_protection", "marketProtection"), ("quantity",),
                    ("filled_quantity", "filledQty", "tradedQty"), ("remaining_quantity", "remainingQuantity"),
                    ("triggered_quantity", "triggeredQuantity"),
                ):
                    number = self._order_number_text(rule, *names)
                    values[names[0]] = Decimal(number) if number is not None else None
                observed_rules[strategy] = values
                if strategy == "ENTRY" and any(name in view for name in ("entry_status", "entryStatus")):
                    if self._text_alias(view, "entry_status", "entryStatus") != self._text_alias(
                        rule, "status", "order_status", "orderStatus",
                    ):
                        raise ValueError
                if strategy == "STOPLOSS" and any(
                    name in view for name in ("stop_loss_trailing_gap", "stopLossTrailingGap")
                ):
                    projected = self._order_number_text(view, "stop_loss_trailing_gap", "stopLossTrailingGap")
                    native = self._order_number_text(rule, "trailing_gap", "trailingGap")
                    if (projected is None) != (native is None) or (
                        projected is not None and native is not None and Decimal(projected) != Decimal(native)
                    ):
                        raise ValueError
            if "ENTRY" not in strategies:
                raise ValueError
            self._text_alias(view, "status", "resource_status", "resourceStatus")
            rule_observations.append(observed_rules)
        # Normalised and native copies may differ in representation (null vs
        # empty text, integer vs exact decimal text), never in observed meaning.
        if len(rule_observations) == 2 and rule_observations[0] != rule_observations[1]:
            raise ValueError
        self._text_alias(row, "orderid", "order_id", "gtt_order_id", "gttOrderId")
        if len(views) == 2:
            for names in (("gtt_order_id", "gttOrderId"), ("type",)):
                if self._text_alias(row, *names) != self._text_alias(views[1], *names):
                    raise ValueError
            if any(name in row for name in ("resource_status", "resourceStatus")) and (
                self._text_alias(row, "resource_status", "resourceStatus")
                != self._text_alias(views[1], "status", "resource_status", "resourceStatus")
            ):
                raise ValueError
        return encoded

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
                    self._order_number_text(leg, "quantity"),
                    self._order_number_text(leg, "filled_quantity", "filledQty", "tradedQty"),
                    self._order_number_text(leg, "price"),
                    self._order_number_text(leg, "trigger_price", "triggerPrice"),
                    total_quantity=self._order_number_text(leg, "total_quantity", "totalQuatity"),
                    remaining_quantity=self._order_number_text(leg, "remaining_quantity", "remainingQuantity"),
                    triggered_quantity=self._order_number_text(leg, "triggered_quantity", "triggeredQuantity"),
                    trailing_jump=self._order_number_text(leg, "trailing_jump", "trailingJump"),
                    target_price=self._order_number_text(leg, "target_price", "targetPrice"),
                    stop_loss_price=self._order_number_text(leg, "stop_loss_price", "stopLossPrice"),
                    average_price=self._order_number_text(leg, "average_price", "averageTradedPrice"),
                    disclosed_quantity=self._order_number_text(leg, "disclosed_quantity", "disclosedQuantity"),
                    parent_order_id=self._text_alias(leg, "parent_order_id", "parentOrderId"),
                    created_at=self._text_alias(leg, "created_at", "createTime"),
                    updated_at=self._text_alias(leg, "updated_at", "updateTime"),
                    exchange_time=self._text_alias(leg, "exchange_time", "exchangeTime"),
                    raw_observation_json=self._order_observation_json(leg),
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
        # The pinned Upstox resource observes integer epoch times. Preserve
        # their exact text without guessing units or converting to a date.
        created_at = (
            str(row["created_at"])
            if "gtt_order_id" in row and type(row.get("created_at")) is int
            else self._text(row, "created_at")
        )
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
            broker_product=self._text(row, "broker_product"),
            broker_order_type=self._text(row, "broker_order_type"),
            validity=self._text(row, "validity"),
            created_at=created_at,
            updated_at=self._text(row, "updated_at"),
            exchange_time=self._text(row, "exchange_time"),
            remaining_quantity=self._order_number_text(row, "remaining_quantity", "remainingQuantity"),
            target_price=self._order_number_text(row, "target_price", "targetPrice"),
            stop_loss_price=self._order_number_text(row, "stop_loss_price", "stopLossPrice"),
            trailing_jump=self._order_number_text(row, "trailing_jump", "trailingJump"),
            average_price=self._order_number_text(row, "average_price", "averageTradedPrice"),
            leg_details_valid=self._boolean(row, "leg_details_valid"),
            raw_observation_json=self._native_order_observation_json(row),
            broker_account_id=self._text(row, "broker_account_id"),
            broker_exchange_segment=self._text(row, "broker_exchange_segment"),
            correlation_id=self._text_alias(row, "correlation_id", "tag"),
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
                copied = tuple(self._bound_trade(item, call.handle) for item in raw)
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            return self._published(grant, copied)
        finally:
            self._end(grant)

    async def _capture_trade_book(self, facade: _BrokerReadFacade):
        from .brokers.kotakneo import KotakNeoAdapter, KotakNeoTradeBook

        grant = self._begin(facade, _Operation.TRADES, None, None)
        if type(grant) is BrokerReadFailure:
            return grant
        try:
            native_observation = type(self._adapters.get(grant.selector.adapter_id)) is KotakNeoAdapter
            call = await self._admit_provider(grant, "trade_book_observation" if native_observation else "trade_book")
            if type(call) is BrokerReadFailure:
                return call
            try:
                raw = await call.method(call.handle)
            except BrokerReadResponseInvalid:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
            try:
                coverage_json = None
                if native_observation:
                    if type(raw) is not KotakNeoTradeBook:
                        raise ValueError
                    rows = tuple(self._bound_trade(item, call.handle) for item in raw.rows)
                    coverage = copy_json_evidence(raw.coverage)
                    if coverage.get("scope") != "trading_day" or coverage.get("lifetime_complete") is not False:
                        raise ValueError
                    if (
                        type(coverage.get("received_count")) is not int
                        or type(coverage.get("returned_count")) is not int
                    ):
                        raise ValueError
                    if coverage["received_count"] < len(rows) or coverage["returned_count"] != len(rows):
                        raise ValueError
                    coverage_json = json.dumps(coverage, sort_keys=True, separators=(",", ":"))
                else:
                    if type(raw) is not list:
                        raise ValueError
                    rows = tuple(self._bound_trade(item, call.handle) for item in raw)
                return self._published(grant, TradeBookSnapshot(rows, coverage_json))
            except (TypeError, ValueError, AttributeError):
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
        finally:
            self._end(grant)

    @classmethod
    def _contract_projection(cls, row: dict, broker: str) -> tuple[dict, dict]:
        original = dict(row)
        projected = dict(row)
        if broker == "kotakneo" and "contract" in row:
            contract = cls._record(row["contract"])
            for key in ("symbol", "exchange", "instrument_id", "lot_size"):
                if contract.get(key) != row.get(key):
                    raise ValueError
            allowed = {
                "broker",
                "symbol",
                "exchange",
                "instrument_id",
                "broker_exchange_segment",
                "underlying",
                "option_type",
                "instrument_type",
                "expiry",
                "strike",
                "strike_unit",
                "lot_size",
                "quantity_unit",
                "raw_tick_size",
                "raw_precision",
                "tick_size_inr",
                "tick_scale_verified",
                "source",
                "source_revision",
                "schema_revision",
                "source_digest",
                "record_digest",
                "observed_at",
                "valid_until",
                "expiry_source",
                "strike_source",
            }
            kept = {key: contract[key] for key in allowed if key in contract}
            if "tick_source" in contract:
                tick = cls._record(contract["tick_source"])
                kept["tick_source"] = {
                    key: tick[key] for key in ("kind", "url", "sha256", "reviewed_on", "master_scale") if key in tick
                }
            native = cls._native_fields(
                contract,
                frozenset(
                    {
                        "pSymbol",
                        "pTrdSymbol",
                        "pExchSeg",
                        "pSymbolName",
                        "pOptionType",
                        "pInstType",
                        "lExpiryDate",
                        "pExpiryDate",
                        "dStrikePrice;",
                        "lLotSize",
                        "dTickSize",
                        "lPrecision",
                    }
                ),
            )
            if native is not None:
                kept["broker_fields"] = native
            original["contract"] = copy_json_evidence(kept)
            for key in (
                "underlying",
                "expiry",
                "option_type",
                "raw_tick_size",
                "source_revision",
                "source_digest",
                "observed_at",
                "valid_until",
            ):
                if key in contract:
                    projected[key] = contract[key]
            if "strike" in contract:
                projected["strike_price"] = contract["strike"]
            if "tick_size_inr" in contract:
                projected["tick_size"] = contract["tick_size_inr"]
                projected["tick_unit"] = "INR"
            if contract.get("tick_scale_verified") is False:
                projected["raw_tick_unit"] = "unknown"
        if broker == "dhan":
            for key in ("observed_at", "valid_until"):
                value = row.get(key)
                if type(value) is int or type(value) is float:
                    if not math.isfinite(value) or value <= 0:
                        raise ValueError
                    # The reviewed resolver's explicit epoch-second clock, not
                    # any native order/fill timestamp convention.
                    projected[key] = datetime.fromtimestamp(value, UTC).isoformat()
            if row.get("tick_scale") == "unavailable":
                projected["raw_tick_unit"] = "unknown"
            if "tick_source" in row:
                tick = cls._record(row["tick_source"])
                original["tick_source"] = {
                    key: tick[key]
                    for key in (
                        "tick_size",
                        "source_kind",
                        "source_revision",
                        "source_url",
                        "contract_source_revision",
                        "observed_at",
                        "valid_until",
                    )
                    if key in tick
                }
        return projected, original

    @staticmethod
    def _statement_rows(raw, handle, request, resource: str, page: int | None):
        if type(raw) is list:
            return raw, None
        # Exact reviewed type only: arbitrary list subclasses/coverage hooks
        # remain refused. A statement's False is scope, never paid evidence.
        from .brokers.dhan_mapping import DhanStatementPage

        if handle.selector.adapter_id != "dhan" or type(raw) is not DhanStatementPage:
            raise ValueError
        coverage = copy_json_evidence(raw.coverage)
        if (
            type(coverage) is not dict
            or coverage
            != {
                "resource": resource,
                "from_date": request.start_date,
                "to_date": request.end_date,
                "complete": False,
                "terminal": "undocumented",
                "broker_account_id": handle.account_id,
                **({"page": page} if page is not None else {}),
            }
            or type(coverage.get("complete")) is not bool
            or (page is not None and type(coverage.get("page")) is not int)
        ):
            raise ValueError
        return list(list.__iter__(raw)), coverage

    def _history_trade(self, item: object, handle: ConnectedRegistrySession) -> TradeSnapshot:
        row = self._record(item, Trade)
        if "tradingSymbol" in row and "symbol" not in row and handle.selector.adapter_id == "dhan":
            # The reviewed legacy statement method returns native rows, unlike
            # trade_book. Reuse its real mapper for semantics; retain presence
            # before that projection. Never infer a date/zone from a timestamp.
            from .brokers.dhan_mapping import from_dhan_trade

            mapped = from_dhan_trade(row)
            for canonical, native in (
                ("fill_id", "exchangeTradeId"),
                ("exchange_order_id", "exchangeOrderId"),
                ("broker_account_id", "dhanClientId"),
                ("broker_exchange_segment", "exchangeSegment"),
                ("broker_product_type", "productType"),
                ("created_at", "createTime"),
                ("updated_at", "updateTime"),
                ("exchange_time", "exchangeTime"),
                ("trade_date", "tradeDate"),
            ):
                if native in row:
                    mapped[canonical] = row[native]
            mapped["broker_fields"] = row
            row = mapped
        return self._bound_trade(row, handle)

    async def _trade_history(
        self, facade: _BrokerReadFacade, request: TradeHistoryRequest, *, deadline: float | None = None
    ):
        try:
            if type(request) is not TradeHistoryRequest:
                raise ValueError
            request = TradeHistoryRequest(
                request.start_date, request.end_date, request.max_pages, request.start_page, request.max_rows
            )
        except (ValueError, TypeError):
            return BrokerReadFailure(BrokerReadErrorCode.INVALID_REQUEST)
        grant = self._begin(facade, _Operation.TRADE_HISTORY, request, TradeHistoryRequest)
        if type(grant) is BrokerReadFailure:
            return grant
        try:
            if grant.selector.adapter_id != "dhan":
                return BrokerReadFailure(BrokerReadErrorCode.UNSUPPORTED)
            rows, pages, issues = [], [], []
            provider_coverages = []
            page_digests, identities = set(), set()
            availability = "available"
            observed_count = 0
            deadline = time.monotonic() + 30.0 if deadline is None else deadline
            for page in range(request.start_page, request.start_page + request.max_pages):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    availability = "provider_failure"
                    issues.append("read_deadline_exceeded")
                    break
                try:
                    async with asyncio.timeout(remaining):
                        call = await self._admit_provider(grant, "trade_history")
                except TimeoutError:
                    availability = "provider_failure"
                    issues.append("read_deadline_exceeded")
                    break
                if type(call) is BrokerReadFailure:
                    availability = call.code.value
                    issues.append("page_unavailable")
                    break
                try:
                    raw = await self._bounded_observation(
                        lambda call=call, page=page: call.method(
                            call.handle, request.start_date, request.end_date, page=page
                        ),
                        deadline, facade=facade,
                    )
                except TimeoutError:
                    availability = "provider_failure"
                    issues.append("read_deadline_exceeded")
                    break
                except BrokerReadResponseInvalid:
                    availability = "malformed_response"
                    break
                except Exception:
                    availability = "provider_failure"
                    break
                pages.append(page)
                try:
                    raw, provider_coverage = self._statement_rows(raw, call.handle, request, "trade_history", page)
                    if provider_coverage is not None:
                        provider_coverages.append(provider_coverage)
                    if type(raw) is not list:
                        raise ValueError
                    observed_count += len(raw)
                    if observed_count > request.max_rows:
                        issues.append("row_budget_exceeded")
                        break
                    copied = tuple(self._history_trade(item, call.handle) for item in raw)
                except (ValueError, TypeError):
                    availability = "malformed_response"
                    break
                digest = hashlib.sha256(
                    json.dumps(
                        [asdict(row) for row in copied], sort_keys=True, separators=(",", ":"), allow_nan=False
                    ).encode()
                ).hexdigest()
                rows.extend(copied)
                if digest in page_digests:
                    issues.append("repeated_page")
                    break
                page_digests.add(digest)
                for trade in copied:
                    identity = (
                        trade.trade_date,
                        trade.broker_exchange_segment,
                        trade.orderid,
                        trade.fill_id,
                        trade.fill_leg,
                    )
                    if trade.fill_id is not None and identity in identities:
                        issues.append("page_overlap")
                    identities.add(identity)
                if not copied:
                    issues.append("empty_page_not_terminal_evidence")
                    break
            else:
                issues.append("page_budget_reached")
            # No Dhan terminal, retention or page-size guarantee is documented.
            coverage = ObservationCoverage(
                resource="trades.history",
                availability=availability,
                query_start=request.start_date,
                query_end=request.end_date,
                trading_date=None,
                timezone="Asia/Kolkata",
                page_model="zero_based_pages_unknown_terminal",
                pages=tuple(pages),
                observed_count=observed_count,
                source_digest=hashlib.sha256(
                    json.dumps(
                        [asdict(row) for row in rows], sort_keys=True, separators=(",", ":"), allow_nan=False
                    ).encode()
                ).hexdigest(),
                source_revision="broker_read.observations.v1",
                completeness="partial" if pages else "unknown",
                missing_intervals=(request.start_date + "/" + request.end_date,),
                issues=tuple(sorted(set(issues))),
                provider_coverage_json=json.dumps(provider_coverages, sort_keys=True, separators=(",", ":"))
                if provider_coverages
                else None,
            )
            return self._published(grant, TradeHistorySnapshot(tuple(rows), coverage))
        finally:
            self._end(grant)

    async def _ledger(self, facade: _BrokerReadFacade, request: LedgerRequest):
        try:
            if type(request) is not LedgerRequest:
                raise ValueError
            request = LedgerRequest(request.start_date, request.end_date, request.max_rows)
        except (ValueError, TypeError):
            return BrokerReadFailure(BrokerReadErrorCode.INVALID_REQUEST)
        grant = self._begin(facade, _Operation.LEDGER, request, LedgerRequest)
        if type(grant) is BrokerReadFailure:
            return grant
        try:
            if grant.selector.adapter_id != "dhan":
                return BrokerReadFailure(BrokerReadErrorCode.UNSUPPORTED)
            call = await self._admit_provider(grant, "ledger")
            if type(call) is BrokerReadFailure:
                return call
            try:
                raw = await call.method(call.handle, request.start_date, request.end_date)
            except BrokerReadResponseInvalid:
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            except Exception:
                return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
            try:
                raw, provider_coverage = self._statement_rows(raw, call.handle, request, "ledger", None)
                if type(raw) is not list or len(raw) > request.max_rows:
                    raise ValueError
                postings = []
                for item in raw:
                    row = self._record(item)
                    if (
                        "dhanClientId" in row
                        and self._text(row, "dhanClientId", required=True) != call.handle.account_id
                    ):
                        raise ValueError
                    observed = {
                        key: row[key]
                        for key in (
                            "dhanClientId",
                            "narration",
                            "voucherdate",
                            "exchange",
                            "voucherdesc",
                            "vouchernumber",
                            "debit",
                            "credit",
                            "runbal",
                        )
                        if key in row
                    }
                    posting = AccountPostingSnapshot(
                        self._text(row, "vouchernumber"),
                        self._text(row, "voucherdate"),
                        self._number_text(row, "debit", required=True),
                        self._number_text(row, "credit", required=True),
                        json.dumps(copy_json_evidence(observed), sort_keys=True, separators=(",", ":")),
                    )
                    self._number_text(row, "runbal")
                    postings.append(posting)
                digest = hashlib.sha256(
                    json.dumps([asdict(row) for row in postings], sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
            except (ValueError, TypeError):
                return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
            coverage = ObservationCoverage(
                resource="ledger.account_postings",
                availability="available",
                query_start=request.start_date,
                query_end=request.end_date,
                trading_date=None,
                timezone="Asia/Kolkata",
                page_model="single_request",
                pages=(),
                observed_count=len(postings),
                source_digest=digest,
                source_revision="broker_read.observations.v1",
                completeness="partial",
                missing_intervals=(request.start_date + "/" + request.end_date,),
                issues=("posting_to_fill_allocation_unavailable",),
                provider_coverage_json=json.dumps(provider_coverage, sort_keys=True, separators=(",", ":"))
                if provider_coverage is not None
                else None,
            )
            return self._published(grant, LedgerSnapshot(tuple(postings), coverage))
        finally:
            self._end(grant)

    def observation_binding(self, facade: BrokerReadPort) -> tuple[BrokerReadProvenance, str] | BrokerReadFailure:
        """Local current-generation check; never authenticates or fetches data.

        Args:
            facade: Exact account-bound port issued by this owner.

        Returns:
            Owner-resolved provenance and native account, or a typed refusal.
        """
        if type(facade) is not _BrokerReadFacade or _facade_owner(facade) is not self:
            return BrokerReadFailure(BrokerReadErrorCode.REVOKED)
        with self._lock:
            grant = self._grants.get(facade)
        if grant is None or grant.role is not None:
            return BrokerReadFailure(BrokerReadErrorCode.UNAUTHORISED)
        handle = self._revalidate(grant)
        if type(handle) is BrokerReadFailure:
            return handle
        if type(handle.account_id) is not str or not handle.account_id:
            return BrokerReadFailure(BrokerReadErrorCode.MALFORMED_RESPONSE)
        return self._provenance(grant.binding, grant.role), handle.account_id

    async def capture_observations(
        self,
        facade: BrokerReadPort,
        *,
        history: TradeHistoryRequest | None = None,
        lots: LotSizeRequest | None = None,
        margin: MarginRequest | None = None,
        ledger: LedgerRequest | None = None,
        timeout_seconds: float = 30.0,
        read_plan: object | None = None,
        quotes: BatchQuoteRequest | None = None,
    ) -> BrokerObservationSnapshot | BrokerReadFailure:
        """Explicit authorised collection, not a GET/inspection side effect.

        Args:
            facade: Exact account-bound port issued by this owner.
            history: Optional bounded historical trade request.
            lots: Optional exact contract selection.
            margin: Optional single-order estimate request, not standalone capital.
            ledger: Optional bounded account-posting request.
            timeout_seconds: Positive finite collector budget, at most sixty seconds.

        Returns:
            A bounded capture retaining uncertainty and accepted prefixes, or a
            typed refusal. Timed-out SDK work remains owned until it actually exits.
        """
        if read_plan is not None:
            from .canonical_read_plan import capture_plan

            return await capture_plan(self, facade, read_plan, history=history, lots=lots, margin=margin,
                                      ledger=ledger, quotes=quotes, timeout_seconds=timeout_seconds)
        if quotes is not None:
            return BrokerReadFailure(BrokerReadErrorCode.INVALID_REQUEST)
        try:
            if (
                type(timeout_seconds) not in (int, float)
                or not math.isfinite(timeout_seconds)
                or not 0 < timeout_seconds <= 60
            ):
                raise ValueError
            if history is not None:
                if type(history) is not TradeHistoryRequest:
                    raise ValueError
                history = TradeHistoryRequest(
                    history.start_date, history.end_date, history.max_pages, history.start_page, history.max_rows
                )
            if ledger is not None:
                if type(ledger) is not LedgerRequest:
                    raise ValueError
                ledger = LedgerRequest(ledger.start_date, ledger.end_date, ledger.max_rows)
            if lots is not None:
                lots = self._copy_request(lots, LotSizeRequest)
                if not 1 <= len(lots.symbols) <= 64:
                    raise ValueError
            if margin is not None:
                margin = self._copy_request(margin, MarginRequest)
        except (ValueError, TypeError):
            return BrokerReadFailure(BrokerReadErrorCode.INVALID_REQUEST)
        binding = self.observation_binding(facade)
        if type(binding) is BrokerReadFailure:
            return binding
        started = datetime.now(UTC)
        day = started.astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat()
        deadline = time.monotonic() + timeout_seconds
        timed_out = False

        async def collect(factory):
            nonlocal timed_out
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
            try:
                return await self._bounded_observation(factory, deadline, facade=facade)
            except TimeoutError:
                timed_out = True
                return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)

        result = await collect(lambda: self._capture_trade_book(facade))
        history_result = await self._trade_history(facade, history, deadline=deadline) if history is not None else None
        lots_result = await collect(lambda: self._lot_sizes(facade, lots)) if lots is not None else None
        margin_result = await collect(lambda: self._margin(facade, margin)) if margin is not None else None
        ledger_result = await collect(lambda: self._ledger(facade, ledger)) if ledger is not None else None
        if self.observation_binding(facade) != binding:
            return BrokerReadFailure(BrokerReadErrorCode.TARGET_STALE)
        finished = datetime.now(UTC)
        if finished < started:
            return BrokerReadFailure(BrokerReadErrorCode.TARGET_STALE)
        end_day = finished.astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat()
        rows = result.value.trades if type(result) is BrokerReadSuccess else ()
        provider_coverage_json = result.value.provider_coverage_json if type(result) is BrokerReadSuccess else None
        digest = (
            hashlib.sha256(
                json.dumps(
                    [asdict(row) for row in rows], sort_keys=True, separators=(",", ":"), allow_nan=False
                ).encode()
            ).hexdigest()
            if type(result) is BrokerReadSuccess
            else None
        )
        coverage = ObservationCoverage(
            resource="trades.daily",
            availability="available" if type(result) is BrokerReadSuccess else result.code.value,
            query_start=day,
            query_end=end_day,
            trading_date=day if day == end_day else None,
            timezone="Asia/Kolkata",
            page_model="unpaged_documented",
            pages=(),
            observed_count=len(rows),
            source_digest=digest,
            source_revision="broker_read.observations.v1",
            completeness=("window_only" if day == end_day else "partial")
            if type(result) is BrokerReadSuccess else "unknown",
            missing_intervals=("before_current_trading_day",)
            if type(result) is BrokerReadSuccess
            else (day + "/" + end_day,),
            issues=(("collection_crossed_trading_day",) if day != end_day else ())
            + (("read_deadline_exceeded",) if timed_out else ()),
            provider_coverage_json=provider_coverage_json,
            returned_count=len(rows) if type(result) is BrokerReadSuccess else None,
        )
        coverages = [coverage]
        if type(ledger_result) is BrokerReadSuccess:
            coverages.append(ledger_result.value.coverage)
        elif type(ledger_result) is BrokerReadFailure:
            coverages.append(
                ObservationCoverage(
                    resource="ledger.account_postings",
                    availability=ledger_result.code.value,
                    query_start=ledger.start_date,
                    query_end=ledger.end_date,
                    trading_date=None,
                    timezone="Asia/Kolkata",
                    page_model="single_request",
                    pages=(),
                    observed_count=0,
                    source_digest=None,
                    source_revision="broker_read.observations.v1",
                    completeness="unknown",
                )
            )
        if type(history_result) is BrokerReadSuccess:
            rows += history_result.value.trades
            coverages.append(history_result.value.coverage)
        elif type(history_result) is BrokerReadFailure:
            if history_result.code is BrokerReadErrorCode.INVALID_REQUEST:
                return history_result
            coverages.append(
                ObservationCoverage(
                    resource="trades.history",
                    availability=history_result.code.value,
                    query_start=history.start_date,
                    query_end=history.end_date,
                    trading_date=None,
                    timezone="Asia/Kolkata",
                    page_model="unavailable",
                    pages=(),
                    observed_count=0,
                    source_digest=None,
                    source_revision="broker_read.observations.v1",
                    completeness="unknown",
                    missing_intervals=(history.start_date + "/" + history.end_date,),
                )
            )
        for resource, outcome in (("instruments.contracts", lots_result), ("margin.single_estimate", margin_result)):
            if outcome is not None:
                coverages.append(
                    ObservationCoverage(
                        resource=resource,
                        availability="available" if type(outcome) is BrokerReadSuccess else outcome.code.value,
                        query_start=None,
                        query_end=None,
                        trading_date=day,
                        timezone="Asia/Kolkata",
                        page_model="single_request",
                        pages=(),
                        observed_count=(len(outcome.value) if resource == "instruments.contracts" else 1)
                        if type(outcome) is BrokerReadSuccess
                        else 0,
                        source_digest=None,
                        source_revision="broker_read.observations.v1",
                        completeness="requested_scope" if type(outcome) is BrokerReadSuccess else "unknown",
                    )
                )
        captured = BrokerObservationSnapshot(
            binding[0],
            binding[1],
            started.isoformat(),
            finished.isoformat(),
            rows,
            tuple(coverages),
            contracts=lots_result.value if type(lots_result) is BrokerReadSuccess else (),
            margins=(margin_result.value,) if type(margin_result) is BrokerReadSuccess else (),
            account_postings=ledger_result.value.postings if type(ledger_result) is BrokerReadSuccess else (),
        )
        return await self._capture_native_scope(facade, captured, deadline)

    async def _capture_native_scope(
        self, facade: _BrokerReadFacade, captured: BrokerObservationSnapshot, deadline: float,
    ) -> BrokerObservationSnapshot | BrokerReadFailure:
        """Collect optional server-owned primitives through the same read custody."""
        source = self._native_scope_source
        if source is None:
            return captured
        binding = (captured.provenance, captured.provider_account_id)

        async def read() -> BrokerReadFailure | BrokerReadSuccess:
            grant = self._begin(facade, _Operation.ORDER_STATES, None, None)
            if type(grant) is BrokerReadFailure:
                return grant
            try:
                handle = self._revalidate(grant)
                if type(handle) is BrokerReadFailure:
                    return handle
                if source.adapter is not self._adapters.get(grant.selector.adapter_id):
                    return BrokerReadFailure(BrokerReadErrorCode.TARGET_STALE)
                from .canonical_read_plan import current_budget

                budget = current_budget()
                if budget is not None and not budget.take():
                    return BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
                rows = await source.read(handle)
                return self._published(grant, rows)
            finally:
                self._end(grant)
        try:
            outcome = await self._bounded_observation(read, deadline, facade=facade)
        except (TimeoutError, ValueError, TypeError):
            outcome = BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
        if self.observation_binding(facade) != binding:
            return BrokerReadFailure(BrokerReadErrorCode.TARGET_STALE)
        facts = {"availability": "available" if type(outcome) is BrokerReadSuccess else outcome.code.value,
                 "records": outcome.value if type(outcome) is BrokerReadSuccess else None,
                 "provenance": "synthetic", "source_id": source.source_id}
        return replace(captured, native_scope_json=json.dumps(facts, sort_keys=True, separators=(",", ":")))

    def _bound_trade(self, item: object, handle: ConnectedRegistrySession) -> TradeSnapshot:
        trade = self._trade(item)
        native = json.loads(trade.raw_observation_json).get("broker_fields", {})
        account = handle.account_id
        if type(account) is not str or not account:
            raise ValueError
        if trade.broker_account_id is not None and trade.broker_account_id != account:
            raise ValueError
        if handle.selector.adapter_id == "dhan":
            account_names = ("dhanClientId",)
            identities = (
                ("exchangeTradeId", trade.fill_id),
                ("exchangeOrderId", trade.exchange_order_id),
                ("orderId", trade.orderid),
                ("securityId", trade.instrument_id),
            )
            numeric = (("quantity", ("tradedQuantity", "quantity")), ("price", ("tradedPrice", "price")))
        elif handle.selector.adapter_id == "kotakneo":
            account_names = ("actId", "accountId")
            identities = (("flId", trade.fill_id), ("exOrdId", trade.exchange_order_id), ("nOrdNo", trade.orderid))
            # qty is NOT fldQty. avgPrc and flPrc remain independent observations.
            numeric = (("quantity", ("fldQty",)),)
        else:
            account_names, identities, numeric = (), (), ()
        for name in account_names:
            if name in native and (type(native[name]) is not str or native[name] != account):
                raise ValueError
        for name, value in identities:
            if name in native and value is not None and native[name] != value:
                raise ValueError
        for attribute, names in numeric:
            expected = Decimal(getattr(trade, attribute))
            for name in names:
                if name in native and Decimal(self._number_text(native, name, required=True)) != expected:
                    raise ValueError
        return trade

    @staticmethod
    def _native_fields(row: dict[str, object], allowed: frozenset[str]) -> dict | None:
        native = row.get("broker_fields")
        if native is None:
            return None
        if type(native) is not dict or any(type(key) is not str for key in native):
            raise ValueError
        return copy_json_evidence({key: native[key] for key in native if key in allowed})

    @staticmethod
    def _trade_observation_json(row: dict[str, object]) -> str:
        # An allowlist, not arbitrary adapter output, crosses this seam. Native
        # independent quantities/times are observations, not semantic aliases.
        native_keys = frozenset(
            {
                "dhanClientId",
                "orderId",
                "exchangeOrderId",
                "exchangeTradeId",
                "transactionType",
                "exchangeSegment",
                "productType",
                "orderType",
                "tradingSymbol",
                "securityId",
                "tradedQuantity",
                "quantity",
                "tradedPrice",
                "price",
                "createTime",
                "updateTime",
                "exchangeTime",
                "drvExpiryDate",
                "drvOptionType",
                "drvStrikePrice",
                "tradeDate",
                "sebiTax",
                "stt",
                "brokerageCharges",
                "serviceTax",
                "exchangeTransactionCharges",
                "stampDuty",
                "flId",
                "flLeg",
                "nOrdNo",
                "exOrdId",
                "exSeg",
                "rptTp",
                "fldQty",
                "qty",
                "avgPrc",
                "flPrc",
                "flDt",
                "flTm",
                "exTm",
                "flDtTm",
                "hsUpTm",
                "updRecvTm",
                "tok",
                "trdSym",
                "sym",
                "trnsTp",
                "prod",
                "actId",
                "accountId",
                "genNum",
                "genDen",
                "prcNum",
                "prcDen",
                "multiplier",
                "precision",
                "ordDtTm",
                "boeSec",
                "uSec",
                "lotSz",
                "brdLtQty",
                "it",
                "optTp",
                "exp",
                "expDt",
                "stkPrc",
                "prcTp",
                "ordDur",
                "ordGenTp",
                "GuiOrdId",
                "prc",
            }
        )
        retained = {
            key: row[key]
            for key in (
                "fill_id",
                "fill_leg",
                "exchange_order_id",
                "broker_account_id",
                "broker_exchange_segment",
                "broker_product_type",
                "trade_date",
                "created_at",
                "updated_at",
                "exchange_time",
                "fill_time",
                "option_type",
                "expiry",
                "strike_price",
                "underlying",
            )
            if key in row
        }
        if "broker_fields" in row and row["broker_fields"] is not None:
            native = row["broker_fields"]
            if type(native) is not dict or any(type(key) is not str for key in native):
                raise ValueError
            retained["broker_fields"] = {key: native[key] for key in native if key in native_keys}
        return json.dumps(copy_json_evidence(retained), sort_keys=True, separators=(",", ":"), allow_nan=False)

    def _trade(self, item: object) -> TradeSnapshot:
        row = self._record(item, Trade)
        return TradeSnapshot(
            self._text(row, "orderid"),
            self._text(row, "symbol", required=True),
            self._text(row, "instrument_id"),
            self._text(row, "exchange", required=True),
            self._text(row, "action", required=True),
            self._number_text(row, "quantity", required=True),
            self._number_text(row, "price", required=True),
            self._text(row, "product", required=True),
            self._text(row, "timestamp", required=True),
            self._numeric(row, "multiplier"),
            self._numeric(row, "fx_rate"),
            self._boolean(row, "cross_currency"),
            **{
                key: self._text(row, key)
                for key in (
                    "fill_id",
                    "fill_leg",
                    "exchange_order_id",
                    "broker_account_id",
                    "broker_exchange_segment",
                    "broker_product_type",
                    "trade_date",
                    "created_at",
                    "updated_at",
                    "exchange_time",
                    "fill_time",
                )
            },
            raw_observation_json=self._trade_observation_json(row),
        )


def create_broker_read_owner(
    *,
    registry: BrokerRegistry,
    session_provider: AuthenticatingSessionProvider,
    adapters: dict[str, object],
    workspace_path: Path,
    rate_limiter: object | None = None,
    runtime_accepting_requests: Callable[[], bool],
    native_scope_source: object | None = None,
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
    if native_scope_source is not None:
        from .native_scope_primitives import SyntheticNativeScopeSource

        if (type(native_scope_source) is not SyntheticNativeScopeSource
                or native_scope_source.workspace_path != workspace_path.resolve()
                or not any(native_scope_source.adapter is adapter for adapter in adapters.values())):
            raise RegistrySessionUnavailable
    return BrokerReadOwner(
        registry=registry,
        session_provider=session_provider,
        adapters=adapters,
        workspace_path=workspace_path,
        rate_limiter=rate_limiter,
        runtime_accepting_requests=runtime_accepting_requests,
        native_scope_source=native_scope_source,
    )
