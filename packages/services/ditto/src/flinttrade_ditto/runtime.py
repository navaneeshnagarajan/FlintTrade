"""In-process owner for Ditto mirroring, risk reads, and emergency flattening."""

from __future__ import annotations

import hashlib
import logging
import math
import threading
import time
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from flinttrade_core.models import Order
from flinttrade_gateway.log_safety import account_ref

from .account_manager import BrokerAccount
from .mirror import (
    AllocationMode,
    MirrorRiskError,
    PositionIdentity,
    PositionMirror,
    PositionWatcher,
    normalise_position_row,
    position_identity,
)

logger = logging.getLogger("flinttrade.ditto.runtime")

_IST = timezone(timedelta(hours=5, minutes=30))
_MAX_STATUS_ERRORS = 20
_RECONCILIATION_REQUIRED_ERROR = (
    "Mirror dispatch did not complete; stop Ditto, reconcile target positions, and restart"
)
_SOURCE_POSITION_UNAVAILABLE_ERROR = (
    "Source position state became unavailable; stop Ditto, reconcile target positions, and restart"
)
_TARGET_RISK_BLOCKED_ERROR = (
    "Target-account risk state or daily loss limit blocked mirroring; "
    "stop Ditto, reconcile target positions, and restart"
)


class DittoCapabilityUnavailable(RuntimeError):
    """Raised when Ditto cannot prove the state needed for a requested action."""


def _ditto_ledger_account_id(account_id: str) -> str:
    """Return a stable non-secret ledger identity outside the main bridge scope."""
    digest = hashlib.sha256(f"ditto\0{account_id}".encode()).hexdigest()
    return f"ditto-{digest[:24]}"


class _DittoLifecycleStore:
    """Namespace Ditto dispatches while delegating to the app-owned ledger."""

    def __init__(self, delegate: Any, account_ids: Mapping[str, str]) -> None:
        self._delegate = delegate
        self._account_ids = dict(account_ids)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def prepare_dispatch(self, **kwargs: Any) -> str:
        external_account_id = str(kwargs.get("account_id") or "")
        ledger_account_id = self._account_ids.get(external_account_id)
        if ledger_account_id is None:
            raise DittoCapabilityUnavailable("managed account is unavailable")
        return str(
            self._delegate.prepare_dispatch(
                **{**kwargs, "account_id": ledger_account_id}
            )
        )


def _finite_number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _required_finite_number(value: Any) -> float:
    """Return a finite real number or fail when broker risk state is incomplete."""
    if isinstance(value, bool):
        raise MirrorRiskError("target-account risk state is unavailable")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise MirrorRiskError("target-account risk state is unavailable") from exc
    if not math.isfinite(number):
        raise MirrorRiskError("target-account risk state is unavailable")
    return number


def _enforce_daily_loss_limit(account: BrokerAccount, state: Mapping[str, Any]) -> None:
    """Require complete target risk and enforce the configured daily-loss cap."""
    cap = _required_finite_number(account.max_loss_daily)
    if cap < 0:
        raise MirrorRiskError("target-account risk configuration is invalid")
    pnl_today = _required_finite_number(state.get("pnl_today"))
    if cap > 0 and pnl_today <= -cap:
        raise MirrorRiskError("target-account daily loss limit has been reached")


def _validate_target_risk_state(account: BrokerAccount, state: Mapping[str, Any]) -> None:
    """Validate the complete funds/position risk snapshot used for mirror admission."""
    for field in ("available_balance", "used_margin", "total_balance", "pnl_today", "positions"):
        _required_finite_number(state.get(field))
    _enforce_daily_loss_limit(account, state)


def _normalise_mode(mode: str) -> AllocationMode:
    value = str(mode or "").strip().upper()
    aliases = {
        "PROPORTIONAL": AllocationMode.WEIGHTED,
        "FIXED": AllocationMode.EQUAL,
        "EQUAL": AllocationMode.EQUAL,
        "WEIGHTED": AllocationMode.WEIGHTED,
        "MARGIN_AWARE": AllocationMode.MARGIN_AWARE,
        "LOT_BASED": AllocationMode.LOT_BASED,
        "MULTIPLIER": AllocationMode.MULTIPLIER,
    }
    try:
        return aliases[value]
    except KeyError as exc:
        raise DittoCapabilityUnavailable("unsupported Ditto allocation mode") from exc


def _mode_api_value(mode: AllocationMode) -> str:
    """Return the stable lowercase allocation-mode value used by the HTTP API."""
    return mode.value.lower()


