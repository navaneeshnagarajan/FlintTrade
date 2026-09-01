"""Dhan v2 native adapter (doc-grounded against dhanhq 2.2.0).

Implements the BrokerAdapter contract for Dhan: auth, the gated write surface
(place/modify/cancel), and the portfolio reads (order book / trade book /
positions / holdings / funds). Request/response translation lives in
``dhan_mapping`` and is unit-tested; here the methods are thin wrappers that call
the dhanhq SDK on a worker thread (the SDK is synchronous) and normalise results.

Safety: writes still require the router's per-process ``_ROUTER_TOKEN`` (§8), so
a bare call raises before any Dhan request. ``build_broker_router``'s
native-activation factory registers this adapter automatically once its pinned
SDK (``dhanhq``) is attested AND vault credentials exist; until then it stays
dormant. Dhan is the one native with a real ``brokers.lock`` pin, so where
``dhanhq`` is installed at the pinned version it *is* attested — only stored
credentials + a live login then separate it from going live (verify live order
placement against the real SDK + a Dhan account).

This adapter implements the FULL contract plus the complete Dhan v2.x surface
(through v2.5): auth, gated writes (regular / bracket / cover / iceberg /
forever / super / conditional-trigger), portfolio reads + convert position,
market data (quotes / historical / option chain / expired rolling options),
EDIS, Trader's Control (kill switch + P&L-based exit + Exit All), static-IP
management, the binary tick stream, the order-update stream and the 20/200-level
depth streams. v2.5 endpoints absent from the pinned SDK (dhanhq 2.2.0) are
called through the SDK's own ``DhanHTTP`` transport with doc-grounded paths.
"""

from __future__ import annotations

import asyncio
import math
import threading
import time
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable
from urllib.parse import urlencode

from flinttrade_core.exceptions import BrokerError, UnsupportedCapabilityError
from flinttrade_engine.safety import EmergencyBrokerWrite, EmergencyReductionPlan, EmergencyWritePolicy
from flinttrade_gateway.capabilities import (
    AuthModel,
    Capabilities,
    DepthLevels,
    OrderTypes,
    Segments,
    TickProtocol,
)

from . import dhan_mapping as M
from ._base import BrokerAdapter, Session, run_blocking_sdk_call

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flinttrade_core.models import Candles, OptionChain, Order, Position, Quote, Trade
    from flinttrade_gateway.reconciliation import LocalStateSnapshot, ReconciliationReport

_EMERGENCY_READBACK_ATTEMPTS = 5
_EMERGENCY_QUIET_READS = 3
_EMERGENCY_READBACK_DELAY_SECONDS = 0.05
_EMERGENCY_TRIGGER_SETTLEMENT_SECONDS = 300.0
_EMERGENCY_BATCH_LIMIT = 10
_OPTION_CHAIN_CACHE_SECONDS = 3.0
_SAFETY_TERMINAL_ORDER_STATUSES = frozenset(
    {
        "CANCELED",
        "CANCELLED",
        "CLOSED",
        "COMPLETE",
        "COMPLETED",
        "DELETED",
        "DISABLED",
        "EXPIRED",
        "FILLED",
        "REJECTED",
        "TRADED",
    }
)
_SAFETY_SUPER_NO_CHILD_STATUSES = frozenset({"CANCELED", "CANCELLED", "EXPIRED", "REJECTED"})
_SAFETY_SUPER_ENTRY_TERMINAL_STATUSES = _SAFETY_TERMINAL_ORDER_STATUSES | {"TRIGGERED"}
_SAFETY_CONDITIONAL_TERMINAL_STATUSES = frozenset(
    {"CANCELED", "CANCELLED", "DELETED", "DISABLED", "EXPIRED", "TRIGGERED"}
)

DHAN_CAPABILITIES = Capabilities(
    segments=Segments.NSE_EQ | Segments.BSE_EQ | Segments.NFO | Segments.BFO | Segments.CDS | Segments.MCX,
    order_types=(
        OrderTypes.MARKET
        | OrderTypes.LIMIT
        | OrderTypes.SL
        | OrderTypes.SLM
        | OrderTypes.MIS
        | OrderTypes.CNC
        | OrderTypes.NRML
        | OrderTypes.AMO
        | OrderTypes.GTT
        | OrderTypes.ICEBERG
        | OrderTypes.BO
        | OrderTypes.CO
    ),
    # Standard market-depth feed is 5-level, but Dhan v2 also offers a dedicated
    # 20-level depth feed (wss://depth-api-feed.dhan.co/twentydepth) and a
    # 200-level full-depth feed (wss://full-depth-api.dhan.co/twohundreddepth),
    # so the advertised maximum is L20 (the enum ceiling; 200-level is beyond it).
    depth_levels=DepthLevels.L20,
    tick_protocol=TickProtocol.DHAN_BINARY,
    auth_model=AuthModel.OAUTH_RENEWABLE_24H,
    session_lifetime_hours=24.0,
    session_renewal_leeway_seconds=120,
    sandbox=True,
    rate_limit_orders_per_sec=10,
    rate_limit_orders_per_min=250,
    rate_limit_orders_per_hour=1000,
    rate_limit_orders_per_day=7000,
    rate_limit_data_per_sec=5,
    rate_limit_data_per_day=100_000,
    rate_limit_quote_per_sec=1,
    rate_limit_non_trading_per_sec=20,
    order_modifications_per_order=25,
    algo_tag_required=True,
    # Intraday history reaches ~5 years back (historical-data.md "for last 5
    # years"); the documented 90-day cap is the per-REQUEST date range, not the
    # lookback, so it is noted here, not encoded as the lookback. Dhan documents
    # no max-candles-per-request limit (it caps by date range), so 0 = unknown.
    historical_max_lookback_days_intraday=1825,  # ~5 years (90 days = per-request range cap)
    historical_max_lookback_days_daily=None,
    historical_max_candles_per_request=0,
    historical_intraday_intervals_minutes=[1, 5, 15, 25, 60],
    historical_calendar_intervals=["1D"],
    option_chain_supported=True,
    option_chain_greeks_supported=True,
    option_chain_rate_limit_seconds=3,
    # Dhan's edge: historical option-chain / options-OHLC with rolling expiry
    # series (a strike's history readable across its expiry rollover).
    options_history_supported=True,
    options_history_rolling=True,
    streaming_supported=True,
    market_depth_runtime_ready=False,
    streaming_max_connections_per_user=5,
    streaming_max_symbols_per_connection=5000,
    streaming_max_total_symbols=25_000,
    streaming_heartbeat_seconds=10,
    streaming_disconnect_timeout_seconds=40,
    bracket_order_native=True,
    cover_order_native=True,
    basket_order_native=True,
    multi_quote_supported=True,
    multi_option_greeks_supported=True,
    iceberg_native=True,
    gtt_native=True,
    modify_qty_supported=True,
    modify_after_partial_fill=False,
)


def _build_dhan_client(client_id: str, access_token: str) -> Any:
    """Construct a live dhanhq 2.2.0 client (lazy import — SDK optional)."""
    from dhanhq import DhanContext, dhanhq  # noqa: PLC0415

    return dhanhq(DhanContext(client_id, access_token))


def _build_dhan_login(client_id: str) -> Any:
    """Construct a live ``DhanLogin`` auth helper (lazy import — SDK optional)."""
    from dhanhq import DhanLogin  # noqa: PLC0415

    return DhanLogin(client_id)


def _download_text(url: str) -> str:
    """Fetch a (HTTPS-only) text resource — the scrip-master CSV downloader."""
    if not url.startswith("https://"):
        raise BrokerError(f"Refusing non-HTTPS scrip master URL: {url!r}")
    from urllib.request import urlopen  # noqa: PLC0415

    with urlopen(url, timeout=60) as response:  # noqa: S310 - scheme pinned to https above
        return response.read().decode("utf-8", errors="replace")


def _optional_safety_text(value: Any) -> str:
    return "" if value in (None, "") else str(value)


def load_scrip_master_rows(mode: str = "compact", *, downloader: Callable[[str], str] | None = None) -> list[dict]:
    """Download + parse the Dhan scrip-master CSV (public, synchronous).

    The ONE canonical fetch+parse composition for Dhan instrument rows:
    :meth:`DhanAdapter.fetch_security_list` wraps it for async adapter use and
    the core app's lazy Dhan security resolver calls it directly — so a future
    retry/timeout/URL fix lands on both paths instead of drifting. Feed the
    returned rows to ``dhan_mapping.build_security_resolver``.

    Args:
        mode: ``"compact"`` or ``"detailed"`` scrip-master variant.
        downloader: Injectable fetcher for tests; defaults to the HTTPS-pinned
            stdlib downloader.

    Returns:
        The CSV rows as dicts keyed by the header tags (``SEM_*`` for compact).

    Raises:
        BrokerError: If ``mode`` is not a known scrip-master variant.
    """
    url = M.SCRIP_MASTER_URLS.get(str(mode).lower())
    if url is None:
        raise BrokerError(f"Scrip master mode must be 'compact' or 'detailed', got {mode!r}")
    text = (downloader or _download_text)(url)
    import csv  # noqa: PLC0415
    import io  # noqa: PLC0415

    return [dict(row) for row in csv.DictReader(io.StringIO(text))]


