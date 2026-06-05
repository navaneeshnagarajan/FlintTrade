"""Kotak Neo native adapter (doc-grounded against neo-api-client v2).

Implements the BrokerAdapter contract for Kotak Neo: the two-step MPIN+TOTP auth,
the gated write surface (place/modify/cancel), and the portfolio reads
(order report / trade report / positions / holdings / limits). Request/response
translation lives in ``kotakneo_mapping`` and is unit-tested.

The neo-api-client SDK is dict-based but blocking, so the adapter talks to a
small facade (``KotakNeoClient``) that owns the ``NeoAPI`` handle and runs the
2FA; ``login`` builds the live facade and tests inject a mock one. The adapter
itself only depends on the facade's dict interface, so it is fully mock-testable
without the SDK.

Auth (neo-api-client v2, ``Kotak-Neo/Kotak-neo-api-v2`` tag ``v2.0.1`` — no PyPI
package): ``NeoAPI(environment='prod', access_token=None, neo_fin_key=None,
consumer_key=...)`` then ``totp_login(mobile_number, ucc, totp)`` mints a view
token + session id and ``totp_validate(mpin)`` mints the trade token. ``refresh``
is a full daily re-login. v2.0.1 added MCX trading and the MTF product.

Cost: Kotak Neo advertises **zero brokerage** on API order execution and a free
API. The one documented exception is that a bracket order's square-off leg
attracts standard brokerage even though the initial leg is free.

Market data: live ``quotes`` is implemented (the NEO trade API exposes live
quotes + streaming but **no** historical-candle or option-chain endpoint, so
those raise explicitly — see ``capabilities``). Only live tick streaming remains
a separate wave.

Safety: writes still require the router's per-process ``_ROUTER_TOKEN`` (§8).
``build_broker_router``'s native-activation factory registers this adapter
automatically once its pinned SDK is attested AND vault credentials exist;
until then it stays dormant (the ``brokers.lock`` Kotak Neo pin is still
PLACEHOLDER, so it is ``skipped`` and never activates today).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable

from flinttrade_core.exceptions import BrokerError
from flinttrade_gateway.capabilities import (
    AuthModel,
    Capabilities,
    DepthLevels,
    OrderTypes,
    Segments,
    TickProtocol,
)

from . import kotakneo_mapping as M
from ._base import BrokerAdapter, Session

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flinttrade_core.models import Candles, OptionChain, Order, Position, Quote, Trade
    from flinttrade_gateway.reconciliation import ReconciliationReport

_PENDING = "Kotak Neo {0} — streaming wave pending live SDK verification"


def _split_symbol(raw: str) -> tuple[str, str]:
    """Split a ``"NSE:IDEA"`` quote symbol into ``(exchange, name)``.

    A bare symbol (no ``":"``) defaults to the NSE cash segment.
    """
    if ":" in raw:
        exchange, name = raw.split(":", 1)
        return exchange.strip().upper(), name.strip()
    return "NSE", raw.strip()

KOTAKNEO_CAPABILITIES = Capabilities(
    segments=(
        Segments.NSE_EQ
        | Segments.BSE_EQ
        | Segments.NFO
        | Segments.BFO
        | Segments.CDS
        | Segments.BCD
        | Segments.MCX
    ),
    # Native bracket (BO) and cover (CO) orders; no GTT and no iceberg
    # (only disclosed-quantity). Market orders are auto-converted to a protected
    # limit per SEBI retail-algo rules — handled at the adapter layer when wired.
    order_types=(
        OrderTypes.MARKET
        | OrderTypes.LIMIT
        | OrderTypes.SL
        | OrderTypes.SLM
        | OrderTypes.MIS
        | OrderTypes.CNC
        | OrderTypes.NRML
        | OrderTypes.AMO
        | OrderTypes.BO
        | OrderTypes.CO
    ),
    depth_levels=DepthLevels.L5,
    tick_protocol=TickProtocol.KOTAK_NEO_JSON,
    auth_model=AuthModel.MPIN_TOTP_DAILY,
    # Trade-token TTL is not stated in the local docs; 24h is the daily-cycle
    # ceiling used for refresh timing (the only JWT shown is a view-scope token).
    session_lifetime_hours=24.0,
    sandbox=True,
    # "Currently the system supports up to 10 orders per second."
    rate_limit_orders_per_sec=10,
    # 'tag' is an optional order field, not a mandated algo tag.
    algo_tag_required=False,
    # Zero brokerage on execution + zero API subscription charge (BO square-off
    # leg attracts standard brokerage — see module docstring).
    cost_paid=False,
    cost_inr_per_month=0,
    brokerage_free=True,
    brokerage_note=(
        "Zero brokerage on all API order execution; only statutory charges "
        "apply. Exception: a bracket order's square-off leg attracts standard "
        "brokerage."
    ),
    # No historical/OHLC-candle API in the Neo trade API — only live quotes.
    # No option-chain endpoint (search_scrip only).
    option_chain_supported=False,
    streaming_supported=True,
    bracket_order_native=True,
    cover_order_native=True,
    modify_qty_supported=True,
)


class KotakNeoClient:
    """Dict-based facade over the neo-api-client v2 SDK (lazy import).

    Owns the ``NeoAPI`` handle and runs the two-step MPIN+TOTP 2FA at
    construction so the adapter stays SDK-free. Built by ``KotakNeoAdapter.login``
    for live use; tests inject a mock with the same method surface instead.
    """

    def __init__(self, credentials: dict[str, Any]) -> None:
        from neo_api_client import NeoAPI  # noqa: PLC0415

        self._neo = NeoAPI(
            environment=str(credentials.get("environment", "prod")),
            access_token=None,
            neo_fin_key=credentials.get("neo_fin_key"),
            consumer_key=credentials.get("consumer_key"),
        )
        self._neo.totp_login(
            mobile_number=credentials.get("mobile_number"),
            ucc=credentials.get("ucc"),
            totp=credentials.get("totp"),
        )
        self._neo.totp_validate(mpin=credentials.get("mpin"))

    def place_order(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._neo.place_order(**params)

    def modify_order(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._neo.modify_order(**params)

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        return self._neo.cancel_order(order_id)

    def order_book(self) -> dict[str, Any]:
        return self._neo.order_report()

    def trade_book(self) -> dict[str, Any]:
        return self._neo.trade_report()

    def positions(self) -> dict[str, Any]:
        return self._neo.positions()

    def holdings(self) -> dict[str, Any]:
        return self._neo.holdings()

    def funds(self) -> dict[str, Any]:
        return self._neo.limits()

    def quotes(self, instrument_tokens: list[dict[str, str]]) -> dict[str, Any]:
        return self._neo.quotes(instrument_tokens=instrument_tokens, quote_type="all")


class KotakNeoAdapter(BrokerAdapter):
    """Native Kotak Neo adapter.

    Args:
        client_factory: ``session -> KotakNeoClient``-like facade (tests inject a
            mock). When omitted, ``login`` builds the live facade and runs 2FA.
        symbol_resolver: ``(symbol, exchange) -> trading_symbol`` — NEO trades by
            its scrip symbol (e.g. ``"IDEA-EQ"``), resolved via ``search_scrip``.
    """

    def __init__(
        self,
        *,
        client_factory: Callable[[Session], Any] | None = None,
        symbol_resolver: Callable[[str, str], str] | None = None,
    ) -> None:
        self._client_factory = client_factory
        self._symbol_resolver = symbol_resolver

    # ---------- identity + capabilities ----------

    @property
    def broker_id(self) -> str:
        return "kotakneo"

    @property
    def capabilities(self) -> Capabilities:
        return KOTAKNEO_CAPABILITIES

    # ---------- helpers ----------

    def _client(self, session: Session) -> Any:
        if self._client_factory is not None:
            return self._client_factory(session)
        client = session.extra.get("client")
        if client is None:
            raise BrokerError("Kotak Neo client not initialised — call login() first")
        return client

    def _resolve_symbol(self, symbol: str, exchange: str) -> str:
        if self._symbol_resolver is not None:
            return str(self._symbol_resolver(symbol, exchange))
        raise BrokerError(
            f"Cannot resolve Kotak Neo trading_symbol for {symbol}/{exchange} — "
            "configure a symbol resolver"
        )

    @staticmethod
    async def _call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        return await asyncio.to_thread(fn, *args, **kwargs)

    @staticmethod
    def _rows(resp: Any) -> list[dict[str, Any]]:
        data = resp.get("data", []) if isinstance(resp, dict) else []
        return data if isinstance(data, list) else []

    # ---------- auth lifecycle ----------

    async def login(self, credentials: dict) -> Session:
        for required in ("consumer_key", "mobile_number", "ucc", "mpin"):
            if not credentials.get(required):
                raise BrokerError(f"Kotak Neo login requires {required!r}")
        client = (
            None
            if self._client_factory is not None
            else await self._call(KotakNeoClient, dict(credentials))
        )
        return Session(
            access_token=str(credentials.get("ucc", "")),
            expires_at=datetime.now(tz=timezone.utc).timestamp() + 24 * 3600,
            account_id=str(credentials.get("ucc", "")),
            adapter_id="kotakneo",
            extra={"client": client},
        )

    async def refresh(self, session: Session) -> Session:
        # NEO tokens are single-day (daily MPIN+TOTP cycle, no refresh token) —
        # a fresh login() is required at expiry.
        return session

    async def logout(self, session: Session) -> None:
        session.extra.pop("client", None)
        return None

    # ---------- trading: writes (router-only) ----------

    async def place_order(self, session: Session, order: Order, *, _router_token: object | None = None) -> str:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        trading_symbol = self._resolve_symbol(order.symbol, order.exchange)
        tag = session.algo_id or None
        params = M.to_place_order_params(order, trading_symbol, tag=tag)
        resp = await self._call(self._client(session).place_order, params)
        return M.extract_order_id(resp)

    async def modify_order(
        self, session: Session, order_id: str, changes: dict, *, _router_token: object | None = None
    ) -> None:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        params = M.to_modify_order_params(order_id, changes)
        await self._call(self._client(session).modify_order, params)

    async def cancel_order(
        self, session: Session, order_id: str, *, _router_token: object | None = None
    ) -> None:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        await self._call(self._client(session).cancel_order, str(order_id))

    # ---------- trading: reads ----------

    async def order_book(self, session: Session) -> list[Order]:
        resp = await self._call(self._client(session).order_book)
        return [M.from_kotak_order(r) for r in self._rows(resp)]  # type: ignore[misc]

    async def trade_book(self, session: Session) -> list[Trade]:
        resp = await self._call(self._client(session).trade_book)
        return [M.from_kotak_trade(r) for r in self._rows(resp)]  # type: ignore[misc]

    async def positions(self, session: Session) -> list[Position]:
        resp = await self._call(self._client(session).positions)
        return [M.from_kotak_position(r) for r in self._rows(resp)]  # type: ignore[misc]

    async def holdings(self, session: Session) -> list[dict]:
        resp = await self._call(self._client(session).holdings)
        return [M.from_kotak_holding(r) for r in self._rows(resp)]

    async def funds(self, session: Session) -> dict:
        resp = await self._call(self._client(session).funds)
        return M.from_kotak_funds(resp)

    # ---------- market data ----------

    async def quotes(self, session: Session, symbols: list[str]) -> list[Quote]:
        from flinttrade_core.models import Quote  # noqa: PLC0415

        resolved: list[tuple[str, str]] = []
        for raw in symbols:
            exchange, name = _split_symbol(raw)
            resolved.append((self._resolve_symbol(name, exchange), exchange))
        tokens = M.to_quote_tokens(resolved)
        resp = await self._call(self._client(session).quotes, tokens)
        rows = self._rows(resp)
        if not rows and isinstance(resp, list):
            rows = [r for r in resp if isinstance(r, dict)]
        return [Quote(**M.from_kotak_quote(r)) for r in rows]

    async def historical(self, session: Session, req: dict) -> Candles:
        # NEO trade API has no historical-candle endpoint (capability is False).
        raise NotImplementedError("Kotak Neo exposes no historical-candle API")

    async def option_chain(self, session: Session, req: dict) -> OptionChain:
        # NEO has no option-chain endpoint (capability is False).
        raise NotImplementedError("Kotak Neo exposes no option-chain API")

    def stream(self, session: Session) -> AsyncIterator[Any]:
        raise NotImplementedError(_PENDING.format("stream"))

    async def subscribe(self, session: Session, symbols: list[str], mode: str = "FULL") -> None:
        raise NotImplementedError(_PENDING.format("subscribe"))

    async def unsubscribe(self, session: Session, symbols: list[str]) -> None:
        raise NotImplementedError(_PENDING.format("unsubscribe"))

    async def reconcile(self, session: Session) -> ReconciliationReport:
        raise NotImplementedError(_PENDING.format("reconcile"))


_ROUTER_TOKEN = object()