class DittoRouterOwner:
    """Own a dedicated gated router and per-account OpenAlgo clients.

    Ditto accounts may point at different OpenAlgo origins and therefore cannot
    borrow the application's single bridge client. This owner builds one immutable
    ``BrokerRouter`` generation over those account-bound clients, with the same
    process-wide gate secret, ACL check, per-second rate limiter, and Layer-5 write
    admission used by the main router.
    """

    def __init__(
        self,
        accounts: list[BrokerAccount],
        actor_id: str,
        *,
        write_admission: Callable[[bool, str], Any],
        intent_journal: Any,
        safety_system: Any,
        time_scheduler: Any | None = None,
        lifecycle_store: Any | None = None,
    ) -> None:
        if not accounts:
            raise DittoCapabilityUnavailable("no managed accounts")
        account_ids = [str(account.account_id).strip() for account in accounts]
        if any(not account_id for account_id in account_ids):
            raise DittoCapabilityUnavailable("managed account identity is unavailable")
        if len(set(account_ids)) != len(account_ids):
            raise DittoCapabilityUnavailable("managed account identities must be unique")
        if not str(actor_id).strip():
            raise DittoCapabilityUnavailable("authenticated operator identity is unavailable")
        if not callable(write_admission):
            raise DittoCapabilityUnavailable("broker write admission is unavailable")
        if intent_journal is None:
            raise DittoCapabilityUnavailable("emergency intent journal is unavailable")
        if not callable(getattr(safety_system, "check_order", None)):
            raise DittoCapabilityUnavailable("validated order safety system is unavailable")

        from flinttrade_core.config import Settings  # noqa: PLC0415
        from flinttrade_core.openalgo_client import OpenAlgoClient  # noqa: PLC0415
        from flinttrade_engine.safety import SafetyGate  # noqa: PLC0415
        from flinttrade_gateway.brokers._base import Session  # noqa: PLC0415
        from flinttrade_gateway.brokers.openalgo import OpenAlgoAdapter  # noqa: PLC0415
        from flinttrade_gateway.rate_limiter import BrokerRateLimiter  # noqa: PLC0415
        from flinttrade_gateway.registry import BrokerRegistry  # noqa: PLC0415
        from flinttrade_gateway.router import BrokerRouter  # noqa: PLC0415
        from flinttrade_gateway.routing_config import (  # noqa: PLC0415
            CostAwareConfig,
            DataRouting,
            ExecutionRouting,
            FailoverConfig,
            RoutingConfig,
        )
        from flinttrade_gateway.session_provider import AuthenticatingSessionProvider  # noqa: PLC0415

        self.accounts = list(accounts)
        self.actor_id = str(actor_id).strip()
        self._intent_journal = intent_journal
        self._safety_system = safety_system
        self._time_scheduler = time_scheduler
        self._ledger_account_ids = {
            account_id: _ditto_ledger_account_id(account_id)
            for account_id in account_ids
        }
        self._external_account_ids = {
            ledger_account_id: account_id
            for account_id, ledger_account_id in self._ledger_account_ids.items()
        }
        self._clients: dict[str, OpenAlgoClient] = {}
        self._client_close_attempts: dict[
            str,
            tuple[Any, threading.Thread, dict[str, bool | None]],
        ] = {}
        self._registry: Any | None = None
        self._adapter: Any | None = None
        self.router: Any | None = None

        try:
            for account in self.accounts:
                settings = Settings(
                    openalgo_host=account.openalgo_host,
                    openalgo_api_key=account.api_key,
                )
                self._clients[account.account_id] = OpenAlgoClient(settings)

            registry = BrokerRegistry()
            for account in self.accounts:
                registry.put_session(
                    "openalgo",
                    account.account_id,
                    Session(
                        access_token="",
                        expires_at=4_102_444_800.0,
                        account_id=self._ledger_account_ids[account.account_id],
                        adapter_id="openalgo",
                    ),
                )

            selectors = tuple(f"openalgo:{account.account_id}" for account in self.accounts)
            default_selector = selectors[0]
            routing = RoutingConfig(
                registered=selectors,
                execution=ExecutionRouting(default=default_selector),
                data=DataRouting(
                    ticks=default_selector,
                    historical=default_selector,
                    option_chains=default_selector,
                    quote=default_selector,
                ),
                failover=FailoverConfig(),
                cost_aware=CostAwareConfig(),
                account_acls={
                    "openalgo": {
                        account.account_id: [self.actor_id]
                        for account in self.accounts
                    }
                },
            )
            session_provider = AuthenticatingSessionProvider(registry, routing.account_acls)

            def client_for_session(session: Any) -> Any:
                account_id = self._external_account_ids.get(str(session.account_id))
                if account_id is None:
                    raise DittoCapabilityUnavailable("managed account is unavailable")
                return self._clients[account_id]

            adapter = OpenAlgoAdapter(
                client_factory=client_for_session,
                local_state_provider=lifecycle_store,
            )
            self._registry = registry
            self._adapter = adapter
            rate_limiter = BrokerRateLimiter.from_capabilities(
                {"openalgo": adapter.capabilities}
            )
            gate = SafetyGate()
            router_lifecycle_store = (
                _DittoLifecycleStore(lifecycle_store, self._ledger_account_ids)
                if lifecycle_store is not None
                else None
            )
            self.router = BrokerRouter(
                {"openalgo": adapter},
                session_provider,
                consume_gate=gate.consume,
                config=routing,
                rate_limiter=rate_limiter,
                write_admission=write_admission,
                lifecycle_store=router_lifecycle_store,
            )
        except Exception:
            cleanup_deadline = time.monotonic() + 5.0
            if not self._close_clients(deadline=cleanup_deadline):
                logger.error("Ditto router initialisation cleanup did not complete")
            raise

    def reconciliation_targets(self) -> list[tuple[Any, Any]]:
        """Return the live account-bound adapter sessions owned by this router."""
        registry = self._registry
        adapter = self._adapter
        if self.router is None or registry is None or adapter is None:
            return []
        targets: list[tuple[Any, Any]] = []
        for account in self.accounts:
            try:
                session = registry.get_session_for("openalgo", account.account_id)
            except Exception:
                continue
            targets.append((adapter, session))
        return targets

    def run_router_call(self, account_id: str, awaitable: Any) -> Any:
        """Run router work on a persistent client-owned event loop."""
        if account_id not in self._clients:
            close_coro = getattr(awaitable, "close", None)
            if callable(close_coro):
                close_coro()
            raise DittoCapabilityUnavailable("managed account is unavailable")
        control_client = next(iter(self._clients.values()))
        return control_client.run_sync(awaitable)

    @contextmanager
    def admit_order(self, account_id: str, order: Order) -> Any:
        """Lease complete target-account admission through broker acknowledgement."""
        from flinttrade_core.l2_state import gather_safety_state  # noqa: PLC0415
        from flinttrade_gateway.log_safety import account_ref  # noqa: PLC0415

        client = self._clients.get(account_id)
        if client is None:
            raise DittoCapabilityUnavailable("managed account is unavailable")
        account = next(
            (candidate for candidate in self.accounts if candidate.account_id == account_id),
            None,
        )
        if account is None:
            raise DittoCapabilityUnavailable("managed account is unavailable")
        config = {
            "OPENALGO_CLIENT": client,
            "TIME_SCHEDULER": self._time_scheduler,
        }
        selector = f"openalgo:{account_id}"
        with self._safety_system.order_admission(selector) as lease:
            try:
                portfolio_state = self.run_router_call(
                    account_id,
                    gather_safety_state(
                        config,
                        "openalgo",
                        account_id="default",
                        orders=[order],
                        reservations=lease.reservations,
                        include_order_margin=True,
                    ),
                )
                lease.reconcile(getattr(portfolio_state, "reconciled_reservation_ids", ()))
            except Exception as exc:
                logger.error(
                    "Ditto safety state unavailable for %s (%s)",
                    account_ref(account_id),
                    type(exc).__name__,
                )
                raise MirrorRiskError("target-account risk state is unavailable") from exc

            _enforce_daily_loss_limit(
                account,
                {"pnl_today": getattr(portfolio_state, "daily_pnl", None)},
            )

            try:
                admission = portfolio_state.admission_for(0)
                results = self._safety_system.check_order(
                    order,
                    selector=selector,
                    positions=admission.positions,
                    used_margin=admission.used_margin,
                    total_balance=portfolio_state.total_balance,
                    daily_pnl=portfolio_state.daily_pnl,
                    starting_capital=portfolio_state.starting_capital,
                    ltp=portfolio_state.ltp_for(order),
                    net_delta=admission.net_delta,
                    net_vega=admission.net_vega,
                )
                blocked = next((result for result in results if not result.passed), None)
            except Exception as exc:
                logger.error(
                    "Ditto safety admission unavailable for %s (%s)",
                    account_ref(account_id),
                    type(exc).__name__,
                )
                raise DittoCapabilityUnavailable("target-account safety admission is unavailable") from exc
            if blocked is not None:
                logger.warning(
                    "Ditto order blocked by safety layer %s for %s",
                    blocked.layer,
                    account_ref(account_id),
                )
                raise DittoCapabilityUnavailable("mirror order was blocked by the safety system")
            yield lease, admission.positions

    def risk_state(self, account: BrokerAccount) -> dict[str, Any]:
        """Read one account's funds and position P&L from its real OpenAlgo origin."""
        client = self._clients[account.account_id]
        funds = client.run_sync(client.funds())
        positions = client.run_sync(client.positionbook())
        return {
            "available_balance": _required_finite_number(funds.available_balance),
            "used_margin": _required_finite_number(funds.used_margin),
            "total_balance": _required_finite_number(funds.total_balance),
            "pnl_today": sum(_required_finite_number(position.pnl) for position in positions),
            "positions": sum(
                1 for position in positions if _required_finite_number(position.quantity) != 0
            ),
        }

    def dispatch_kill_all(
        self,
        *,
        actor_id: str,
        jti: str,
        reason: str,
    ) -> Any:
        """Cancel and flatten every managed account through gated emergency writes."""
        from flinttrade_engine.request_context import RequestContext  # noqa: PLC0415
        from flinttrade_engine.safety import (  # noqa: PLC0415
            EmergencyBrokerTarget,
            EmergencyWritePolicy,
            GatedEmergencyBrokerDispatcher,
        )

        targets = tuple(
            EmergencyBrokerTarget(
                request_ctx=RequestContext(
                    jti=f"{jti}:{index}",
                    actor_type="human",
                    actor_id=actor_id,
                    mode="live",
                    selector=f"openalgo:{account.account_id}",
                ),
                adapter_id="openalgo",
                account_id=account.account_id,
            )
            for index, account in enumerate(self.accounts)
        )
        control_client = next(iter(self._clients.values()))
        dispatcher = GatedEmergencyBrokerDispatcher(
            router_provider=lambda: self.router,
            targets_provider=lambda: targets,
            run_awaitable=control_client.run_sync,
            intent_journal=self._intent_journal,
        )
        return dispatcher.dispatch(
            EmergencyWritePolicy(
                name="ditto_kill_all",
                verbs=("cancel_all_orders", "exit_all_positions"),
            ),
            reason=reason,
        )

    def _close_clients(self, *, deadline: float) -> bool:
        """Close each remaining client within one shared absolute deadline."""
        complete = True
        attempts = getattr(self, "_client_close_attempts", None)
        if attempts is None:
            attempts = {}
            self._client_close_attempts = attempts
        account_ids = list(self._clients)
        if account_ids:
            account_ids = account_ids[1:] + account_ids[:1]
        for account_id in account_ids:
            client = self._clients.get(account_id)
            if client is None:
                continue
            attempt = attempts.get(account_id)
            if attempt is None or attempt[0] is not client:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                state: dict[str, bool | None] = {"succeeded": None}

                def close_client(
                    owned_client: Any = client,
                    close_timeout: float = remaining,
                    outcome: dict[str, bool | None] = state,
                ) -> None:
                    try:
                        owned_client.close_sync(timeout=close_timeout)
                    except Exception:  # noqa: BLE001 - detail may contain credentials
                        outcome["succeeded"] = False
                    else:
                        outcome["succeeded"] = True

                thread = threading.Thread(
                    target=close_client,
                    name=f"ditto-client-close-{account_ref(account_id)}",
                    daemon=True,
                )
                attempt = (client, thread, state)
                attempts[account_id] = attempt
                thread.start()

            _attempt_client, thread, state = attempt
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
            if thread.is_alive():
                return False
            attempts.pop(account_id, None)
            if state["succeeded"] is not True:
                logger.error("Ditto managed-account client cleanup failed")
                complete = False
            else:
                if self._clients.get(account_id) is client:
                    self._clients.pop(account_id, None)
        return complete and not self._clients

    def close(self, *, timeout: float = 5.0) -> bool:
        """Revoke this router generation, drain writes, then close all clients."""
        deadline = time.monotonic() + max(0.0, timeout)
        router = self.router
        if router is not None:
            remaining = max(0.0, deadline - time.monotonic())
            if not router.revoke_and_drain(timeout=remaining):
                return False
        if not self._close_clients(deadline=deadline):
            return False
        self.router = None
        self._adapter = None
        self._registry = None
        return True


