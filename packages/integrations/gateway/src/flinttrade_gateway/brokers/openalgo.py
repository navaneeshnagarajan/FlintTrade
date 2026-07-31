"""OpenAlgo bridge adapter — routes the selector-bound principal through OpenAlgo.

OpenAlgo already integrates every broker the operator uses (Dhan, Upstox, Kotak
Neo, IndMoney, …), so this single ``BrokerAdapter`` lets the safety-gated
``BrokerRouter`` dispatch to ALL of them via selectors like ``openalgo:dhan``
without per-broker SDK risk — the path the operator already runs and trusts.

It forwards each contract-§5 method to a :class:`~flinttrade_core.openalgo_client.OpenAlgoClient`.
The client is injected (or built per-session for multi-account), so the adapter
never couples to ``Settings`` and is trivially testable. OpenAlgo's REST client
does not expose tick streaming, so those methods raise
:class:`UnsupportedCapabilityError` honestly rather than pretending.

Writes (place/modify/cancel and emergency account sweeps) keep the §8 invariant:
they are reachable only with the router's per-process ``_router_token``; a bare
call raises ``SafetyBypassError`` before any OpenAlgo request is made.
"""

from __future__ import annotations

import hashlib
import logging
import unicodedata
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable

from flinttrade_core.exceptions import (
    APIError,
    BrokerError,
    OpenAlgoAuthError,
    OpenAlgoRateLimitError,
    OrderRejectedByBroker,
    RateLimitError,
    SessionExpired,
    UnsupportedCapabilityError,
)
from flinttrade_core.models import ModifyOrder
from flinttrade_engine.safety import EmergencyBrokerWrite, EmergencyReductionPlan, EmergencyWritePolicy
from flinttrade_gateway.capabilities import (
    AuthModel,
    Capabilities,
    DepthLevels,
    OrderTypes,
    Segments,
    TickProtocol,
)

