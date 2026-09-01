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

import hashlib
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable

from flinttrade_core.exceptions import BrokerError
from flinttrade_engine.safety import EmergencyBrokerWrite, EmergencyReductionPlan, EmergencyWritePolicy
from flinttrade_gateway.capabilities import (
    AuthModel,
    Capabilities,
    DepthLevels,
    OrderTypes,
    Segments,
    TickProtocol,
)

from . import kotakneo_mapping as M
from ._base import BrokerAdapter, Session, run_blocking_sdk_call

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flinttrade_core.models import Candles, OptionChain, Order, Position, Quote, Trade
    from flinttrade_gateway.reconciliation import LocalStateSnapshot, ReconciliationReport

_PENDING = "Kotak Neo {0} — streaming wave pending live SDK verification"
_EMERGENCY_BATCH_LIMIT = 10
_EMERGENCY_EXIT_TAG_PREFIX = "FTE-KN-"
_EMERGENCY_TERMINAL_ORDER_STATUSES = frozenset({"rejected", "cancelled", "complete", "traded"})
_EMERGENCY_ACTIVE_ORDER_STATUSES = frozenset(
    {
        "open",
        "open pending",
        "validation pending",
        "put order req received",
        "after market order req received",
    }
)
_EMERGENCY_SUCCESSFUL_ORDER_STATUSES = frozenset({"complete", "traded"})
_EMERGENCY_ORDER_PRODUCTS = frozenset({"NRML", "CNC", "MIS", "INTRADAY", "MTF", "BO", "CO"})
_EMERGENCY_POSITION_PRODUCTS = frozenset({"NRML", "CNC", "MIS"})


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
        Segments.NSE_EQ | Segments.BSE_EQ | Segments.NFO | Segments.BFO | Segments.CDS | Segments.BCD | Segments.MCX
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

    def _cancel_order_rest(
        self,
        order_id: str,
        *,
        route_key: str,
        amo: str = "NO",
        is_verify: bool = False,
        trading_symbol: str | None = None,
    ) -> dict[str, Any]:
        """Call the SDK's cancel REST route with an optional compatibility field.

        The pinned SDK posts ``on`` and ``am``. A third-party mirror also
        describes ``ts``; retain it only for explicit compatibility callers,
        while emergency cancellation follows the pinned SDK contract.
        """
        from neo_api_client import OrderReportAPI, req_data_validation  # noqa: PLC0415

        if not self._neo.configuration.edit_token or not self._neo.configuration.edit_sid:
            return {"Error Message": "Complete the 2fa process before accessing this application"}
        try:
            req_data_validation.cancel_order_validation(order_id, amo)
            api_client = self._neo.api_client
            if is_verify:
                order_book_resp = OrderReportAPI(api_client).ordered_books()
                if "data" in order_book_resp:
                    for item in order_book_resp["data"]:
                        if item["nOrdNo"] == order_id.strip() and item["ordSt"] in (
                            "rejected",
                            "cancelled",
                            "complete",
                            "traded",
                        ):
                            status = "Traded" if item["ordSt"] == "complete" else item["ordSt"]
                            return {"Error": "The Given Order Status is " + str(status), "Reason": item["rejRsn"]}

            body_params = {"on": order_id, "am": amo}
            if trading_symbol:
                body_params["ts"] = trading_symbol
            cancel_resp = api_client.rest_client.request(
                url=api_client.configuration.get_url_details(route_key),
                method="POST",
                query_params={"sId": api_client.configuration.serverId},
                headers={
                    "Sid": api_client.configuration.edit_sid,
                    "Auth": api_client.configuration.edit_token,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                body=body_params,
            )
            return cancel_resp.json()
        except Exception as exc:  # match the SDK wrapper's response contract
            return {"Error": exc}

    def cancel_order(
        self,
        order_id: str,
        amo: str = "NO",
        is_verify: bool = False,
        trading_symbol: str | None = None,
    ) -> dict[str, Any]:
        if trading_symbol:
            return self._cancel_order_rest(
                order_id,
                route_key="cancel_order",
                amo=amo,
                is_verify=is_verify,
                trading_symbol=trading_symbol,
            )
        return self._neo.cancel_order(order_id, amo=amo, isVerify=is_verify)

    def cancel_cover_order(
        self,
        order_id: str,
        amo: str = "NO",
        is_verify: bool = False,
        trading_symbol: str | None = None,
    ) -> dict[str, Any]:
        if trading_symbol:
            return self._cancel_order_rest(
                order_id,
                route_key="cancel_cover_order",
                amo=amo,
                is_verify=is_verify,
                trading_symbol=trading_symbol,
            )
        return self._neo.cancel_cover_order(order_id, amo=amo, isVerify=is_verify)

    def cancel_bracket_order(
        self,
        order_id: str,
        amo: str = "NO",
        is_verify: bool = False,
        trading_symbol: str | None = None,
    ) -> dict[str, Any]:
        if trading_symbol:
            return self._cancel_order_rest(
                order_id,
                route_key="cancel_bracket_order",
                amo=amo,
                is_verify=is_verify,
                trading_symbol=trading_symbol,
            )
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
        return await run_blocking_sdk_call(fn, *args, **kwargs)

    @staticmethod
    def _rows(resp: Any) -> list[dict[str, Any]]:
        data = resp.get("data", []) if isinstance(resp, dict) else []
        return data if isinstance(data, list) else []

    @staticmethod
    def _emergency_identifier(value: Any, *, label: str) -> str:
        if not isinstance(value, str):
            raise BrokerError(f"Kotak Neo emergency {label} is not canonical")
        identifier = value
        if (
            not identifier
            or identifier != identifier.strip()
            or not identifier.isprintable()
            or any(character.isspace() for character in identifier)
        ):
            raise BrokerError(f"Kotak Neo emergency {label} is not canonical")
        return identifier

    @staticmethod
    def _emergency_label(value: Any, *, label: str) -> str:
        if not isinstance(value, str):
            raise BrokerError(f"Kotak Neo emergency {label} is not canonical")
        text = value
        if not text or text != text.strip() or not text.isprintable():
            raise BrokerError(f"Kotak Neo emergency {label} is not canonical")
        return text

    @staticmethod
    def _emergency_integer(value: Any, *, label: str) -> int:
        try:
            number = Decimal(str(value).strip())
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise BrokerError(f"Kotak Neo emergency {label} is invalid") from exc
        if not number.is_finite() or number != number.to_integral_value():
            raise BrokerError(f"Kotak Neo emergency {label} is invalid")
        return int(number)

    @staticmethod
    def _emergency_book_rows(response: Any, *, book: str) -> tuple[dict[str, Any], ...]:
        """Accept only Kotak's documented explicit-success book envelope."""
        if not isinstance(response, dict):
            raise BrokerError(f"Kotak Neo emergency {book} response is malformed")
        status = response.get("stat")
        status_code = response.get("stCode")
        rows = response.get("data")
        if not isinstance(status, str) or status.strip().lower() != "ok":
            raise BrokerError(f"Kotak Neo emergency {book} response has no explicit success status")
        if isinstance(status_code, bool) or not isinstance(status_code, int) or status_code != 200:
            raise BrokerError(f"Kotak Neo emergency {book} response has no explicit HTTP 200 status")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise BrokerError(f"Kotak Neo emergency {book} is not a list of objects")
        return tuple(rows)

    async def _emergency_order_rows(self, session: Session) -> tuple[dict[str, Any], ...]:
        response = await self._call(self._client(session).order_book)
        raw_rows = self._emergency_book_rows(response, book="order book")
        rows: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for raw in raw_rows:
            order_id = self._emergency_identifier(raw.get("nOrdNo"), label="order id")
            if order_id in seen_ids:
                raise BrokerError("Kotak Neo emergency order book contains a duplicate order id")
            seen_ids.add(order_id)

            status = self._emergency_label(raw.get("ordSt"), label="order status").lower()
            if status not in _EMERGENCY_TERMINAL_ORDER_STATUSES | _EMERGENCY_ACTIVE_ORDER_STATUSES:
                raise BrokerError("Kotak Neo emergency order status is not authoritative")
            product = self._emergency_identifier(raw.get("prod"), label="order product").upper()
            if product not in _EMERGENCY_ORDER_PRODUCTS:
                raise BrokerError("Kotak Neo emergency order product is unsupported")
            variety = "bracket" if product == "BO" else "cover" if product == "CO" else "regular"

            raw_generation = raw.get("ordGenTp")
            if raw_generation is None:
                raise BrokerError("Kotak Neo order has no authoritative AMO discriminator")
            if not isinstance(raw_generation, str) or raw_generation != raw_generation.strip():
                raise BrokerError("Kotak Neo emergency order generation type is malformed")
            generation = raw_generation.upper()
            if generation not in {"", "NA", "--", "AMO"}:
                raise BrokerError("Kotak Neo emergency order generation type is unsupported")
            amo = generation == "AMO"
            if status == "after market order req received" and not amo:
                raise BrokerError("Kotak Neo after-market order status contradicts its generation type")
            if amo and variety == "regular":
                variety = "amo"

            trading_symbol = self._emergency_identifier(raw.get("trdSym"), label="trading symbol")
            exchange_segment = self._emergency_identifier(raw.get("exSeg"), label="order exchange segment")
            exchange = M.KOTAK_TO_EXCHANGE.get(exchange_segment)
            if exchange is None:
                raise BrokerError("Kotak Neo emergency order exchange segment is unsupported")
            side = self._emergency_identifier(raw.get("trnsTp"), label="order side").upper()
            action = M.KOTAK_TO_SIDE.get(side)
            if action is None:
                raise BrokerError("Kotak Neo emergency order side is unsupported")
            quantity = self._emergency_integer(raw.get("qty"), label="order quantity")
            if quantity <= 0:
                raise BrokerError("Kotak Neo emergency order quantity must be positive")
            filled_quantity = self._emergency_integer(raw.get("fldQty"), label="order filled quantity")
            if filled_quantity < 0 or filled_quantity > quantity:
                raise BrokerError("Kotak Neo emergency order filled quantity is inconsistent")
            price_type = self._emergency_identifier(raw.get("prcTp"), label="order price type").upper()
            raw_tag = raw.get("GuiOrdId", "")
            if raw_tag in (None, ""):
                tag = ""
            else:
                tag = self._emergency_label(raw_tag, label="order tag")

            rows.append(
                {
                    "orderid": order_id,
                    "status": status,
                    "symbol": trading_symbol,
                    "exchange": exchange,
                    "exchange_segment": exchange_segment,
                    "product": product,
                    "broker_product": product,
                    "action": action,
                    "quantity": quantity,
                    "filled_quantity": filled_quantity,
                    "price_type": price_type,
                    "tag": tag,
                    "variety": variety,
                    "amo": amo,
                }
            )
        return tuple(rows)

    async def _emergency_trade_fills(self, session: Session) -> dict[str, int]:
        """Aggregate the full broker trade book without the SDK's lossy filter."""
        response = await self._call(self._client(session).trade_book)
        raw_rows = self._emergency_book_rows(response, book="trade book")
        fills: dict[str, int] = {}
        seen_fill_ids: set[str] = set()
        for raw in raw_rows:
            order_id = self._emergency_identifier(raw.get("nOrdNo"), label="trade order id")
            fill_id = self._emergency_identifier(raw.get("flId"), label="trade fill id")
            if fill_id in seen_fill_ids:
                raise BrokerError("Kotak Neo emergency trade book contains a duplicate fill id")
            seen_fill_ids.add(fill_id)
            report_type = self._emergency_identifier(raw.get("rptTp"), label="trade report type").lower()
            if report_type != "fill":
                raise BrokerError("Kotak Neo emergency trade book contains a non-fill row")
            quantity = self._emergency_integer(raw.get("fldQty"), label="trade fill quantity")
            if quantity <= 0:
                raise BrokerError("Kotak Neo emergency trade fill quantity must be positive")
            fills[order_id] = fills.get(order_id, 0) + quantity
        return fills

    async def _emergency_positions(self, session: Session) -> tuple[dict[str, Any], ...]:
        response = await self._call(self._client(session).positions)
        raw_rows = self._emergency_book_rows(response, book="position book")
        positions: dict[tuple[str, str, str], dict[str, Any]] = {}
        for raw in raw_rows:
            accounting_fields = ("cfBuyQty", "cfSellQty", "flBuyQty", "flSellQty")
            if not all(field in raw for field in accounting_fields):
                raise BrokerError("Kotak Neo emergency position accounting is incomplete")
            carry_buy = self._emergency_integer(raw["cfBuyQty"], label="carry-forward buy quantity")
            carry_sell = self._emergency_integer(raw["cfSellQty"], label="carry-forward sell quantity")
            filled_buy = self._emergency_integer(raw["flBuyQty"], label="filled buy quantity")
            filled_sell = self._emergency_integer(raw["flSellQty"], label="filled sell quantity")
            if min(carry_buy, carry_sell, filled_buy, filled_sell) < 0:
                raise BrokerError("Kotak Neo emergency position accounting cannot be negative")
            quantity = carry_buy + filled_buy - carry_sell - filled_sell
            if quantity == 0:
                continue

            trading_symbol = self._emergency_identifier(raw.get("trdSym"), label="position trading symbol")
            exchange_segment = self._emergency_identifier(raw.get("exSeg"), label="position exchange segment")
            exchange = M.KOTAK_TO_EXCHANGE.get(exchange_segment)
            if exchange is None:
                raise BrokerError("Kotak Neo emergency position exchange segment is unsupported")
            broker_product = self._emergency_identifier(raw.get("prod"), label="position product").upper()
            if broker_product not in _EMERGENCY_POSITION_PRODUCTS:
                raise BrokerError("Kotak Neo emergency position product cannot be reduced authoritatively")
            lot_size = self._emergency_integer(raw.get("lotSz"), label="position lot size")
            if lot_size <= 0 or abs(quantity) % lot_size:
                raise BrokerError("Kotak Neo emergency position quantity is not a whole lot")

            position = {
                "symbol": trading_symbol,
                "exchange": exchange,
                "exchange_segment": exchange_segment,
                "product": broker_product,
                "broker_product": broker_product,
                "quantity": quantity,
                "lot_size": lot_size,
                "carry_buy_quantity": carry_buy,
                "carry_sell_quantity": carry_sell,
                "filled_buy_quantity": filled_buy,
                "filled_sell_quantity": filled_sell,
            }
            key = self._emergency_position_key(position)
            if key in positions:
                raise BrokerError("Kotak Neo emergency position book contains a duplicate identity")
            positions[key] = position
        return tuple(positions[key] for key in sorted(positions))

    @staticmethod
    def _emergency_position_key(position: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(position["symbol"]),
            str(position["exchange_segment"]),
            str(position["broker_product"]),
        )

    @classmethod
    def _emergency_exit_tag(cls, position: dict[str, Any], *, quantity: int | None = None) -> str:
        signed_quantity = (
            cls._emergency_integer(position.get("quantity"), label="position quantity")
            if quantity is None
            else quantity
        )
        if signed_quantity == 0:
            raise BrokerError("Kotak Neo emergency position is flat")
        identity = "|".join(
            (
                cls._emergency_identifier(position.get("symbol"), label="position trading symbol"),
                cls._emergency_identifier(position.get("exchange_segment"), label="position exchange segment"),
                cls._emergency_identifier(position.get("broker_product"), label="position product"),
                str(signed_quantity),
                str(cls._emergency_integer(position.get("lot_size"), label="position lot size")),
                str(cls._emergency_integer(position.get("carry_buy_quantity"), label="carry-forward buy quantity")),
                str(cls._emergency_integer(position.get("carry_sell_quantity"), label="carry-forward sell quantity")),
                str(cls._emergency_integer(position.get("filled_buy_quantity"), label="filled buy quantity")),
                str(cls._emergency_integer(position.get("filled_sell_quantity"), label="filled sell quantity")),
            )
        )
        return f"{_EMERGENCY_EXIT_TAG_PREFIX}{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}"

    @staticmethod
    def _emergency_order_matches_position(order: dict[str, Any], position: dict[str, Any]) -> bool:
        return (
            str(order.get("symbol") or ""),
            str(order.get("exchange_segment") or ""),
            str(order.get("broker_product") or "").upper(),
        ) == (
            str(position.get("symbol") or ""),
            str(position.get("exchange_segment") or ""),
            str(position.get("broker_product") or "").upper(),
        )

    @classmethod
    def _emergency_original_position(
        cls,
        order: dict[str, Any],
        position: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Reconstruct the pre-fill episode for one still-active reducing order."""
        filled = order.get("filled_quantity")
        if filled is None:
            return None
        filled_quantity = cls._emergency_integer(filled, label="exit filled quantity")
        current_quantity = cls._emergency_integer(position.get("quantity"), label="position quantity")
        original = dict(position)
        action = str(order.get("action") or "").upper()
        if action == "SELL":
            current_sell = cls._emergency_integer(position.get("filled_sell_quantity"), label="filled sell quantity")
            if current_sell < filled_quantity:
                return None
            original["quantity"] = current_quantity + filled_quantity
            original["filled_sell_quantity"] = current_sell - filled_quantity
        elif action == "BUY":
            current_buy = cls._emergency_integer(position.get("filled_buy_quantity"), label="filled buy quantity")
            if current_buy < filled_quantity:
                return None
            original["quantity"] = current_quantity - filled_quantity
            original["filled_buy_quantity"] = current_buy - filled_quantity
        else:
            return None
        return original

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
        client = None if self._client_factory is not None else await self._call(KotakNeoClient, dict(credentials))
        return Session(
            access_token=str(credentials.get("ucc", "")),
            expires_at=datetime.now(tz=UTC).timestamp() + 24 * 3600,
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
        return

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
        return M.extract_order_id(M.require_write_success(resp))

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
        M.require_write_success(resp, expected_order_id=str(order_id))

    async def cancel_order(
        self,
        session: Session,
        order_id: str,
        *,
        variety: str = "regular",
        amo: bool = False,
        trading_symbol: str | None = None,
        _router_token: object | None = None,
    ) -> None:
        """Cancel an order (gated) — variety dispatch within the gated method.

        ``regular``/``amo`` use the plain cancel endpoint; ``cover`` exits via
        ``quick/order/co/exit`` and ``bracket`` via ``quick/order/bo/exit`` (the
        dedicated leg-cancel endpoints — ``Cancel_Cover_Order.md`` /
        ``Cancel_Bracket_Order.md``). ``amo=True`` forwards the pinned SDK's
        documented ``am=YES`` flag. ``trading_symbol`` remains an optional
        compatibility field, but the emergency planner does not rely on it.
        The default call shape (``cancel_order(session, order_id,
        _router_token=…)``) is exactly what ``BrokerRouter`` dispatches today;
        the variety/amo/trading_symbol keywords are adapter-level extras for
        variety-aware callers and are signed by the cancel route before the
        router forwards them.
        """
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        client = self._client(session)
        v = str(variety).lower()
        amo_flag = "YES" if (amo or v == "amo") else "NO"
        if v in ("regular", "", "amo"):
            if amo_flag == "YES" or trading_symbol:
                resp = await self._call(
                    client.cancel_order,
                    str(order_id),
                    amo_flag,
                    trading_symbol=trading_symbol,
                )
            else:
                resp = await self._call(client.cancel_order, str(order_id))
        elif v == "cover":
            resp = await self._call(
                client.cancel_cover_order,
                str(order_id),
                amo_flag,
                trading_symbol=trading_symbol,
            )
        elif v == "bracket":
            resp = await self._call(
                client.cancel_bracket_order,
                str(order_id),
                amo_flag,
                trading_symbol=trading_symbol,
            )
        else:
            raise BrokerError(f"Kotak Neo cannot cancel order variety {variety!r}")
        M.require_write_success(resp, expected_order_id=str(order_id))

    @classmethod
    def _emergency_active_exit_state(
        cls,
        order: dict[str, Any],
        position: dict[str, Any],
        *,
        protected_exit_order_ids: frozenset[str],
        protected_exit_tags: frozenset[str],
    ) -> str:
        """Classify a journal/tag-identified active exit against one exposure."""
        order_id = str(order.get("orderid") or "")
        tag = str(order.get("tag") or "")
        trusted_id = order_id in protected_exit_order_ids
        tagged = tag.startswith(_EMERGENCY_EXIT_TAG_PREFIX) or tag in protected_exit_tags
        if not (trusted_id or tagged) or not cls._emergency_order_matches_position(order, position):
            return "unrelated"
        if bool(order.get("amo")) or str(order.get("variety") or "").lower() != "regular":
            return "conflicting"
        if str(order.get("price_type") or "").upper() not in {"MKT", "L"}:
            return "conflicting"
        filled_quantity = order.get("filled_quantity")
        if filled_quantity is None:
            return "unsettled"
        current_quantity = cls._emergency_integer(position.get("quantity"), label="position quantity")
        requested_quantity = cls._emergency_integer(order.get("quantity"), label="exit requested quantity")
        filled = cls._emergency_integer(filled_quantity, label="exit filled quantity")
        expected_action = "SELL" if current_quantity > 0 else "BUY"
        action = str(order.get("action") or "").upper()
        if action != expected_action or requested_quantity <= 0 or filled < 0 or filled > requested_quantity:
            return "conflicting"
        pending_quantity = requested_quantity - filled
        if pending_quantity <= 0:
            return "conflicting"
        original = cls._emergency_original_position(order, position)
        if original is None:
            return "conflicting"
        original_quantity = cls._emergency_integer(original.get("quantity"), label="original position quantity")
        if requested_quantity != abs(original_quantity) or pending_quantity != abs(current_quantity):
            return "conflicting"
        expected_tag = cls._emergency_exit_tag(original)
        if tag and tag != expected_tag:
            return "conflicting"
        if not tag and not trusted_id:
            return "unrelated"
        return "exact"

    @classmethod
    def _emergency_completed_exit_matches(
        cls,
        order: dict[str, Any],
        position: dict[str, Any],
        *,
        protected_exit_order_ids: frozenset[str],
        protected_exit_tags: frozenset[str],
    ) -> bool:
        if not cls._emergency_order_matches_position(order, position):
            return False
        if bool(order.get("amo")) or str(order.get("variety") or "").lower() != "regular":
            return False
        if str(order.get("price_type") or "").upper() not in {"MKT", "L"}:
            return False
        order_id = str(order.get("orderid") or "")
        tag = str(order.get("tag") or "")
        if not (
            order_id in protected_exit_order_ids
            or tag in protected_exit_tags
            or tag.startswith(_EMERGENCY_EXIT_TAG_PREFIX)
        ):
            return False
        filled_quantity = order.get("filled_quantity")
        if filled_quantity is None:
            return False
        current_quantity = cls._emergency_integer(position.get("quantity"), label="position quantity")
        requested_quantity = cls._emergency_integer(order.get("quantity"), label="exit requested quantity")
        filled = cls._emergency_integer(filled_quantity, label="exit filled quantity")
        expected_action = "SELL" if current_quantity > 0 else "BUY"
        if (
            str(order.get("action") or "").upper() != expected_action
            or requested_quantity != abs(current_quantity)
            or filled != requested_quantity
        ):
            return False
        expected_tag = cls._emergency_exit_tag(position)
        return not tag or tag == expected_tag

    @staticmethod
    def _emergency_cancel_write(
        order: dict[str, Any],
        *,
        parent_verb: str,
    ) -> EmergencyBrokerWrite:
        payload: dict[str, object] = {
            "_op": "cancel_order",
            "order_id": str(order["orderid"]),
            "variety": str(order["variety"]),
            "amo": bool(order["amo"]),
        }
        return EmergencyBrokerWrite(
            parent_verb=parent_verb,
            verb="cancel_order",
            payload=payload,
        )

    async def plan_emergency_reduction(
        self,
        session: Session,
        *,
        policy: EmergencyWritePolicy,
        protected_order_ids: frozenset[str],
        protected_exit_order_ids: frozenset[str] = frozenset(),
        protected_exit_tags: frozenset[str],
        unidentified_exit_inflight: bool = False,
    ) -> EmergencyReductionPlan:
        """Derive bounded concrete writes from strict Kotak order/position books."""
        requested = frozenset(policy.verbs)
        orders = await self._emergency_order_rows(session)
        if "exit_all_positions" in requested:
            trade_fills = await self._emergency_trade_fills(session)
            known_order_ids = frozenset(str(order["orderid"]) for order in orders)
            if set(trade_fills) - known_order_ids:
                raise BrokerError("Kotak Neo emergency trade book contains an unknown order id")
            if any(int(order["filled_quantity"]) != trade_fills.get(str(order["orderid"]), 0) for order in orders):
                raise BrokerError("Kotak Neo emergency order and trade books disagree on fills")
            positions = await self._emergency_positions(session)
        else:
            positions = ()
        active_orders = tuple(order for order in orders if order["status"] not in _EMERGENCY_TERMINAL_ORDER_STATUSES)
        known_order_ids = frozenset(str(order["orderid"]) for order in orders)
        observed_tags = {str(order["tag"]) for order in orders if str(order.get("tag") or "")}
        positions_by_key = {self._emergency_position_key(position): position for position in positions}
        current_position_tags = {self._emergency_exit_tag(position) for position in positions}

        exact_exit_order_ids: set[str] = set()
        unsettled_exit_order_ids: set[str] = set()
        conflicting_exit_rows: dict[str, dict[str, Any]] = {}
        blocked_position_keys: set[tuple[str, str, str]] = set()
        reconstructed_tags: set[str] = set()

        for order in active_orders:
            order_id = str(order["orderid"])
            tag = str(order.get("tag") or "")
            if not (
                order_id in protected_exit_order_ids
                or tag in protected_exit_tags
                or tag.startswith(_EMERGENCY_EXIT_TAG_PREFIX)
            ):
                continue
            matches: list[tuple[tuple[str, str, str], dict[str, Any], str]] = []
            for key, position in positions_by_key.items():
                state = self._emergency_active_exit_state(
                    order,
                    position,
                    protected_exit_order_ids=protected_exit_order_ids,
                    protected_exit_tags=protected_exit_tags,
                )
                if state != "unrelated":
                    matches.append((key, position, state))
            if len(matches) != 1:
                conflicting_exit_rows[order_id] = order
                continue
            key, position, state = matches[0]
            if state == "exact":
                exact_exit_order_ids.add(order_id)
                blocked_position_keys.add(key)
                original = self._emergency_original_position(order, position)
                if original is None:  # pragma: no cover - state="exact" proves this
                    raise BrokerError("Kotak Neo active exit episode cannot be reconstructed")
                reconstructed_tags.add(str(order.get("tag") or "") or self._emergency_exit_tag(original))
            elif state == "unsettled":
                unsettled_exit_order_ids.add(order_id)
                blocked_position_keys.add(key)
            else:
                conflicting_exit_rows[order_id] = order

        unreconciled_completed_exit = False
        for order in orders:
            if order["status"] not in _EMERGENCY_SUCCESSFUL_ORDER_STATUSES:
                continue
            order_id = str(order["orderid"])
            tag = str(order.get("tag") or "")
            protected = order_id in protected_exit_order_ids or tag in protected_exit_tags
            current_episode = tag in current_position_tags
            if not (protected or current_episode):
                continue
            matches = [
                (key, position)
                for key, position in positions_by_key.items()
                if self._emergency_order_matches_position(order, position)
            ]
            if not matches:
                # The strict position book proves this completed exit's exact
                # instrument is flat; do not stall a later instrument batch.
                continue
            if len(matches) != 1:
                unreconciled_completed_exit = True
                continue
            key, position = matches[0]
            if not self._emergency_completed_exit_matches(
                order,
                position,
                protected_exit_order_ids=protected_exit_order_ids,
                protected_exit_tags=protected_exit_tags,
            ):
                unreconciled_completed_exit = True
                continue
            blocked_position_keys.add(key)
            reconstructed_tags.add(self._emergency_exit_tag(position))

        missing_protected_exit_ids = protected_exit_order_ids - known_order_ids
        missing_protected_exit_tags = (protected_exit_tags & current_position_tags) - observed_tags - reconstructed_tags
        missing_tag_position_keys = {
            key
            for key, position in positions_by_key.items()
            if self._emergency_exit_tag(position) in missing_protected_exit_tags
        }
        blocked_position_keys.update(missing_tag_position_keys)
        protected_cancellation_ids = set(protected_order_ids)
        protected_inflight_exit_ids = exact_exit_order_ids | unsettled_exit_order_ids
        cancellable = tuple(
            order
            for order in active_orders
            if str(order["orderid"]) not in protected_cancellation_ids | protected_inflight_exit_ids
        )

        pending: set[str] = set()
        if "cancel_all_orders" in requested and active_orders:
            pending.add("cancel_all_orders")
        if "exit_all_positions" in requested and (
            positions
            or any(str(order["orderid"]) in protected_exit_order_ids for order in active_orders)
            or (positions and (missing_protected_exit_ids or missing_protected_exit_tags))
        ):
            pending.add("exit_all_positions")
        if not pending:
            return EmergencyReductionPlan(writes=(), pending_verbs=frozenset())
        if (
            unidentified_exit_inflight
            or unsettled_exit_order_ids
            or unreconciled_completed_exit
            or (positions and missing_protected_exit_ids)
        ):
            return EmergencyReductionPlan(writes=(), pending_verbs=frozenset(pending))

        if "cancel_all_orders" in pending:
            writes = tuple(
                self._emergency_cancel_write(order, parent_verb="cancel_all_orders")
                for order in sorted(cancellable, key=lambda row: str(row["orderid"]))[:_EMERGENCY_BATCH_LIMIT]
            )
            return EmergencyReductionPlan(writes=writes, pending_verbs=frozenset(pending))

        if "exit_all_positions" in pending:
            if conflicting_exit_rows:
                uncancelled_conflicts = (
                    order
                    for order in conflicting_exit_rows.values()
                    if str(order["orderid"]) not in protected_cancellation_ids
                )
                writes = tuple(
                    self._emergency_cancel_write(order, parent_verb="exit_all_positions")
                    for order in sorted(uncancelled_conflicts, key=lambda row: str(row["orderid"]))[
                        :_EMERGENCY_BATCH_LIMIT
                    ]
                )
                return EmergencyReductionPlan(writes=writes, pending_verbs=frozenset(pending))
            positions_to_exit = tuple(
                position
                for position in positions
                if self._emergency_position_key(position) not in blocked_position_keys
            )
            writes = tuple(
                EmergencyBrokerWrite(
                    parent_verb="exit_all_positions",
                    verb="place_reducing_order",
                    payload={
                        "_op": "place_reducing_order",
                        "symbol": str(position["symbol"]),
                        "exchange": str(position["exchange"]),
                        "exchange_segment": str(position["exchange_segment"]),
                        "product": str(position["product"]),
                        "broker_product": str(position["broker_product"]),
                        "lot_size": str(position["lot_size"]),
                        "carry_buy_quantity": str(position["carry_buy_quantity"]),
                        "carry_sell_quantity": str(position["carry_sell_quantity"]),
                        "filled_buy_quantity": str(position["filled_buy_quantity"]),
                        "filled_sell_quantity": str(position["filled_sell_quantity"]),
                        "quantity": str(abs(int(position["quantity"]))),
                        "expected_position_quantity": str(position["quantity"]),
                        "action": "SELL" if int(position["quantity"]) > 0 else "BUY",
                        "pricetype": "MARKET",
                        "price": "0",
                        "trigger_price": "0",
                        "variety": "regular",
                        "emergency_tag": self._emergency_exit_tag(position),
                    },
                )
                for position in positions_to_exit[:_EMERGENCY_BATCH_LIMIT]
            )
            return EmergencyReductionPlan(writes=writes, pending_verbs=frozenset(pending))

        return EmergencyReductionPlan(writes=(), pending_verbs=frozenset(pending))

    async def place_reducing_order(
        self,
        session: Session,
        payload: dict[str, Any],
        *,
        _router_token: object | None = None,
    ) -> str:
        """Place one exact opposite-side MARKET order after final strict readback."""
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        symbol = self._emergency_identifier(payload.get("symbol"), label="position trading symbol")
        exchange = self._emergency_identifier(payload.get("exchange"), label="position exchange").upper()
        exchange_segment = self._emergency_identifier(
            payload.get("exchange_segment"), label="position exchange segment"
        )
        product = self._emergency_identifier(payload.get("product"), label="position product").upper()
        broker_product = self._emergency_identifier(
            payload.get("broker_product"), label="broker position product"
        ).upper()
        expected_quantity = self._emergency_integer(
            payload.get("expected_position_quantity"), label="expected position quantity"
        )
        reducing_quantity = self._emergency_integer(payload.get("quantity"), label="reducing quantity")
        lot_size = self._emergency_integer(payload.get("lot_size"), label="position lot size")
        expected_accounting = {
            field: self._emergency_integer(payload.get(field), label=field.replace("_", " "))
            for field in (
                "carry_buy_quantity",
                "carry_sell_quantity",
                "filled_buy_quantity",
                "filled_sell_quantity",
            )
        }
        expected_action = "SELL" if expected_quantity > 0 else "BUY"
        if (
            expected_quantity == 0
            or reducing_quantity != abs(expected_quantity)
            or lot_size <= 0
            or reducing_quantity % lot_size
            or M.KOTAK_TO_EXCHANGE.get(exchange_segment) != exchange
            or broker_product not in _EMERGENCY_POSITION_PRODUCTS
            or broker_product != product
            or str(payload.get("action") or "").upper() != expected_action
            or str(payload.get("pricetype") or "").upper() != "MARKET"
            or str(payload.get("variety") or "").lower() != "regular"
            or self._emergency_integer(payload.get("price"), label="reducing price") != 0
            or self._emergency_integer(payload.get("trigger_price"), label="reducing trigger price") != 0
        ):
            raise BrokerError("Kotak Neo reducing write is not an exact regular MARKET order")

        current_positions = await self._emergency_positions(session)
        current = next(
            (
                position
                for position in current_positions
                if (
                    position["symbol"],
                    position["exchange"],
                    position["exchange_segment"],
                    position["product"],
                    position["broker_product"],
                )
                == (symbol, exchange, exchange_segment, product, broker_product)
            ),
            None,
        )
        if current is None or int(current["quantity"]) != expected_quantity:
            raise BrokerError("Kotak Neo position changed before the reducing write")
        if int(current["lot_size"]) != lot_size:
            raise BrokerError("Kotak Neo position lot size changed before the reducing write")
        if any(int(current[field]) != value for field, value in expected_accounting.items()):
            raise BrokerError("Kotak Neo position accounting changed before the reducing write")
        tag = str(payload.get("emergency_tag") or "")
        if not tag.startswith(_EMERGENCY_EXIT_TAG_PREFIX) or tag != self._emergency_exit_tag(current):
            raise BrokerError("Kotak Neo reducing position episode changed before dispatch")

        current_orders = await self._emergency_order_rows(session)
        for order in current_orders:
            if order["status"] in _EMERGENCY_TERMINAL_ORDER_STATUSES:
                continue
            if not self._emergency_order_matches_position(order, current):
                continue
            if str(order.get("action") or "").upper() == expected_action:
                raise BrokerError("Kotak Neo concurrent reducing order appeared before dispatch")

        from flinttrade_core.models import Order  # noqa: PLC0415

        order = Order(
            symbol=symbol,
            action=expected_action,
            exchange=exchange,
            pricetype="MARKET",
            product=product,
            quantity=str(reducing_quantity),
            price="0",
            trigger_price="0",
            variety="regular",
            strategy="Emergency",
        )
        response = await self._call(
            self._client(session).place_order,
            M.to_place_order_params(order, symbol, tag=tag),
        )
        return M.extract_order_id(M.require_write_success(response))

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

    async def limits(self, session: Session, segment: str = "ALL", exchange: str = "ALL", product: str = "ALL") -> dict:
        """Filtered RMS limits (NEO ``limits(segment, exchange, product)``).

        ``funds`` is the unfiltered contract read; this exposes the documented
        filter surface (segment ∈ CASH/CUR/FO/ALL, exchange ∈ NSE/BSE/ALL,
        product ∈ CNC/MIS/NRML/ALL — ``Limits.md``). The raw flat response is
        preserved under ``extra``.
        """
        params = M.to_limits_params(segment, exchange, product)
        resp = await self._call(self._client(session).limits, params["segment"], params["exchange"], params["product"])
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
            raise NotImplementedError("Kotak Neo live tick stream needs the HSM market feed (inject feed_factory)")
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
            raise NotImplementedError("Kotak Neo live order feed needs the HSI socket (inject order_feed_factory)")
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
        snapshot (the engine wires a durable selector-scoped provider). A
        broker fetch failure is captured on the report's
        ``error`` field instead of raised, so the runner retries next cycle.
        """
        from flinttrade_gateway.reconciliation import (  # noqa: PLC0415
            EMPTY_LOCAL_STATE,
            build_report,
            declare_unavailable_order_fields,
        )

        generated_at = datetime.now(tz=UTC)
        local = EMPTY_LOCAL_STATE if self._local_state_provider is None else self._local_state_provider(session)
        try:
            broker_orders = declare_unavailable_order_fields(
                await self.order_book(session),
                fields=("variety", "validity", "strategy"),
            )
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
