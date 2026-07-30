"""IndMoney (INDstocks) native adapter — pure REST + WebSocket, no SDK.

IndMoney publishes no official SDK, so this adapter speaks the documented REST
API (``https://api.indstocks.com``) directly through an injected HTTP transport
(default: a thin ``httpx`` wrapper — httpx is already a gateway dependency) and
the documented JSON WebSocket feeds through injected feed factories. All
request/response translation lives in ``indmoney_mapping`` and is unit-tested;
the methods here are thin orchestration over the transport.

Auth: a dashboard-generated access token that resets at the broker's daily
06:00 IST dashboard cycle (max 24 h; manual regeneration — there is no login or
refresh endpoint). ``login`` therefore only builds the Session; ``profile()``
doubles as a token-validity probe.

Coverage: the full BrokerAdapter ABC plus every extra documented INDstocks
feature as capability-style extension methods — order details, per-order trades,
segment trade books, segment/product positions, LTP + market-depth quotes,
instruments master (CSV), pre-trade margin, smart orders (GTT/OCO/TRIGGER), and
both WebSocket feeds (price + order updates). The utility family (option chain /
expiries / Greeks) is documented as "Coming Soon" broker-side and raises until
the API ships. The full parity matrix is
``.local/audits/broker-parity/indmoney.md``.

Safety: writes — including every smart-order variety — require the router's
per-process ``_ROUTER_TOKEN`` (§8), so a bare call raises before any IndMoney
request is made. The variety and its leg prices are part of the
SafetyContext-hashed order, so a GTT/OCO/TRIGGER order is gated identically to a
regular one — no parallel order path.
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

from . import indmoney_mapping as M
from ._base import BrokerAdapter, Session, run_blocking_sdk_call
from ._session_expiry import next_6am_ist_timestamp

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flinttrade_core.models import Candles, OptionChain, Order, Position, Quote, Trade
    from flinttrade_gateway.reconciliation import LocalStateSnapshot, ReconciliationReport

_COMING_SOON = (
    "INDstocks {0} API is documented as 'Coming Soon' (under development broker-side) — "
    "not implementable until it ships"
)

INDMONEY_CAPABILITIES = Capabilities(
    # Order API enums: exchange NSE/BSE × segment EQUITY/DERIVATIVE only.
    segments=Segments.NSE_EQ | Segments.BSE_EQ | Segments.NFO | Segments.BFO,
    # Normal orders accept LIMIT/MARKET (MARKET is broker-converted to LIMIT at
    # the live price) + the is_amo flag; the smart-order family is native GTT
    # (single/OCO legs + TRIGGER parents). No standalone SL/SL-M order type, no
    # bracket/cover/iceberg endpoints — advertising them would credit work the
    # adapter rejects (the Upstox honesty precedent).
    order_types=(
        OrderTypes.MARKET
        | OrderTypes.LIMIT
        | OrderTypes.MIS
        | OrderTypes.CNC
        | OrderTypes.NRML
        | OrderTypes.AMO
        | OrderTypes.GTT
    ),
    depth_levels=DepthLevels.L5,
    tick_protocol=TickProtocol.GENERIC_JSON,  # both WS feeds stream plain JSON
    # Dashboard-generated access token, daily 06:00 IST reset, manual regeneration.
    auth_model=AuthModel.OAUTH_RENEWABLE_24H,
    session_lifetime_hours=24.0,
    sandbox=False,  # no sandbox documented — every call is live
    # Conventions-page rate-limit table.
    rate_limit_orders_per_sec=10,
    rate_limit_data_per_sec=5,
    rate_limit_data_per_day=100_000,
    rate_limit_quote_per_sec=5,
    rate_limit_non_trading_per_sec=15,
    order_modifications_per_order=25,
    # algo_id is a mandatory order field (99999 NSE / 9999999999999999 BSE).
    algo_tag_required=True,
    # API access is free; execution brokerage is a flat ₹5 per order.
    cost_paid=False,
    cost_inr_per_month=0,
    brokerage_free=False,
    brokerage_note="Flat ₹5 brokerage per order regardless of size; API access itself is free.",
    # Historical-data interval table — the doc advertises only per-request "Max
    # Fetch Range" per resolution (sub-minute 1 day, minutes 7 days, hours
    # 14 days, day/week/month 1 year), NOT a documented multi-year intraday
    # total, so historical_max_lookback_days_intraday is intentionally left unset
    # (None). The per-request caps are enforced in the mapping. Leaving lookback
    # unset keeps the recommendation engine honest: IndMoney is credited for its
    # broad interval menu, not over-credited for intraday depth it does not
    # document.
    historical_intraday_intervals_minutes=[1, 2, 3, 4, 5, 10, 15, 30, 60, 120, 180, 240],
    historical_calendar_intervals=["1D", "1W", "1M"],
    option_chain_supported=False,  # utility family is "Coming Soon" broker-side
    option_chain_greeks_supported=False,
    streaming_supported=True,
    streaming_max_connections_per_user=3,
    streaming_max_symbols_per_connection=3000,
    gtt_native=True,
    bracket_order_native=False,
    cover_order_native=False,
    multi_quote_supported=True,
    iceberg_native=False,
    modify_qty_supported=True,
)

# Transport signature: (method, url, headers=..., params=..., json_body=...) ->
# (status_code, decoded_payload). Synchronous — the adapter runs it off the
# event loop via the cancellation-safe blocking-call owner shared by native adapters.
Transport = Callable[..., tuple[int, Any]]

_EMERGENCY_BATCH_LIMIT = 10
_EMERGENCY_EXIT_TAG_PREFIX = "fte-indmoney-"
_EMERGENCY_TERMINAL_ORDER_STATUSES = frozenset(
    {
        "ABORTED",
        "SUCCESS",
        "CANCELLED",
        "EXPIRED",
        "FAILED",
        "PARTIALLY FILLED - CANCELLED",
        "PARTIALLY FILLED - EXPIRED",
    }
)
_EMERGENCY_SUCCESSFUL_ORDER_STATUSES = frozenset({"SUCCESS"})
_EMERGENCY_POSITION_SCOPES = (
    ("derivative", "margin", "NRML"),
    ("derivative", "intraday", "MIS"),
    ("equity", "cnc", "CNC"),
    ("equity", "intraday", "MIS"),
)


def _build_httpx_transport(timeout: float = 10.0) -> Transport:
    """Build the default HTTP transport over httpx (lazy import).

    Args:
        timeout: Per-request timeout in seconds.

    Returns:
        A synchronous transport callable returning ``(status_code, payload)``
        where payload is decoded JSON when possible, else raw text.
    """
    import httpx  # noqa: PLC0415

    def _request(
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> tuple[int, Any]:
        resp = httpx.request(method, url, headers=headers, params=params, json=json_body, timeout=timeout)
        try:
            payload: Any = resp.json()
        except ValueError:
            payload = resp.text
        return resp.status_code, payload

    return _request


class IndMoneyAdapter(BrokerAdapter):
    """Native IndMoney (INDstocks) adapter.

    Args:
        http_factory: ``() -> transport`` override (tests inject a fake). The
            transport is called as ``transport(method, url, headers=...,
            params=..., json_body=...)`` and returns ``(status_code, payload)``.
            When omitted, ``login`` builds the default httpx transport.
        security_resolver: Optional ``(symbol, exchange) -> security_id``
            override. IndMoney trades by instrument token from the instruments
            master; when no resolver is supplied, the adapter downloads and
            caches the documented instruments CSV per session/source. Numeric
            symbols pass through unchanged (already-resolved ids).
        feed_factory: ``session -> AsyncIterator[str | bytes]`` yielding raw
            price-feed JSON frames. The live socket is NOT bundled (no WS client
            dependency); without an injected factory ``stream`` raises.
        order_feed_factory: Same shape for the order-updates feed.
        local_state_provider: ``session -> LocalStateSnapshot`` supplying the
            flinttrade-side mirror that ``reconcile`` diffs broker state
            against. Defaults to EMPTY local state (every broker-side row then
            surfaces as ``exists_only_on_broker``) until the engine wave wires
            the journal-backed provider.
    """

    def __init__(
        self,
        *,
        http_factory: Callable[[], Transport] | None = None,
        security_resolver: Callable[[str, str], str] | None = None,
        feed_factory: Callable[[Session], AsyncIterator[str | bytes]] | None = None,
        order_feed_factory: Callable[[Session], AsyncIterator[str | bytes]] | None = None,
        local_state_provider: Callable[[Session], LocalStateSnapshot] | None = None,
    ) -> None:
        self._http_factory = http_factory
        self._security_resolver = security_resolver
        self._feed_factory = feed_factory
        self._order_feed_factory = order_feed_factory
        self._local_state_provider = local_state_provider
        # security_id -> (symbol, exchange) for routing decoded ticks back to names.
        self._feed_map: dict[str, tuple[str, str]] = {}
        # security_id -> requested feed mode (informational; the subscribe
        # message itself is built per stream() consumer).
        self._feed_modes: dict[str, str] = {}
        # Child GTT id of the most recent smart placement (the contract returns
        # one id, so the parent is returned and the child is surfaced here).
        self.last_child_order_id: str | None = None

    # ---------- identity + capabilities ----------

    @property
    def broker_id(self) -> str:
        return "indmoney"

    @property
    def capabilities(self) -> Capabilities:
        return INDMONEY_CAPABILITIES

    # ---------- helpers ----------

    def _transport(self, session: Session) -> Transport:
        if self._http_factory is not None:
            return self._http_factory()
        transport = session.extra.get("transport")
        if transport is None:
            raise BrokerError("IndMoney transport not initialised — call login() first")
        return transport

    @staticmethod
    def _headers(session: Session) -> dict[str, str]:
        # Header format is the bare token, no "Bearer" prefix (conventions doc).
        return {"Authorization": session.access_token, "Content-Type": "application/json"}

    async def _request(
        self,
        session: Session,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        raw: bool = False,
    ) -> Any:
        """Run one REST call off the event loop; unwrap the envelope or raise.

        Args:
            session: Active broker session (token + transport).
            method: HTTP method.
            path: Path under the API base URL.
            params: Query parameters.
            json_body: JSON request body (IndMoney uses bodies on some GETs).
            raw: Return the payload verbatim (CSV endpoints) instead of
                unwrapping the ``{status, data}`` envelope.
        """
        transport = self._transport(session)
        status, payload = await run_blocking_sdk_call(
            transport,
            method,
            f"{M.BASE_URL}{path}",
            headers=self._headers(session),
            params=params,
            json_body=json_body,
        )
        if status >= 400 or (isinstance(payload, dict) and str(payload.get("status", "")).lower() == "error"):
            raise M.map_error(status, payload)
        return payload if raw else M.unwrap(payload)

    async def _emergency_request(
        self,
        session: Session,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        require_data: bool = True,
    ) -> Any:
        """Accept only an explicit successful broker envelope."""
        status, payload = await run_blocking_sdk_call(
            self._transport(session),
            method,
            f"{M.BASE_URL}{path}",
            headers=self._headers(session),
            params=params,
            json_body=json_body,
        )
        if status >= 400:
            raise M.map_error(status, payload)
        if not isinstance(payload, dict):
            raise BrokerError(f"INDmoney emergency {path} response is malformed")
        response_status = payload.get("status")
        if not isinstance(response_status, str) or response_status.strip().lower() != "success":
            if isinstance(response_status, str) and response_status.strip():
                raise M.map_error(status, payload)
            raise BrokerError(f"INDmoney emergency {path} response is malformed")
        if require_data and "data" not in payload:
            raise BrokerError(f"INDmoney emergency {path} response is malformed")
        return payload.get("data")

    def _resolve_security(self, symbol: str, exchange: str) -> str:
        sym = str(symbol).strip()
        if sym.isdigit():
            return sym  # already an instrument token
        if self._security_resolver is not None:
            return str(self._security_resolver(sym, exchange))
        raise BrokerError(
            f"Cannot resolve IndMoney security_id for {symbol}/{exchange} — "
            "configure a security resolver (instruments master)"
        )

    @staticmethod
    def _instrument_source_for_exchange(exchange: str) -> str:
        """Map a canonical exchange to the INDstocks instruments ``source``."""
        exch = str(exchange).strip().upper()
        if exch in {"NFO", "BFO"}:
            return "fno"
        if exch in {"NSE_INDEX", "BSE_INDEX"}:
            return "index"
        return "equity"

    @staticmethod
    def _row_value(row: dict[str, Any], names: set[str]) -> str:
        """Return the first non-empty row value whose key matches ``names``."""
        for key, value in row.items():
            if str(key).strip().upper() in names and value not in (None, ""):
                return str(value).strip()
        return ""

    @staticmethod
    def _symbol_keys(value: Any) -> set[str]:
        """Normalise symbol aliases from instrument rows and user input."""
        raw = str(value or "").strip().upper()
        if not raw:
            return set()
        keys = {raw}
        compact = raw.replace(" ", "")
        if compact:
            keys.add(compact)
        for key in list(keys):
            if key.endswith("-EQ"):
                keys.add(key[:-3])
            if key.endswith(".EQ"):
                keys.add(key[:-3])
        return keys

    @staticmethod
    def _row_matches_exchange(row: dict[str, Any], exchange: str) -> bool:
        """True when an instrument row belongs to the requested canonical exchange."""
        canonical = str(exchange).strip().upper()
        expected_exchange = {
            "NSE": "NSE",
            "NFO": "NSE",
            "NSE_INDEX": "NSE",
            "BSE": "BSE",
            "BFO": "BSE",
            "BSE_INDEX": "BSE",
        }.get(canonical, canonical)
        row_exchange = IndMoneyAdapter._row_value(row, {"EXCH", "EXCHANGE"})
        if row_exchange and row_exchange.upper() != expected_exchange:
            return False

        segment = IndMoneyAdapter._row_value(row, {"SEGMENT", "EXCHANGE_SEGMENT"}).upper()
        if not segment:
            return True
        expected_segments = {
            "NSE": {"E", "EQ", "EQUITY", "NSE_EQ"},
            "BSE": {"E", "EQ", "EQUITY", "BSE_EQ"},
            "NFO": {"FNO", "D", "DERIVATIVE", "NSE_FNO"},
            "BFO": {"FNO", "D", "DERIVATIVE", "BSE_FNO"},
            "NSE_INDEX": {"I", "IDX", "INDEX", "NIDX", "NSE_INDEX"},
            "BSE_INDEX": {"I", "IDX", "INDEX", "BIDX", "BSE_INDEX"},
        }.get(canonical)
        return expected_segments is None or segment in expected_segments

    async def _instrument_index(self, session: Session, source: str) -> dict[str, list[tuple[dict[str, Any], str]]]:
        """Return a cached symbol -> ``(row, security_id)`` index for ``source``."""
        cache = session.extra.setdefault("indmoney_instrument_index", {})
        if source in cache:
            return cache[source]

        rows = await self.instruments(session, source)
        index: dict[str, list[tuple[dict[str, Any], str]]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            security_id = self._row_value(row, {"SECURITY_ID", "SECURITYID", "INSTRUMENT_TOKEN", "TOKEN"})
            if not security_id:
                continue
            for field in ("TRADING_SYMBOL", "SYMBOL_NAME", "CUSTOM_SYMBOL"):
                for key in self._symbol_keys(row.get(field)):
                    index.setdefault(key, []).append((row, security_id))
        cache[source] = index
        return index

    async def _resolve_security_for_session(self, session: Session, symbol: str, exchange: str) -> str:
        """Resolve an INDstocks security id using override, numeric token, or cached instruments CSV."""
        try:
            return self._resolve_security(symbol, exchange)
        except BrokerError as exc:
            if self._security_resolver is not None:
                raise
            source = self._instrument_source_for_exchange(exchange)
            index = await self._instrument_index(session, source)
            candidates = self._symbol_keys(symbol)
            for key in candidates:
                for row, security_id in index.get(key, []):
                    if self._row_matches_exchange(row, exchange):
                        return str(security_id)
            raise BrokerError(
                f"Cannot resolve IndMoney security_id for {symbol}/{exchange} from instruments source {source!r}"
            ) from exc

    @staticmethod
    def _split_symbol(raw: str) -> tuple[str, str]:
        """Split an ``"EXCHANGE:SYMBOL"`` quote key (defaults exchange to NSE)."""
        if ":" in raw:
            exchange, name = raw.split(":", 1)
            return exchange.strip().upper(), name.strip()
        return "NSE", raw.strip()

    async def _segment_for_order(self, session: Session, order_id: str) -> str:
        """Resolve the EQUITY/DERIVATIVE segment for an order id.

        ``DRV-``/``EQ-`` prefixes are decisive; otherwise (``GTT-`` and unknown
        prefixes) the live order book is consulted. Falls back to EQUITY when
        the order cannot be found (the broker then rejects with its own error).
        """
        seg = M.segment_from_order_id(order_id)
        if seg is not None:
            return seg
        rows = await self._request(session, "GET", "/order-book") or []
        for row in rows:
            if isinstance(row, dict) and str(row.get("id", "")) == str(order_id):
                found = str(row.get("segment", "")).upper()
                if found in ("EQUITY", "DERIVATIVE"):
                    return found
        return "EQUITY"

    # ---------- auth lifecycle ----------

    async def login(self, credentials: dict) -> Session:
        access_token = str(credentials.get("access_token") or "")
        if not access_token:
            raise BrokerError("IndMoney login requires an access_token (generated on the INDstocks dashboard)")
        transport = None if self._http_factory is not None else _build_httpx_transport()
        return Session(
            access_token=access_token,
            # Dashboard tokens reset at the broker's daily 06:00 IST cycle — no refresh endpoint.
            expires_at=next_6am_ist_timestamp(),
            account_id=str(credentials.get("user_id") or ""),
            adapter_id="indmoney",
            extra={"transport": transport},
        )

    async def refresh(self, session: Session) -> Session:
        # IndMoney tokens cannot be refreshed programmatically — a new dashboard
        # token + login() is required at expiry. Nothing to do until then.
        return session

    async def logout(self, session: Session) -> None:
        # No revoke endpoint is documented (revocation is dashboard-side); drop
        # the local transport so the session can no longer be used. Idempotent.
        session.extra.pop("transport", None)
        return

    # ---------- trading: writes (safety-critical; router-only) ----------

    async def place_order(self, session: Session, order: Order, *, _router_token: object | None = None) -> str:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        security_id = await self._resolve_security_for_session(session, order.symbol, str(order.exchange))
        algo_id = session.algo_id or None
        # Dispatch on order variety. Every variety travels this SAME gated method
        # (the router token is already required above and the variety + leg
        # prices are part of the SafetyContext-hashed order), so a GTT/OCO/
        # TRIGGER smart order is gated identically to a regular one.
        variety = str(getattr(order, "variety", "regular")).lower()
        if variety in ("regular", "", "amo"):
            payload = M.to_place_order_payload(order, security_id, algo_id=algo_id)
            resp = await self._request(session, "POST", "/order", json_body=payload)
            self.last_child_order_id = None
            order_id = M.extract_order_id({"data": resp})
            session.extra.setdefault("indmoney_order_families", {})[order_id] = "regular"
            return order_id
        if variety in M.SMART_VARIETIES:
            payload = M.to_smart_order_payload(order, security_id, algo_id=algo_id)
            resp = await self._request(session, "POST", "/smart/order", json_body=payload)
            parent, child = M.extract_smart_order_ids({"data": resp})
            self.last_child_order_id = child
            families = session.extra.setdefault("indmoney_order_families", {})
            families[parent] = "smart"
            if child:
                families[child] = "smart"
            return parent
        raise BrokerError(f"IndMoney does not support order variety {variety!r}")

    async def modify_order(
        self, session: Session, order_id: str, changes: dict, *, _router_token: object | None = None
    ) -> None:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        variety = str(changes.get("variety", "")).lower()
        smart = variety in M.SMART_VARIETIES or variety == "smart" or M.is_smart_order_id(order_id)
        segment = M.resolve_segment(order_id, changes) or await self._segment_for_order(session, order_id)
        if smart:
            payload = M.to_smart_modify_payload(order_id, changes, segment=segment)
            await self._request(session, "POST", "/smart/order/modify", json_body=payload)
        else:
            payload = M.to_modify_order_payload(order_id, changes, segment=segment)
            await self._request(session, "POST", "/order/modify", json_body=payload)

    async def cancel_order(
        self,
        session: Session,
        order_id: str,
        *,
        segment: str | None = None,
        _router_token: object | None = None,
    ) -> None:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        resolved_segment = (
            await self._segment_for_order(session, order_id)
            if segment is None
            else self._emergency_identifier(segment, label="order segment").upper()
        )
        if resolved_segment not in {"EQUITY", "DERIVATIVE"}:
            raise BrokerError("INDmoney cancel segment is unsupported")
        payload = M.to_cancel_payload(order_id, resolved_segment)
        # GTT-prefixed ids identify the smart-order family. EQ/DRV smart parents
        # are deliberately routed through cancel_smart_order only when their
        # family is known; this generic method cannot infer that from the id.
        path = "/smart/order/cancel" if M.is_smart_order_id(order_id) else "/order/cancel"
        await self._emergency_request(
            session,
            "POST",
            path,
            json_body=payload,
            require_data=False,
        )

    async def cancel_smart_order(
        self, session: Session, order_id: str, *, segment: str | None = None, _router_token: object | None = None
    ) -> None:
        """Cancel via ``POST /smart/order/cancel`` explicitly (a gated write).

        ``cancel_order`` auto-routes ``GTT-`` ids here; this method forces the
        smart path for ``EQ-``/``DRV-`` parents of smart orders.
        """
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        seg = (
            await self._segment_for_order(session, order_id)
            if segment is None
            else self._emergency_identifier(segment, label="order segment").upper()
        )
        if seg not in {"EQUITY", "DERIVATIVE"}:
            raise BrokerError("INDmoney smart-cancel segment is unsupported")
        await self._emergency_request(
            session,
            "POST",
            "/smart/order/cancel",
            json_body=M.to_cancel_payload(order_id, seg),
            require_data=False,
        )

    # ---------- authoritative emergency planning (read, then gated exact writes) ----------

    @staticmethod
    def _emergency_identifier(value: Any, *, label: str) -> str:
        identifier = str(value or "")
        if (
            not identifier
            or identifier != identifier.strip()
            or not identifier.isprintable()
            or any(character.isspace() for character in identifier)
        ):
            raise BrokerError(f"INDmoney emergency {label} is not canonical")
        return identifier

    @staticmethod
    def _emergency_label(value: Any, *, label: str) -> str:
        text = str(value or "")
        if not text or text != text.strip() or not text.isprintable():
            raise BrokerError(f"INDmoney emergency {label} is not canonical")
        return text

    @staticmethod
    def _emergency_integer(value: Any, *, label: str) -> int:
        try:
            number = Decimal(str(value).strip())
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise BrokerError(f"INDmoney emergency {label} is invalid") from exc
        if not number.is_finite() or number != number.to_integral_value():
            raise BrokerError(f"INDmoney emergency {label} is invalid")
        return int(number)

    @staticmethod
    def _emergency_position_key(position: dict[str, Any]) -> tuple[str, str, str]:
        return position["security_id"], position["exchange"], position["product"]

    @classmethod
    def _emergency_exit_tag(cls, position: dict[str, Any], *, quantity: int | None = None) -> str:
        signed_quantity = (
            cls._emergency_integer(position.get("quantity"), label="position quantity")
            if quantity is None
            else quantity
        )
        if signed_quantity == 0:
            raise BrokerError("INDmoney emergency position is flat")
        identity = "|".join(
            (
                cls._emergency_identifier(position.get("security_id"), label="security id"),
                cls._emergency_label(position.get("symbol"), label="position symbol"),
                cls._emergency_identifier(position.get("exchange"), label="position exchange").upper(),
                cls._emergency_identifier(position.get("product"), label="position product").upper(),
                str(signed_quantity),
            )
        )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        return f"{_EMERGENCY_EXIT_TAG_PREFIX}{digest}"

    @classmethod
    def _emergency_is_smart_order(
        cls,
        row: dict[str, Any],
        *,
        active: bool,
        known_family: str | None,
    ) -> bool:
        if M.is_smart_order_id(str(row.get("orderid") or "")):
            if known_family == "regular":
                raise BrokerError("INDmoney order-family evidence conflicts with a GTT order id")
            return True
        order_type = str(row.get("pricetype") or "").strip().upper()
        if order_type in {"GTT", "OCO", "TRIGGER"}:
            if known_family == "regular":
                raise BrokerError("INDmoney order-family evidence conflicts with the broker order type")
            return True
        has_smart_leg = False
        for field in ("sl_trigger_price", "tgt_trigger_price"):
            raw_value = row.get(field, "")
            if raw_value in (None, ""):
                continue
            try:
                value = Decimal(str(raw_value).strip())
            except (InvalidOperation, ValueError, TypeError) as exc:
                raise BrokerError(f"INDmoney emergency {field} is invalid") from exc
            if not value.is_finite() or value < 0:
                raise BrokerError(f"INDmoney emergency {field} is invalid")
            has_smart_leg = has_smart_leg or value > 0
        if has_smart_leg:
            if known_family == "regular":
                raise BrokerError("INDmoney order-family evidence conflicts with smart-order legs")
            return True
        if known_family == "smart":
            return True
        if known_family == "regular":
            return False
        if active and order_type not in {"LIMIT", "MARKET"}:
            raise BrokerError("INDmoney active order type does not identify its cancellation family")
        if active:
            raise BrokerError(
                "INDmoney active EQ/DRV MARKET/LIMIT order has no authoritative regular/smart family evidence"
            )
        return False

    async def _emergency_order_rows(self, session: Session) -> tuple[dict[str, Any], ...]:
        raw_rows = await self._emergency_request(session, "GET", "/order-book")
        if not isinstance(raw_rows, list):
            raise BrokerError("INDmoney emergency order book is not a list")
        rows: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        known_families = session.extra.get("indmoney_order_families")
        if not isinstance(known_families, dict):
            known_families = {}
        for raw in raw_rows:
            if not isinstance(raw, dict):
                raise BrokerError("INDmoney emergency order book contains a non-object row")
            row = M.from_indmoney_order(raw)
            order_id = self._emergency_identifier(row.get("orderid"), label="order id")
            if order_id in seen_ids:
                raise BrokerError("INDmoney emergency order book contains a duplicate order id")
            seen_ids.add(order_id)
            segment = self._emergency_identifier(raw.get("segment"), label="order segment").upper()
            if segment not in {"EQUITY", "DERIVATIVE"}:
                raise BrokerError("INDmoney emergency order segment is unsupported")
            exchange = self._emergency_identifier(row.get("exchange"), label="order exchange").upper()
            product = self._emergency_identifier(row.get("product"), label="order product").upper()
            raw_status = raw.get("status")
            if not isinstance(raw_status, str) or not raw_status.strip():
                raise BrokerError("INDmoney emergency order status is missing or malformed")
            status = raw_status.strip().upper()
            known_family = known_families.get(order_id)
            if known_family not in {None, "regular", "smart"}:
                raise BrokerError("INDmoney local order-family evidence is malformed")
            rows.append(
                {
                    **row,
                    "orderid": order_id,
                    "status": status,
                    "segment": segment,
                    "exchange": exchange,
                    "product": product,
                    "_emergency_smart": self._emergency_is_smart_order(
                        row,
                        active=status not in _EMERGENCY_TERMINAL_ORDER_STATUSES,
                        known_family=known_family,
                    ),
                }
            )
        return tuple(rows)

    async def _emergency_positions(self, session: Session) -> tuple[dict[str, Any], ...]:
        positions: dict[tuple[str, str, str], dict[str, Any]] = {}
        for segment, broker_product, canonical_product in _EMERGENCY_POSITION_SCOPES:
            data = await self._emergency_request(
                session,
                "GET",
                "/portfolio/positions",
                params={"segment": segment, "product": broker_product},
            )
            if not isinstance(data, dict):
                raise BrokerError("INDmoney emergency position book is not an object")
            net_rows = data.get("net_positions")
            day_rows = data.get("day_positions")
            if not isinstance(net_rows, list) or not isinstance(day_rows, list):
                raise BrokerError("INDmoney emergency position book is incomplete")
            if any(not isinstance(row, dict) for row in day_rows):
                raise BrokerError("INDmoney emergency day-position book contains a non-object row")
            if day_rows:
                raise BrokerError(
                    "INDmoney emergency day-position book cannot be reconciled with net positions"
                )
            for raw in net_rows:
                if not isinstance(raw, dict):
                    raise BrokerError("INDmoney emergency position book contains a non-object row")
                quantity = self._emergency_integer(raw.get("net_quantity"), label="position quantity")
                raw_position_type = raw.get("position_type")
                if not isinstance(raw_position_type, str) or not raw_position_type.strip():
                    raise BrokerError("INDmoney emergency position type is missing or malformed")
                position_type = raw_position_type.strip().lower()
                if quantity == 0:
                    continue
                if position_type != "open":
                    raise BrokerError("INDmoney reports a non-open position with non-zero quantity")
                mapped = M.from_indmoney_position(raw, product=canonical_product)
                security_id = self._emergency_identifier(raw.get("security_id"), label="security id")
                symbol = self._emergency_label(mapped.get("symbol"), label="position symbol")
                exchange = self._emergency_identifier(mapped.get("exchange"), label="position exchange").upper()
                product = self._emergency_identifier(mapped.get("product"), label="position product").upper()
                expected_exchanges = {"derivative": {"NFO", "BFO"}, "equity": {"NSE", "BSE"}}[segment]
                if exchange not in expected_exchanges or product != canonical_product:
                    raise BrokerError("INDmoney emergency position scope is inconsistent")
                position = {
                    **mapped,
                    "security_id": security_id,
                    "symbol": symbol,
                    "exchange": exchange,
                    "product": product,
                    "quantity": str(quantity),
                }
                key = self._emergency_position_key(position)
                if key in positions:
                    raise BrokerError("INDmoney emergency position book contains a duplicate identity")
                positions[key] = position
        ordered = tuple(positions[key] for key in sorted(positions))
        derivative_positions = tuple(
            position for position in ordered if position["exchange"] in {"NFO", "BFO"}
        )
        if derivative_positions:
            instruments = await self.instruments(session, "fno")
            for position in derivative_positions:
                candidates = [
                    row
                    for row in instruments
                    if self._row_value(row, {"SECURITY_ID", "SECURITYID", "INSTRUMENT_TOKEN", "TOKEN"})
                    == position["security_id"]
                    and self._row_matches_exchange(row, position["exchange"])
                ]
                if len(candidates) != 1:
                    raise BrokerError("INDmoney emergency derivative lot identity is unavailable or ambiguous")
                lot_units = self._emergency_integer(
                    self._row_value(candidates[0], {"LOT_UNITS", "LOT_SIZE", "LOTSIZE"}),
                    label="derivative lot units",
                )
                quantity = abs(self._emergency_integer(position["quantity"], label="position quantity"))
                if lot_units <= 0 or quantity % lot_units:
                    raise BrokerError("INDmoney emergency derivative quantity is not a whole lot")
        return ordered

    @staticmethod
    def _emergency_order_matches_position(order: dict[str, Any], position: dict[str, Any]) -> bool:
        return (
            str(order.get("security_id") or ""),
            str(order.get("exchange") or "").upper(),
            str(order.get("product") or "").upper(),
        ) == (
            str(position.get("security_id") or ""),
            str(position.get("exchange") or "").upper(),
            str(position.get("product") or "").upper(),
        )

    @classmethod
    def _emergency_active_exit_state(
        cls,
        order: dict[str, Any],
        position: dict[str, Any],
        *,
        protected_exit_tags: frozenset[str],
    ) -> str:
        if not cls._emergency_order_matches_position(order, position):
            return "unrelated"
        try:
            current_quantity = cls._emergency_integer(position.get("quantity"), label="position quantity")
            requested_quantity = cls._emergency_integer(order.get("quantity"), label="exit requested quantity")
            filled_quantity = cls._emergency_integer(order.get("filled_quantity"), label="exit filled quantity")
        except BrokerError:
            return "conflicting"
        action = str(order.get("action") or "").strip().upper()
        expected_action = "SELL" if current_quantity > 0 else "BUY"
        if action != expected_action or requested_quantity <= 0 or filled_quantity < 0:
            return "conflicting"
        pending_quantity = requested_quantity - filled_quantity
        if pending_quantity <= 0:
            return "conflicting"
        original_quantity = (
            current_quantity + filled_quantity
            if action == "SELL"
            else current_quantity - filled_quantity
        )
        if original_quantity == 0 or requested_quantity != abs(original_quantity):
            return "conflicting"
        tag = cls._emergency_exit_tag(position, quantity=original_quantity)
        if tag not in protected_exit_tags:
            return "conflicting"
        return "exact" if pending_quantity == abs(current_quantity) else "conflicting"

    @classmethod
    def _emergency_completed_exit_signature(
        cls,
        order: dict[str, Any],
    ) -> tuple[tuple[str, str, str], str, int]:
        """Return the exact identity of a completed protected exit or fail closed."""
        key = (
            cls._emergency_identifier(order.get("security_id"), label="exit security id"),
            cls._emergency_identifier(order.get("exchange"), label="exit exchange").upper(),
            cls._emergency_identifier(order.get("product"), label="exit product").upper(),
        )
        action = str(order.get("action") or "").strip().upper()
        if action not in {"BUY", "SELL"}:
            raise BrokerError("INDmoney completed emergency exit action is malformed")
        requested_quantity = cls._emergency_integer(
            order.get("quantity"),
            label="exit requested quantity",
        )
        filled_quantity = cls._emergency_integer(
            order.get("filled_quantity"),
            label="exit filled quantity",
        )
        if requested_quantity <= 0 or filled_quantity != requested_quantity:
            raise BrokerError("INDmoney completed emergency exit quantity is malformed")
        return key, action, requested_quantity

    @staticmethod
    def _emergency_cancel_write(row: dict[str, Any], *, parent_verb: str) -> EmergencyBrokerWrite:
        verb = "cancel_smart_order" if row.get("_emergency_smart") is True else "cancel_order"
        return EmergencyBrokerWrite(
            parent_verb=parent_verb,
            verb=verb,
            payload={
                "_op": verb,
                "order_id": str(row["orderid"]),
                "segment": str(row["segment"]),
            },
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
        """Derive at most ten exact writes from broker-authoritative account state."""
        requested = frozenset(policy.verbs)
        orders = await self._emergency_order_rows(session)
        positions = await self._emergency_positions(session) if "exit_all_positions" in requested else ()
        active_orders = tuple(
            row for row in orders if row["status"] not in _EMERGENCY_TERMINAL_ORDER_STATUSES
        )
        known_order_ids = frozenset(str(row["orderid"]) for row in orders)
        protected_cancel_rows = tuple(
            row for row in active_orders if str(row["orderid"]) in protected_order_ids
        )
        protected_exit_rows = tuple(
            row for row in active_orders if str(row["orderid"]) in protected_exit_order_ids
        )
        cancellable = tuple(
            row
            for row in active_orders
            if str(row["orderid"]) not in protected_order_ids | protected_exit_order_ids
        )

        positions_by_key = {self._emergency_position_key(position): position for position in positions}
        blocked_position_keys: set[tuple[str, str, str]] = set()
        conflicting_exit_rows: list[dict[str, Any]] = []
        unreconciled_completed_exit = False
        for order in protected_exit_rows:
            matched = False
            for key, position in positions_by_key.items():
                state = self._emergency_active_exit_state(
                    order,
                    position,
                    protected_exit_tags=protected_exit_tags,
                )
                if state == "unrelated":
                    continue
                matched = True
                if state == "exact":
                    blocked_position_keys.add(key)
                else:
                    conflicting_exit_rows.append(order)
                break
            if not matched:
                conflicting_exit_rows.append(order)

        for order in orders:
            if (
                str(order["orderid"]) not in protected_exit_order_ids
                or order["status"] not in _EMERGENCY_SUCCESSFUL_ORDER_STATUSES
            ):
                continue
            order_key, action, requested_quantity = self._emergency_completed_exit_signature(order)
            position = positions_by_key.get(order_key)
            if position is None:
                unreconciled_completed_exit = bool(positions)
                continue
            current_quantity = self._emergency_integer(position["quantity"], label="position quantity")
            expected_action = "SELL" if current_quantity > 0 else "BUY"
            if action != expected_action or requested_quantity != abs(current_quantity):
                unreconciled_completed_exit = True
                continue
            blocked_position_keys.add(order_key)

        missing_protected_exit_ids = protected_exit_order_ids - known_order_ids
        pending: set[str] = set()
        if "cancel_all_orders" in requested and (cancellable or protected_cancel_rows):
            pending.add("cancel_all_orders")
        if "exit_all_positions" in requested and (
            positions or protected_exit_rows or (missing_protected_exit_ids and positions)
        ):
            pending.add("exit_all_positions")
        if not pending:
            return EmergencyReductionPlan(writes=(), pending_verbs=frozenset())
        if unidentified_exit_inflight:
            return EmergencyReductionPlan(writes=(), pending_verbs=frozenset(pending))

        if "cancel_all_orders" in pending:
            writes = tuple(
                self._emergency_cancel_write(row, parent_verb="cancel_all_orders")
                for row in cancellable[:_EMERGENCY_BATCH_LIMIT]
            )
            return EmergencyReductionPlan(writes=writes, pending_verbs=frozenset(pending))

        if "exit_all_positions" in pending:
            if (missing_protected_exit_ids and positions) or unreconciled_completed_exit:
                return EmergencyReductionPlan(writes=(), pending_verbs=frozenset(pending))
            if conflicting_exit_rows:
                writes = tuple(
                    self._emergency_cancel_write(row, parent_verb="exit_all_positions")
                    for row in conflicting_exit_rows[:_EMERGENCY_BATCH_LIMIT]
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
                        "security_id": str(position["security_id"]),
                        "symbol": str(position["symbol"]),
                        "exchange": str(position["exchange"]),
                        "product": str(position["product"]),
                        "quantity": str(abs(self._emergency_integer(position["quantity"], label="position quantity"))),
                        "expected_position_quantity": str(position["quantity"]),
                        "action": "SELL"
                        if self._emergency_integer(position["quantity"], label="position quantity") > 0
                        else "BUY",
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
        """Place one exact opposite-side MARKET order after final position readback."""
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        security_id = self._emergency_identifier(payload.get("security_id"), label="security id")
        symbol = self._emergency_label(payload.get("symbol"), label="position symbol")
        exchange = self._emergency_identifier(payload.get("exchange"), label="position exchange").upper()
        product = self._emergency_identifier(payload.get("product"), label="position product").upper()
        expected_quantity = self._emergency_integer(
            payload.get("expected_position_quantity"), label="expected position quantity"
        )
        reducing_quantity = self._emergency_integer(payload.get("quantity"), label="reducing quantity")
        if expected_quantity == 0 or reducing_quantity <= 0 or reducing_quantity != abs(expected_quantity):
            raise BrokerError("INDmoney reducing position quantity is inconsistent")
        expected_action = "SELL" if expected_quantity > 0 else "BUY"
        if (
            str(payload.get("action") or "").strip().upper() != expected_action
            or str(payload.get("pricetype") or "").strip().upper() != "MARKET"
            or str(payload.get("variety") or "").strip().lower() != "regular"
            or self._emergency_integer(payload.get("price", "0"), label="reducing price") != 0
            or self._emergency_integer(payload.get("trigger_price", "0"), label="reducing trigger price") != 0
        ):
            raise BrokerError("INDmoney reducing write is not an exact regular MARKET order")

        current_positions = await self._emergency_positions(session)
        current = next(
            (
                position
                for position in current_positions
                if self._emergency_position_key(position) == (security_id, exchange, product)
                and str(position["symbol"]) == symbol
            ),
            None,
        )
        if current is None:
            raise BrokerError("INDmoney position disappeared before the reducing write")
        current_quantity = self._emergency_integer(current["quantity"], label="position quantity")
        if current_quantity != expected_quantity:
            raise BrokerError("INDmoney position changed before the reducing write")
        tag = str(payload.get("emergency_tag") or "")
        if not tag.startswith(_EMERGENCY_EXIT_TAG_PREFIX) or tag != self._emergency_exit_tag(current):
            raise BrokerError("INDmoney reducing position episode changed before dispatch")

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
        broker_payload = M.to_place_order_payload(order, security_id, algo_id=session.algo_id or None)
        response = await self._emergency_request(
            session,
            "POST",
            "/order",
            json_body=broker_payload,
        )
        order_id = M.extract_order_id({"data": response})
        session.extra.setdefault("indmoney_order_families", {})[order_id] = "regular"
        return order_id

    # ---------- trading: reads (no SafetyContext required) ----------

    async def order_book(self, session: Session) -> list[Order]:
        rows = await self._request(session, "GET", "/order-book") or []
        return [M.from_indmoney_order(r) for r in rows if isinstance(r, dict)]  # type: ignore[misc]

    async def order_details(self, session: Session, order_id: str, *, segment: str | None = None) -> dict:
        """Full details of a single order (``GET /order`` with a JSON body) — a read."""
        seg = segment or await self._segment_for_order(session, order_id)
        data = await self._request(
            session, "GET", "/order", json_body={"order_id": str(order_id), "segment": seg}
        )
        return M.from_indmoney_order(data if isinstance(data, dict) else {})

    async def order_trades(self, session: Session, order_id: str) -> list[dict]:
        """Executed trades for one order (``GET /trades/{order_id}``) — a read."""
        rows = await self._request(session, "GET", f"/trades/{order_id}") or []
        return [M.from_indmoney_trade(r) for r in rows if isinstance(r, dict)]

    async def trade_book_segment(self, session: Session, segment: str) -> list[dict]:
        """Day fills for one segment (``GET /trade-book?segment=``) — a read."""
        seg = str(segment).upper()
        rows = await self._request(session, "GET", "/trade-book", params={"segment": seg}) or []
        return [M.from_indmoney_tradebook_row(r) for r in rows if isinstance(r, dict)]

    async def trade_book(self, session: Session) -> list[Trade]:
        # The endpoint is segment-scoped; the contract wants ALL fills for the
        # day, so both documented segments are aggregated.
        out: list[dict] = []
        for segment in ("EQUITY", "DERIVATIVE"):
            out.extend(await self.trade_book_segment(session, segment))
        return out  # type: ignore[return-value]

    async def positions_segment(self, session: Session, segment: str, product: str) -> dict:
        """Positions for one documented segment/product combo — a read.

        Returns the raw ``{net_positions, day_positions}`` split with rows
        normalised, preserving the broker's day/net distinction.
        """
        params = {"segment": str(segment).lower(), "product": str(product).lower()}
        data = await self._request(session, "GET", "/portfolio/positions", params=params) or {}
        prod = str(product).upper()
        # Map the IndMoney product spelling back to canonical for row tagging.
        canonical = {"MARGIN": "NRML", "INTRADAY": "MIS", "CNC": "CNC"}.get(prod, prod)
        return {
            "net_positions": [
                M.from_indmoney_position(r, product=canonical)
                for r in (data.get("net_positions") or [])
                if isinstance(r, dict)
            ],
            "day_positions": [
                M.from_indmoney_position(r, product=canonical)
                for r in (data.get("day_positions") or [])
                if isinstance(r, dict)
            ],
        }

    async def positions(self, session: Session) -> list[Position]:
        # The endpoint is (segment, product)-scoped; the contract wants every
        # open position, so all four documented combos are aggregated and
        # de-duplicated on (symbol, product).
        combos = (("derivative", "margin"), ("derivative", "intraday"), ("equity", "cnc"), ("equity", "intraday"))
        seen: set[tuple[str, str]] = set()
        out: list[dict] = []
        for segment, product in combos:
            split = await self.positions_segment(session, segment, product)
            for row in split["net_positions"]:
                key = (row.get("symbol", ""), row.get("product", ""))
                if key not in seen:
                    seen.add(key)
                    out.append(row)
        return out  # type: ignore[return-value]

    async def holdings(self, session: Session) -> list[dict]:
        rows = await self._request(session, "GET", "/portfolio/holdings") or []
        return [M.from_indmoney_holding(r) for r in rows if isinstance(r, dict)]

    async def funds(self, session: Session) -> dict:
        data = await self._request(session, "GET", "/funds")
        return M.from_indmoney_funds({"data": data})

    async def profile(self, session: Session) -> dict:
        """User profile (``GET /user/profile``) — also a token-validity probe."""
        data = await self._request(session, "GET", "/user/profile")
        return data if isinstance(data, dict) else {}

    # ---------- pre-trade info (reads) ----------

    async def margin_calculator(self, session: Session, order: Order) -> dict:
        """Pre-trade margin + charges estimate (``GET /margin``).

        A read-only estimate — it places nothing, so it needs no gate.
        """
        security_id = await self._resolve_security_for_session(session, order.symbol, str(order.exchange))
        body = M.to_margin_params(order, security_id)
        data = await self._request(session, "GET", "/margin", json_body=body)
        return M.from_indmoney_margin({"data": data})

    async def instruments_csv(self, session: Session, source: str = "equity") -> str:
        """Raw instruments-master CSV (``GET /market/instruments?source=``)."""
        payload = await self._request(session, "GET", "/market/instruments", params={"source": source}, raw=True)
        return payload if isinstance(payload, str) else str(payload)

    async def instruments(self, session: Session, source: str = "equity") -> list[dict]:
        """Parsed instruments master for ``source`` (``equity``/``fno``/``index``)."""
        return M.parse_instruments_csv(await self.instruments_csv(session, source))

    async def smart_orders(self, session: Session) -> list[dict]:
        """Smart (GTT-family) rows from the order book — a read.

        There is no dedicated GTT-list endpoint; smart orders surface in the
        order book with ``GTT-`` ids and/or populated SL/target leg prices.
        """
        rows = await self.order_book(session)
        return [
            r
            for r in rows  # type: ignore[union-attr]
            if M.is_smart_order_id(r.get("orderid", ""))
            or any(M.parse_indian_number(r.get(k, "")) > 0 for k in ("sl_trigger_price", "tgt_trigger_price"))
        ]

    # ---------- market data: rest ----------

    async def quotes(self, session: Session, symbols: list[str]) -> list[Quote]:
        from flinttrade_core.models import Quote  # noqa: PLC0415

        resolved: list[tuple[str, str, str]] = []  # (symbol, exchange, scrip)
        for raw in symbols:
            exchange, name = self._split_symbol(raw)
            scrip = M.to_scrip_code(exchange, await self._resolve_security_for_session(session, name, exchange))
            resolved.append((name, exchange, scrip))
        data = await self._request(
            session, "GET", "/market/quotes/full",
            params={"scrip-codes": ",".join(s for _, _, s in resolved)},
        ) or {}
        out: list[Quote] = []
        for name, exchange, scrip in resolved:
            rec = data.get(scrip)
            if isinstance(rec, dict):
                out.append(Quote(**M.from_indmoney_quote(name, exchange, rec)))
        return out

    async def ltp(self, session: Session, symbols: list[str]) -> dict[str, float]:
        """Last traded prices (``GET /market/quotes/ltp``) keyed by ``EXCHANGE:SYMBOL``."""
        resolved: list[tuple[str, str]] = []  # (key, scrip)
        for raw in symbols:
            exchange, name = self._split_symbol(raw)
            scrip = M.to_scrip_code(exchange, await self._resolve_security_for_session(session, name, exchange))
            resolved.append((f"{exchange}:{name}", scrip))
        data = await self._request(
            session, "GET", "/market/quotes/ltp",
            params={"scrip-codes": ",".join(s for _, s in resolved)},
        ) or {}
        return {
            key: float((data.get(scrip) or {}).get("live_price", 0) or 0)
            for key, scrip in resolved
            if isinstance(data.get(scrip), dict)
        }

    async def market_depth(self, session: Session, symbols: list[str]) -> dict[str, dict]:
        """Five-level market depth (``GET /market/quotes/mkt``) keyed by ``EXCHANGE:SYMBOL``."""
        resolved: list[tuple[str, str]] = []
        for raw in symbols:
            exchange, name = self._split_symbol(raw)
            scrip = M.to_scrip_code(exchange, await self._resolve_security_for_session(session, name, exchange))
            resolved.append((f"{exchange}:{name}", scrip))
        data = await self._request(
            session, "GET", "/market/quotes/mkt",
            params={"scrip-codes": ",".join(s for _, s in resolved)},
        ) or {}
        return {
            key: M.from_indmoney_depth(data.get(scrip) or {})
            for key, scrip in resolved
            if isinstance(data.get(scrip), dict)
        }

    async def historical(self, session: Session, req: dict) -> Candles:
        from flinttrade_core.models import OHLCV, Candles  # noqa: PLC0415

        symbol = str(req.get("symbol", ""))
        exchange = str(req.get("exchange", "NSE"))
        interval = str(req.get("interval", req.get("timeframe", "1m")))
        start = req.get("start_time") or req.get("from_date") or req.get("start") or req.get("start_date")
        end = req.get("end_time") or req.get("to_date") or req.get("end") or req.get("end_date")
        if start is None or end is None:
            raise BrokerError("IndMoney historical requires start_time and end_time")
        label, max_days = M.interval_to_indmoney(interval)
        start_ms, end_ms = M.to_epoch_ms(start), M.to_epoch_ms(end)
        M.validate_history_range(start_ms, end_ms, max_days)
        scrip = M.to_scrip_code(exchange, await self._resolve_security_for_session(session, symbol, exchange))
        data = await self._request(
            session, "GET", f"/market/historical/{label}",
            params={"scrip-codes": scrip, "start_time": start_ms, "end_time": end_ms},
        )
        cd = M.to_candles_dict(symbol, exchange, interval, {"data": data})
        return Candles(
            symbol=cd["symbol"],
            exchange=cd["exchange"],
            interval=cd["interval"],
            bars=[OHLCV(**b) for b in cd["bars"]],
        )

    # ---------- utility family (documented "Coming Soon" broker-side) ----------

    async def option_chain(self, session: Session, req: dict) -> OptionChain:
        raise NotImplementedError(_COMING_SOON.format("option-chain"))

    async def option_chain_symbols(self, session: Session, token: str) -> list[str]:
        """Expiry dates for an option underlying (``GET /option-chain-symbols``)."""
        raise NotImplementedError(_COMING_SOON.format("option-chain-symbols (expiry list)"))

    async def greeks(self, session: Session, tokens: list[str]) -> list[dict]:
        """Option Greeks for instrument tokens (``POST /greeks``)."""
        raise NotImplementedError(_COMING_SOON.format("greeks"))

    # ---------- market data: streaming ----------

    async def subscribe(self, session: Session, symbols: list[str], mode: str = "FULL") -> None:
        # Resolve each symbol to its instrument token and remember it so decoded
        # JSON ticks (which carry only the token) route back to symbol names.
        # The actual subscribe message (built by M.subscribe_message) is sent by
        # whatever owns the live socket — the injected feed factory.
        for raw in symbols:
            exchange, name = self._split_symbol(raw)
            security_id = await self._resolve_security_for_session(session, name, exchange)
            M.ws_instrument(exchange, security_id)  # validates the segment early
            self._feed_map[str(security_id)] = (name, exchange)
            self._feed_modes[str(security_id)] = mode

    async def unsubscribe(self, session: Session, symbols: list[str]) -> None:
        for raw in symbols:
            exchange, name = self._split_symbol(raw)
            try:
                security_id = await self._resolve_security_for_session(session, name, exchange)
            except BrokerError:
                continue
            self._feed_map.pop(str(security_id), None)
            self._feed_modes.pop(str(security_id), None)

    def stream(self, session: Session) -> AsyncIterator[Any]:
        return self._stream_impl(session)

    async def _stream_impl(self, session: Session) -> AsyncIterator[Any]:
        from flinttrade_core.models import TickEvent  # noqa: PLC0415

        if self._feed_factory is None:
            # Live: the price-feed WebSocket needs a WS client + the token. The
            # decode path (decode_price_frame) and the subscribe-message builder
            # are implemented and tested; the live socket is provided by
            # injecting a feed_factory (no WS client dependency is bundled).
            raise NotImplementedError(
                "IndMoney live price feed needs an injected feed_factory "
                f"(connect to {M.PRICE_FEED_WS_URL} and yield raw frames)"
            )
        async for frame in self._feed_factory(session):
            tick = M.decode_price_frame(frame)
            if tick is None:
                continue  # heartbeat / control frame
            symbol, exchange = self._feed_map.get(tick["security_id"], ("", ""))
            yield TickEvent(
                symbol=symbol,
                exchange=exchange,
                ltp=tick.get("ltp", 0.0),
                volume=int(tick.get("volume", 0)),
                timestamp=str(tick.get("timestamp", "")),
            )

    async def order_update_stream(self, session: Session) -> AsyncIterator[dict]:
        """Stream normalised order updates from the order-updates WebSocket.

        A read-only feed (placement/execution/cancellation notifications) — it
        cannot place anything, so it needs no gate. The live socket is an
        injected ``order_feed_factory``; heartbeats are skipped.
        """
        if self._order_feed_factory is None:
            raise NotImplementedError(
                "IndMoney live order-updates feed needs an injected order_feed_factory "
                f"(connect to {M.ORDER_FEED_WS_URL} and yield raw frames)"
            )
        async for frame in self._order_feed_factory(session):
            update = M.decode_order_update(frame)
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
