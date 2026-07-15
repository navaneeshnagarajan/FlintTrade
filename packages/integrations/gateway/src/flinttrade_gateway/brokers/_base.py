"""BrokerAdapter — the contract every direct broker SDK adapter implements.

Every trading/data method is async (contract §5). Every method may raise from
the ``flinttrade_core.exceptions`` taxonomy ONLY — broker-native exceptions
MUST be mapped (contract §7).

The adapter is the LAST mile to the broker. It is invoked by ``BrokerRouter``
(``flinttrade_gateway.router``) after the router has verified a SafetyContext
against the (order, mode, jti, adapter_id) tuple and consumed the gate exactly
once. Adapters MUST NOT bypass the router and MUST NOT mint SafetyContexts
(contract §8).

Annotations reference some model classes that land in later waves
(``Candles``/``TickEvent`` in the §10 data-model wave, ``ReconciliationReport``
in the §14 reconciliation wave). Because ``from __future__ import annotations``
makes every annotation a lazy string, those forward references never resolve at
import time — keeping this contract declarable ahead of its model substrate
without overscoping into those waves.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from contextvars import copy_context
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable

from flinttrade_gateway.capabilities import Capabilities

if TYPE_CHECKING:  # pragma: no cover - typing only; not evaluated at runtime
    from flinttrade_core.models import (
        Candles,
        OptionChain,
        Order,
        Position,
        Quote,
        TickEvent,
        Trade,
    )
    from flinttrade_gateway.reconciliation import ReconciliationReport


# The single per-process router-call token (contract §8.0c). EVERY adapter's
# write guard must compare against THIS object, and ``BrokerRouter`` passes THIS
# object on every place/modify/cancel — so identity holds across all adapters.
# Adapters re-export it as a module-private ``_ROUTER_TOKEN`` (``from ._base
# import ROUTER_TOKEN as _ROUTER_TOKEN``) so a bare ``adapter.place_order``
# without it still raises, while a real router dispatch always matches. Minting a
# per-module ``object()`` instead silently breaks the gated path (the router's
# token would never be identity-equal) — never do that.
ROUTER_TOKEN = object()


async def run_blocking_sdk_call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run blocking broker I/O without releasing ownership on cancellation.

    ``asyncio.to_thread`` cannot stop a worker after it has entered a
    synchronous broker SDK. If the awaiting router task is cancelled, keep that
    task alive until the worker really exits so generation and safety write
    leases remain truthful. The original cancellation is re-raised afterwards.
    """
    loop = asyncio.get_running_loop()
    context = copy_context()
    worker = loop.run_in_executor(None, context.run, partial(fn, *args, **kwargs))
    cancellation: asyncio.CancelledError | None = None
    while True:
        try:
            result = await asyncio.shield(worker)
            break
        except asyncio.CancelledError as exc:
            if worker.cancelled():
                raise
            cancellation = cancellation or exc
            current = asyncio.current_task()
            if current is not None:
                current.uncancel()
        except BaseException:
            if cancellation is not None:
                raise cancellation from None
            raise
    if cancellation is not None:
        raise cancellation
    return result


@dataclass
class Session:
    """Canonical broker session (contract §9). All adapters share this shape;
    broker-specific overflow goes in ``extra`` rather than a bespoke dataclass."""

    access_token: str
    expires_at: float
    account_id: str = ""
    adapter_id: str = ""
    algo_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    read_only_until_at: float | None = None

    def is_expiring_soon(self, leeway_seconds: int = 60) -> bool:
        return self.expires_at <= datetime.now(tz=timezone.utc).timestamp() + leeway_seconds

    @property
    def is_read_only(self) -> bool:
        if self.read_only_until_at is None:
            return False
        return datetime.now(tz=timezone.utc).timestamp() < self.read_only_until_at


