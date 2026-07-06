"""Kotak Neo native adapter (doc-grounded against the NEO v2 API shape).

Implements the BrokerAdapter contract for Kotak Neo: the two-step MPIN+TOTP auth,
the gated write surface (place/modify/cancel — every variety, including the
dedicated bracket/cover leg-cancel endpoints), the portfolio reads (order report
/ per-order history / trade report / per-order fills / positions / holdings /
limits), pre-trade margin, scrip master/search, typed quotes + market depth and
the HSM market feed / HSI order feed (injected feed factories). Request/response
translation lives in ``kotakneo_mapping`` and is unit-tested.

The neo-api-client SDK is dict-based but blocking, so the adapter talks to a
small facade (``KotakNeoClient``) that owns the ``NeoAPI`` handle and runs the
2FA; ``login`` builds the live facade and tests inject a mock one. The adapter
itself only depends on the facade's dict interface, so it is fully mock-testable
without the SDK.

Auth follows the public NEO v2 SDK shape:
``NeoAPI(environment='prod', access_token=None, neo_fin_key=None,
consumer_key=...)`` then ``totp_login(mobile_number, ucc, totp)`` mints a view
token + session id and ``totp_validate(mpin)`` mints the trade token. The v1
mobile+password / OTP ``session_2fa`` flow was removed in v2 — TOTP+MPIN is the
only login. ``refresh`` is a full daily re-login. The SDK pin is present and the
adapter is mock-tested; native connect stays disabled until a maintainer-entered
live account login/read probe passes.

The broker's public docs call the TOTP route's ``Authorization`` header a Trade
API access token, while the Python SDK stores that same header value as
``consumer_key``. FlintTrade accepts either credential name and normalises the
docs-facing token into the SDK-facing field.

Cost: Kotak Neo advertises **zero brokerage** on API order execution and a free
API. The one documented exception is that a bracket order's square-off leg
attracts standard brokerage even though the initial leg is free.

Market data: live ``quotes`` (all documented quote types) is implemented; the
NEO trade API exposes **no** historical-candle or option-chain endpoint, so
those raise explicitly — see ``capabilities``. Streaming uses the SDK's
callback-driven ``NeoWebSocket`` live, so ``stream()`` / ``order_stream()``
consume injected async feed factories (tests feed synthetic frames; live wiring
wraps the websocket callbacks into an async queue) while ``subscribe`` /
``unsubscribe`` drive the facade's HSM subscription surface.

Safety: writes still require the router's per-process ``_ROUTER_TOKEN`` (§8).
``build_broker_router``'s native-activation factory registers this adapter
automatically once its pinned SDK is attested AND vault credentials exist;
until then it stays dormant. Kotak Neo remains ``connectable=False`` in the
catalogue until the live account, static-IP, and order-path requirements are
verified end to end.
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
    from flinttrade_gateway.reconciliation import LocalStateSnapshot, ReconciliationReport

_PENDING = "Kotak Neo {0} — streaming wave pending live SDK verification"


def _split_symbol(raw: str) -> tuple[str, str]:
    """Split a ``"NSE:IDEA"`` quote symbol into ``(exchange, name)``.

    A bare symbol (no ``":"``) defaults to the NSE cash segment.
    """
    if ":" in raw:
        exchange, name = raw.split(":", 1)
        return exchange.strip().upper(), name.strip()
    return "NSE", raw.strip()


def _normalise_credentials(credentials: dict[str, Any]) -> dict[str, Any]:
    """Map Kotak's docs-facing token name onto the SDK's ``consumer_key`` slot."""
    normalised = dict(credentials)
    auth_token = normalised.get("consumer_key") or normalised.get("access_token")
    if auth_token:
        normalised["consumer_key"] = auth_token
    return normalised


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
    # (only disclosed-quantity). NEO's optional market-protection value is
    # forwarded when the caller explicitly sets ``Order.market_protection``.
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
    # Captured Kotak Neo v2 WebSocket docs: 16 channels and 200 scrips at a
    # time. Runtime remains disabled until the SDK callback bridge is live-proven.
    streaming_max_connections_per_user=16,
    streaming_max_symbols_per_connection=200,
    streaming_max_total_symbols=200,
    bracket_order_native=True,
    cover_order_native=True,
    multi_quote_supported=True,
    modify_qty_supported=True,
)


class KotakNeoClient:
    """Dict-based facade over the neo-api-client v2 SDK (lazy import).

    Owns the ``NeoAPI`` handle and runs the two-step TOTP+MPIN 2FA at
    construction so the adapter stays SDK-free. Built by ``KotakNeoAdapter.login``
    for live use; tests inject a mock with the same method surface instead.

    The public docs' Trade API access token is sent by the SDK as
    ``consumer_key`` on the TOTP ``Authorization`` header. If a caller supplies
    only ``access_token``, FlintTrade maps it to that SDK field while still
    forwarding the original value to ``NeoAPI`` for compatibility with captured
    portal-token flows. TOTP+MPIN 2FA is still required to mint the trade-scope
    session.
    """

    def __init__(self, credentials: dict[str, Any]) -> None:
        from neo_api_client import NeoAPI  # noqa: PLC0415

        credentials = _normalise_credentials(credentials)
        self._neo = NeoAPI(
            environment=str(credentials.get("environment", "prod")),
            access_token=credentials.get("access_token") or None,
            neo_fin_key=credentials.get("neo_fin_key"),
            consumer_key=credentials.get("consumer_key"),
        )
        self._install_fin_key_header_patch(self._neo)
        M.ensure_ok(
            self._neo.totp_login(
                mobile_number=credentials.get("mobile_number"),
                ucc=credentials.get("ucc"),
                totp=credentials.get("totp"),
            )
        )
        M.ensure_ok(self._neo.totp_validate(mpin=credentials.get("mpin")))

    @staticmethod
    def _install_fin_key_header_patch(neo: Any) -> None:
        """Patch the SDK REST client to send ``neo-fin-key`` where required.

        The current Kotak docs require ``neo-fin-key`` on the fixed login calls
        and on Auth/Sid-backed order/report/portfolio/limits/margin calls, while
        quotes and scrip-master remain Authorization-only. Some SDK modules omit
        the fin-key header, so the facade adds it only for login URLs or when
        the outgoing request already carries ``Auth``/``Sid``. This keeps the
        SDK surface intact and avoids adding the header to quotes/scrip-master.
        """
        api_client = getattr(neo, "api_client", None)
        rest_client = getattr(api_client, "rest_client", None)
        original = getattr(rest_client, "request", None)
        configuration = getattr(neo, "configuration", None)
        fin_key = getattr(configuration, "get_neo_fin_key", None)
        if not callable(original) or not callable(fin_key):
            return
        if getattr(rest_client, "_flinttrade_fin_key_wrapped", False):
            return

        def request(*args: Any, **kwargs: Any) -> Any:
            mutable_args = list(args)
            positional_headers = len(mutable_args) >= 4 and "headers" not in kwargs
            headers = mutable_args[3] if positional_headers else kwargs.get("headers")
            if isinstance(headers, dict):
                patched = dict(headers)
                lower = {str(key).lower() for key in patched}
                url = kwargs.get("url")
                if url is None and len(mutable_args) >= 2:
                    url = mutable_args[1]
                path = str(url or "").lower()
                login_call = "tradeapilogin" in path or "tradeapivalidate" in path
                needs_fin_key = "auth" in lower or "sid" in lower or login_call
                if needs_fin_key and "neo-fin-key" not in lower:
                    patched["neo-fin-key"] = fin_key()
                if positional_headers:
                    mutable_args[3] = patched
                else:
                    kwargs["headers"] = patched
            return original(*mutable_args, **kwargs)

        rest_client.request = request
        rest_client._flinttrade_fin_key_wrapped = True

    _install_post_login_fin_key_header = _install_fin_key_header_patch

    # -- gated writes -------------------------------------------------------

    def place_order(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._neo.place_order(**params)

    def modify_order(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._neo.modify_order(**params)

    def cancel_order(self, order_id: str, amo: str = "NO", is_verify: bool = False) -> dict[str, Any]:
        return self._neo.cancel_order(order_id, amo=amo, isVerify=is_verify)

    def cancel_cover_order(self, order_id: str, amo: str = "NO", is_verify: bool = False) -> dict[str, Any]:
        return self._neo.cancel_cover_order(order_id, amo=amo, isVerify=is_verify)

    def cancel_bracket_order(self, order_id: str, amo: str = "NO", is_verify: bool = False) -> dict[str, Any]:
        return self._neo.cancel_bracket_order(order_id, amo=amo, isVerify=is_verify)

    # -- reads ---------------------------------------------------------------

    def order_book(self) -> dict[str, Any]:
        return self._neo.order_report()

    def order_history(self, order_id: str) -> dict[str, Any]:
        return self._neo.order_history(order_id=order_id)

    def trade_book(self, order_id: str | None = None) -> dict[str, Any]:
        return self._neo.trade_report(order_id=order_id)

    def positions(self) -> dict[str, Any]:
        return self._neo.positions()

    def holdings(self) -> dict[str, Any]:
        return self._neo.holdings()

    def funds(self) -> dict[str, Any]:
        return self._neo.limits()

    def limits(self, segment: str = "ALL", exchange: str = "ALL", product: str = "ALL") -> dict[str, Any]:
        return self._neo.limits(segment=segment, exchange=exchange, product=product)

    def quotes(self, instrument_tokens: list[dict[str, str]], quote_type: str = "all") -> Any:
        return self._neo.quotes(instrument_tokens=instrument_tokens, quote_type=quote_type)

    def margin(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._neo.margin_required(**params)

    def scrip_master(self, exchange_segment: str | None = None) -> Any:
        return self._neo.scrip_master(exchange_segment=exchange_segment)

    def search_scrip(
        self,
        exchange_segment: str,
        symbol: str,
        expiry: str | None = None,
        option_type: str | None = None,
        strike_price: str | None = None,
        ignore_50multiple: bool = True,
    ) -> Any:
        return self._neo.search_scrip(
            exchange_segment=exchange_segment,
            symbol=symbol,
            expiry=expiry,
            option_type=option_type,
            strike_price=strike_price,
            ignore_50multiple=ignore_50multiple,
        )

    # -- streaming + session ------------------------------------------------

    def subscribe(self, instrument_tokens: list[dict[str, str]], is_index: bool, is_depth: bool) -> None:
        self._neo.subscribe(instrument_tokens=instrument_tokens, isIndex=is_index, isDepth=is_depth)

    def un_subscribe(self, instrument_tokens: list[dict[str, str]], is_index: bool, is_depth: bool) -> None:
        self._neo.un_subscribe(instrument_tokens=instrument_tokens, isIndex=is_index, isDepth=is_depth)

    def subscribe_to_orderfeed(self) -> None:
        self._neo.subscribe_to_orderfeed()

    def logout(self) -> dict[str, Any]:
        return self._neo.logout()


class KotakNeoAdapter(BrokerAdapter):
    """Native Kotak Neo adapter.

    Args:
        client_factory: ``session -> KotakNeoClient``-like facade (tests inject a
            mock). When omitted, ``login`` builds the live facade and runs 2FA.
        symbol_resolver: ``(symbol, exchange) -> trading_symbol`` — NEO trades by
            its scrip symbol (e.g. ``"IDEA-EQ"``), resolved via ``search_scrip``.
        token_resolver: ``(symbol, exchange) -> instrument_token`` — the HSM feed
            subscribes by numeric scrip token (``pSymbol``), not trading symbol.
            When omitted, ``subscribe`` resolves tokens live via ``search_scrip``
            (index names like ``"Nifty 50"`` pass through unresolved).
        feed_factory: ``session -> AsyncIterator`` of raw HSM market-feed frames
            (what ``NeoWebSocket`` hands to ``on_message``); ``stream()`` decodes
            them via ``kotakneo_mapping.decode_kotak_feed``. Tests inject
            synthetic frames; live wiring bridges the websocket callbacks into an
            async queue.
        order_feed_factory: ``session -> AsyncIterator`` of raw HSI order-feed
            frames for ``order_stream()``.
        local_state_provider: ``session -> LocalStateSnapshot`` supplying the
            flinttrade-side mirror that ``reconcile`` diffs broker state
            against. Defaults to EMPTY local state (every broker-side row then
            surfaces as ``exists_only_on_broker``) until the engine wave wires
            the journal-backed provider.
    """

    def __init__(
        self,
        *,
        client_factory: Callable[[Session], Any] | None = None,
        symbol_resolver: Callable[[str, str], str] | None = None,
        token_resolver: Callable[[str, str], str] | None = None,
        feed_factory: Callable[[Session], AsyncIterator[Any]] | None = None,
        order_feed_factory: Callable[[Session], AsyncIterator[Any]] | None = None,
        local_state_provider: Callable[[Session], LocalStateSnapshot] | None = None,
    ) -> None:
        self._client_factory = client_factory
        self._symbol_resolver = symbol_resolver
        self._token_resolver = token_resolver
        self._feed_factory = feed_factory
        self._order_feed_factory = order_feed_factory
        self._local_state_provider = local_state_provider
        # (exchange_segment, SYMBOL) -> {"token": dict, "is_index": bool,
        # "is_depth": bool}, so unsubscribe can replay exactly what was
        # subscribed (NEO's unsubscribe type must match the subscribe type).
        self._subscriptions: dict[tuple[str, str], dict[str, Any]] = {}

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

    async def _resolve_trading_symbol(self, session: Session, symbol: str, exchange: str) -> str:
        """Resolve a FlintTrade symbol to NEO's trading symbol (``pTrdSymbol``)."""
        if self._symbol_resolver is not None:
            return str(self._symbol_resolver(symbol, exchange))
        scrips = await self.search_scrip(session, symbol, exchange)
        if not scrips or not scrips[0].get("trading_symbol"):
            raise BrokerError(
                f"Cannot resolve Kotak Neo trading_symbol for {symbol}/{exchange} — "
                "configure a symbol resolver or check the symbol"
            )
        return str(scrips[0]["trading_symbol"])

    async def _resolve_token(self, session: Session, name: str, exchange: str) -> str:
        """Resolve a scrip ``name`` to its numeric NEO instrument token (``pSymbol``).

        The quote, margin and feed surfaces all key the scrip by its numeric
        ``pSymbol`` (``Quotes.md`` / ``Margin_Required.md`` / ``webSocket.md``),
        NOT the trading symbol. Uses the injected ``token_resolver`` when present,
        otherwise a live ``search_scrip`` lookup. Index names are the caller's
        responsibility (they pass through by name); this always resolves a token.
        """
        if self._token_resolver is not None:
            return str(self._token_resolver(name, exchange))
        scrips = await self.search_scrip(session, name, exchange)
        if not scrips or not scrips[0].get("token"):
            raise BrokerError(
                f"Cannot resolve Kotak Neo instrument token for {name}/{exchange} — "
                "configure a token resolver or check the symbol"
            )
        return str(scrips[0]["token"])

    @staticmethod
    async def _call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        return await asyncio.to_thread(fn, *args, **kwargs)

    @staticmethod
    def _rows(resp: Any) -> list[dict[str, Any]]:
        data = resp.get("data", []) if isinstance(resp, dict) else []
        return data if isinstance(data, list) else []

    # ---------- auth lifecycle ----------

    async def login(self, credentials: dict) -> Session:
        """Run the v2 TOTP+MPIN login and return a day-scoped session.

        Credentials: ``access_token`` (Kotak docs' Trade API token) or
        ``consumer_key`` (the SDK name for the same TOTP ``Authorization``
        header), ``mobile_number`` + ``ucc`` + ``totp`` (view token via
        ``totp_login``) and ``mpin`` (trade token via ``totp_validate``).
        Optional: ``environment`` (``prod``/``uat``) and ``neo_fin_key``. The v1
        mobile+password / OTP flow no longer exists in the v2 SDK.
        """
        credentials = _normalise_credentials(credentials)
        if not credentials.get("consumer_key"):
            raise BrokerError("Kotak Neo login requires 'consumer_key' or 'access_token'")
        for required in ("mobile_number", "ucc", "mpin", "totp"):
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

    def replay_credentials(self, credentials: dict, session: Session) -> dict:
        """The replayable vault payload after a successful login (G7).

        The NEO 2FA consumes a live 30-second TOTP and yields SDK-internal
        session state that cannot be rehydrated from a stored token, so there
        is nothing minted to write back — just drop the one-time ``totp``. Token
        naming is preserved as entered (``access_token`` or ``consumer_key``)
        because login accepts either form on the next fresh authentication.
        """
        return {k: v for k, v in credentials.items() if k != "totp"}

    async def refresh(self, session: Session) -> Session:
        # NEO tokens are single-day (daily MPIN+TOTP cycle, no refresh token) —
        # a fresh login() is required at expiry.
        return session

    async def logout(self, session: Session) -> None:
        """Invalidate the NEO session (clears the trade token) — idempotent.

        ``NeoAPI.logout`` drops the edit token/sid client-side (the v2 SDK's
        REST logout call is disabled upstream); a facade/mock without ``logout``
        is tolerated so logout never fails mid-teardown.
        """
        client = session.extra.get("client") if self._client_factory is None else self._client_factory(session)
        log_off = getattr(client, "logout", None)
        if callable(log_off):
            await self._call(log_off)
        session.extra.pop("client", None)
        return None

    # ---------- trading: writes (router-only) ----------

    async def place_order(self, session: Session, order: Order, *, _router_token: object | None = None) -> str:
        """Place one order through the gated path; return the NEO order number.

        Variety dispatch happens inside ``to_place_order_params`` so EVERY
        variety travels this same gated method: ``regular``, ``amo`` (the
        ``amo="YES"`` flag), ``bracket``/``cover`` (BO/CO product override +
        protective legs). ``iceberg`` is refused — NEO has no slice endpoint,
        only ``disclosed_quantity``.
        """
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        trading_symbol = await self._resolve_trading_symbol(session, order.symbol, order.exchange)
        tag = session.algo_id or None
        params = M.to_place_order_params(order, trading_symbol, tag=tag)
        resp = await self._call(self._client(session).place_order, params)
        return M.extract_order_id(resp)

    async def modify_order(
        self, session: Session, order_id: str, changes: dict, *, _router_token: object | None = None
    ) -> None:
        """Modify an open order (gated). ``changes`` may carry the full NEO
        surface — quick-method extras (``instrument_token``/``exchange_segment``/
        ``product``/``trading_symbol``/``transaction_type``) and the ``amo``
        flag are forwarded when present (``Modify_Order.md``)."""
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        params = M.to_modify_order_params(order_id, changes)
        resp = await self._call(self._client(session).modify_order, params)
        M.ensure_ok(resp)

    async def cancel_order(
        self,
        session: Session,
        order_id: str,
        *,
        variety: str = "regular",
        amo: bool = False,
        _router_token: object | None = None,
    ) -> None:
        """Cancel an order (gated) — variety dispatch within the gated method.

        ``regular``/``amo`` use the plain cancel endpoint; ``cover`` exits via
        ``quick/order/co/exit`` and ``bracket`` via ``quick/order/bo/exit`` (the
        dedicated leg-cancel endpoints — ``Cancel_Cover_Order.md`` /
        ``Cancel_Bracket_Order.md``). ``amo=True`` flags an after-market order.
        The default call shape (``cancel_order(session, order_id,
        _router_token=…)``) is exactly what ``BrokerRouter`` dispatches today;
        the variety/amo keywords are adapter-level extras for variety-aware
        callers.
        """
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        client = self._client(session)
        v = str(variety).lower()
        amo_flag = "YES" if (amo or v == "amo") else "NO"
        if v in ("regular", "", "amo"):
            if amo_flag == "YES":
                resp = await self._call(client.cancel_order, str(order_id), amo_flag)
            else:
                resp = await self._call(client.cancel_order, str(order_id))
        elif v == "cover":
            resp = await self._call(client.cancel_cover_order, str(order_id), amo_flag)
        elif v == "bracket":
            resp = await self._call(client.cancel_bracket_order, str(order_id), amo_flag)
        else:
            raise BrokerError(f"Kotak Neo cannot cancel order variety {variety!r}")
        M.ensure_ok(resp)

    # ---------- trading: reads ----------

    async def order_book(self, session: Session) -> list[Order]:
        resp = await self._call(self._client(session).order_book)
        return [M.from_kotak_order(r) for r in self._rows(resp)]  # type: ignore[misc]

    async def order_history(self, session: Session, order_id: str) -> list[dict]:
        """Per-order state history (NEO ``order_history`` — a read).

        Returns the order's lifecycle rows (``put order req received`` →
        ``validation pending`` → ``open`` → ``complete`` …) normalised to the
        FlintTrade order shape, in the OMS's newest-first ordering.
        """
        resp = await self._call(self._client(session).order_history, str(order_id))
        return [M.from_kotak_order(r) for r in M.order_history_rows(resp)]

    async def trade_book(self, session: Session) -> list[Trade]:
        resp = await self._call(self._client(session).trade_book)
        return [M.from_kotak_trade(r) for r in self._rows(resp)]  # type: ignore[misc]

    async def order_trades(self, session: Session, order_id: str) -> list[dict]:
        """Fills for ONE order (NEO ``trade_report(order_id)`` — a read).

        The SDK filters server-side rows down to ``{"data": {row}}`` for a
        single fill (or an error envelope when nothing traded); a multi-fill
        list is tolerated too. No trades → ``[]``, never a raise.
        """
        resp = await self._call(self._client(session).trade_book, str(order_id))
        if not isinstance(resp, dict):
            return []
        data = resp.get("data")
        rows = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
        return [M.from_kotak_trade(r) for r in rows if isinstance(r, dict)]

    async def positions(self, session: Session) -> list[Position]:
        resp = await self._call(self._client(session).positions)
        return [M.from_kotak_position(r) for r in self._rows(resp)]  # type: ignore[misc]

    async def holdings(self, session: Session) -> list[dict]:
        resp = await self._call(self._client(session).holdings)
        return [M.from_kotak_holding(r) for r in self._rows(resp)]

    async def funds(self, session: Session) -> dict:
        resp = await self._call(self._client(session).funds)
        return M.from_kotak_funds(resp)

    async def limits(
        self, session: Session, segment: str = "ALL", exchange: str = "ALL", product: str = "ALL"
    ) -> dict:
        """Filtered RMS limits (NEO ``limits(segment, exchange, product)``).

        ``funds`` is the unfiltered contract read; this exposes the documented
        filter surface (segment ∈ CASH/CUR/FO/ALL, exchange ∈ NSE/BSE/ALL,
        product ∈ CNC/MIS/NRML/ALL — ``Limits.md``). The raw flat response is
        preserved under ``extra``.
        """
        params = M.to_limits_params(segment, exchange, product)
        resp = await self._call(
            self._client(session).limits, params["segment"], params["exchange"], params["product"]
        )
        return M.from_kotak_funds(resp)

    # ---------- market data ----------

    async def _fetch_quote_rows(self, session: Session, symbols: list[str], quote_type: str) -> list[dict]:
        """Resolve ``symbols`` to numeric tokens and fetch raw NEO quote rows.

        The quotes endpoint keys each scrip by its numeric ``pSymbol``/``wToken``
        (``webSocket.md`` lines 44–47 / ``Quotes.md``), NOT the trading symbol;
        only indexes are passed by NAME (``Quotes.md`` "Nifty 50" example). Each
        non-index symbol is resolved via the shared ``_resolve_token`` path.
        """
        try:
            quote_type = M.canonical_quote_type(quote_type)
        except M.KotakNeoMappingError as exc:
            raise BrokerError(
                f"Kotak Neo quote_type must be one of {sorted(M.QUOTE_TYPES)}, got {quote_type!r}"
            ) from exc
        resolved: list[tuple[str, str]] = []
        for raw in symbols:
            exchange, name = _split_symbol(raw)
            if M.is_index_name(name):
                resolved.append((M.canonical_index_name(name), exchange))  # indexes key by case-sensitive name
            else:
                resolved.append((await self._resolve_token(session, name, exchange), exchange))
        tokens = M.to_quote_tokens(resolved)
        client = self._client(session)
        if quote_type == "all":
            # Single-arg call keeps the facade's default ("all") authoritative.
            resp = await self._call(client.quotes, tokens)
        else:
            resp = await self._call(client.quotes, tokens, quote_type)
        rows = self._rows(resp)
        if not rows and isinstance(resp, list):
            rows = [r for r in resp if isinstance(r, dict)]
        return rows

    async def quotes(self, session: Session, symbols: list[str]) -> list[Quote]:
        from flinttrade_core.models import Quote  # noqa: PLC0415

        rows = await self._fetch_quote_rows(session, symbols, "all")
        return [Quote(**M.from_kotak_quote(r)) for r in rows]

    async def quote_details(self, session: Session, symbols: list[str], quote_type: str = "all") -> list[dict]:
        """Typed quote snapshot (read) — the full NEO quote_type surface.

        ``quote_type`` ∈ all / depth / ohlc / ltp / oi / 52W / circuit_limits /
        scrip_details (``Quotes.md``). ``depth`` rows are book-shaped — use
        ``market_depth`` for the normalised bid/ask ladder; everything else is
        returned as the raw row dicts NEO serves.
        """
        return await self._fetch_quote_rows(session, symbols, quote_type)

    async def market_depth(self, session: Session, symbols: list[str]) -> list[dict]:
        """5-level market depth via the quotes endpoint (``quote_type="depth"``).

        Each entry carries ``symbol`` / ``exchange`` / ``token`` and the
        ``bids`` / ``asks`` ladders (price / quantity / orders) — a read.
        """
        rows = await self._fetch_quote_rows(session, symbols, "depth")
        return [M.from_kotak_depth(r) for r in rows]

    async def margin_calculator(self, session: Session, order: Order) -> dict:
        """Pre-trade margin estimate for ``order`` (NEO ``margin_required``).

        Read-only — places nothing, so it needs no gate. NEO keys the scrip by
        its numeric ``pSymbol`` (``Margin_Required.md`` line 35), so the token is
        resolved via the shared ``_resolve_token`` path and the trading symbol
        rides its own ``trading_symbol`` field. If the numeric token is not
        resolvable the trading symbol is used as a best-effort fallback.
        """
        trading_symbol = await self._resolve_trading_symbol(session, order.symbol, order.exchange)
        try:
            instrument_token: str | None = await self._resolve_token(session, order.symbol, order.exchange)
        except BrokerError:
            # No token resolver and search_scrip could not resolve it — fall back
            # to keying margin by trading symbol (handled in to_margin_params).
            instrument_token = None
        params = M.to_margin_params(order, trading_symbol, instrument_token=instrument_token)
        resp = await self._call(self._client(session).margin, params)
        return M.from_kotak_margin(resp)

    async def search_scrip(
        self,
        session: Session,
        symbol: str,
        exchange: str = "NSE",
        *,
        expiry: str | None = None,
        option_type: str | None = None,
        strike_price: str | None = None,
        ignore_50multiple: bool = True,
    ) -> list[dict]:
        """Resolve a symbol to NEO scrip metadata (trading_symbol, token, lot size).

        A read — makes the adapter self-sufficient for symbol resolution rather
        than always requiring an injected ``symbol_resolver``. The full
        ``Scrip_Search.md`` filter surface is supported: ``expiry``
        (``DDMMMYYYY``, e.g. ``28JUN2023``), ``option_type`` (``CE``/``PE``),
        ``strike_price`` (``45000``, ``40000-45000``, ``>40000``, ``<45000``)
        and ``ignore_50multiple`` (skip non-50-multiple strikes).
        """
        seg = M.EXCHANGE_TO_KOTAK.get(str(exchange).upper(), str(exchange).lower())
        client = self._client(session)
        if expiry is None and option_type is None and strike_price is None and ignore_50multiple:
            # Two-arg call keeps minimal facades (and the SDK defaults) authoritative.
            resp = await self._call(client.search_scrip, seg, symbol)
        else:
            resp = await self._call(
                client.search_scrip, seg, symbol, expiry, option_type, strike_price, ignore_50multiple
            )
        rows = resp if isinstance(resp, list) else (resp.get("data", []) if isinstance(resp, dict) else [])
        return [M.from_kotak_scrip(r) for r in rows if isinstance(r, dict)]

    async def scrip_master(self, session: Session, exchange: str | None = None) -> dict:
        """Scrip-master CSV download URLs (read — ``Scrip_Master.md``).

        Without ``exchange`` returns every segment's transformed CSV URL plus
        the base folder; with an exchange (``NSE``/``NFO``/…) the SDK filters
        down to that segment's single CSV URL.
        """
        seg = M.EXCHANGE_TO_KOTAK.get(str(exchange).upper(), str(exchange).lower()) if exchange else None
        resp = await self._call(self._client(session).scrip_master, seg)
        return M.from_kotak_scrip_master(resp)

    async def historical(self, session: Session, req: dict) -> Candles:
        # NEO trade API has no historical-candle endpoint (capability is False).
        raise NotImplementedError("Kotak Neo exposes no historical-candle API")

    async def option_chain(self, session: Session, req: dict) -> OptionChain:
        # NEO has no option-chain endpoint (capability is False).
        raise NotImplementedError("Kotak Neo exposes no option-chain API")

    # ---------- market data: streaming ----------

    async def _resolve_feed_tokens(
        self, session: Session, symbols: list[str], *, is_index: bool
    ) -> list[dict[str, str]]:
        """Resolve quote symbols to NEO HSM subscription token dicts.

        The HSM feed subscribes by instrument token (``pSymbol``), not trading
        symbol — resolved via the injected ``token_resolver`` or a live
        ``search_scrip`` lookup. Index subscriptions use the index NAME as the
        token (``webSocket.md`` "For Indexes"), so they pass through unresolved.
        """
        tokens: list[dict[str, str]] = []
        for raw in symbols:
            exchange, name = _split_symbol(raw)
            seg = M.EXCHANGE_TO_KOTAK.get(exchange, exchange.lower())
            token = M.canonical_index_name(name) if is_index else await self._resolve_token(session, name, exchange)
            tokens.append({"instrument_token": token, "exchange_segment": seg})
        return tokens

    async def subscribe(self, session: Session, symbols: list[str], mode: str = "FULL") -> None:
        """Subscribe symbols on the HSM live feed.

        ``mode`` maps to NEO's subscription types (``kotakneo_mapping.
        subscription_flags``): LTP/QUOTE → scrip feed (``mws``), FULL/DEPTH →
        5-level depth feed (``dps``), INDEX → index feed (``ifs``). The public
        docs cap the WebSocket surface at 16 channels and 200 subscribed scrips.
        Each subscription is recorded (token + flags) so ``unsubscribe`` can
        replay it exactly.
        """
        is_index, is_depth = M.subscription_flags(mode)
        tokens = await self._resolve_feed_tokens(session, symbols, is_index=is_index)
        await self._call(self._client(session).subscribe, tokens, is_index, is_depth)
        for raw, tok in zip(symbols, tokens):
            exchange, name = _split_symbol(raw)
            self._subscriptions[(M.EXCHANGE_TO_KOTAK.get(exchange, exchange.lower()), name.upper())] = {
                "token": tok,
                "is_index": is_index,
                "is_depth": is_depth,
            }

    async def unsubscribe(self, session: Session, symbols: list[str]) -> None:
        """Unsubscribe symbols from the HSM live feed. Idempotent.

        Replays each symbol's RECORDED subscription (token + index/depth flags
        — NEO's ``mwu``/``ifu``/``dpu`` must match the original ``mws``/``ifs``/
        ``dps`` type to take effect). Symbols never subscribed are skipped.
        """
        client = self._client(session)
        by_flags: dict[tuple[bool, bool], list[dict[str, str]]] = {}
        keys: list[tuple[str, str]] = []
        for raw in symbols:
            exchange, name = _split_symbol(raw)
            key = (M.EXCHANGE_TO_KOTAK.get(exchange, exchange.lower()), name.upper())
            sub = self._subscriptions.get(key)
            if sub is None:
                continue  # never subscribed — idempotent no-op
            by_flags.setdefault((sub["is_index"], sub["is_depth"]), []).append(sub["token"])
            keys.append(key)
        for (is_index, is_depth), tokens in by_flags.items():
            await self._call(client.un_subscribe, tokens, is_index, is_depth)
        for key in keys:
            self._subscriptions.pop(key, None)

    def stream(self, session: Session) -> AsyncIterator[Any]:
        return self._stream_impl(session)

    async def _stream_impl(self, session: Session) -> AsyncIterator[Any]:
        from flinttrade_core.models import TickEvent  # noqa: PLC0415

        if self._feed_factory is None:
            # Live: the HSM feed is callback-driven inside the SDK; wiring wraps
            # NeoWebSocket's on_message into an async queue and injects it here.
            # The decode path (decode_kotak_feed) is implemented and tested.
            raise NotImplementedError(
                "Kotak Neo live tick stream needs the HSM market feed (inject feed_factory)"
            )
        async for frame in self._feed_factory(session):
            for tick in M.decode_kotak_feed(frame):
                yield TickEvent(
                    symbol=tick.get("symbol", "") or tick.get("token", ""),
                    exchange=tick.get("exchange", ""),
                    ltp=float(tick.get("ltp", 0.0)),
                    volume=int(tick.get("volume", 0)),
                    bid=float(tick.get("bid", 0.0)),
                    ask=float(tick.get("ask", 0.0)),
                    oi=int(tick.get("oi", 0)),
                    timestamp=str(tick.get("timestamp", "")),
                )

    def order_stream(self, session: Session) -> AsyncIterator[dict]:
        """Order-update stream (HSI order feed — ``webSocket_orderfeed.md``).

        Yields normalised order-update dicts (``decode_kotak_order_feed``);
        connection acks and heartbeats are skipped. Live wiring calls
        ``subscribe_to_orderfeed`` on the facade and bridges the callbacks into
        the injected ``order_feed_factory``.
        """
        return self._order_stream_impl(session)

    async def _order_stream_impl(self, session: Session) -> AsyncIterator[dict]:
        if self._order_feed_factory is None:
            raise NotImplementedError(
                "Kotak Neo live order feed needs the HSI socket (inject order_feed_factory)"
            )
        starter = getattr(self._client(session), "subscribe_to_orderfeed", None)
        if not callable(starter):
            raise BrokerError("Kotak Neo client does not expose subscribe_to_orderfeed")
        M.ensure_ok(await self._call(starter))
        async for frame in self._order_feed_factory(session):
            update = M.decode_kotak_order_feed(frame)
            if update is not None:
                yield update

    # ---------- reconciliation ----------

    async def reconcile(self, session: Session) -> ReconciliationReport:
        """Broker-truth vs flinttrade-mirror diff (contract §14).

        Fetches the order book, positions and holdings through this adapter's
        own reads and diffs them against the injected ``local_state_provider``
        snapshot (empty until the engine wave wires the journal-backed
        provider). A broker fetch failure is captured on the report's
        ``error`` field instead of raised, so the runner retries next cycle.
        """
        from flinttrade_gateway.reconciliation import EMPTY_LOCAL_STATE, build_report  # noqa: PLC0415

        generated_at = datetime.now(tz=timezone.utc)
        local = EMPTY_LOCAL_STATE if self._local_state_provider is None else self._local_state_provider(session)
        try:
            broker_orders = await self.order_book(session)
            broker_positions = await self.positions(session)
            broker_holdings = await self.holdings(session)
        except (BrokerError, ValueError) as exc:  # ValueError covers the mapping-error classes
            return build_report(
                adapter_id=self.broker_id,
                account_id=session.account_id,
                generated_at=generated_at,
                local_state=local,
                error=f"broker fetch failed: {exc}",
            )
        # The read methods return the normalised row dicts at runtime (see the
        # mapping layer); build_report consumes them as plain mappings.
        return build_report(
            adapter_id=self.broker_id,
            account_id=session.account_id,
            generated_at=generated_at,
            broker_orders=broker_orders,  # type: ignore[arg-type]
            broker_positions=broker_positions,  # type: ignore[arg-type]
            broker_holdings=broker_holdings,
            local_state=local,
        )


from ._base import ROUTER_TOKEN as _ROUTER_TOKEN  # noqa: E402  shared per-process token (§8.0c)