from ._base import (
    ROUTER_TOKEN as _ROUTER_TOKEN,  # the shared per-process router token (§8.0c)
    BrokerAdapter,
    Session,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flinttrade_core.models import Candles, OptionChain, Order, Position, Quote, Trade
    from flinttrade_core.openalgo_client import OpenAlgoClient
    from flinttrade_gateway.reconciliation import LocalStateSnapshot, ReconciliationReport

logger = logging.getLogger("flinttrade.gateway.brokers.openalgo")

# OpenAlgo's api-key auth is persistent; the underlying broker session is daily,
# but the adapter treats the api-key as the credential (the operator re-links the
# broker in the OpenAlgo UI). Far-future so SafetyContext/Session expiry never
# trips on the bridge itself.
_FAR_FUTURE = 4_102_444_800.0  # 2100-01-01 UTC
_EMERGENCY_BATCH_LIMIT = 10
_EMERGENCY_EXIT_TAG_PREFIX = "FTE-OA-"
_ORDER_BOOK_NUMERIC_FIELDS = frozenset(
    {"quantity", "filled_quantity", "price", "trigger_price", "average_price"}
)
_TERMINAL_ORDER_STATUSES = frozenset(
    {
        "cancelled",
        "canceled",
        "closed",
        "complete",
        "completed",
        "expired",
        "filled",
        "rejected",
        "traded",
    }
)

OPENALGO_CAPABILITIES = Capabilities(
    segments=Segments.NSE_EQ | Segments.BSE_EQ | Segments.NFO | Segments.BFO | Segments.CDS | Segments.MCX,
    order_types=(
        OrderTypes.MARKET
        | OrderTypes.LIMIT
        | OrderTypes.SL
        | OrderTypes.SLM
        | OrderTypes.MIS
        | OrderTypes.CNC
        | OrderTypes.NRML
    ),
    depth_levels=DepthLevels.L5,
    tick_protocol=TickProtocol.OPENALGO_JSON,
    auth_model=AuthModel.API_KEY_PERSISTENT,
    session_lifetime_hours=24.0,
    session_renewal_leeway_seconds=120,
    sandbox=False,
    rate_limit_orders_per_sec=10,
    rate_limit_orders_per_min=250,
    rate_limit_orders_per_hour=1000,
    rate_limit_orders_per_day=7000,
    rate_limit_data_per_sec=5,
    rate_limit_data_per_day=100_000,
    rate_limit_quote_per_sec=1,
    rate_limit_non_trading_per_sec=20,
    order_modifications_per_order=25,
    algo_tag_required=False,
    historical_max_lookback_days_intraday=90,
    historical_max_lookback_days_daily=None,
    historical_max_candles_per_request=5000,
    historical_intraday_intervals_minutes=[1, 5, 15, 30, 60],
    option_chain_supported=True,
    option_chain_greeks_supported=True,
    option_chain_rate_limit_seconds=3,
    # This REST bridge does not expose the OpenAlgo websocket feed — advertise it
    # off so the router never resolves a tick stream to this adapter.
    streaming_supported=False,
    streaming_max_connections_per_user=0,
    streaming_max_symbols_per_connection=0,
    streaming_max_total_symbols=0,
    streaming_heartbeat_seconds=10,
    streaming_disconnect_timeout_seconds=40,
    bracket_order_native=False,
    cover_order_native=False,
    iceberg_native=False,
    # Honesty: this bridge's place_order forwards a plain order to OpenAlgo's
    # /placeorder — there is no GTT/standing-order path here, and order_types
    # above omits GTT. Advertising gtt_native=True would have a `gtt` variety
    # silently placed as a plain order (losing the trigger). Keep it False.
    gtt_native=False,
    modify_qty_supported=True,
    modify_after_partial_fill=False,
)


class OpenAlgoAdapter(BrokerAdapter):
    """Bridge :class:`BrokerAdapter` that forwards to OpenAlgo (contract §5).

    Args:
        default_client: An ``OpenAlgoClient`` used when a session does not select
            a specific one — the common single-instance case.
        client_factory: Optional ``Session -> OpenAlgoClient`` for multi-account
            setups where each OpenAlgo account has its own host/api-key (built
            from ``session.extra``). Takes precedence over ``default_client``.
        local_state_provider: ``session -> LocalStateSnapshot`` supplying the
            FlintTrade-side mirror that ``reconcile`` diffs against. Defaults
            to empty local state when the engine has not wired a provider.
    """

    def __init__(
        self,
        default_client: OpenAlgoClient | None = None,
        *,
        client_factory: Callable[[Session], OpenAlgoClient] | None = None,
        local_state_provider: Callable[[Session], LocalStateSnapshot] | None = None,
    ) -> None:
        self._default_client = default_client
        self._client_factory = client_factory
        self._local_state_provider = local_state_provider

    # ---------- identity + capabilities ----------

    @property
    def broker_id(self) -> str:
        return "openalgo"

    @property
    def capabilities(self) -> Capabilities:
        return OPENALGO_CAPABILITIES

    # ---------- client resolution ----------

    def _client(self, session: Session) -> OpenAlgoClient:
        if self._client_factory is not None:
            return self._client_factory(session)
        if self._default_client is not None:
            return self._default_client
        raise UnsupportedCapabilityError(
            "OpenAlgoAdapter has no client configured — pass default_client or client_factory"
        )

    # ---------- auth lifecycle ----------

    async def login(self, credentials: dict) -> Session:
        """Build a Session from an OpenAlgo api-key (no clock-based expiry)."""
        return Session(
            access_token=str(credentials.get("api_key", "")),
            expires_at=_FAR_FUTURE,
            account_id=str(credentials.get("account_id", "default")),
            adapter_id="openalgo",
            extra={
                k: credentials[k]
                for k in ("host", "ws_port", "strategy")
                if k in credentials
            },
        )

    async def refresh(self, session: Session) -> Session:
        # OpenAlgo api-keys do not expire on a clock; nothing to refresh.
        return session

    async def logout(self, session: Session) -> None:
        # api-key auth has no server-side session to invalidate. Idempotent no-op.
        return None

    # ---------- trading: writes (router-only) ----------

    async def place_order(self, session: Session, order: Order, *, _router_token: object | None = None) -> str:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        # Honesty guard (audit HIGH): this bridge forwards a plain order to
        # OpenAlgo's /placeorder, which fires IMMEDIATELY — it has no resting
        # trigger semantics. A non-regular variety (gtt/forever, bracket, cover,
        # iceberg, conditional) carries a trigger/OCO/validity contract the
        # forward silently drops, so a "working order that rests until the
        # trigger fires" would instead be placed NOW. Refuse honestly rather
        # than downgrade. (capabilities advertises gtt/bracket/cover/iceberg as
        # not native; the route maps UnsupportedCapabilityError to a 501.)
        variety = str(getattr(order, "variety", "") or "").strip().lower()
        if variety not in ("", "regular"):
            raise UnsupportedCapabilityError(
                f"OpenAlgo bridge adapter does not support {variety!r} orders — it forwards a plain "
                "immediate order with no resting trigger. Route forever/GTT, bracket, cover, iceberg "
                "and conditional orders to a native broker adapter (Dhan/Upstox/…)."
            )
        with self._mapped("order placement"):
            resp = await self._client(session).place_order(order)
        return self._order_id_or_raise(resp)

    async def modify_order(
        self, session: Session, order_id: str, changes: dict, *, _router_token: object | None = None
    ) -> None:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        with self._mapped("order modification"):
            modify = ModifyOrder(orderid=order_id, **changes)
            resp = await self._client(session).modify_order(modify)
        self._order_id_or_raise(resp)

    async def cancel_order(
        self, session: Session, order_id: str, *, _router_token: object | None = None
    ) -> None:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        strategy = str(session.extra.get("strategy", "Flint"))
        with self._mapped("order cancellation"):
            resp = await self._client(session).cancel_order(order_id, strategy=strategy)
        self._order_id_or_raise(resp)

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
        """Plan bounded concrete writes from an authoritative account snapshot."""
        requested = frozenset(policy.verbs)
        protected_orders = self._canonical_identifier_set(
            protected_order_ids,
            what="protected order id",
        )
        protected_exit_orders = self._canonical_identifier_set(
            protected_exit_order_ids,
            what="protected exit order id",
        )
        protected_tags = self._canonical_identifier_set(
            protected_exit_tags,
            what="protected exit tag",
        )

        order_rows = await self.order_book(session) if requested else []
        active_orders, known_order_ids = self._active_emergency_orders(order_rows)
        positions = await self.positions(session) if "exit_all_positions" in requested else []
        active_positions = self._active_emergency_positions(positions)

        exit_orders = tuple(
            order
            for order in active_orders
            if (
                order["orderid"] in protected_exit_orders
                or self._order_tags(order).intersection(protected_tags)
                or any(tag.startswith(_EMERGENCY_EXIT_TAG_PREFIX) for tag in self._order_tags(order))
            )
        )
        exit_order_ids = {str(order["orderid"]) for order in exit_orders}
        ordinary_orders = tuple(
            order for order in active_orders if order["orderid"] not in exit_order_ids
        )
        visible_exit_tags = frozenset(
            tag
            for order in active_orders
            for tag in self._order_tags(order)
            if tag.startswith(_EMERGENCY_EXIT_TAG_PREFIX)
        )
        unidentifiable_response_lost_exit = bool(
            active_positions
            and active_orders
            and protected_tags.difference(visible_exit_tags)
        )

        pending: set[str] = set()
        if "cancel_all_orders" in requested and ordinary_orders:
            pending.add("cancel_all_orders")
        missing_protected_exit_ids = protected_exit_orders - known_order_ids
        if "exit_all_positions" in requested and (active_positions or exit_orders):
            pending.add("exit_all_positions")
        if not pending:
            return EmergencyReductionPlan(writes=(), pending_verbs=frozenset())
        if unidentified_exit_inflight:
            return EmergencyReductionPlan(writes=(), pending_verbs=frozenset(pending))

        if "cancel_all_orders" in pending:
            if unidentifiable_response_lost_exit:
                return EmergencyReductionPlan(writes=(), pending_verbs=frozenset(pending))
            cancellable = tuple(
                order
                for order in ordinary_orders
                if order["orderid"] not in protected_orders
            )
            return EmergencyReductionPlan(
                writes=tuple(
                    EmergencyBrokerWrite(
                        parent_verb="cancel_all_orders",
                        verb="cancel_order",
                        payload={"_op": "cancel_order", "order_id": order["orderid"]},
                    )
                    for order in cancellable[:_EMERGENCY_BATCH_LIMIT]
                ),
                pending_verbs=frozenset(pending),
            )

        position_by_key = {
            self._position_key(position): position for position in active_positions
        }
        exact_exit_keys: set[tuple[str, str, str]] = set()
        conflicting_exit_ids: list[str] = []
        exits_by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for order in exit_orders:
            key = self._order_position_key(order)
            position = position_by_key.get(key)
            if position is None or not self._exit_order_exactly_reduces(order, position):
                conflicting_exit_ids.append(str(order["orderid"]))
                continue
            exits_by_key.setdefault(key, []).append(order)
        for key, matching_orders in exits_by_key.items():
            if len(matching_orders) == 1:
                exact_exit_keys.add(key)
            else:
                conflicting_exit_ids.extend(str(order["orderid"]) for order in matching_orders)

        if conflicting_exit_ids:
            protected_conflict_ids = protected_orders | protected_exit_orders | {
                str(order["orderid"])
                for order in exit_orders
                if self._order_tags(order).intersection(protected_tags)
            }
            cancellable_conflicts = tuple(
                order_id for order_id in conflicting_exit_ids if order_id not in protected_conflict_ids
            )
            return EmergencyReductionPlan(
                writes=tuple(
                    EmergencyBrokerWrite(
                        parent_verb="exit_all_positions",
                        verb="cancel_order",
                        payload={"_op": "cancel_order", "order_id": order_id},
                    )
                    for order_id in cancellable_conflicts[:_EMERGENCY_BATCH_LIMIT]
                ),
                pending_verbs=frozenset(pending),
            )

        inactive_protected_exit_ids = protected_exit_orders.intersection(known_order_ids) - exit_order_ids
        if active_positions and (missing_protected_exit_ids or inactive_protected_exit_ids):
            return EmergencyReductionPlan(writes=(), pending_verbs=frozenset(pending))

        positions_requiring_exit = tuple(
            position
            for position in active_positions
            if (
                self._position_key(position) not in exact_exit_keys
                and self._emergency_exit_tag(position) not in protected_tags
            )
        )
        return EmergencyReductionPlan(
            writes=tuple(
                EmergencyBrokerWrite(
                    parent_verb="exit_all_positions",
                    verb="place_reducing_order",
                    payload=self._emergency_reducing_payload(position),
                )
                for position in positions_requiring_exit[:_EMERGENCY_BATCH_LIMIT]
            ),
            pending_verbs=frozenset(pending),
        )

    async def place_reducing_order(
        self,
        session: Session,
        payload: dict[str, Any],
        *,
        _router_token: object | None = None,
    ) -> str | dict[str, Any]:
        """Place one exact opposite-side market order after final readback."""
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        symbol = self._canonical_position_identifier(payload.get("symbol"), what="symbol")
        exchange = self._canonical_position_identifier(
            payload.get("exchange"),
            what="exchange",
            uppercase=True,
        )
        product = self._canonical_position_identifier(
            payload.get("product"),
            what="product",
            uppercase=True,
        )
        expected_quantity = self._position_quantity(payload.get("expected_position_quantity"))
        reducing_quantity = self._position_quantity(payload.get("quantity"))
        expected_action = "SELL" if expected_quantity > 0 else "BUY"
        if expected_quantity == 0 or reducing_quantity != abs(expected_quantity):
            raise BrokerError("OpenAlgo reducing position fingerprint is incomplete", broker_id="openalgo")
        if str(payload.get("action") or "").strip().upper() != expected_action:
            raise BrokerError("OpenAlgo reducing position side is invalid", broker_id="openalgo")
        if (
            str(payload.get("pricetype") or "").strip().upper() != "MARKET"
            or str(payload.get("variety") or "").strip().lower() != "regular"
        ):
            raise BrokerError("OpenAlgo emergency reduction must be a regular market order", broker_id="openalgo")
        tag = self._canonical_identifier(payload.get("emergency_tag"), what="emergency exit tag")

        current_positions = self._active_emergency_positions(await self.positions(session))
        current = next(
            (
                position
                for position in current_positions
                if self._position_key(position) == (symbol, exchange, product)
            ),
            None,
        )
        if current is None:
            return {"order_ids": [], "errors": [], "total": 0, "success": 0}
        current_quantity = int(current["quantity"])
        if current_quantity != expected_quantity:
            raise BrokerError("OpenAlgo position changed before the reducing write", broker_id="openalgo")
        if tag != self._emergency_exit_tag(current):
            raise BrokerError("OpenAlgo reducing position episode changed before dispatch", broker_id="openalgo")

        from flinttrade_core.models import Order  # noqa: PLC0415

        try:
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
                strategy=tag,
            )
        except (TypeError, ValueError) as exc:
            raise BrokerError("OpenAlgo reducing position payload is invalid", broker_id="openalgo") from exc
        order_id = await self.place_order(session, order, _router_token=_router_token)
        return self._canonical_identifier(order_id, what="emergency exit order id")

    async def cancel_all_orders(
        self,
        session: Session,
        *,
        tag: str | None = None,
        segment: str | None = None,
        _router_token: object | None = None,
    ) -> Any:
        """Cancel every OpenAlgo order for the session strategy through the router."""
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        self._require_unscoped_sweep(tag=tag, segment=segment)
        strategy = str(session.extra.get("strategy", "Flint"))
        with self._mapped("cancel-all emergency action"):
            response = await self._client(session).cancel_all_orders(strategy=strategy)
        return self._successful_sweep_or_raise(response, "cancel-all emergency action")

    async def exit_all_positions(
        self,
        session: Session,
        *,
        tag: str | None = None,
        segment: str | None = None,
        _router_token: object | None = None,
    ) -> Any:
        """Close every OpenAlgo position for the session strategy through the router."""
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        self._require_unscoped_sweep(tag=tag, segment=segment)
        strategy = str(session.extra.get("strategy", "Flint"))
        with self._mapped("exit-all emergency action"):
            response = await self._client(session).close_position(strategy=strategy)
        return self._successful_sweep_or_raise(response, "exit-all emergency action")

    # ---------- trading: reads ----------

    async def order_book(self, session: Session) -> list[Order]:
        with self._mapped("order_book"):
            return await self._client(session).orderbook()  # type: ignore[return-value]

    async def trade_book(self, session: Session) -> list[Trade]:
        with self._mapped("trade_book"):
            return await self._client(session).tradebook()

    async def positions(self, session: Session) -> list[Position]:
        with self._mapped("positions"):
            return await self._client(session).positionbook()

    async def holdings(self, session: Session) -> list[dict]:
        with self._mapped("holdings"):
            return await self._client(session).holdings()  # type: ignore[return-value]

    async def funds(self, session: Session) -> dict:
        with self._mapped("funds"):
            funds = await self._client(session).funds()
        return funds if isinstance(funds, dict) else getattr(funds, "__dict__", {"funds": funds})

    # ---------- market data: rest ----------

    async def quotes(self, session: Session, symbols: list[str]) -> list[Quote]:
        payload = [self._split_symbol(s) for s in symbols]
        with self._mapped("quotes"):
            return await self._client(session).multi_quotes(payload)

    async def historical(self, session: Session, req: dict) -> Candles:
        with self._mapped("historical"):
            return await self._client(session).history(**req)  # type: ignore[return-value]

    async def option_chain(self, session: Session, req: dict) -> OptionChain:
        symbol = str(req.get("symbol", ""))
        exchange = str(req.get("exchange", "NFO"))
        expiry = str(req.get("expiry") or req.get("expiry_date") or "")
        with self._mapped("option_chain"):
            return await self._client(session).option_chain(symbol, exchange, expiry)

    # ---------- market data: streaming (not exposed by the REST bridge) ----------

    def stream(self, session: Session) -> AsyncIterator[TickEvent]:  # type: ignore[name-defined]  # noqa: F821
        raise UnsupportedCapabilityError(
            "OpenAlgo bridge adapter does not expose tick streaming; route data.ticks to a native adapter"
        )

    async def subscribe(self, session: Session, symbols: list[str], mode: str = "FULL") -> None:
        raise UnsupportedCapabilityError("OpenAlgo bridge adapter does not expose tick subscription")

    async def unsubscribe(self, session: Session, symbols: list[str]) -> None:
        raise UnsupportedCapabilityError("OpenAlgo bridge adapter does not expose tick subscription")

    # ---------- reconciliation ----------

    async def reconcile(self, session: Session) -> ReconciliationReport:
        """Diff canonical OpenAlgo account reads against the local mirror."""
        from flinttrade_gateway.reconciliation import (  # noqa: PLC0415
            EMPTY_LOCAL_STATE,
            LocalStateSnapshot,
            build_report,
            declare_unavailable_order_fields,
        )

        generated_at = datetime.now(tz=UTC)
        try:
            local_state = (
                EMPTY_LOCAL_STATE
                if self._local_state_provider is None
                else self._local_state_provider(session)
            )
            if not isinstance(local_state, LocalStateSnapshot):
                raise BrokerError("OpenAlgo local state snapshot is malformed", broker_id="openalgo")

            broker_orders = self._reconciliation_rows(
                await self.order_book(session),
                book="order-book",
            )
            broker_orders = declare_unavailable_order_fields(
                broker_orders,
                fields=("variety", "validity", "strategy"),
            )
            broker_positions = self._reconciliation_rows(
                await self.positions(session),
                book="position-book",
            )
            broker_holdings = self._reconciliation_rows(
                await self.holdings(session),
                book="holdings",
            )
            return build_report(
                adapter_id=self.broker_id,
                account_id=session.account_id,
                generated_at=generated_at,
                broker_orders=broker_orders,
                broker_positions=broker_positions,
                broker_holdings=broker_holdings,
                local_state=local_state,
            )
        except Exception as exc:
            logger.warning(
                "OpenAlgo reconciliation failed (%s)",
                type(exc).__name__,
            )
            return build_report(
                adapter_id=self.broker_id,
                account_id=session.account_id,
                generated_at=generated_at,
                error=f"reconciliation failed ({type(exc).__name__})",
            )

    # ---------- helpers ----------

    @staticmethod
    def _row_mapping(row: Any, *, book: str) -> dict[str, Any]:
        if isinstance(row, Mapping):
            mapped = dict(row)
        else:
            model_dump = getattr(row, "model_dump", None)
            if callable(model_dump):
                dumped = model_dump()
                mapped = dict(dumped) if isinstance(dumped, Mapping) else None
            else:
                legacy_dict = getattr(row, "dict", None)
                dumped = legacy_dict() if callable(legacy_dict) else None
                mapped = dict(dumped) if isinstance(dumped, Mapping) else None
            if mapped is None:
                raise BrokerError(f"OpenAlgo {book} row is malformed", broker_id="openalgo")
        if book == "order-book":
            for field in _ORDER_BOOK_NUMERIC_FIELDS:
                value = mapped.get(field)
                if field not in mapped or value is None or (isinstance(value, str) and not value.strip()):
                    mapped.pop(field, None)
        return mapped

    @classmethod
    def _reconciliation_rows(cls, rows: Any, *, book: str) -> tuple[dict[str, Any], ...]:
        if not isinstance(rows, (list, tuple)):
            raise BrokerError(f"OpenAlgo {book} response is malformed", broker_id="openalgo")
        return tuple(cls._row_mapping(row, book=book) for row in rows)

    @staticmethod
    def _canonical_identifier(value: Any, *, what: str) -> str:
        if not isinstance(value, str) or not value or value != value.strip():
            raise BrokerError(f"OpenAlgo {what} is non-canonical", broker_id="openalgo")
        if (
            not value.isprintable()
            or any(character.isspace() for character in value)
            or unicodedata.normalize("NFC", value) != value
        ):
            raise BrokerError(f"OpenAlgo {what} is non-canonical", broker_id="openalgo")
        return value

    @classmethod
    def _canonical_identifier_set(cls, values: frozenset[str], *, what: str) -> frozenset[str]:
        return frozenset(cls._canonical_identifier(value, what=what) for value in values)

    @staticmethod
    def _canonical_position_identifier(
        value: Any,
        *,
        what: str,
        uppercase: bool = False,
    ) -> str:
        if not isinstance(value, str) or not value or value != value.strip():
            raise BrokerError(f"OpenAlgo emergency position {what} is incomplete", broker_id="openalgo")
        if not value.isprintable() or unicodedata.normalize("NFC", value) != value:
            raise BrokerError(f"OpenAlgo emergency position {what} is non-canonical", broker_id="openalgo")
        return value.upper() if uppercase else value

    @staticmethod
    def _position_quantity(value: Any) -> int:
        if value is None or isinstance(value, bool):
            raise BrokerError("OpenAlgo emergency position quantity is unknown", broker_id="openalgo")
        try:
            canonical = str(value)
            quantity = int(canonical)
        except (TypeError, ValueError, OverflowError) as exc:
            raise BrokerError("OpenAlgo emergency position quantity is unknown", broker_id="openalgo") from exc
        if canonical != str(quantity):
            raise BrokerError("OpenAlgo emergency position quantity is unknown", broker_id="openalgo")
        return quantity

    @classmethod
    def _active_emergency_orders(
        cls,
        rows: Any,
    ) -> tuple[tuple[dict[str, Any], ...], frozenset[str]]:
        if not isinstance(rows, (list, tuple)):
            raise BrokerError("OpenAlgo order-book response is malformed", broker_id="openalgo")
        active: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in rows:
            row = cls._row_mapping(raw, book="order-book")
            raw_status = row.get("status") or row.get("order_status")
            if not isinstance(raw_status, str) or not raw_status.strip():
                raise BrokerError("OpenAlgo active order status is missing", broker_id="openalgo")
            status = raw_status.strip().lower()
            raw_order_id = row.get("orderid") or row.get("order_id")
            if status in _TERMINAL_ORDER_STATUSES and raw_order_id in (None, ""):
                continue
            order_id = cls._canonical_identifier(raw_order_id, what="active order id")
            if order_id in seen:
                raise BrokerError("OpenAlgo order book contains a duplicate order id", broker_id="openalgo")
            seen.add(order_id)
            if status in _TERMINAL_ORDER_STATUSES:
                continue
            active.append(
                {
                    **row,
                    "orderid": order_id,
                    "status": status,
                    "symbol": row.get("symbol") or row.get("trading_symbol") or row.get("tradingsymbol"),
                    "exchange": row.get("exchange"),
                    "product": row.get("product") or row.get("product_type"),
                    "action": row.get("action") or row.get("transaction_type"),
                    "quantity": row.get("quantity"),
                }
            )
        return tuple(sorted(active, key=lambda order: str(order["orderid"]))), frozenset(seen)

    @classmethod
    def _active_emergency_positions(cls, rows: Any) -> tuple[dict[str, Any], ...]:
        if not isinstance(rows, (list, tuple)):
            raise BrokerError("OpenAlgo position-book response is malformed", broker_id="openalgo")
        aggregated: dict[tuple[str, str, str], int] = {}
        for raw in rows:
            row = cls._row_mapping(raw, book="position-book")
            symbol = cls._canonical_position_identifier(row.get("symbol"), what="symbol")
            exchange = cls._canonical_position_identifier(
                row.get("exchange"),
                what="exchange",
                uppercase=True,
            )
            product = cls._canonical_position_identifier(
                row.get("product") or row.get("product_type"),
                what="product",
                uppercase=True,
            )
            quantity = cls._position_quantity(row.get("quantity"))
            key = (symbol, exchange, product)
            aggregated[key] = aggregated.get(key, 0) + quantity
        return tuple(
            {
                "symbol": symbol,
                "exchange": exchange,
                "product": product,
                "quantity": str(quantity),
            }
            for (symbol, exchange, product), quantity in sorted(aggregated.items())
            if quantity != 0
        )

    @staticmethod
    def _position_key(position: Mapping[str, Any]) -> tuple[str, str, str]:
        return (
            str(position["symbol"]),
            str(position["exchange"]),
            str(position["product"]),
        )

    @classmethod
    def _order_position_key(cls, order: Mapping[str, Any]) -> tuple[str, str, str]:
        return (
            cls._canonical_position_identifier(order.get("symbol"), what="exit order symbol"),
            cls._canonical_position_identifier(
                order.get("exchange"),
                what="exit order exchange",
                uppercase=True,
            ),
            cls._canonical_position_identifier(
                order.get("product"),
                what="exit order product",
                uppercase=True,
            ),
        )

    @staticmethod
    def _order_tags(order: Mapping[str, Any]) -> frozenset[str]:
        return frozenset(
            value
            for key in ("emergency_tag", "tag", "strategy", "correlation_id", "correlationid")
            if isinstance((value := order.get(key)), str) and value
        )

    @classmethod
    def _exit_order_exactly_reduces(
        cls,
        order: Mapping[str, Any],
        position: Mapping[str, Any],
    ) -> bool:
        signed_quantity = cls._position_quantity(position.get("quantity"))
        remaining_quantity = cls._remaining_exit_quantity(order)
        expected_action = "SELL" if signed_quantity > 0 else "BUY"
        action = str(order.get("action") or "").strip().upper()
        return (
            signed_quantity != 0
            and remaining_quantity == abs(signed_quantity)
            and action == expected_action
        )

    @classmethod
    def _remaining_exit_quantity(cls, order: Mapping[str, Any]) -> int:
        """Return an active exit's authoritative unfilled quantity."""
        requested_quantity = cls._position_quantity(order.get("quantity"))
        raw_filled_quantity = order.get("filled_quantity")
        filled_quantity = (
            0
            if raw_filled_quantity in (None, "")
            else cls._position_quantity(raw_filled_quantity)
        )
        if requested_quantity <= 0 or filled_quantity < 0 or filled_quantity > requested_quantity:
            raise BrokerError("OpenAlgo emergency exit order quantity is invalid", broker_id="openalgo")

        explicit_remaining: list[int] = []
        for field in ("remaining_quantity", "pending_quantity", "unfilled_quantity"):
            raw_value = order.get(field)
            if raw_value not in (None, ""):
                explicit_remaining.append(cls._position_quantity(raw_value))
        derived_remaining = requested_quantity - filled_quantity
        if any(quantity < 0 for quantity in explicit_remaining) or any(
            quantity != derived_remaining for quantity in explicit_remaining
        ):
            raise BrokerError("OpenAlgo emergency exit remaining quantity is inconsistent", broker_id="openalgo")
        return explicit_remaining[0] if explicit_remaining else derived_remaining

    @classmethod
    def _emergency_exit_tag(cls, position: Mapping[str, Any]) -> str:
        signed_quantity = cls._position_quantity(position.get("quantity"))
        if signed_quantity == 0:
            raise BrokerError("OpenAlgo emergency position is flat", broker_id="openalgo")
        action = "SELL" if signed_quantity > 0 else "BUY"
        identity = "|".join((*cls._position_key(position), action, str(abs(signed_quantity))))
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        return f"{_EMERGENCY_EXIT_TAG_PREFIX}{digest}"

    @classmethod
    def _emergency_reducing_payload(cls, position: Mapping[str, Any]) -> dict[str, str]:
        signed_quantity = cls._position_quantity(position.get("quantity"))
        if signed_quantity == 0:
            raise BrokerError("OpenAlgo emergency position is flat", broker_id="openalgo")
        return {
            "_op": "place_reducing_order",
            "symbol": str(position["symbol"]),
            "exchange": str(position["exchange"]),
            "product": str(position["product"]),
            "quantity": str(abs(signed_quantity)),
            "expected_position_quantity": str(signed_quantity),
            "action": "SELL" if signed_quantity > 0 else "BUY",
            "pricetype": "MARKET",
            "price": "0",
            "trigger_price": "0",
            "variety": "regular",
            "emergency_tag": cls._emergency_exit_tag(position),
        }

    @staticmethod
    def _split_symbol(symbol: str) -> dict[str, str]:
        """Parse ``'EXCHANGE:SYMBOL'`` (or bare ``'SYMBOL'``, default NSE)."""
        if ":" in symbol:
            exchange, _, sym = symbol.partition(":")
            return {"symbol": sym, "exchange": exchange}
        return {"symbol": symbol, "exchange": "NSE"}

    @staticmethod
    def _order_id_or_raise(resp: Any) -> str:
        """Extract the order id from an OpenAlgo OrderResponse, raising on failure."""
        status = str(getattr(resp, "status", "") or "").lower()
        order_id = str(getattr(resp, "orderid", "") or "")
        if status and status not in ("success", "ok"):
            raise OrderRejectedByBroker(
                f"OpenAlgo rejected the order (status={status!r}, orderid={order_id!r})"
            )
        return order_id

    @staticmethod
    def _require_unscoped_sweep(*, tag: str | None, segment: str | None) -> None:
        """Refuse narrower semantics the OpenAlgo account-wide APIs cannot honour."""
        if tag is not None or segment is not None:
            raise UnsupportedCapabilityError(
                "OpenAlgo emergency sweeps do not support tag or segment scope narrowing"
            )

    @staticmethod
    def _successful_sweep_or_raise(response: Any, action: str) -> Any:
        """Require an explicit OpenAlgo success status before reporting completion."""
        status = str(getattr(response, "status", "") or "").strip().lower()
        if status not in {"ok", "success"}:
            raise OrderRejectedByBroker(
                f"OpenAlgo rejected the {action} (status={status!r})"
            )
        return response

    class _MapBrokerErrors:
        """Context manager mapping OpenAlgo client errors to the broker taxonomy (§7)."""

        def __init__(self, what: str) -> None:
            self._what = what

        def __enter__(self) -> OpenAlgoAdapter._MapBrokerErrors:
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            if exc is None:
                return False
            if isinstance(exc, BrokerError):
                return False  # already in-taxonomy (incl. OrderRejectedByBroker) — propagate as-is
            if isinstance(exc, OpenAlgoRateLimitError):
                raise RateLimitError(f"OpenAlgo rate limit during {self._what}: {exc}") from exc
            if isinstance(exc, OpenAlgoAuthError):
                raise SessionExpired(f"OpenAlgo auth failed during {self._what}: {exc}") from exc
            if isinstance(exc, APIError):
                raise BrokerError(f"OpenAlgo API error during {self._what}: {exc}") from exc
            return False  # unexpected — let it propagate

    def _mapped(self, what: str) -> OpenAlgoAdapter._MapBrokerErrors:
        return self._MapBrokerErrors(what)