class BrokerAdapter(ABC):
    """The contract every direct broker SDK adapter implements (contract §5).

    Subclasses MUST implement every abstract method below, advertise
    capabilities truthfully (the router relies on them for failover), and map
    broker-native exceptions to ``flinttrade_core.exceptions`` (contract §7).
    """

    # ---------- identity + capabilities ----------

    @property
    @abstractmethod
    def broker_id(self) -> str:
        """Canonical lowercase id (e.g. 'dhan', 'upstox'); unique per adapter."""
        raise NotImplementedError

    @property
    @abstractmethod
    def capabilities(self) -> Capabilities:
        """Capability flags advertised by this adapter (contract §6)."""
        raise NotImplementedError

    # ---------- auth lifecycle ----------

    @abstractmethod
    async def login(self, credentials: dict) -> Session:
        """Authenticate with the broker; return a fresh Session."""
        raise NotImplementedError

    @abstractmethod
    async def refresh(self, session: Session) -> Session:
        """Refresh an existing session, or raise UnsupportedCapabilityError."""
        raise NotImplementedError

    @abstractmethod
    async def logout(self, session: Session) -> None:
        """Invalidate the session broker-side. Idempotent."""
        raise NotImplementedError

    # ---------- trading: writes (safety-critical; router-only) ----------

    @abstractmethod
    async def place_order(self, session: Session, order: Order, *, _router_token: object | None = None) -> str:
        """Place one order; return the broker-side order_id.

        Called ONLY by ``BrokerRouter.place_order`` after SafetyContext
        verification + one-shot gate consumption (contract §8). The
        ``_router_token`` proves the call came through the router (§8.0c)."""
        raise NotImplementedError

    @abstractmethod
    async def modify_order(
        self, session: Session, order_id: str, changes: dict, *, _router_token: object | None = None
    ) -> None:
        """Modify an existing order. Same SafetyContext invariant as place_order."""
        raise NotImplementedError

    @abstractmethod
    async def cancel_order(
        self, session: Session, order_id: str, *, _router_token: object | None = None
    ) -> None:
        """Cancel an existing order. Idempotent. Same invariant as place_order."""
        raise NotImplementedError

    # ---------- trading: reads (no SafetyContext required) ----------

    @abstractmethod
    async def order_book(self, session: Session) -> list[Order]:
        """All orders for the current day, oldest first."""
        raise NotImplementedError

    @abstractmethod
    async def trade_book(self, session: Session) -> list[Trade]:
        """All trades (fills) for the current day, oldest first."""
        raise NotImplementedError

    @abstractmethod
    async def positions(self, session: Session) -> list[Position]:
        """Open positions (net + day) at the current moment."""
        raise NotImplementedError

    @abstractmethod
    async def holdings(self, session: Session) -> list[dict]:
        """Long-term holdings (settled equity in demat); broker-specific dicts."""
        raise NotImplementedError

    @abstractmethod
    async def funds(self, session: Session) -> dict:
        """Funds snapshot; caller MUST tolerate missing keys."""
        raise NotImplementedError

    # ---------- market data: rest ----------

    @abstractmethod
    async def quotes(self, session: Session, symbols: list[str]) -> list[Quote]:
        """Instantaneous quotes, same order as input; missing → Quote.available=False."""
        raise NotImplementedError

    @abstractmethod
    async def historical(self, session: Session, req: dict) -> Candles:
        """Historical OHLCV bars."""
        raise NotImplementedError

    @abstractmethod
    async def option_chain(self, session: Session, req: dict) -> OptionChain:
        """Option-chain snapshot."""
        raise NotImplementedError

    # ---------- market data: streaming ----------

    @abstractmethod
    def stream(self, session: Session) -> AsyncIterator[TickEvent]:
        """Open a tick stream and yield TickEvent objects (auto-reconnect)."""
        raise NotImplementedError

    @abstractmethod
    async def subscribe(self, session: Session, symbols: list[str], mode: str = "FULL") -> None:
        """Subscribe to the tick feed for the listed symbols."""
        raise NotImplementedError

    @abstractmethod
    async def unsubscribe(self, session: Session, symbols: list[str]) -> None:
        """Unsubscribe from listed symbols. Idempotent."""
        raise NotImplementedError

    # ---------- reconciliation ----------

    @abstractmethod
    async def reconcile(self, session: Session) -> ReconciliationReport:
        """Compare broker-side state vs flinttrade-side state; return the diff."""
        raise NotImplementedError

    # ---------- router-call guard (contract §8.0c) ----------

    @staticmethod
    def _require_router_token(_router_token: object | None, expected: object) -> None:
        """Raise unless the caller presented the router's per-process token.

        Even if a caller bypasses the AST gate, a bare ``adapter.place_order``
        without the token raises here before the broker SDK is touched."""
        if _router_token is not expected:
            from flinttrade_engine.safety import SafetyBypassError

            raise SafetyBypassError("adapter write method called outside BrokerRouter")