class DhanAdapter(BrokerAdapter):
    """Native Dhan adapter.

    Args:
        client_factory: ``session -> dhanhq client`` override (tests inject a
            mock). When omitted, ``login`` builds a live client and stores it on
            ``session.extra['client']``.
        security_resolver: ``(symbol, exchange) -> security_id`` — Dhan trades by
            numeric security id, so the operator must supply a scrip-master
            resolver (see :meth:`fetch_security_list` +
            ``dhan_mapping.build_security_resolver``). Common indices are
            resolved from a built-in fast path.
        feed_factory: ``session -> async iterator of binary frames`` for the
            live tick stream (tests inject synthetic frames; live wiring uses
            the dhanhq market feed).
        order_feed_factory: ``session -> async iterator of JSON frames`` for the
            order-update stream. When omitted, a live socket to
            ``wss://api-order-update.dhan.co`` is opened (the documented
            transport behind the SDK's ``orderupdate.OrderUpdate``).
        depth_feed_factory: ``(session, level) -> async iterator of binary
            frames`` for the 20/200-level depth streams (live sockets:
            ``wss://depth-api-feed.dhan.co/twentydepth`` and
            ``wss://full-depth-api.dhan.co/twohundreddepth``, the transports
            behind the SDK's ``fulldepth.FullDepth``).
        login_factory: ``client_id -> DhanLogin-like`` override for the auth
            surface (token generation / renewal / static-IP management).
        local_state_provider: ``session -> LocalStateSnapshot`` supplying the
            flinttrade-side mirror that ``reconcile`` diffs broker state
            against. Defaults to EMPTY local state (every broker-side row then
            surfaces as ``exists_only_on_broker``) until the engine wave wires
            the journal-backed provider.
    """

    safety_snapshot_requires_serial_reads = True

    def __init__(
        self,
        *,
        client_factory: Callable[[Session], Any] | None = None,
        security_resolver: Callable[[str, str], str] | None = None,
        feed_factory: Callable[[Session], AsyncIterator[bytes]] | None = None,
        order_feed_factory: Callable[[Session], AsyncIterator[Any]] | None = None,
        depth_feed_factory: Callable[[Session, int], AsyncIterator[bytes]] | None = None,
        login_factory: Callable[[str], Any] | None = None,
        local_state_provider: Callable[[Session], LocalStateSnapshot] | None = None,
    ) -> None:
        self._client_factory = client_factory
        self._security_resolver = security_resolver
        self._feed_factory = feed_factory
        self._order_feed_factory = order_feed_factory
        self._depth_feed_factory = depth_feed_factory
        self._login_factory = login_factory
        self._local_state_provider = local_state_provider
        # security_id -> (symbol, exchange) for routing decoded ticks back to names.
        self._feed_map: dict[str, tuple[str, str]] = {}
        # security_id -> requested feed RequestCode (TICKER/QUOTE/FULL).
        self._feed_modes: dict[str, int] = {}
        self._option_chain_cache: dict[tuple[int, str, str, str], tuple[float, Any]] = {}
        self._option_chain_locks: dict[tuple[int, str, str, str], asyncio.Lock] = {}
        # dhanhq exposes one mutable synchronous client/HTTP transport per
        # session. Serialise every call at the adapter boundary so safety
        # snapshots cannot overlap account-page reads or broker writes.
        self._sdk_transport_lock = threading.Lock()

    # ---------- identity + capabilities ----------

    @property
    def broker_id(self) -> str:
        return "dhan"

    @property
    def capabilities(self) -> Capabilities:
        return DHAN_CAPABILITIES

    # ---------- helpers ----------

    def _client(self, session: Session) -> Any:
        if self._client_factory is not None:
            return self._client_factory(session)
        client = session.extra.get("client")
        if client is None:
            raise BrokerError("Dhan client not initialised — call login() first")
        return client

    def _http(self, session: Session) -> Any:
        """The SDK's ``DhanHTTP`` transport — used for v2.5 endpoints that the
        pinned SDK (2.2.0) does not wrap (conditional triggers, P&L exit,
        Exit All). Doc-grounded paths live in ``dhan_mapping``."""
        http = getattr(self._client(session), "dhan_http", None)
        if http is None:
            raise BrokerError("Dhan client exposes no DhanHTTP transport (dhan_http)")
        return http

    def _login_helper(self, client_id: str) -> Any:
        """A ``DhanLogin``-shaped auth helper for the token/IP surface."""
        if self._login_factory is not None:
            return self._login_factory(client_id)
        return _build_dhan_login(client_id)

    def _resolve_security(self, symbol: str, exchange: str) -> str:
        key = str(symbol).upper()
        if key in M.INDEX_SECURITY_IDS:
            return M.INDEX_SECURITY_IDS[key][0]
        if self._security_resolver is not None:
            return str(self._security_resolver(symbol, exchange))
        raise BrokerError(
            f"Cannot resolve Dhan security_id for {symbol}/{exchange} — configure a security resolver (scrip master)"
        )

    @staticmethod
    def _split_symbol(s: str) -> tuple[str, str]:
        """Split an ``"EXCHANGE:SYMBOL"`` quote key (defaults exchange to NSE)."""
        if ":" in s:
            exchange, name = s.split(":", 1)
            return exchange.strip().upper(), name.strip()
        return "NSE", s.strip()

    async def _call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        # dhanhq is synchronous — run it off the event loop.
        def locked_call() -> Any:
            with self._sdk_transport_lock:
                return fn(*args, **kwargs)

        return await run_blocking_sdk_call(locked_call)

    # ---------- auth lifecycle ----------

    @staticmethod
    def build_login_url(
        app_id: str,
        _redirect_uri: str,
        _state: str | None = None,
        *,
        account_id: str = "",
        api_secret: str = "",
    ) -> str:
        """Generate the DhanHQ consent URL for the operator's browser.

        Dhan's app-consent flow is not a normal ``client_id + redirect_uri``
        URL. The server first calls ``/app/generate-consent`` with the Dhan
        client id plus app credentials, then opens the returned
        ``consentAppId`` URL. The app's registered redirect URL controls where
        Dhan sends the final ``tokenId`` callback.
        """
        if not account_id:
            raise BrokerError("Dhan OAuth login requires the Dhan client ID as the account ID")
        if not app_id or not api_secret:
            raise BrokerError("Dhan OAuth login requires app_id and app_secret")
        import requests  # noqa: PLC0415

        resp = requests.post(
            "https://auth.dhan.co/app/generate-consent",
            params={"client_id": account_id},
            headers={"app_id": app_id, "app_secret": api_secret},
            timeout=20,
        )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise BrokerError("Dhan consent generation returned a non-JSON response") from exc
        if resp.status_code != 200 or payload.get("status") != "success" or not payload.get("consentAppId"):
            raise BrokerError(f"Dhan consent generation failed with status {resp.status_code}")
        return "https://auth.dhan.co/login/consentApp-login?" + urlencode(
            {"consentAppId": str(payload["consentAppId"])}
        )

    async def login(self, credentials: dict) -> Session:
        client_id = str(credentials.get("client_id") or credentials.get("dhan_client_id") or "")
        access_token = str(credentials.get("access_token") or "")
        pin = str(credentials.get("pin") or "")
        totp = str(credentials.get("totp") or "")
        token_id = str(credentials.get("token_id") or credentials.get("code") or "")
        app_id = str(credentials.get("app_id") or credentials.get("api_key") or "")
        app_secret = str(credentials.get("app_secret") or credentials.get("api_secret") or "")
        if not access_token and token_id:
            if not client_id:
                raise BrokerError("Dhan OAuth login requires client_id")
            if not (app_id and app_secret):
                raise BrokerError("Dhan OAuth login requires app_id and app_secret")
            resp = await self.consume_token_id(client_id, token_id, app_id, app_secret)
            access_token = str(resp.get("accessToken") or resp.get("access_token") or "")
            if not access_token:
                raise BrokerError("Dhan OAuth token consumption failed")
        if not access_token and pin and totp:
            # PIN + TOTP path: mint a fresh 24h token via the v2.5 token API
            # (generate_token needs no existing token), then log in with it. Lets
            # an operator connect without pasting a console-generated token —
            # requires TOTP enabled on the account.
            if not client_id:
                raise BrokerError("Dhan PIN+TOTP login requires client_id")
            resp = await self.generate_token(client_id, pin, totp)
            access_token = str(resp.get("accessToken") or resp.get("access_token") or "")
            if not access_token:
                raise BrokerError("Dhan PIN+TOTP token generation failed")
        if not access_token:
            raise BrokerError("Dhan login requires an access_token (or client_id + pin + totp)")
        client = None if self._client_factory is not None else _build_dhan_client(client_id, access_token)
        return Session(
            access_token=access_token,
            expires_at=datetime.now(tz=UTC).timestamp() + 24 * 3600,
            account_id=client_id,
            adapter_id="dhan",
            extra={"client": client, "client_id": client_id},
        )

    def replay_credentials(self, credentials: dict, session: Session) -> dict:
        """The replayable vault payload after a successful login (G7).

        A pasted TOTP and the OAuth ``tokenId``/``code`` are one-time artefacts
        — replaying them at the next boot is guaranteed to fail. Swap them for
        the minted 24h ``access_token`` (restart-within-validity reconnects
        cleanly); keep ``client_id`` and ``pin`` so a UI-assisted re-auth only
        needs a fresh TOTP.
        """
        replayable = {k: v for k, v in credentials.items() if k not in {"totp", "token_id", "code"}}
        replayable["access_token"] = session.access_token
        return replayable

    async def refresh(self, session: Session) -> Session:
        # Dhan access tokens are long-lived (manual 24h renewal); nothing to do
        # until expiry, at which point a fresh login() is required.
        return session

    async def logout(self, session: Session) -> None:
        session.extra.pop("client", None)
        return

    # ---------- trading: writes (router-only) ----------

    async def place_order(self, session: Session, order: Order, *, _router_token: object | None = None) -> str:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        security_id = self._resolve_security(order.symbol, order.exchange)
        tag = session.algo_id or None
        # Dispatch on order variety. Every variety travels this SAME gated method
        # (the router token is already required above and the variety + leg prices
        # are part of the SafetyContext-hashed order), so a bracket/cover/iceberg
        # order is gated identically to a regular one — no parallel order path.
        variety = str(getattr(order, "variety", "regular")).lower()
        client = self._client(session)
        if variety in ("regular", ""):
            resp = await self._call(client.place_order, **M.to_place_order_kwargs(order, security_id, tag=tag))
        elif variety == "amo":
            # After-market order: POST /orders directly via DhanHTTP with the
            # afterMarketOrder flag + amoTime pump window. We bypass the SDK's
            # place_order because dhanhq 2.2.0 drops amoTime from its payload
            # (so the pump window would never reach the broker) — see
            # to_amo_order_payload. Still the SAME gated method/variety dispatch.
            resp = await self._call(
                self._http(session).post, M.ORDERS_ENDPOINT, M.to_amo_order_payload(order, security_id, tag=tag)
            )
        elif variety in ("bracket", "cover"):
            resp = await self._call(client.place_super_order, **M.to_super_order_kwargs(order, security_id, tag=tag))
        elif variety == "iceberg":
            resp = await self._call(client.place_slice_order, **M.to_slice_order_kwargs(order, security_id, tag=tag))
        elif variety == "gtt":
            resp = await self._call(client.place_forever, **M.to_forever_kwargs(order, security_id, tag=tag))
        else:
            raise BrokerError(f"Dhan does not support order variety {variety!r}")
        return M.extract_order_id(resp)

    async def modify_order(
        self, session: Session, order_id: str, changes: dict, *, _router_token: object | None = None
    ) -> None:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        kwargs = M.to_modify_order_kwargs(order_id, changes)
        resp = await self._call(self._client(session).modify_order, **kwargs)
        M.unwrap(resp)

    async def cancel_order(self, session: Session, order_id: str, *, _router_token: object | None = None) -> None:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        resp = await self._call(self._client(session).cancel_order, str(order_id))
        M.unwrap(resp)

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
        """Expand Dhan's non-bulk cancellation surface into exact writes."""
        requested = frozenset(policy.verbs)
        active_orders = (
            await self._active_order_targets(session)
            if "cancel_all_orders" in requested
            else {}
        )
        active_positions = (
            await self._active_positions(session)
            if "exit_all_positions" in requested
            else {}
        )
        pending: set[str] = set()
        if active_orders:
            pending.add("cancel_all_orders")
        if active_positions:
            pending.add("exit_all_positions")
        if not pending:
            return EmergencyReductionPlan(writes=(), pending_verbs=frozenset())
        if unidentified_exit_inflight:
            return EmergencyReductionPlan(writes=(), pending_verbs=frozenset(pending))

        if "cancel_all_orders" in pending:
            writes: list[EmergencyBrokerWrite] = []
            for (family, order_id), row in sorted(active_orders.items()):
                tags = {
                    str(row.get(key) or "")
                    for key in ("tag", "correlation_id", "correlationid")
                }
                if (
                    order_id in protected_order_ids
                    or order_id in protected_exit_order_ids
                    or tags.intersection(protected_exit_tags)
                ):
                    continue
                if family == "regular":
                    verb = "cancel_order"
                    payload: dict[str, object] = {"_op": verb, "order_id": order_id}
                elif family == "forever":
                    verb = "cancel_forever"
                    payload = {"_op": verb, "order_id": order_id}
                elif family == "super":
                    verb = "cancel_super_order"
                    payload = {"_op": verb, "order_id": order_id, "leg": "ENTRY_LEG"}
                elif family == "conditional":
                    verb = "cancel_conditional_trigger"
                    payload = {"_op": verb, "alert_id": order_id}
                else:  # pragma: no cover - _active_order_targets is a closed family set
                    continue
                writes.append(
                    EmergencyBrokerWrite(
                        parent_verb="cancel_all_orders",
                        verb=verb,
                        payload=payload,
                    )
                )
                if len(writes) >= _EMERGENCY_BATCH_LIMIT:
                    break
            return EmergencyReductionPlan(
                writes=tuple(writes),
                pending_verbs=frozenset(pending),
            )

        return EmergencyReductionPlan(
            writes=(
                EmergencyBrokerWrite(
                    parent_verb="exit_all_positions",
                    verb="exit_all_positions",
                    payload={"_op": "exit_all_positions"},
                ),
            ),
            pending_verbs=frozenset(pending),
        )

    async def cancel_all_orders(
        self,
        session: Session,
        *,
        _router_token: object | None = None,
    ) -> dict[str, Any]:
        """Refuse synthetic bulk cancellation at the adapter boundary.

        Dhan has no native bulk-cancel operation. Expanding this verb here would
        let one consumed SafetyContext authorise several concrete broker calls.
        Emergency callers use :meth:`plan_emergency_reduction`; ordinary callers
        must enumerate and gate each cancellation explicitly.
        """
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        del session
        raise UnsupportedCapabilityError(
            "Dhan has no native bulk-cancel endpoint; each concrete order must be gated separately",
            broker_id="dhan",
        )

    async def _active_order_targets(self, session: Session) -> dict[tuple[str, str], dict]:
        """Return active targets across Dhan's four independently managed books."""
        common_terminal = {"CANCELLED", "REJECTED", "EXPIRED", "CLOSED", "COMPLETED"}
        regular_terminal = common_terminal | {"TRADED"}
        trigger_terminal = common_terminal | {"DISABLED", "DELETED"}

        # The pinned SDK reuses one authenticated client/HTTP transport; keep
        # reads sequential rather than concurrently entering that shared object.
        regular = await self.order_book(session)
        forever = await self.forever_orders(session)
        super_orders = await self.super_orders(session)
        conditional = await self.conditional_triggers(session)
        targets: dict[tuple[str, str], dict] = {}

        def add(family: str, row: dict, id_key: str, terminal: set[str]) -> None:
            status = str(row.get("status") or "").strip().upper()
            if status in terminal:
                return
            order_id = str(row.get(id_key) or "")
            if (
                not order_id
                or order_id != order_id.strip()
                or not order_id.isprintable()
                or any(character.isspace() for character in order_id)
            ):
                raise M.DhanMappingError(f"Active Dhan {family} order lacks a canonical Dhan order id")
            targets[(family, order_id)] = row

        for row in regular:
            if isinstance(row, dict):
                add("regular", row, "orderid", regular_terminal)
        for row in forever:
            if isinstance(row, dict):
                add("forever", row, "orderid", regular_terminal)
        for row in super_orders:
            if not isinstance(row, dict):
                continue
            legs = tuple(leg for leg in row.get("legs", ()) if isinstance(leg, dict))
            trusted_legs = row.get("leg_details_valid") is True
            active_leg = not trusted_legs or any(
                str(leg.get("orderStatus") or leg.get("status") or "").strip().upper() not in regular_terminal
                for leg in legs
            )
            terminal = common_terminal | ({"TRADED"} if not active_leg else set())
            add("super", row, "orderid", terminal)
        for row in conditional:
            if isinstance(row, dict):
                status = str(row.get("status") or "").strip().upper()
                if status == "TRIGGERED" and not self._trigger_still_settling(row):
                    continue
                add("conditional", row, "alert_id", trigger_terminal)
        return targets

    @staticmethod
    def _trigger_still_settling(row: dict) -> bool:
        """Keep recent/undated fired alerts unresolved until generated orders settle."""
        raw_triggered_at = str(row.get("triggered_at") or "").strip()
        if not raw_triggered_at:
            return True
        try:
            triggered_at = datetime.fromisoformat(raw_triggered_at)
        except ValueError:
            return True
        if triggered_at.tzinfo is None:
            triggered_at = triggered_at.replace(tzinfo=UTC)
        age_seconds = (datetime.now(UTC) - triggered_at.astimezone(UTC)).total_seconds()
        return age_seconds <= _EMERGENCY_TRIGGER_SETTLEMENT_SECONDS

    async def _settled_active_order_targets(
        self,
        session: Session,
    ) -> dict[tuple[str, str], dict]:
        """Poll the full horizon and trust only a terminal quiet window."""
        consecutive_empty = 0
        last_nonempty: dict[tuple[str, str], dict] = {}
        for attempt in range(_EMERGENCY_READBACK_ATTEMPTS):
            current = await self._active_order_targets(session)
            if current:
                last_nonempty = current
                consecutive_empty = 0
            else:
                consecutive_empty += 1
            if attempt < _EMERGENCY_READBACK_ATTEMPTS - 1:
                await asyncio.sleep(_EMERGENCY_READBACK_DELAY_SECONDS)
        if consecutive_empty >= _EMERGENCY_QUIET_READS:
            return {}
        return last_nonempty

    # ---------- trading: forever (GTT) management (router-only writes) ----------

    async def modify_forever(
        self, session: Session, order_id: str, changes: dict, *, _router_token: object | None = None
    ) -> None:
        """Modify a resting forever (GTT) order (``PUT /forever/orders/{id}``)."""
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        kwargs = M.to_modify_forever_kwargs(order_id, changes)
        resp = await self._call(self._client(session).modify_forever, **kwargs)
        M.unwrap(resp)

    async def cancel_forever(self, session: Session, order_id: str, *, _router_token: object | None = None) -> None:
        """Cancel a resting forever (GTT) order (``DELETE /forever/orders/{id}``)."""
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        resp = await self._call(self._client(session).cancel_forever, str(order_id))
        M.unwrap(resp)

    async def forever_orders(self, session: Session) -> list[dict]:
        """List all resting forever (GTT) orders (``GET /forever/orders``) — a read."""
        resp = await self._call(self._client(session).get_forever)
        rows = M.unwrap(resp) or []
        return [M.from_dhan_forever_order(r) for r in rows if isinstance(r, dict)]

    # ---------- trading: super-order management (router-only writes) ----------

    async def modify_super_order(
        self, session: Session, order_id: str, changes: dict, *, _router_token: object | None = None
    ) -> None:
        """Modify one leg of a pending super order (``PUT /super/orders/{id}``).

        ``changes['leg_name']`` selects ENTRY_LEG / TARGET_LEG / STOP_LOSS_LEG;
        the mapping layer builds the leg-appropriate payload.
        """
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        kwargs = M.to_modify_super_order_kwargs(order_id, changes)
        resp = await self._call(self._client(session).modify_super_order, **kwargs)
        M.unwrap(resp)

    async def cancel_super_order(
        self, session: Session, order_id: str, leg: str = "ENTRY_LEG", *, _router_token: object | None = None
    ) -> None:
        """Cancel a super order or one leg (``DELETE /super/orders/{id}/{leg}``).

        Cancelling ENTRY_LEG cancels every leg; a target/stop-loss leg cancelled
        individually cannot be re-added later (super-order.md).
        """
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        leg_name = str(leg).upper()
        if leg_name not in M.SUPER_ORDER_LEGS:
            raise BrokerError(f"Super order leg must be one of {M.SUPER_ORDER_LEGS}, got {leg!r}")
        resp = await self._call(self._client(session).cancel_super_order, str(order_id), leg_name)
        M.unwrap(resp)

    async def super_orders(self, session: Session) -> list[dict]:
        """List all super orders with nested leg details (``GET /super/orders``) — a read."""
        resp = await self._call(self._client(session).get_super_order_list)
        rows = M.unwrap(resp) or []
        return [M.from_dhan_super_order(r) for r in rows if isinstance(r, dict)]

    # ---------- trading: conditional triggers (v2.5; router-only writes) ----------

    async def place_conditional_trigger(
        self, session: Session, condition: dict, orders: list[Order], *, _router_token: object | None = None
    ) -> str:
        """Place a conditional trigger (``POST /alerts/orders``, v2.5) and return its alert id.

        The trigger fires the supplied order legs when the price/indicator
        condition is met, so it is trade-affecting and traverses the same
        router gate as a direct order. The pinned SDK (2.2.0) has no wrapper,
        so the documented endpoint is called via the SDK's ``DhanHTTP``.
        """
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        legs = [M.to_conditional_order_leg(o, self._resolve_security(o.symbol, o.exchange)) for o in orders]
        payload = M.to_conditional_trigger_payload(condition, legs)
        resp = await self._call(self._http(session).post, M.CONDITIONAL_TRIGGER_ENDPOINT, payload)
        return M.extract_alert_id(resp)

    async def modify_conditional_trigger(
        self,
        session: Session,
        alert_id: str,
        condition: dict,
        orders: list[Order],
        *,
        _router_token: object | None = None,
    ) -> None:
        """Modify a conditional trigger (``PUT /alerts/orders/{alertId}``, v2.5)."""
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        legs = [M.to_conditional_order_leg(o, self._resolve_security(o.symbol, o.exchange)) for o in orders]
        payload = M.to_conditional_trigger_payload(condition, legs)
        payload["alertId"] = str(alert_id)
        resp = await self._call(self._http(session).put, f"{M.CONDITIONAL_TRIGGER_ENDPOINT}/{alert_id}", payload)
        M.unwrap(resp)

    async def cancel_conditional_trigger(
        self, session: Session, alert_id: str, *, _router_token: object | None = None
    ) -> None:
        """Delete a conditional trigger (``DELETE /alerts/orders/{alertId}``, v2.5)."""
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        resp = await self._call(self._http(session).delete, f"{M.CONDITIONAL_TRIGGER_ENDPOINT}/{alert_id}")
        M.unwrap(resp)

    async def conditional_triggers(self, session: Session) -> list[dict]:
        """List all conditional triggers (``GET /alerts/orders``, v2.5) — a read."""
        resp = await self._call(self._http(session).get, M.CONDITIONAL_TRIGGER_ENDPOINT)
        rows = M.unwrap(resp) or []
        return [M.from_dhan_conditional_trigger(r) for r in rows if isinstance(r, dict)]

    async def get_conditional_trigger(self, session: Session, alert_id: str) -> dict:
        """Fetch one conditional trigger by alert id (``GET /alerts/orders/{alertId}``) — a read."""
        resp = await self._call(self._http(session).get, f"{M.CONDITIONAL_TRIGGER_ENDPOINT}/{alert_id}")
        data = M.unwrap(resp)
        return M.from_dhan_conditional_trigger(data if isinstance(data, dict) else {})

    # ---------- trading: portfolio writes (router-only) ----------

    async def convert_position(self, session: Session, req: dict, *, _router_token: object | None = None) -> None:
        """Convert an open position intraday↔delivery (``POST /positions/convert``).

        ``req`` carries symbol/exchange (or an explicit ``security_id``),
        ``from_product`` / ``to_product``, ``position_type`` and ``quantity``.
        Changing a position's product changes margin treatment, so this is a
        gated write like any order mutation.
        """
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        security_id = str(
            req.get("security_id")
            or self._resolve_security(str(req.get("symbol", "")), str(req.get("exchange", "NSE")))
        )
        kwargs = M.to_convert_position_kwargs(req, security_id)
        resp = await self._call(self._client(session).convert_position, **kwargs)
        M.unwrap(resp)

    async def exit_all_positions(self, session: Session, *, _router_token: object | None = None) -> dict:
        """Exit ALL active positions and cancel ALL open orders (``DELETE /positions``, v2.5).

        SAFETY: this is the broker-side flatten-everything control. It places
        live exit orders for every open position, so it is router-gated like
        any other trade-affecting call, and any caller/route wiring it MUST
        additionally gate it behind an explicit, authenticated operator action
        (Live-mode + operator confirmation) and audit it.
        """
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        before_positions = await self._active_positions(session)
        before_orders = await self._active_order_targets(session)
        resp = await self._call(self._http(session).delete, M.EXIT_ALL_ENDPOINT)
        M.unwrap(resp)
        after_positions, after_orders = await self._settled_emergency_state(session)
        position_targets = set(before_positions) | set(after_positions)
        order_targets = set(before_orders) | set(after_orders)
        unresolved_positions = sorted(after_positions)
        unresolved_orders = sorted(after_orders)
        total = len(position_targets) + len(order_targets)
        return {
            "errors": (
                [{"position": key} for key in unresolved_positions]
                + [{"family": family, "id": order_id} for family, order_id in unresolved_orders]
            ),
            "total": total,
            "success": total - len(unresolved_positions) - len(unresolved_orders),
        }

    async def _active_positions(self, session: Session) -> dict[str, dict]:
        """Return non-zero positions keyed without including account-sensitive data."""
        targets: dict[str, dict] = {}
        for position in await self.positions(session):
            if not isinstance(position, dict):
                continue
            quantity = position.get("quantity", "")
            try:
                is_open = Decimal(str(quantity)) != 0
            except (InvalidOperation, ValueError, TypeError):
                is_open = True
            if not is_open:
                continue
            key = ":".join(
                (
                    str(position.get("exchange") or "UNKNOWN"),
                    str(position.get("symbol") or "UNKNOWN"),
                    str(position.get("product") or "UNKNOWN"),
                )
            )
            targets[key] = position
        return targets

    async def _settled_active_positions(self, session: Session) -> dict[str, dict]:
        """Poll the full horizon and trust only the terminal quiet window."""
        consecutive_empty = 0
        last_nonempty: dict[str, dict] = {}
        for attempt in range(_EMERGENCY_READBACK_ATTEMPTS):
            current = await self._active_positions(session)
            if current:
                last_nonempty = current
                consecutive_empty = 0
            else:
                consecutive_empty += 1
            if attempt < _EMERGENCY_READBACK_ATTEMPTS - 1:
                await asyncio.sleep(_EMERGENCY_READBACK_DELAY_SECONDS)
        if consecutive_empty >= _EMERGENCY_QUIET_READS:
            return {}
        return last_nonempty

    async def _settled_emergency_state(
        self,
        session: Session,
    ) -> tuple[dict[str, dict], dict[tuple[str, str], dict]]:
        """Read positions and orders in five shared cycles and require joint quiet."""
        consecutive_quiet = 0
        observed_positions: dict[str, dict] = {}
        observed_orders: dict[tuple[str, str], dict] = {}
        for attempt in range(_EMERGENCY_READBACK_ATTEMPTS):
            # Read orders first so a fill between the two reads is visible in
            # the paired position snapshot rather than falling between horizons.
            current_orders = await self._active_order_targets(session)
            current_positions = await self._active_positions(session)
            observed_orders.update(current_orders)
            observed_positions.update(current_positions)
            if current_orders or current_positions:
                consecutive_quiet = 0
            else:
                consecutive_quiet += 1
            if attempt < _EMERGENCY_READBACK_ATTEMPTS - 1:
                await asyncio.sleep(_EMERGENCY_READBACK_DELAY_SECONDS)
        if consecutive_quiet >= _EMERGENCY_QUIET_READS:
            return {}, {}
        return observed_positions, observed_orders

    # ---------- trading: reads ----------

    @staticmethod
    def _safety_status(value: Any, *, family: str) -> str:
        status = str(value or "").strip().upper()
        if not status:
            raise M.DhanMappingError(f"Active Dhan {family} row lacks an order status")
        return status

    @staticmethod
    def _safety_id(value: Any, *, field: str) -> str:
        identifier = str(value or "")
        if (
            not identifier
            or identifier != identifier.strip()
            or not identifier.isprintable()
            or any(character.isspace() for character in identifier)
        ):
            raise M.DhanMappingError(f"Active Dhan safety row lacks a canonical {field}")
        return identifier

    @staticmethod
    def _safety_quantity(value: Any, *, field: str, allow_zero: bool = False) -> int:
        try:
            quantity = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise M.DhanMappingError(f"Active Dhan {field} is invalid") from exc
        if not quantity.is_finite() or quantity != quantity.to_integral_value():
            raise M.DhanMappingError(f"Active Dhan {field} is invalid")
        number = int(quantity)
        if number < 0 or (number == 0 and not allow_zero):
            raise M.DhanMappingError(f"Active Dhan {field} is invalid")
        return number

    def _safety_option_identity(
        self,
        *,
        symbol: str,
        exchange: str,
        instrument_id: str,
        option_type: Any,
        expiry: Any,
        strike_price: Any,
        underlying: Any,
    ) -> tuple[str, str, float | str, str]:
        def normalise_expiry(value: Any) -> str:
            candidate = str(value or "").strip()[:10]
            try:
                return datetime.fromisoformat(candidate).date().isoformat()
            except ValueError:
                return ""

        raw_option_type = str(option_type or "").strip().upper()
        canonical_option_type = {
            "CALL": "CE",
            "CE": "CE",
            "PUT": "PE",
            "PE": "PE",
        }.get(raw_option_type, "")
        if raw_option_type and not canonical_option_type:
            raise M.DhanMappingError("Active Dhan option row has an invalid option type")
        if not canonical_option_type:
            return "", "", "", ""

        resolved_expiry = normalise_expiry(expiry)
        resolved_underlying = str(underlying or "").strip()
        try:
            resolved_strike = float(strike_price)
        except (TypeError, ValueError):
            resolved_strike = 0.0
        if not instrument_id or self._security_resolver is None:
            raise M.DhanMappingError("Active Dhan option row lacks canonical contract identity")
        identity = M.reverse_security_id(self._security_resolver, instrument_id, exchange)
        if self._resolve_security(symbol, exchange).strip() != instrument_id:
            raise M.DhanMappingError("Dhan security-id lookup conflicts with the active order symbol")
        reverse_option_type = str(identity.get("option_type") or "").strip().upper()
        reverse_expiry = normalise_expiry(identity.get("expiry"))
        reverse_underlying = str(identity.get("underlying") or "").strip()
        try:
            reverse_strike = float(identity.get("strike_price"))
        except (TypeError, ValueError):
            reverse_strike = 0.0
        if (
            reverse_option_type != canonical_option_type
            or not reverse_expiry
            or not reverse_underlying
            or not math.isfinite(reverse_strike)
            or reverse_strike <= 0
        ):
            raise M.DhanMappingError("Dhan security-id lookup lacks canonical contract identity")
        if resolved_expiry and resolved_expiry != reverse_expiry:
            raise M.DhanMappingError("Dhan security-id lookup conflicts with the active expiry")
        if resolved_underlying and resolved_underlying.upper() != reverse_underlying.upper():
            raise M.DhanMappingError("Dhan security-id lookup conflicts with the active underlying")
        if (
            math.isfinite(resolved_strike)
            and resolved_strike > 0
            and not math.isclose(resolved_strike, reverse_strike, rel_tol=0.0, abs_tol=1e-6)
        ):
            raise M.DhanMappingError("Dhan security-id lookup conflicts with the active strike")
        return canonical_option_type, reverse_expiry, reverse_strike, reverse_underlying

    def _safety_row(
        self,
        *,
        family: str,
        order_id: Any,
        raw_broker_order_id: Any,
        status: Any,
        symbol: Any,
        exchange: Any,
        action: Any,
        product: Any,
        quantity: Any,
        filled_quantity: Any = None,
        pricetype: Any = "MARKET",
        price: Any = 0,
        trigger_price: Any = 0,
        instrument_id: Any = "",
        option_type: Any = "",
        expiry: Any = "",
        strike_price: Any = "",
        underlying: Any = "",
        leg_name: Any = "",
        exchange_order_id: Any = "",
        parent_order_id: Any = "",
        margin_unfunded: bool = False,
    ) -> dict[str, Any]:
        canonical_order_id = self._safety_id(order_id, field="safety order id")
        canonical_raw_id = self._safety_id(raw_broker_order_id, field="raw broker order id")
        canonical_status = self._safety_status(status, family=family)
        canonical_symbol = str(symbol or "").strip()
        canonical_exchange = str(exchange or "").strip().upper()
        canonical_action = str(action or "").strip().upper()
        canonical_product = str(product or "").strip().upper()
        if not canonical_symbol:
            raise M.DhanMappingError(f"Active Dhan {family} row lacks a canonical symbol")
        if canonical_exchange not in M.EXCHANGE_SEGMENT_MAP:
            raise M.DhanMappingError(f"Active Dhan {family} row has an invalid exchange")
        if canonical_action not in {"BUY", "SELL"}:
            raise M.DhanMappingError(f"Active Dhan {family} row has an invalid action")
        if canonical_product not in M.PRODUCT_MAP:
            raise M.DhanMappingError(f"Active Dhan {family} row has an invalid product")
        canonical_quantity = self._safety_quantity(quantity, field=f"{family} quantity")
        raw_filled = _optional_safety_text(filled_quantity)
        terminal_fill_unknown = not raw_filled and (
            canonical_status in _SAFETY_TERMINAL_ORDER_STATUSES
            or (
                family == "conditional"
                and canonical_status in _SAFETY_CONDITIONAL_TERMINAL_STATUSES
            )
        )
        canonical_filled = (
            None
            if terminal_fill_unknown
            else self._safety_quantity(
                filled_quantity,
                field=f"{family} filled quantity",
                allow_zero=True,
            )
        )
        if canonical_filled is not None and canonical_filled > canonical_quantity:
            raise M.DhanMappingError(f"Active Dhan {family} row has inconsistent filled quantity")
        canonical_instrument_id = str(instrument_id or "").strip()
        option_identity = self._safety_option_identity(
            symbol=canonical_symbol,
            exchange=canonical_exchange,
            instrument_id=canonical_instrument_id,
            option_type=option_type,
            expiry=expiry,
            strike_price=strike_price,
            underlying=underlying,
        )
        row = {
            "orderid": canonical_order_id,
            "safety_order_id": f"{family}:{canonical_order_id}",
            "broker_order_id": canonical_order_id,
            "raw_broker_order_id": canonical_raw_id,
            "order_family": family,
            "status": canonical_status,
            "symbol": canonical_symbol,
            "instrument_id": canonical_instrument_id,
            "exchange": canonical_exchange,
            "action": canonical_action,
            "product": canonical_product,
            "quantity": str(canonical_quantity),
            "filled_quantity": "" if canonical_filled is None else str(canonical_filled),
            "pricetype": M.DHAN_TO_ORDER_TYPE.get(
                str(pricetype or "MARKET").strip().upper(),
                str(pricetype or "MARKET").strip().upper(),
            ),
            "price": str(price or 0),
            "trigger_price": str(trigger_price or 0),
            "option_type": option_identity[0],
            "expiry": option_identity[1],
            "strike_price": option_identity[2],
            "underlying": option_identity[3],
            "leg_name": str(leg_name or "").strip().upper(),
            "exchange_order_id": str(exchange_order_id or "").strip(),
            "parent_order_id": str(parent_order_id or "").strip(),
        }
        if margin_unfunded:
            row["margin_unfunded"] = True
        return row

    def _regular_safety_row(
        self,
        row: dict[str, Any],
        *,
        family: str = "regular",
        margin_unfunded: bool = False,
    ) -> dict[str, Any] | None:
        status = self._safety_status(row.get("status"), family=family)
        order_id = self._safety_id(row.get("orderid"), field="broker order id")
        if status in _SAFETY_TERMINAL_ORDER_STATUSES:
            # Terminal rows remain in the authoritative horizon so a locally
            # reserved fast fill can settle after positions propagate. Dhan
            # may omit descriptive fields on old terminal records; retain the
            # raw values and fail closed if they cannot prove a matched intent.
            terminal = {
                "orderid": order_id,
                "safety_order_id": f"{family}:{order_id}",
                "broker_order_id": order_id,
                "raw_broker_order_id": order_id,
                "order_family": family,
                "status": status,
                "symbol": str(row.get("symbol") or "").strip(),
                "instrument_id": str(row.get("instrument_id") or "").strip(),
                "exchange": str(row.get("exchange") or "").strip().upper(),
                "action": str(row.get("action") or "").strip().upper(),
                "product": str(row.get("product") or "").strip().upper(),
                "quantity": str(row.get("quantity") or ""),
                "filled_quantity": _optional_safety_text(row.get("filled_quantity")),
                "pricetype": str(row.get("pricetype") or "").strip().upper(),
                "price": str(row.get("price") or 0),
                "trigger_price": str(row.get("trigger_price") or 0),
            }
            if margin_unfunded:
                terminal["margin_unfunded"] = True
            return terminal
        return self._safety_row(
            family=family,
            order_id=order_id,
            raw_broker_order_id=order_id,
            status=status,
            symbol=row.get("symbol"),
            exchange=row.get("exchange"),
            action=row.get("action"),
            product=row.get("product"),
            quantity=row.get("quantity"),
            filled_quantity=row.get("filled_quantity"),
            pricetype=row.get("pricetype"),
            price=row.get("price"),
            trigger_price=row.get("trigger_price"),
            instrument_id=row.get("instrument_id"),
            option_type=row.get("option_type"),
            expiry=row.get("expiry"),
            strike_price=row.get("strike_price"),
            underlying=row.get("underlying"),
            leg_name=row.get("leg_name"),
            exchange_order_id=row.get("exchange_order_id"),
            margin_unfunded=margin_unfunded,
        )

    def _forever_safety_rows(self, row: dict[str, Any]) -> list[dict[str, Any]]:
        status = self._safety_status(row.get("status"), family="forever")
        order_id = self._safety_id(row.get("orderid"), field="forever order id")
        if status in _SAFETY_TERMINAL_ORDER_STATUSES:
            return [{
                "orderid": order_id,
                "safety_order_id": f"forever:{order_id}",
                "broker_order_id": order_id,
                "raw_broker_order_id": order_id,
                "order_family": "forever",
                "status": status,
                "symbol": str(row.get("symbol") or "").strip(),
                "instrument_id": str(row.get("instrument_id") or "").strip(),
                "exchange": str(row.get("exchange") or "").strip().upper(),
                "action": str(row.get("action") or "").strip().upper(),
                "product": str(row.get("product") or "").strip().upper(),
                "quantity": str(row.get("quantity") or ""),
                "filled_quantity": _optional_safety_text(row.get("filled_quantity")),
                "pricetype": str(row.get("pricetype") or "").strip().upper(),
                "price": str(row.get("price") or 0),
                "trigger_price": str(row.get("trigger_price") or 0),
                "parent_order_id": order_id,
                "margin_unfunded": True,
            }]
        order_flag = str(row.get("order_flag") or "").strip().upper()
        if order_flag not in M.FOREVER_ORDER_FLAGS:
            raise M.DhanMappingError("Active Dhan forever row has an invalid order flag")
        common = {
            "family": "forever",
            "raw_broker_order_id": order_id,
            "status": status,
            "symbol": row.get("symbol"),
            "exchange": row.get("exchange"),
            "action": row.get("action"),
            "product": row.get("product"),
            "pricetype": row.get("pricetype"),
            "instrument_id": row.get("instrument_id"),
            "option_type": row.get("option_type"),
            "expiry": row.get("expiry"),
            "strike_price": row.get("strike_price"),
            "underlying": row.get("underlying"),
            "parent_order_id": order_id,
            "margin_unfunded": True,
        }
        rows = [
            self._safety_row(
                **common,
                order_id=order_id,
                quantity=row.get("quantity"),
                filled_quantity=row.get("filled_quantity"),
                price=row.get("price"),
                trigger_price=row.get("trigger_price"),
                leg_name="TARGET_LEG",
                exchange_order_id=row.get("exchange_order_id"),
            )
        ]
        secondary_values = (row.get("quantity1"), row.get("price1"), row.get("trigger_price1"))
        if order_flag == "SINGLE":
            if any(str(value or "").strip() not in {"", "0", "0.0"} for value in secondary_values):
                raise M.DhanMappingError("Active Dhan SINGLE forever row contains an unclassified second leg")
            return rows
        if row.get("oco_leg_complete") is not True:
            raise M.DhanMappingError("Active Dhan OCO forever row has incomplete second-leg data")
        rows.append(
            self._safety_row(
                **common,
                order_id=f"{order_id}:STOP_LOSS_LEG",
                quantity=row.get("quantity1"),
                filled_quantity=0,
                price=row.get("price1"),
                trigger_price=row.get("trigger_price1"),
                leg_name="STOP_LOSS_LEG",
            )
        )
        return rows

    def _super_safety_rows(self, row: dict[str, Any]) -> list[dict[str, Any]]:
        status = self._safety_status(row.get("status"), family="super")
        parent_order_id = self._safety_id(row.get("orderid"), field="super order id")
        legs = row.get("legs")
        if row.get("leg_details_valid") is not True or not isinstance(legs, list):
            if status in _SAFETY_TERMINAL_ORDER_STATUSES:
                return [{
                    "orderid": parent_order_id,
                    "safety_order_id": f"super:{parent_order_id}",
                    "broker_order_id": parent_order_id,
                    "raw_broker_order_id": parent_order_id,
                    "order_family": "super",
                    "status": status,
                    "symbol": str(row.get("symbol") or "").strip(),
                    "instrument_id": str(row.get("instrument_id") or "").strip(),
                    "exchange": str(row.get("exchange") or "").strip().upper(),
                    "action": str(row.get("action") or "").strip().upper(),
                    "product": str(row.get("product") or "").strip().upper(),
                    "quantity": str(row.get("quantity") or ""),
                    "filled_quantity": _optional_safety_text(row.get("filled_quantity")),
                    "pricetype": str(row.get("pricetype") or "").strip().upper(),
                    "price": str(row.get("price") or 0),
                    "trigger_price": str(row.get("trigger_price") or 0),
                    "leg_name": "ENTRY_LEG",
                    "parent_order_id": parent_order_id,
                    "margin_unfunded": True,
                }]
            raise M.DhanMappingError("Active Dhan super row has incomplete leg details")
        parent_action = str(row.get("action") or "").strip().upper()
        if parent_action not in {"BUY", "SELL"}:
            raise M.DhanMappingError("Active Dhan super row has an invalid action")
        rows: list[dict[str, Any]] = []
        common = {
            "family": "super",
            "symbol": row.get("symbol"),
            "exchange": row.get("exchange"),
            "product": row.get("product"),
            "instrument_id": row.get("instrument_id"),
            "option_type": row.get("option_type"),
            "expiry": row.get("expiry"),
            "strike_price": row.get("strike_price"),
            "underlying": row.get("underlying"),
            "parent_order_id": parent_order_id,
            "margin_unfunded": True,
        }
        rows.append(
            self._safety_row(
                **common,
                order_id=parent_order_id,
                raw_broker_order_id=parent_order_id,
                status=status,
                action=parent_action,
                quantity=row.get("quantity"),
                filled_quantity=row.get("filled_quantity"),
                pricetype=row.get("pricetype"),
                price=row.get("price"),
                leg_name="ENTRY_LEG",
                exchange_order_id=row.get("exchange_order_id"),
            )
        )
        child_action = "SELL" if parent_action == "BUY" else "BUY"
        for leg in legs:
            leg_name = str(leg.get("legName") or "").strip().upper()
            leg_status = self._safety_status(leg.get("orderStatus"), family="super leg")
            if leg_name not in {"TARGET_LEG", "STOP_LOSS_LEG"}:
                raise M.DhanMappingError("Active Dhan super row has an invalid leg name")
            explicit_action = str(leg.get("transactionType") or "").strip().upper()
            if explicit_action and explicit_action != child_action:
                raise M.DhanMappingError("Active Dhan super leg conflicts with the parent action")
            raw_child_id = str(leg.get("orderId") or "").strip()
            child_order_id = raw_child_id or f"{parent_order_id}:{leg_name}"
            raw_broker_order_id = raw_child_id or parent_order_id
            rows.append(
                self._safety_row(
                    **common,
                    order_id=child_order_id,
                    raw_broker_order_id=raw_broker_order_id,
                    status=leg_status,
                    action=child_action,
                    quantity=leg.get("quantity"),
                    filled_quantity=leg.get("filledQty", leg.get("tradedQty")),
                    pricetype=leg.get("orderType", row.get("pricetype")),
                    price=leg.get("price", 0),
                    trigger_price=leg.get("triggerPrice", 0),
                    leg_name=leg_name,
                    exchange_order_id=leg.get("exchangeOrderId"),
                )
            )
        return rows

    def _conditional_safety_rows(self, row: dict[str, Any]) -> list[dict[str, Any]]:
        status = self._safety_status(row.get("status"), family="conditional")
        alert_id = self._safety_id(row.get("alert_id"), field="conditional alert id")
        if row.get("orders_valid") is not True:
            if status in _SAFETY_CONDITIONAL_TERMINAL_STATUSES:
                return [{
                    "orderid": alert_id,
                    "safety_order_id": f"conditional:{alert_id}",
                    "broker_order_id": alert_id,
                    "raw_broker_order_id": alert_id,
                    "order_family": "conditional",
                    "status": status,
                    "symbol": "",
                    "exchange": "",
                    "action": "",
                    "product": "",
                    "quantity": "",
                    "filled_quantity": "",
                    "parent_order_id": alert_id,
                    "margin_unfunded": True,
                }]
            raise M.DhanMappingError("Active Dhan conditional trigger has malformed order legs")
        order_legs = row.get("orders")
        if not isinstance(order_legs, list) or not order_legs:
            raise M.DhanMappingError("Active Dhan conditional trigger has no order legs")
        rows: list[dict[str, Any]] = []
        for index, leg in enumerate(order_legs):
            security_id = self._safety_id(leg.get("securityId"), field="conditional security id")
            exchange_segment = str(leg.get("exchangeSegment") or "").strip().upper()
            if self._security_resolver is None:
                raise M.DhanMappingError("Dhan conditional safety mapping needs a security resolver")
            identity = M.reverse_security_id(self._security_resolver, security_id, exchange_segment)
            product_type = str(leg.get("productType") or "").strip().upper()
            product = M.DHAN_TO_PRODUCT.get(product_type, product_type)
            order_type = str(leg.get("orderType") or "").strip().upper()
            order_id = f"{alert_id}:{index}"
            rows.append(
                self._safety_row(
                    family="conditional",
                    order_id=order_id,
                    raw_broker_order_id=alert_id,
                    status=status,
                    symbol=identity.get("symbol"),
                    exchange=identity.get("exchange"),
                    action=leg.get("transactionType"),
                    product=product,
                    quantity=leg.get("quantity"),
                    filled_quantity=(
                        None
                        if status in _SAFETY_CONDITIONAL_TERMINAL_STATUSES
                        else 0
                    ),
                    pricetype=M.DHAN_TO_ORDER_TYPE.get(order_type, order_type),
                    price=leg.get("price", 0),
                    trigger_price=leg.get("triggerPrice", 0),
                    instrument_id=security_id,
                    option_type=identity.get("option_type"),
                    expiry=identity.get("expiry"),
                    strike_price=identity.get("strike_price"),
                    underlying=identity.get("underlying"),
                    leg_name=f"CONDITIONAL_LEG_{index}",
                    parent_order_id=alert_id,
                    margin_unfunded=True,
                )
            )
        return rows

    @staticmethod
    def _same_safety_exposure(left: dict[str, Any], right: dict[str, Any]) -> bool:
        return all(
            str(left.get(field) or "").strip().upper() == str(right.get(field) or "").strip().upper()
            for field in ("symbol", "exchange", "action", "product", "quantity", "leg_name")
        )

    @staticmethod
    def _super_source_keys(rows: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
        order_ids: set[str] = set()
        exchange_order_ids: set[str] = set()
        for row in rows:
            for value in (row.get("orderid"),):
                if str(value or "").strip():
                    order_ids.add(str(value).strip())
            if str(row.get("exchange_order_id") or "").strip():
                exchange_order_ids.add(str(row["exchange_order_id"]).strip())
            for leg in row.get("legs") or ():
                if not isinstance(leg, dict):
                    continue
                if str(leg.get("orderId") or "").strip():
                    order_ids.add(str(leg["orderId"]).strip())
                if str(leg.get("exchangeOrderId") or "").strip():
                    exchange_order_ids.add(str(leg["exchangeOrderId"]).strip())
        return order_ids, exchange_order_ids

    def _merge_regular_super_rows(
        self,
        regular_rows: list[dict[str, Any]],
        super_rows: list[dict[str, Any]],
        super_source: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        source_order_ids, source_exchange_ids = self._super_source_keys(super_source)
        merged = list(super_rows)
        matched_super_rows: set[int] = set()
        for regular in regular_rows:
            candidates = [
                row
                for row in super_rows
                if regular["broker_order_id"] == row["broker_order_id"]
                or (
                    regular.get("exchange_order_id")
                    and regular.get("exchange_order_id") == row.get("exchange_order_id")
                )
                or self._same_safety_exposure(regular, row)
            ]
            if len(candidates) > 1:
                raise M.DhanMappingError("Dhan regular and super books contain ambiguous duplicate legs")
            if candidates:
                candidate = candidates[0]
                candidate_key = id(candidate)
                if candidate_key in matched_super_rows:
                    raise M.DhanMappingError("Dhan regular book contains duplicate super-order legs")
                matched_super_rows.add(candidate_key)
                for field in ("symbol", "exchange", "action", "product"):
                    if str(regular[field]).upper() != str(candidate[field]).upper():
                        raise M.DhanMappingError("Dhan regular and super books disagree on order identity")
                candidate_quantity = self._safety_quantity(
                    candidate["quantity"],
                    field="super quantity",
                )
                regular_quantity = self._safety_quantity(
                    regular["quantity"],
                    field="regular quantity",
                )
                candidate_active = candidate["status"] not in _SAFETY_TERMINAL_ORDER_STATUSES
                regular_active = regular["status"] not in _SAFETY_TERMINAL_ORDER_STATUSES
                candidate["quantity"] = str(max(candidate_quantity, regular_quantity))
                candidate_fill_text = _optional_safety_text(candidate["filled_quantity"])
                regular_fill_text = _optional_safety_text(regular["filled_quantity"])
                if candidate_active and not regular_active:
                    candidate["filled_quantity"] = candidate_fill_text
                elif regular_active and not candidate_active:
                    candidate["status"] = regular["status"]
                    candidate["filled_quantity"] = regular_fill_text
                elif not candidate_fill_text or not regular_fill_text:
                    candidate["filled_quantity"] = ""
                else:
                    candidate_filled = self._safety_quantity(
                        candidate["filled_quantity"],
                        field="super filled quantity",
                        allow_zero=True,
                    )
                    regular_filled = self._safety_quantity(
                        regular["filled_quantity"],
                        field="regular filled quantity",
                        allow_zero=True,
                    )
                    merged_filled = (
                        min(candidate_filled, regular_filled)
                        if candidate_active and regular_active
                        else max(candidate_filled, regular_filled)
                    )
                    candidate["filled_quantity"] = str(merged_filled)
                candidate["orderid"] = regular["orderid"]
                candidate["broker_order_id"] = regular["broker_order_id"]
                candidate["raw_broker_order_id"] = regular["raw_broker_order_id"]
                candidate["safety_order_id"] = f"super:{regular['orderid']}"
                candidate["exchange_order_id"] = regular.get("exchange_order_id") or candidate.get(
                    "exchange_order_id",
                    "",
                )
                continue
            belongs_to_super = (
                regular["raw_broker_order_id"] in source_order_ids
                or regular.get("exchange_order_id") in source_exchange_ids
                or regular.get("leg_name") in {"TARGET_LEG", "STOP_LOSS_LEG"}
            )
            if belongs_to_super:
                regular["order_family"] = "super"
                regular["safety_order_id"] = f"super:{regular['orderid']}"
                regular["margin_unfunded"] = True
            merged.append(regular)
        return merged

    @staticmethod
    def _strict_safety_source(resp: Any, *, family: str) -> list[dict[str, Any]]:
        rows = M.unwrap(resp)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise M.DhanMappingError(f"Dhan {family} safety book returned malformed rows")
        return rows

    async def safety_order_book(self, session: Session) -> list[dict[str, Any]]:
        """Return the complete fail-closed Dhan order horizon for admission.

        The four APIs share one SDK transport, so they are read sequentially.
        Core performs the outer stable-snapshot retry; this method makes each
        returned horizon deterministic and refuses incomplete active features.
        """
        client = self._client(session)
        regular_source = [
            M.from_dhan_order(row)
            for row in self._strict_safety_source(
                await self._call(client.get_order_list),
                family="regular",
            )
        ]
        forever_source = [
            M.from_dhan_forever_order(row)
            for row in self._strict_safety_source(
                await self._call(client.get_forever),
                family="forever",
            )
        ]
        super_source = [
            M.from_dhan_super_order(row)
            for row in self._strict_safety_source(
                await self._call(client.get_super_order_list),
                family="super",
            )
        ]
        conditional_source = [
            M.from_dhan_conditional_trigger(row)
            for row in self._strict_safety_source(
                await self._call(self._http(session).get, M.CONDITIONAL_TRIGGER_ENDPOINT),
                family="conditional",
            )
        ]

        regular_rows = [
            safety_row
            for row in regular_source
            if isinstance(row, dict)
            if (safety_row := self._regular_safety_row(row)) is not None
        ]
        forever_rows = [
            safety_row
            for row in forever_source
            if isinstance(row, dict)
            for safety_row in self._forever_safety_rows(row)
        ]
        super_rows = [
            safety_row
            for row in super_source
            if isinstance(row, dict)
            for safety_row in self._super_safety_rows(row)
        ]
        conditional_rows = [
            safety_row
            for row in conditional_source
            if isinstance(row, dict)
            for safety_row in self._conditional_safety_rows(row)
        ]
        rows = [
            *self._merge_regular_super_rows(regular_rows, super_rows, super_source),
            *forever_rows,
            *conditional_rows,
        ]
        order_ids = [str(row["orderid"]) for row in rows]
        safety_ids = [str(row["safety_order_id"]) for row in rows]
        if len(set(order_ids)) != len(order_ids) or len(set(safety_ids)) != len(safety_ids):
            raise M.DhanMappingError("Dhan safety order horizon contains duplicate identities")
        return sorted(rows, key=lambda row: str(row["safety_order_id"]))

    async def order_book(self, session: Session) -> list[Order]:
        resp = await self._call(self._client(session).get_order_list)
        rows = M.unwrap(resp) or []
        return [M.from_dhan_order(r) for r in rows]  # type: ignore[misc]

    async def get_order_by_id(self, session: Session, order_id: str) -> dict:
        """Fetch one order's current status by Dhan order id (``GET /orders/{id}``)."""
        resp = await self._call(self._client(session).get_order_by_id, str(order_id))
        data = M.unwrap(resp)
        if isinstance(data, list):  # Dhan returns a single-element array for this endpoint
            data = data[0] if data else {}
        return M.from_dhan_order(data if isinstance(data, dict) else {})

    async def get_order_by_correlation_id(self, session: Session, correlation_id: str) -> dict:
        """Fetch one order by the caller-supplied correlation id (``GET /orders/external/{id}``)."""
        resp = await self._call(self._client(session).get_order_by_correlationID, str(correlation_id))
        data = M.unwrap(resp)
        if isinstance(data, list):
            data = data[0] if data else {}
        return M.from_dhan_order(data if isinstance(data, dict) else {})

    async def trade_book(self, session: Session) -> list[Trade]:
        resp = await self._call(self._client(session).get_trade_book)
        rows = M.unwrap(resp) or []
        return [M.from_dhan_trade(r) for r in rows]  # type: ignore[misc]

    async def positions(self, session: Session) -> list[Position]:
        resp = await self._call(self._client(session).get_positions)
        rows = M.unwrap(resp) or []
        return [M.from_dhan_position(r) for r in rows]  # type: ignore[misc]

    async def holdings(self, session: Session) -> list[dict]:
        resp = await self._call(self._client(session).get_holdings)
        try:
            rows = M.unwrap(resp) or []
        except M.DhanMappingError as exc:
            if "no holdings available" in str(exc).lower():
                return []
            raise
        return [M.from_dhan_holding(r) for r in rows]

    async def funds(self, session: Session) -> dict:
        resp = await self._call(self._client(session).get_fund_limits)
        return M.from_dhan_funds(resp)

    # ---------- market data: rest ----------

    async def quotes(self, session: Session, symbols: list[str]) -> list[Quote]:
        from flinttrade_core.models import Quote  # noqa: PLC0415

        # Resolve every symbol to (segment, security_id) and batch by segment.
        resolved: list[tuple[str, str, str, str]] = []
        securities: dict[str, list[Any]] = {}
        for raw in symbols:
            exchange, name = self._split_symbol(raw)
            sec_id = self._resolve_security(name, exchange)
            segment = M.to_dhan_segment(exchange)
            securities.setdefault(segment, []).append(int(sec_id) if sec_id.isdigit() else sec_id)
            resolved.append((name, exchange, segment, sec_id))

        resp = await self._call(self._client(session).quote_data, securities)

        out: list[Quote] = []
        for name, exchange, segment, sec_id in resolved:
            rec = M.quote_from_feed(segment, sec_id, resp)
            if rec is not None:
                out.append(Quote(**M.from_dhan_quote(name, exchange, rec)))
        return out

    async def ltp(self, session: Session, symbols: list[str]) -> dict[str, float]:
        """Last traded prices from the existing quote snapshot, keyed by ``EXCHANGE:SYMBOL``."""
        quotes = await self.quotes(session, symbols)
        return {f"{q.exchange}:{q.symbol}": q.ltp for q in quotes}

    async def ohlc(self, session: Session, symbols: list[str]) -> list[dict[str, Any]]:
        """OHLC snapshot from the existing quote path."""
        quotes = await self.quotes(session, symbols)
        return [
            {
                "symbol": q.symbol,
                "exchange": q.exchange,
                "open": q.open,
                "high": q.high,
                "low": q.low,
                "close": q.close,
            }
            for q in quotes
        ]

    async def quote_details(
        self,
        session: Session,
        symbols: list[str],
        quote_type: str = "all",
    ) -> list[dict[str, Any]]:
        """Quote snapshot from the existing quote path (Dhan has no typed quote REST verb)."""
        kind = str(quote_type or "all").strip().lower() or "all"
        allowed = {"all", "ltp", "ohlc"}
        if kind not in allowed:
            raise BrokerError(f"Dhan quote_type must be one of {sorted(allowed)}, got {quote_type!r}")
        quotes = await self.quotes(session, symbols)
        return [
            {
                "symbol": q.symbol,
                "exchange": q.exchange,
                "ltp": q.ltp,
                "open": q.open,
                "high": q.high,
                "low": q.low,
                "close": q.close,
                "volume": q.volume,
                "oi": q.oi,
            }
            for q in quotes
        ]

    async def historical(self, session: Session, req: dict) -> Candles:
        from flinttrade_core.models import OHLCV, Candles  # noqa: PLC0415

        symbol = str(req.get("symbol", ""))
        exchange = str(req.get("exchange", "NSE"))
        interval = str(req.get("interval", req.get("timeframe", "1m")))
        instrument = str(req.get("instrument_type", req.get("instrument", "EQUITY")))
        from_date = req.get("from_date") or req.get("start") or req.get("start_date")
        to_date = req.get("to_date") or req.get("end") or req.get("end_date")
        security_id = self._resolve_security(symbol, exchange)
        segment = M.to_dhan_segment(exchange)
        kind, minutes = M.interval_to_dhan(interval)
        client = self._client(session)
        if kind == "daily":
            resp = await self._call(client.historical_daily_data, security_id, segment, instrument, from_date, to_date)
        else:
            resp = await self._call(
                client.intraday_minute_data, security_id, segment, instrument, from_date, to_date, minutes
            )
        cd = M.to_candles_dict(symbol, exchange, interval, resp)
        return Candles(
            symbol=cd["symbol"],
            exchange=cd["exchange"],
            interval=cd["interval"],
            bars=[OHLCV(**b) for b in cd["bars"]],
        )

    async def option_chain(self, session: Session, req: dict) -> OptionChain:
        from flinttrade_core.models import OptionChain, OptionChainStrike  # noqa: PLC0415

        underlying = str(req.get("symbol") or req.get("underlying") or "")
        exchange = str(req.get("exchange", "NSE_INDEX"))
        expiry = req.get("expiry") or req.get("expiry_date")
        cache_key = (id(session), underlying.upper(), exchange.upper(), str(expiry or ""))
        cached = self._option_chain_cache.get(cache_key)
        now = time.monotonic()
        if cached is not None and now - cached[0] < _OPTION_CHAIN_CACHE_SECONDS:
            return cached[1]
        lock = self._option_chain_locks.setdefault(cache_key, asyncio.Lock())
        async with lock:
            cached = self._option_chain_cache.get(cache_key)
            now = time.monotonic()
            if cached is not None and now - cached[0] < _OPTION_CHAIN_CACHE_SECONDS:
                return cached[1]
            try:
                security_id = self._resolve_security(underlying, exchange)
                segment = M.to_dhan_segment(exchange)
                resp = await self._call(self._client(session).option_chain, security_id, segment, expiry)
                oc = M.to_option_chain_dict(underlying, exchange, resp)
                result = OptionChain(
                    underlying=oc["underlying"],
                    exchange=oc["exchange"],
                    spot_price=oc["spot_price"],
                    strikes=[OptionChainStrike(**s) for s in oc["strikes"]],
                )
            except BrokerError:
                raise
            except Exception as exc:  # noqa: BLE001 - enforce the BrokerAdapter exception boundary
                raise BrokerError("Dhan option-chain response is invalid") from exc
            self._option_chain_cache[cache_key] = (time.monotonic(), result)
            return result

    async def option_greeks(self, session: Session, symbols: list[str]) -> list[dict[str, Any]]:
        """Return native option Greeks for the selector-aware terminal read."""
        positions: list[dict[str, Any]] = []
        for raw_symbol in symbols:
            exchange, symbol = self._split_symbol(raw_symbol)
            if exchange not in {"NFO", "BFO"} or not symbol:
                raise BrokerError("Dhan option Greeks require an NFO or BFO option symbol")
            try:
                instrument_id = self._resolve_security(symbol, exchange).strip()
                if not instrument_id or self._security_resolver is None:
                    raise M.DhanMappingError("Dhan option symbol lacks authoritative contract identity")
                identity = M.reverse_security_id(self._security_resolver, instrument_id, exchange)
            except Exception as exc:  # noqa: BLE001 - enforce the BrokerAdapter exception boundary
                raise BrokerError("Dhan option symbol lacks authoritative contract identity") from exc
            positions.append({
                "symbol": symbol,
                "instrument_id": instrument_id,
                "exchange": exchange,
                "quantity": 1.0,
                "option_type": identity.get("option_type"),
                "expiry": identity.get("expiry"),
                "strike_price": identity.get("strike_price"),
                "underlying": identity.get("underlying"),
            })
        return await self.portfolio_greeks(session, positions)

    async def portfolio_greeks(
        self,
        session: Session,
        positions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Return complete per-contract Delta/Vega rows for a live portfolio."""
        rows: list[dict[str, Any]] = []
        for position in positions:
            symbol = str(position.get("symbol") or "").strip()
            instrument_id = str(position.get("instrument_id") or "").strip()
            exchange = str(position.get("exchange") or "").strip().upper()
            option_type = str(position.get("option_type") or "").strip().upper()
            expiry = str(position.get("expiry") or "").strip()
            underlying = str(position.get("underlying") or "").strip()
            try:
                strike_price = float(position.get("strike_price") or 0)
            except (TypeError, ValueError) as exc:
                raise BrokerError("Dhan option position has an invalid strike") from exc
            if not symbol or exchange not in {"NFO", "BFO"} or option_type not in {"CE", "PE"}:
                raise BrokerError("Dhan option position lacks authoritative contract identity")
            try:
                if not instrument_id:
                    instrument_id = self._resolve_security(symbol, exchange).strip()
                option_type, expiry, strike_price, underlying = self._safety_option_identity(
                    symbol=symbol,
                    exchange=exchange,
                    instrument_id=instrument_id,
                    option_type=option_type,
                    expiry=expiry,
                    strike_price=strike_price,
                    underlying=underlying,
                )
            except Exception as exc:  # noqa: BLE001 - enforce the BrokerAdapter exception boundary
                raise BrokerError("Dhan option position lacks authoritative contract identity") from exc
            if not instrument_id:
                raise BrokerError("Dhan option position lacks authoritative contract identity")
            if exchange == "NFO":
                underlying_exchange = "NSE_INDEX" if underlying.upper() in M.INDEX_SYMBOLS else "NSE"
            elif exchange == "BFO":
                underlying_exchange = "BSE_INDEX" if underlying.upper() in M.INDEX_SYMBOLS else "BSE"
            else:
                raise BrokerError(f"Dhan option-chain Greeks are unavailable for {exchange}")
            try:
                chain = await self.option_chain(
                    session,
                    {
                        "symbol": underlying,
                        "exchange": underlying_exchange,
                        "expiry": expiry,
                    },
                )
            except (M.DhanMappingError, BrokerError) as exc:
                raise BrokerError("Dhan option-chain Greek read failed") from exc
            strike = next(
                (
                    candidate
                    for candidate in chain.strikes
                    if math.isclose(candidate.strike_price, strike_price, rel_tol=0.0, abs_tol=1e-6)
                ),
                None,
            )
            side = "ce" if option_type == "CE" else "pe"
            if strike is None:
                raise BrokerError("Dhan option-chain response lacks complete Greek values")
            chain_instrument_id = str(getattr(strike, f"{side}_instrument_id") or "").strip()
            if not chain_instrument_id or chain_instrument_id != instrument_id:
                raise BrokerError("Dhan option-chain response conflicts with the option security identity")
            if not getattr(strike, f"{side}_greeks_complete"):
                raise BrokerError("Dhan option-chain response lacks complete Greek values")
            delta = float(getattr(strike, f"{side}_delta"))
            gamma = float(getattr(strike, f"{side}_gamma"))
            theta = float(getattr(strike, f"{side}_theta"))
            vega = float(getattr(strike, f"{side}_vega"))
            iv = float(getattr(strike, f"{side}_iv"))
            if not all(math.isfinite(value) for value in (delta, gamma, theta, vega, iv)):
                raise BrokerError("Dhan option-chain response contains non-finite Greeks")
            row = {
                "symbol": symbol,
                "instrument_id": instrument_id,
                "exchange": exchange,
                "ltp": float(getattr(strike, f"{side}_ltp")),
                "iv": iv,
                "delta": delta,
                "gamma": gamma,
                "theta": theta,
                "vega": vega,
            }
            oi = getattr(strike, f"{side}_oi")
            if oi is not None:
                row["oi"] = int(oi)
            rows.append(row)
        return rows

    # ---------- pre-trade info (reads) ----------

    async def margin_calculator(self, session: Session, order: Order) -> dict:
        """Pre-trade margin estimate for ``order`` (Dhan ``/margincalculator``).

        A read-only estimate — does NOT place anything, so it needs no gate.
        """
        security_id = self._resolve_security(order.symbol, order.exchange)
        kwargs = M.to_margin_kwargs(order, security_id)
        resp = await self._call(self._client(session).margin_calculator, **kwargs)
        return M.from_dhan_margin(resp)

    async def expiry_list(self, session: Session, symbol: str, exchange: str = "NSE_INDEX") -> list[str]:
        """List the available option expiries for an underlying (read)."""
        security_id = self._resolve_security(symbol, exchange)
        segment = M.to_dhan_segment(exchange)
        resp = await self._call(self._client(session).expiry_list, security_id, segment)
        return M.from_dhan_expiry_list(resp)

    async def trade_history(self, session: Session, from_date: str, to_date: str, page: int = 0) -> list[dict]:
        """Historical trade statement for a date range (Dhan ``/trades``) — a read."""
        resp = await self._call(self._client(session).get_trade_history, from_date, to_date, page)
        return M.from_dhan_statement_list(resp)

    async def ledger(self, session: Session, from_date: str, to_date: str) -> list[dict]:
        """Ledger / funds statement for a date range (Dhan ledger report) — a read."""
        resp = await self._call(self._client(session).ledger_report, from_date, to_date)
        return M.from_dhan_statement_list(resp)

    async def kill_switch(self, session: Session, action: str) -> dict:
        """Toggle Dhan's broker-side kill switch (``ACTIVATE`` disables trading for
        the day; ``DEACTIVATE`` re-enables it). An account control, not an order —
        it places nothing, so it is outside the order gate.

        SAFETY: ``DEACTIVATE`` re-opens live trading, so any caller/route wiring it
        MUST gate ``DEACTIVATE`` behind an explicit, authenticated operator action
        (Live-mode + operator confirmation) and audit it. ``ACTIVATE`` is purely
        risk-reducing and may be invoked freely.
        """
        act = str(action).upper()
        if act not in ("ACTIVATE", "DEACTIVATE"):
            raise BrokerError(f"kill_switch action must be ACTIVATE or DEACTIVATE, got {action!r}")
        resp = await self._call(self._client(session).kill_switch, act)
        unwrapped = M.unwrap(resp)
        return unwrapped if isinstance(unwrapped, dict) else {"status": str(resp)}

    async def kill_switch_status(self, session: Session) -> dict:
        """Read the kill-switch state for the account (``GET /killswitch``) — a read."""
        resp = await self._call(self._client(session).status_kill_switch)
        data = M.unwrap(resp)
        return data if isinstance(data, dict) else {"status": str(data)}

    # ---------- trader's control: P&L based exit (v2.5) ----------

    async def set_pnl_exit(
        self,
        session: Session,
        profit_value: float,
        loss_value: float,
        product_types: list[str] | None = None,
        enable_kill_switch: bool = False,
    ) -> dict:
        """Configure the day's P&L-based auto-exit (``POST /pnlExit``, v2.5).

        A purely risk-reducing account control (it can only flatten positions
        when thresholds breach), so like ``kill_switch`` ACTIVATE it sits
        outside the order gate. Resets at the end of the trading session.
        """
        payload = M.to_pnl_exit_payload(profit_value, loss_value, product_types, enable_kill_switch)
        resp = await self._call(self._http(session).post, M.PNL_EXIT_ENDPOINT, payload)
        data = M.unwrap(resp)
        return data if isinstance(data, dict) else {"status": str(data)}

    async def stop_pnl_exit(self, session: Session) -> dict:
        """Disable the active P&L-based exit configuration (``DELETE /pnlExit``, v2.5).

        SAFETY: stopping the P&L exit REMOVES a protective control, so any
        caller/route wiring it MUST gate it behind an explicit, authenticated
        operator action (Live-mode + operator confirmation) and audit it —
        the same pattern as ``kill_switch`` DEACTIVATE. Configuring
        (:meth:`set_pnl_exit`) is risk-reducing and may be invoked freely.
        """
        resp = await self._call(self._http(session).delete, M.PNL_EXIT_ENDPOINT)
        data = M.unwrap(resp)
        return data if isinstance(data, dict) else {"status": str(data)}

    async def get_pnl_exit(self, session: Session) -> dict:
        """Read the currently active P&L-based exit configuration (``GET /pnlExit``) — a read."""
        resp = await self._call(self._http(session).get, M.PNL_EXIT_ENDPOINT)
        data = M.unwrap(resp)
        return data if isinstance(data, dict) else {"status": str(data)}

    # ---------- EDIS (sell-side demat authorisation) ----------

    async def generate_tpin(self, session: Session) -> dict:
        """Trigger a CDSL T-PIN to the registered mobile (``GET /edis/tpin``) — a read-shaped trigger."""
        resp = await self._call(self._client(session).generate_tpin)
        return resp if isinstance(resp, dict) else {"status": str(resp)}

    async def edis_form(
        self, session: Session, isin: str, qty: int, exchange: str, segment: str = "EQ", bulk: bool = False
    ) -> dict:
        """Fetch the escaped CDSL eDIS form HTML (``POST /edis/form``) — headless.

        The SDK's ``open_browser_for_tpin`` writes a temp file and opens a
        browser, which is useless on a server — so the documented endpoint is
        called directly and the (unescaped) form HTML is returned for the
        caller to render. The form posts to CDSL where the operator enters
        their T-PIN; FlintTrade never sees it.
        """
        payload = {
            "isin": str(isin),
            "qty": int(qty),
            "exchange": str(exchange).upper(),
            "segment": str(segment).upper(),
            "bulk": bool(bulk),
        }
        resp = await self._call(self._http(session).post, "/edis/form", payload)
        data = M.unwrap(resp)
        if not isinstance(data, dict):
            return {"edis_form_html": ""}
        html = str(data.get("edisFormHtml", "")).replace("\\", "")
        return {**data, "edis_form_html": html}

    async def edis_inquiry(self, session: Session, isin: str = "ALL") -> dict:
        """Check eDIS approval status for an ISIN, or ``\"ALL\"`` (``GET /edis/inquire/{isin}``)."""
        resp = await self._call(self._client(session).edis_inquiry, str(isin))
        data = M.unwrap(resp)
        return data if isinstance(data, dict) else {"status": str(data)}

    # ---------- auth surface (token + static IP management) ----------

    async def user_profile(self, session: Session) -> dict:
        """Validate the token / account setup (``GET /profile``) — a read."""
        login = self._login_helper(str(session.extra.get("client_id") or session.account_id))
        resp = await self._call(login.user_profile, session.access_token)
        return resp if isinstance(resp, dict) else {"status": str(resp)}

    async def generate_token(self, client_id: str, pin: str, totp: str) -> dict:
        """Generate a fresh 24h access token via PIN + TOTP (v2.5 token API).

        Pre-session auth: needs no existing token, so it takes the client id
        directly. Returns Dhan's response (``accessToken`` + ``expiryTime``);
        feed it to :meth:`login` to mint a Session.
        """
        login = self._login_helper(str(client_id))
        resp = await self._call(login.generate_token, str(pin), str(totp))
        return resp if isinstance(resp, dict) else {"status": str(resp)}

    async def consume_token_id(self, client_id: str, token_id: str, app_id: str, app_secret: str) -> dict:
        """Consume a DhanHQ OAuth ``tokenId`` into a 24h access token."""
        login = self._login_helper(str(client_id))
        resp = await self._call(login.consume_token_id, str(token_id), str(app_id), str(app_secret))
        return resp if isinstance(resp, dict) else {"status": str(resp)}

    async def renew_token(self, session: Session) -> dict:
        """Renew a still-active access token for another 24h (``GET /RenewToken``).

        Returns Dhan's response (new ``accessToken``); the caller re-runs
        :meth:`login` with it — the adapter does not mutate the old Session.
        """
        login = self._login_helper(str(session.extra.get("client_id") or session.account_id))
        resp = await self._call(login.renew_token, session.access_token)
        return resp if isinstance(resp, dict) else {"status": str(resp)}

    async def set_ip(self, session: Session, ip: str, ip_flag: str = "PRIMARY") -> dict:
        """Whitelist a static IP for order placement (``POST /ip/setIP``).

        Once set, an IP cannot be modified for 7 days (authentication.md).
        """
        login = self._login_helper(str(session.extra.get("client_id") or session.account_id))
        resp = await self._call(login.set_ip, session.access_token, str(ip), str(ip_flag).upper())
        data = M.unwrap(resp)
        return data if isinstance(data, dict) else {"status": str(data)}

    async def modify_ip(self, session: Session, ip: str, ip_flag: str = "PRIMARY") -> dict:
        """Modify the whitelisted static IP (``PUT /ip/modifyIP``; once per 7 days)."""
        login = self._login_helper(str(session.extra.get("client_id") or session.account_id))
        resp = await self._call(login.modify_ip, session.access_token, str(ip), str(ip_flag).upper())
        data = M.unwrap(resp)
        return data if isinstance(data, dict) else {"status": str(data)}

    async def get_ip(self, session: Session) -> dict:
        """Read the currently whitelisted static IPs (``GET /ip/getIP``) — a read."""
        login = self._login_helper(str(session.extra.get("client_id") or session.account_id))
        resp = await self._call(login.get_ip, session.access_token)
        data = M.unwrap(resp)
        return data if isinstance(data, dict) else {"status": str(data)}

    # ---------- instruments (scrip master) ----------

    async def fetch_security_list(
        self, mode: str = "compact", *, downloader: Callable[[str], str] | None = None
    ) -> list[dict]:
        """Download + parse the Dhan scrip master CSV (instruments.md).

        Thin async wrapper over the canonical module-level
        :func:`load_scrip_master_rows` (run off the event loop). Returns the
        rows as dicts keyed by the CSV header tags (``SEM_*`` for compact).
        Feed the rows to ``dhan_mapping.build_security_resolver`` to obtain a
        ``security_resolver`` for this adapter. ``downloader`` is injectable
        for tests; the default fetches over HTTPS via stdlib.
        """
        return await self._call(load_scrip_master_rows, mode, downloader=downloader)

    # ---------- market data: expired (rolling) options ----------

    async def expired_options(self, session: Session, req: dict) -> dict:
        """Historical expired-options data on a rolling basis (``POST /charts/rollingoption``).

        Dhan's edge feature: up to 5 years of strike-relative (ATM±n) options
        history readable ACROSS expiry rollovers — this backs the advertised
        ``options_history_supported`` / ``options_history_rolling`` capability.
        ``req`` carries symbol/exchange (or ``security_id``), ``expiry_flag``
        (WEEK/MONTH), ``expiry_code``, ``strike`` (e.g. ``"ATM"``),
        ``option_type`` (CALL/PUT), ``required_data``, dates and ``interval``.
        """
        security_id = str(
            req.get("security_id")
            or self._resolve_security(
                str(req.get("symbol", req.get("underlying", ""))), str(req.get("exchange", "NFO"))
            )
        )
        kwargs = M.to_expired_options_kwargs(req, security_id)
        resp = await self._call(self._client(session).expired_options_data, **kwargs)
        return M.from_dhan_expired_options(resp)

    # ---------- market data: streaming ----------

    async def subscribe(self, session: Session, symbols: list[str], mode: str = "FULL") -> None:
        # Resolve each symbol to its Dhan security id and remember it so decoded
        # binary ticks (which carry only the security id) can be routed back to
        # the symbol when streamed. The mode maps to the v2 feed RequestCode
        # (TICKER=15 / QUOTE=17 / FULL=21 — the SDK marketfeed constants) and is
        # recorded per instrument for the live feed wiring.
        request_code = M.subscribe_mode_to_request_code(mode)
        for raw in symbols:
            exchange, name = self._split_symbol(raw)
            security_id = self._resolve_security(name, exchange)
            self._feed_map[str(security_id)] = (name, exchange)
            self._feed_modes[str(security_id)] = request_code

    async def unsubscribe(self, session: Session, symbols: list[str]) -> None:
        for raw in symbols:
            exchange, name = self._split_symbol(raw)
            try:
                security_id = self._resolve_security(name, exchange)
            except BrokerError:
                continue
            self._feed_map.pop(str(security_id), None)
            self._feed_modes.pop(str(security_id), None)

    def stream(self, session: Session) -> AsyncIterator[Any]:
        return self._stream_impl(session)

    async def _stream_impl(self, session: Session) -> AsyncIterator[Any]:
        from flinttrade_core.models import TickEvent  # noqa: PLC0415

        if self._feed_factory is None:
            # Live: the binary WS feed needs the dhanhq SDK + credentials. The
            # decode path (decode_dhan_tick) is implemented and tested; the live
            # socket is provided by injecting a feed_factory.
            raise NotImplementedError("Dhan live tick stream needs the dhanhq market feed (inject feed_factory)")

        async for frame in self._feed_factory(session):
            tick = M.decode_dhan_tick(frame)
            if tick is None:
                continue
            symbol, exchange = self._feed_map.get(
                tick["security_id"],
                ("", tick.get("exchange", "")),
            )
            yield TickEvent(
                symbol=symbol,
                exchange=exchange or tick.get("exchange", ""),
                ltp=tick.get("ltp", 0.0),
                volume=int(tick.get("volume", 0)),
                timestamp="",
            )

    # ---------- order-update streaming ----------

    def stream_order_updates(self, session: Session) -> AsyncIterator[dict]:
        """Open the live order-update stream and yield normalised update dicts.

        Frames arrive as JSON over ``wss://api-order-update.dhan.co``
        (order-update.md); non-``order_alert`` frames are skipped. Tests inject
        ``order_feed_factory``; live runs open the documented socket (the
        transport behind the SDK's ``orderupdate.OrderUpdate``).
        """
        return self._order_updates_impl(session)

    async def _order_updates_impl(self, session: Session) -> AsyncIterator[dict]:
        if self._order_feed_factory is not None:
            frames = self._order_feed_factory(session)
        else:
            frames = self._live_order_update_frames(session)
        async for frame in frames:
            update = M.decode_order_update(frame)
            if update is not None:
                yield update

    async def _live_order_update_frames(self, session: Session) -> AsyncIterator[Any]:
        """Live order-update socket: authorise (MsgCode 42) then relay frames."""
        import json  # noqa: PLC0415

        try:
            import websockets  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise BrokerError("Dhan order-update stream needs the 'websockets' package") from exc

        client_id = str(session.extra.get("client_id") or session.account_id)
        async with websockets.connect(M.ORDER_UPDATE_WSS) as ws:  # pragma: no cover - live socket
            await ws.send(json.dumps(M.order_update_login_payload(client_id, session.access_token)))
            async for message in ws:
                yield message

    # ---------- market depth streaming (20 / 200 level) ----------

    def stream_depth(self, session: Session, level: int = 20) -> AsyncIterator[dict]:
        """Open a 20- or 200-level depth stream and yield per-side depth dicts.

        Each yielded dict carries ``side`` (bid/ask), ``security_id``,
        ``symbol`` (routed via the subscribe map), ``exchange`` and ``depth``
        rows of ``{price, quantity, orders}`` — decoded per the documented
        binary layout (full-market-depth.md / the SDK's ``fulldepth.py``).
        The live sockets (``wss://depth-api-feed.dhan.co/twentydepth`` and
        ``wss://full-depth-api.dhan.co/twohundreddepth``) are provided by
        injecting ``depth_feed_factory``.
        """
        return self._depth_impl(session, level)

    async def _depth_impl(self, session: Session, level: int) -> AsyncIterator[dict]:
        if level not in M.DHAN_DEPTH_LEVELS:
            raise BrokerError(f"Dhan depth level must be one of {M.DHAN_DEPTH_LEVELS}, got {level!r}")
        if self._depth_feed_factory is None:
            raise NotImplementedError(
                "Dhan live depth stream needs the depth feed socket (inject depth_feed_factory; "
                "live default is the dhanhq fulldepth.FullDepth transport)"
            )
        async for frame in self._depth_feed_factory(session, level):
            for message in M.iter_dhan_depth_messages(frame):
                symbol, exchange = self._feed_map.get(
                    message["security_id"],
                    ("", message.get("exchange", "")),
                )
                message["symbol"] = symbol
                if exchange:
                    message["exchange"] = exchange
                yield message

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