class DittoRuntime:
    """Coordinate one live mirror session plus bounded read/emergency operations."""

    def __init__(
        self,
        *,
        account_provider: Callable[[], list[BrokerAccount]],
        watcher_factory: Callable[[BrokerAccount], Any] = PositionWatcher,
        router_owner_factory: Callable[[list[BrokerAccount], str], Any] | None = None,
    ) -> None:
        self._account_provider = account_provider
        self._watcher_factory = watcher_factory
        self._router_owner_factory = router_owner_factory or self._owner_unavailable
        self._lock = threading.RLock()
        self._dispatch_lock = threading.Lock()
        self._active = False
        self._source_account: str | None = None
        self._target_accounts: list[str] = []
        self._mode = "equal"
        self._mirrored_positions = 0
        self._last_sync: str | None = None
        self._errors: list[str] = []
        self._source_quantities: dict[PositionIdentity, int] = {}
        self._watcher: Any | None = None
        self._mirror: PositionMirror | None = None
        self._router_owner: Any | None = None
        self._next_generation = 0
        self._claimed_generation: int | None = None
        self._starting = False
        self._lifecycle = "idle"
        self._reconciliation_needed = False
        self._one_shot_lock = threading.RLock()
        self._retained_router_owners: list[Any] = []

    @staticmethod
    def _owner_unavailable(_accounts: list[BrokerAccount], _actor_id: str) -> Any:
        raise DittoCapabilityUnavailable("gated Ditto router is unavailable")

    def _accounts(self) -> list[BrokerAccount]:
        try:
            accounts = list(self._account_provider())
        except Exception as exc:
            raise DittoCapabilityUnavailable("managed accounts are unavailable") from exc
        if any(not isinstance(account, BrokerAccount) for account in accounts):
            raise DittoCapabilityUnavailable("managed account registry returned invalid data")
        return accounts

    @staticmethod
    def _close_one_shot_owner(owner: Any, *, timeout: float) -> bool:
        try:
            return owner.close(timeout=max(0.0, timeout)) is True
        except Exception:  # noqa: BLE001 - owner detail must remain private
            logger.error("Ditto one-shot router cleanup failed")
            return False

    def _retain_router_owner(self, owner: Any) -> None:
        with self._lock:
            if all(retained is not owner for retained in self._retained_router_owners):
                self._retained_router_owners.append(owner)

    def _retry_retained_router_owners(self, *, deadline: float) -> bool:
        with self._one_shot_lock:
            with self._lock:
                retained = list(self._retained_router_owners)
            for owner in retained:
                closed = self._close_one_shot_owner(
                    owner,
                    timeout=max(0.0, deadline - time.monotonic()),
                )
                if closed:
                    with self._lock:
                        self._retained_router_owners = [
                            candidate
                            for candidate in self._retained_router_owners
                            if candidate is not owner
                        ]
            with self._lock:
                return not self._retained_router_owners

    def status(self) -> dict[str, Any]:
        with self._lock:
            lifecycle = self._lifecycle
            if self._retained_router_owners and lifecycle not in {"starting", "stopping"}:
                lifecycle = "retained-shutdown"
            elif self._reconciliation_needed and lifecycle == "idle":
                lifecycle = "reconciliation-needed"
            return {
                "active": self._active,
                "lifecycle": lifecycle,
                "source_account": self._source_account,
                "target_accounts": list(self._target_accounts),
                "mode": self._mode,
                "mirrored_positions": self._mirrored_positions,
                "last_sync": self._last_sync,
                "errors": list(self._errors),
            }

    def reconciliation_targets(self) -> list[tuple[Any, Any]]:
        """Snapshot the active Ditto router's broker reconciliation targets."""
        with self._lock:
            owner = self._router_owner
        if owner is None:
            return []
        provider = getattr(owner, "reconciliation_targets", None)
        if not callable(provider):
            raise DittoCapabilityUnavailable(
                "Ditto reconciliation target provider is unavailable"
            )
        targets = list(provider())
        if any(not isinstance(target, tuple) or len(target) != 2 for target in targets):
            raise DittoCapabilityUnavailable("Ditto reconciliation targets are invalid")
        return targets

    def start(
        self,
        *,
        source_account: str,
        target_accounts: list[str],
        mode: str,
        actor_id: str,
        jti: str,
    ) -> dict[str, Any]:
        """Prime the source state and start mirroring future position deltas."""
        source_id = str(source_account).strip()
        target_ids = [str(account_id).strip() for account_id in target_accounts]
        if not source_id or not target_ids or any(not account_id for account_id in target_ids):
            raise DittoCapabilityUnavailable("source and target accounts are required")
        if len(set(target_ids)) != len(target_ids) or source_id in target_ids:
            raise DittoCapabilityUnavailable("Ditto source and target accounts must be distinct")
        if not str(actor_id).strip() or not str(jti).strip():
            raise DittoCapabilityUnavailable("authenticated operator identity is unavailable")

        allocation_mode = _normalise_mode(mode)
        with self._lock:
            if self._claimed_generation is not None or self._retained_router_owners:
                raise DittoCapabilityUnavailable(
                    "a Ditto mirror session is already active or awaiting shutdown"
                )
            self._next_generation += 1
            generation = self._next_generation
            self._claimed_generation = generation
            self._starting = True
            self._lifecycle = "starting"
            self._active = False
            self._source_account = source_id
            self._target_accounts = list(target_ids)
            self._mode = _mode_api_value(allocation_mode)
            self._mirrored_positions = 0
            self._last_sync = None
            self._errors = []
            self._source_quantities = {}
            self._reconciliation_needed = False

        owner: Any | None = None
        watcher: Any | None = None
        mirror: PositionMirror | None = None
        try:
            by_id = {account.account_id: account for account in self._accounts()}
            source = by_id.get(source_id)
            targets = [by_id.get(account_id) for account_id in target_ids]
            if source is None or any(account is None for account in targets):
                raise DittoCapabilityUnavailable("one or more managed accounts were not found")
            if not source.enabled or any(not account.enabled for account in targets if account is not None):
                raise DittoCapabilityUnavailable("source and target accounts must be enabled")
            resolved_targets = [account for account in targets if account is not None]
            if any(account.is_master for account in resolved_targets):
                raise DittoCapabilityUnavailable("master accounts cannot be selected as Ditto targets")
            effective_targets = [
                account for account in resolved_targets if account.enabled and not account.is_master
            ]
            if not effective_targets:
                raise DittoCapabilityUnavailable("no executable Ditto target accounts are available")

            owner = self._router_owner_factory(effective_targets, str(actor_id).strip())
            watcher = self._watcher_factory(source)
            mirror = PositionMirror(
                effective_targets,
                mode=allocation_mode,
                broker_router=owner.router,
                actor_id=str(actor_id).strip(),
                actor_type="human",
                trading_mode="live",
                run_router_call=owner.run_router_call,
                admit_order=owner.admit_order,
            )
            primed = watcher.prime()
            if not isinstance(primed, dict):
                raise DittoCapabilityUnavailable("source position state is unavailable")
            quantities: dict[PositionIdentity, int] = {}
            for snapshot_identity, position in primed.items():
                normalised = normalise_position_row(position)
                identity = position_identity(normalised)
                if snapshot_identity != identity:
                    raise DittoCapabilityUnavailable("source position state is unavailable")
                quantities[identity] = normalised["quantity"]

            def handle_position_change(account_id: str, position: dict[str, Any]) -> None:
                self._handle_position_change(generation, account_id, position)

            def handle_source_error(account_id: str) -> None:
                self._handle_source_error(generation, account_id)

            register_error_callback = getattr(watcher, "on_error", None)
            if not callable(register_error_callback):
                raise DittoCapabilityUnavailable("source watcher failure reporting is unavailable")
            watcher.on_change(handle_position_change)
            register_error_callback(handle_source_error)
            with self._lock:
                if self._claimed_generation != generation:
                    raise DittoCapabilityUnavailable("Ditto generation ownership was lost")
                self._active = True
                self._lifecycle = "active"
                self._source_quantities = quantities
                self._watcher = watcher
                self._mirror = mirror
                self._router_owner = owner
            watcher.start()
            with self._lock:
                if self._claimed_generation == generation:
                    self._starting = False
        except Exception as exc:
            with self._lock:
                self._active = False
                self._starting = False
                self._lifecycle = "stopping"

            watcher_stopped = True
            if watcher is not None:
                try:
                    watcher_stopped = watcher.stop(timeout=5.0) is True
                except Exception:  # noqa: BLE001 - cleanup failure stays generic
                    watcher_stopped = False
                    logger.warning("Ditto source watcher cleanup did not complete")

            owner_closed = owner is None
            if owner is not None and watcher_stopped:
                try:
                    owner_closed = owner.close(timeout=5.0) is True
                except Exception:  # noqa: BLE001 - cleanup failure stays generic
                    owner_closed = False
                    logger.warning("Ditto router cleanup did not complete")

            cleanup_complete = watcher_stopped and owner_closed
            with self._lock:
                if self._claimed_generation == generation:
                    if cleanup_complete:
                        self._watcher = None
                        self._mirror = None
                        self._router_owner = None
                        self._source_account = None
                        self._target_accounts = []
                        self._source_quantities = {}
                        self._claimed_generation = None
                        self._lifecycle = "idle"
                    else:
                        self._source_account = source_id
                        self._target_accounts = list(target_ids)
                        self._mode = _mode_api_value(allocation_mode)
                        self._watcher = watcher
                        self._mirror = mirror
                        self._router_owner = owner
                        self._lifecycle = "retained-shutdown"

            if not cleanup_complete:
                raise DittoCapabilityUnavailable(
                    "Ditto start failed and cleanup did not complete"
                ) from exc
            if isinstance(exc, DittoCapabilityUnavailable):
                raise
            raise DittoCapabilityUnavailable("source position state is unavailable") from exc
        return self.status()

    def _handle_source_error(self, generation: int, _account_id: str) -> None:
        paused = False
        with self._lock:
            if self._claimed_generation == generation and self._active:
                self._active = False
                self._reconciliation_needed = True
                if self._lifecycle not in {"stopping", "retained-shutdown"}:
                    self._lifecycle = "reconciliation-needed"
                self._errors = (self._errors + [_SOURCE_POSITION_UNAVAILABLE_ERROR])[
                    -_MAX_STATUS_ERRORS:
                ]
                paused = True
        if paused:
            logger.error("Ditto source position polling failed; session paused")

    @staticmethod
    def _prove_target_risk(owner: Any) -> None:
        """Prove every selected target is below its daily-loss cap before a delta."""
        accounts = getattr(owner, "accounts", None)
        risk_state = getattr(owner, "risk_state", None)
        if not isinstance(accounts, list) or not accounts or not callable(risk_state):
            raise MirrorRiskError("target-account risk state is unavailable")
        for account in accounts:
            if not isinstance(account, BrokerAccount):
                raise MirrorRiskError("target-account risk state is unavailable")
            state = risk_state(account)
            if not isinstance(state, Mapping):
                raise MirrorRiskError("target-account risk state is unavailable")
            _validate_target_risk_state(account, state)

    def _handle_position_change(
        self,
        generation: int,
        _account_id: str,
        position: dict[str, Any],
    ) -> None:
        try:
            normalised = normalise_position_row(position)
        except Exception:
            paused = False
            with self._lock:
                if self._claimed_generation == generation and self._active:
                    self._active = False
                    self._lifecycle = "reconciliation-needed"
                    self._reconciliation_needed = True
                    self._errors = (self._errors + [_RECONCILIATION_REQUIRED_ERROR])[
                        -_MAX_STATUS_ERRORS:
                    ]
                    paused = True
            if paused:
                logger.error("Ditto source position change was invalid; session paused")
            return
        identity = position_identity(normalised)
        symbol = normalised["symbol"]
        current_quantity = normalised["quantity"]
        with self._dispatch_lock:
            with self._lock:
                if (
                    self._claimed_generation != generation
                    or not self._active
                    or self._mirror is None
                    or self._router_owner is None
                ):
                    return
                previous_quantity = self._source_quantities.get(identity, 0)
                self._source_quantities[identity] = current_quantity
                mirror = self._mirror
                owner = self._router_owner
            delta = current_quantity - previous_quantity
            if delta == 0:
                return
            try:
                self._prove_target_risk(owner)
            except Exception:
                logger.error("Ditto target-account risk blocked mirroring; session paused")
                with self._lock:
                    if self._claimed_generation == generation:
                        self._active = False
                        self._reconciliation_needed = True
                        if self._lifecycle not in {"stopping", "retained-shutdown"}:
                            self._lifecycle = "reconciliation-needed"
                        self._errors = (self._errors + [_TARGET_RISK_BLOCKED_ERROR])[
                            -_MAX_STATUS_ERRORS:
                        ]
                return
            try:
                result = mirror.execute(
                    Order(
                        symbol=symbol,
                        exchange=normalised["exchange"],
                        action="BUY" if delta > 0 else "SELL",
                        product=normalised["product"],
                        quantity=str(abs(delta)),
                        strategy="FlintDitto",
                    )
                )
            except Exception:
                logger.error("Ditto mirror dispatch failed; reconciliation is required")
                with self._lock:
                    if self._claimed_generation == generation:
                        self._active = False
                        self._reconciliation_needed = True
                        if self._lifecycle not in {"stopping", "retained-shutdown"}:
                            self._lifecycle = "reconciliation-needed"
                        self._errors = (self._errors + [_RECONCILIATION_REQUIRED_ERROR])[
                            -_MAX_STATUS_ERRORS:
                        ]
                return

            with self._lock:
                if self._claimed_generation != generation:
                    return
                self._mirrored_positions += result.successful
                if result.all_succeeded:
                    self._last_sync = datetime.now(_IST).isoformat()
                else:
                    self._active = False
                    self._reconciliation_needed = True
                    if self._lifecycle not in {"stopping", "retained-shutdown"}:
                        self._lifecycle = "reconciliation-needed"
                    status_error = (
                        _TARGET_RISK_BLOCKED_ERROR
                        if any(
                            item.failure_code == "risk_blocked"
                            for item in result.results
                        )
                        else _RECONCILIATION_REQUIRED_ERROR
                    )
                    self._errors = (self._errors + [status_error])[-_MAX_STATUS_ERRORS:]

    def stop(self, *, timeout: float = 5.0) -> dict[str, Any]:
        """Stop the watcher and drain the dedicated router generation."""
        deadline = time.monotonic() + max(0.0, timeout)
        with self._lock:
            if self._starting:
                raise DittoCapabilityUnavailable("Ditto mirror session is still starting")
            if self._lifecycle == "stopping":
                raise DittoCapabilityUnavailable("Ditto mirror session is already stopping")
            generation = self._claimed_generation
            watcher = self._watcher
            owner = self._router_owner
            self._active = False
            if generation is not None:
                self._lifecycle = "stopping"

        if generation is None:
            if not self._retry_retained_router_owners(deadline=deadline):
                raise DittoCapabilityUnavailable("Ditto router cleanup did not complete")
            return self.status()

        remaining = max(0.0, deadline - time.monotonic())
        dispatch_quiesced = self._dispatch_lock.acquire(timeout=remaining)
        if not dispatch_quiesced:
            with self._lock:
                if self._claimed_generation == generation:
                    self._lifecycle = "retained-shutdown"
            raise DittoCapabilityUnavailable("Ditto mirror dispatch did not quiesce before timeout")
        self._dispatch_lock.release()

        if watcher is not None:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                watcher_stopped = watcher.stop(timeout=remaining) is True
            except Exception as exc:  # noqa: BLE001 - broker/runtime detail stays redacted
                logger.error("Ditto source watcher shutdown failed")
                with self._lock:
                    if self._claimed_generation == generation:
                        self._lifecycle = "retained-shutdown"
                raise DittoCapabilityUnavailable("Ditto source watcher did not stop") from exc
            if not watcher_stopped:
                with self._lock:
                    if self._claimed_generation == generation:
                        self._lifecycle = "retained-shutdown"
                raise DittoCapabilityUnavailable("Ditto source watcher did not stop before timeout")

        if owner is not None:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                owner_closed = owner.close(timeout=remaining) is True
            except Exception as exc:  # noqa: BLE001 - broker/runtime detail stays redacted
                logger.error("Ditto router shutdown failed")
                with self._lock:
                    if self._claimed_generation == generation:
                        self._lifecycle = "retained-shutdown"
                raise DittoCapabilityUnavailable("Ditto router did not drain") from exc
            if not owner_closed:
                with self._lock:
                    if self._claimed_generation == generation:
                        self._lifecycle = "retained-shutdown"
                raise DittoCapabilityUnavailable("Ditto router did not drain before timeout")

        with self._lock:
            if self._claimed_generation == generation:
                self._watcher = None
                self._mirror = None
                self._router_owner = None
                self._source_account = None
                self._target_accounts = []
                self._source_quantities = {}
                self._claimed_generation = None
                self._lifecycle = (
                    "reconciliation-needed" if self._reconciliation_needed else "idle"
                )
        if not self._retry_retained_router_owners(deadline=deadline):
            raise DittoCapabilityUnavailable("Ditto router cleanup did not complete")
        return self.status()

    def shutdown(self, *, timeout: float = 5.0) -> bool:
        try:
            self.stop(timeout=timeout)
        except Exception:  # noqa: BLE001 - shutdown reports failure without broker detail
            logger.error("Ditto shutdown did not complete")
            return False
        return True

    def risk_snapshot(self) -> dict[str, Any]:
        """Return a complete real-state snapshot or fail closed with no partial data."""
        deadline = time.monotonic() + 5.0
        with self._one_shot_lock:
            if not self._retry_retained_router_owners(deadline=deadline):
                raise DittoCapabilityUnavailable("managed-account router cleanup is incomplete")
            accounts = self._accounts()
            if not accounts:
                return {
                    "complete": True,
                    "aggregate_pnl": 0.0,
                    "aggregate_capital": 0.0,
                    "accounts": [],
                }
            try:
                owner = self._router_owner_factory(accounts, "ditto-risk-read")
            except Exception as exc:
                raise DittoCapabilityUnavailable("managed-account risk state is unavailable") from exc

            rows: list[dict[str, Any]] = []
            read_error: Exception | None = None
            try:
                for account in accounts:
                    state = owner.risk_state(account)
                    capital = _finite_number(state.get("total_balance"))
                    used_margin = _finite_number(state.get("used_margin"))
                    pnl = _finite_number(state.get("pnl_today"))
                    loss_ratio = (
                        (-pnl / account.max_loss_daily)
                        if pnl < 0 and account.max_loss_daily > 0
                        else 0.0
                    )
                    risk_status = (
                        "PAUSED"
                        if not account.enabled
                        else "CRITICAL"
                        if loss_ratio >= 1.0
                        else "WARNING"
                        if loss_ratio >= 0.8
                        else "OK"
                    )
                    rows.append(
                        {
                            "id": account.account_id,
                            "name": account.name or account.account_id,
                            "margin_used_pct": round(
                                (used_margin / capital * 100.0) if capital > 0 else 0.0,
                                2,
                            ),
                            "pnl_today": pnl,
                            "positions": int(_finite_number(state.get("positions"))),
                            "risk_status": risk_status,
                            "capital": capital,
                        }
                    )
            except Exception as exc:  # noqa: BLE001 - converted to a bounded capability error
                read_error = exc

            owner_closed = self._close_one_shot_owner(
                owner,
                timeout=max(0.0, deadline - time.monotonic()),
            )
            if not owner_closed:
                self._retain_router_owner(owner)
                raise DittoCapabilityUnavailable(
                    "managed-account risk snapshot cleanup did not complete"
                ) from read_error
            if read_error is not None:
                raise DittoCapabilityUnavailable("managed-account risk state is unavailable") from read_error
            return {
                "complete": True,
                "aggregate_pnl": sum(row["pnl_today"] for row in rows),
                "aggregate_capital": sum(row.pop("capital") for row in rows),
                "accounts": rows,
            }

    def kill_all(self, *, actor_id: str, jti: str, reason: str) -> dict[str, Any]:
        """Cancel orders and flatten positions across every managed account."""
        deadline = time.monotonic() + 5.0
        try:
            self.stop(timeout=max(0.0, deadline - time.monotonic()))
        except Exception as exc:
            # The flatten is declined when the mirror cannot be drained in time:
            # flattening around a still-racing mirror order could silently
            # re-open a position the operator believes is closed. Guarantee the
            # mirror is deactivated before surfacing the refusal — stop() flips
            # this on the drain-timeout path, but its early "starting"/"stopping"
            # guards raise beforehand — so it cannot keep issuing orders while
            # the operator escalates to the account-wide kill switch.
            with self._lock:
                self._active = False
            raise DittoCapabilityUnavailable(
                "active Ditto mirroring could not be quiesced before emergency flattening; "
                "the mirror has been deactivated — escalate to the account-wide kill switch"
            ) from exc
        with self._one_shot_lock:
            if not self._retry_retained_router_owners(deadline=deadline):
                raise DittoCapabilityUnavailable("managed-account router cleanup is incomplete")
            accounts = self._accounts()
            if not accounts:
                raise DittoCapabilityUnavailable("no managed accounts")
            try:
                owner = self._router_owner_factory(accounts, str(actor_id).strip())
            except Exception as exc:
                raise DittoCapabilityUnavailable("managed-account emergency action is unavailable") from exc

            dispatch_error: Exception | None = None
            result: Any | None = None
            try:
                result = owner.dispatch_kill_all(
                    actor_id=str(actor_id).strip(),
                    jti=str(jti).strip(),
                    reason=str(reason).strip(),
                )
            except Exception as exc:  # noqa: BLE001 - converted to a bounded capability error
                dispatch_error = exc

            owner_closed = self._close_one_shot_owner(
                owner,
                timeout=max(0.0, deadline - time.monotonic()),
            )
            if not owner_closed:
                self._retain_router_owner(owner)
            if dispatch_error is not None or result is None:
                raise DittoCapabilityUnavailable(
                    "managed-account emergency action is unavailable"
                ) from dispatch_error

            dispatch_complete = bool(result.complete)
            complete = dispatch_complete and owner_closed
            return {
                "complete": complete,
                "mirror_quiesced": True,
                "cleanup_complete": owner_closed,
                "message": (
                    "All managed accounts are flat"
                    if complete
                    else "Emergency actions completed but router cleanup is incomplete"
                    if dispatch_complete
                    else "One or more managed accounts could not be fully flattened"
                ),
                "accounts_affected": len(accounts),
                "emergency_actions": result.as_dict(),
            }
