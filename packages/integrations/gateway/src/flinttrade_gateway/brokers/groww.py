"""Groww native adapter (REST, access-token based).

Groww publishes a Trade API with REST endpoints for orders, smart orders,
portfolio, margins, live market data, historical candles and user profile. This
adapter keeps the broker as a native FlintTrade target behind the existing
encrypted vault and ``BrokerRouter`` gates, but the catalogue still marks Groww
``connectable=False`` until the remaining live blockers clear. Account reads and
margin estimation have live proof; market-data/API permissions, static-IP
registration, and order-safety smoke evidence are still pending.

Safety: every write requires the router's shared ``_ROUTER_TOKEN``. A direct
``adapter.place_order`` call raises before any Groww HTTP request is made.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable
from zoneinfo import ZoneInfo

from flinttrade_core.exceptions import BrokerError, UnsupportedCapabilityError
from flinttrade_gateway.capabilities import (
    AuthModel,
    Capabilities,
    DepthLevels,
    OrderTypes,
    Segments,
    TickProtocol,
)

from . import groww_mapping as M
from ._base import BrokerAdapter, Session

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flinttrade_core.models import Candles, OptionChain, Order, Position, Quote, Trade
    from flinttrade_gateway.reconciliation import LocalStateSnapshot, ReconciliationReport

Transport = Callable[..., tuple[int, Any]]

GROWW_CAPABILITIES = Capabilities(
    segments=Segments.NSE_EQ | Segments.BSE_EQ | Segments.NFO | Segments.BFO | Segments.MCX,
    order_types=(
        OrderTypes.MARKET
        | OrderTypes.LIMIT
        | OrderTypes.SL
        | OrderTypes.SLM
        | OrderTypes.MIS
        | OrderTypes.CNC
        | OrderTypes.NRML
        | OrderTypes.GTT
    ),
    depth_levels=DepthLevels.L5,
    tick_protocol=TickProtocol.GENERIC_JSON,
    auth_model=AuthModel.OAUTH_RENEWABLE_24H,
    session_lifetime_hours=24.0,
    sandbox=False,
    rate_limit_orders_per_sec=10,
    rate_limit_data_per_sec=5,
    rate_limit_quote_per_sec=5,
    rate_limit_non_trading_per_sec=15,
    algo_tag_required=False,
    cost_paid=False,
    cost_inr_per_month=0,
    brokerage_free=False,
    brokerage_note="Groww Trade API is free; execution brokerage follows the operator's Groww plan.",
    historical_max_lookback_days_intraday=1080,
    historical_intraday_intervals_minutes=[1, 5, 10, 60, 240],
    option_chain_supported=True,
    option_chain_greeks_supported=True,
    streaming_supported=True,
    streaming_runtime_ready=False,
    market_depth_runtime_ready=False,
    gtt_native=True,
    modify_qty_supported=True,
)


def _build_httpx_transport(timeout: float = 10.0) -> Transport:
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


def _next_6am_ist() -> float:
    """Groww API tokens shown in the console expire at 06:00 IST."""
    ist = ZoneInfo("Asia/Kolkata")
    now = datetime.now(tz=ist)
    expiry = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if expiry <= now:
        expiry += timedelta(days=1)
    return expiry.astimezone(timezone.utc).timestamp()


def _expiry_from_token_payload(payload: Any) -> float:
    """Best-effort expiry parser for Groww token responses."""
    if not isinstance(payload, dict):
        return _next_6am_ist()
    now = datetime.now(tz=timezone.utc).timestamp()
    for key in ("expires_at", "expiry", "expiresAt", "expiryTime", "expiry_time"):
        value = payload.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, (int, float)):
            return float(value) / 1000 if value > 10_000_000_000 else float(value)
        text = str(value).strip()
        if not text:
            continue
        if text.isdigit():
            numeric = float(text)
            return numeric / 1000 if numeric > 10_000_000_000 else numeric
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    expires_in = payload.get("expires_in") or payload.get("expiresIn")
    try:
        if expires_in:
            return now + float(expires_in)
    except (TypeError, ValueError):
        pass
    return _next_6am_ist()


class GrowwAdapter(BrokerAdapter):
    """Native Groww Trade API adapter."""

    def __init__(
        self,
        *,
        http_factory: Callable[[], Transport] | None = None,
        local_state_provider: Callable[[Session], LocalStateSnapshot] | None = None,
    ) -> None:
        self._http_factory = http_factory
        self._local_state_provider = local_state_provider

    @property
    def broker_id(self) -> str:
        return "groww"

    @property
    def capabilities(self) -> Capabilities:
        return GROWW_CAPABILITIES

    def _transport(self, session: Session) -> Transport:
        if self._http_factory is not None:
            return self._http_factory()
        transport = session.extra.get("transport")
        if transport is None:
            raise BrokerError("Groww transport not initialised - call login() first", broker_id="groww")
        return transport

    @staticmethod
    def _headers(session: Session) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {session.access_token}",
            "X-API-VERSION": "1.0",
        }

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
        transport = self._transport(session)
        status, payload = await asyncio.to_thread(
            transport,
            method,
            f"{M.BASE_URL}{path}",
            headers=self._headers(session),
            params=params,
            json_body=json_body,
        )
        if status >= 400:
            raise M.map_error(status, payload, endpoint=path)
        return payload if raw else M.unwrap(payload)

    async def _mint_access_token(
        self,
        transport: Transport,
        *,
        api_key: str,
        api_secret: str = "",
        totp: str = "",
    ) -> tuple[str, float]:
        if bool(api_secret) == bool(totp):
            raise BrokerError(
                "Groww API-key login requires exactly one of api_secret or totp",
                broker_id="groww",
            )
        if totp:
            body: dict[str, Any] = {"key_type": "totp", "totp": totp}
        else:
            timestamp = str(int(datetime.now(tz=timezone.utc).timestamp()))
            checksum = hashlib.sha256(f"{api_secret}{timestamp}".encode("utf-8")).hexdigest()
            body = {
                "key_type": "approval",
                "checksum": checksum,
                "timestamp": timestamp,
            }
        status, payload = await asyncio.to_thread(
            transport,
            "POST",
            f"{M.BASE_URL}/v1/token/api/access",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "x-client-id": "growwapi",
                "x-client-platform": "flinttrade",
                "X-API-VERSION": "1.0",
            },
            params=None,
            json_body=body,
        )
        if status >= 400:
            raise M.map_error(status, payload, endpoint="/v1/token/api/access")
        data = M.unwrap(payload)
        token = ""
        if isinstance(data, dict):
            token = str(data.get("token") or data.get("access_token") or data.get("accessToken") or "").strip()
        elif isinstance(data, str):
            token = data.strip()
        if not token:
            raise BrokerError("Groww access-token mint did not return a token", broker_id="groww")
        return token, _expiry_from_token_payload(data)

    async def login(self, credentials: dict) -> Session:
        access_token = str(credentials.get("access_token") or "").strip()
        expires_at = _next_6am_ist()
        auth_method = "access_token"
        if not access_token:
            api_key = str(credentials.get("api_key") or "").strip()
            api_secret = str(credentials.get("api_secret") or credentials.get("secret") or "").strip()
            totp = str(credentials.get("totp") or "").strip()
            if not (api_key or api_secret or totp):
                raise BrokerError(
                    "Groww login requires access_token, api_key + api_secret, or api_key + totp",
                    broker_id="groww",
                )
            if not api_key:
                raise BrokerError("Groww API-key login requires api_key", broker_id="groww")
            if bool(api_secret) == bool(totp):
                raise BrokerError(
                    "Groww API-key login requires exactly one of api_secret or totp",
                    broker_id="groww",
                )
            mint_transport = self._http_factory() if self._http_factory is not None else _build_httpx_transport()
            access_token, expires_at = await self._mint_access_token(
                mint_transport,
                api_key=api_key,
                api_secret=api_secret,
                totp=totp,
            )
            auth_method = "api_key_secret" if api_secret else "api_key_totp"
        transport = None if self._http_factory is not None else _build_httpx_transport()
        return Session(
            access_token=access_token,
            expires_at=expires_at,
            account_id=str(credentials.get("user_id") or credentials.get("account_id") or ""),
            adapter_id="groww",
            extra={"transport": transport, "auth_method": auth_method},
        )

    def replay_credentials(self, credentials: dict, session: Session) -> dict:
        """Swap a one-time TOTP code for the minted token after a successful login."""
        if session.extra.get("auth_method") != "api_key_totp":
            return dict(credentials)
        replayable = {k: v for k, v in credentials.items() if k != "totp"}
        replayable["access_token"] = session.access_token
        return replayable

    async def refresh(self, session: Session) -> Session:
        # Groww console tokens expire at 06:00 IST and must be regenerated by the
        # operator; there is no documented refresh endpoint.
        return session

    async def logout(self, session: Session) -> None:
        session.extra.pop("transport", None)
        return None

    async def place_order(self, session: Session, order: Order, *, _router_token: object | None = None) -> str:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        variety = str(getattr(order, "variety", "regular") or "regular").lower()
        if variety in {"", "regular", "amo"}:
            resp = await self._request(session, "POST", "/v1/order/create", json_body=M.to_place_order_payload(order))
            order_id = M.extract_order_id(resp)
            if not order_id:
                raise BrokerError("Groww order placement did not return an order id", broker_id="groww")
            return order_id
        if variety in {"gtt", "oco"}:
            payload = M.to_place_order_payload(order)
            payload["smart_order_type"] = "OCO" if variety == "oco" else "GTT"
            resp = await self._request(session, "POST", "/v1/order-advance/create", json_body=payload)
            order_id = M.extract_order_id(resp)
            if not order_id:
                raise BrokerError("Groww smart order did not return an order id", broker_id="groww")
            return order_id
        raise UnsupportedCapabilityError(f"Groww does not support order variety {variety!r}", broker_id="groww")

    async def modify_order(
        self, session: Session, order_id: str, changes: dict, *, _router_token: object | None = None
    ) -> None:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        segment = str(changes.get("segment") or M.exchange_segment(changes.get("exchange", "NSE"))[1])
        if str(changes.get("variety", "")).lower() in {"gtt", "oco", "smart"} or str(order_id).startswith(("gtt_", "oco_")):
            await self._request(session, "PUT", f"/v1/order-advance/modify/{order_id}", json_body=dict(changes))
            return
        await self._request(session, "POST", "/v1/order/modify", json_body=M.to_modify_payload(order_id, changes, segment=segment))

    async def cancel_order(
        self,
        session: Session,
        order_id: str,
        *,
        segment: str = "CASH",
        _router_token: object | None = None,
    ) -> None:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        await self._request(session, "POST", "/v1/order/cancel", json_body=M.to_cancel_payload(order_id, segment=segment))

    async def cancel_smart_order(
        self,
        session: Session,
        order_id: str,
        *,
        segment: str = "CASH",
        smart_order_type: str = "GTT",
        _router_token: object | None = None,
    ) -> None:
        self._require_router_token(_router_token, _ROUTER_TOKEN)
        await self._request(
            session,
            "POST",
            f"/v1/order-advance/cancel/{segment}/{smart_order_type}/{order_id}",
        )

    async def order_book(self, session: Session) -> list[Order]:
        out: list[dict[str, Any]] = []
        for segment in ("CASH", "FNO", "COMMODITY"):
            payload = await self._request(
                session,
                "GET",
                "/v1/order/list",
                params={"segment": segment, "page": 0, "page_size": 100},
            )
            rows = payload.get("order_list") if isinstance(payload, dict) else []
            out.extend(M.from_order(r) for r in rows or [] if isinstance(r, dict))
        return out  # type: ignore[return-value]

    async def order_details(self, session: Session, order_id: str, *, segment: str = "CASH") -> dict:
        payload = await self._request(session, "GET", f"/v1/order/detail/{order_id}", params={"segment": segment})
        return M.from_order(payload if isinstance(payload, dict) else {})

    async def order_status(self, session: Session, order_id: str, *, segment: str = "CASH") -> dict:
        payload = await self._request(session, "GET", f"/v1/order/status/{order_id}", params={"segment": segment})
        return M.from_order(payload if isinstance(payload, dict) else {})

    async def order_trades(self, session: Session, order_id: str, *, segment: str = "CASH") -> list[dict]:
        payload = await self._request(
            session,
            "GET",
            f"/v1/order/trades/{order_id}",
            params={"segment": segment, "page": 0, "page_size": 50},
        )
        rows = payload.get("trade_list") if isinstance(payload, dict) else []
        return [M.from_trade(r) for r in rows or [] if isinstance(r, dict)]

    async def trade_book(self, session: Session) -> list[Trade]:
        orders = await self.order_book(session)
        out: list[dict[str, Any]] = []
        for order in orders:  # type: ignore[assignment]
            oid = str(order.get("orderid") or "")
            exchange = order.get("exchange")
            if exchange == "MCX":
                segment = "COMMODITY"
            else:
                segment = "FNO" if exchange in {"NFO", "BFO"} else "CASH"
            if oid:
                out.extend(await self.order_trades(session, oid, segment=segment))
        return out  # type: ignore[return-value]

    async def positions(self, session: Session) -> list[Position]:
        payload = await self._request(session, "GET", "/v1/positions/user")
        rows = payload.get("positions") if isinstance(payload, dict) else []
        return [M.from_position(r) for r in rows or [] if isinstance(r, dict)]  # type: ignore[return-value]

    async def holdings(self, session: Session) -> list[dict]:
        payload = await self._request(session, "GET", "/v1/holdings/user")
        rows = payload.get("holdings") if isinstance(payload, dict) else []
        return [M.from_holding(r) for r in rows or [] if isinstance(r, dict)]

    async def funds(self, session: Session) -> dict:
        payload = await self._request(session, "GET", "/v1/margins/detail/user")
        return M.from_funds(payload if isinstance(payload, dict) else {})

    async def profile(self, session: Session) -> dict:
        payload = await self._request(session, "GET", "/v1/user/detail")
        return payload if isinstance(payload, dict) else {}

    async def margin_calculator(self, session: Session, order: Order) -> dict:
        segment, payload = M.to_margin_payload(order)
        data = await self._request(
            session,
            "POST",
            "/v1/margins/detail/orders",
            params={"segment": segment},
            json_body=payload,
        )
        return data if isinstance(data, dict) else {"raw": data}

    async def quotes(self, session: Session, symbols: list[str]) -> list[Quote]:
        from flinttrade_core.models import Quote  # noqa: PLC0415

        out: list[Quote] = []
        for raw in symbols:
            exchange, symbol = M.split_symbol(raw)
            groww_exchange, segment = M.exchange_segment(exchange)
            payload = await self._request(
                session,
                "GET",
                "/v1/live-data/quote",
                params={"exchange": groww_exchange, "segment": segment, "trading_symbol": symbol},
            )
            out.append(Quote(**M.from_quote(symbol, exchange, payload if isinstance(payload, dict) else {})))
        return out

    async def ltp(self, session: Session, symbols: list[str]) -> dict[str, float]:
        resolved = [M.split_symbol(raw) for raw in symbols]
        by_segment: dict[str, list[tuple[str, str]]] = {}
        for exchange, symbol in resolved:
            _groww_exchange, segment = M.exchange_segment(exchange)
            by_segment.setdefault(segment, []).append((exchange, symbol))
        out: dict[str, float] = {}
        for segment, rows in by_segment.items():
            symbols_param = ",".join(M.groww_exchange_symbol(exchange, symbol) for exchange, symbol in rows)
            payload = await self._request(
                session,
                "GET",
                "/v1/live-data/ltp",
                params={"segment": segment, "exchange_symbols": symbols_param},
            )
            if isinstance(payload, dict):
                for exchange, symbol in rows:
                    key = f"{exchange}:{symbol}"
                    out[key] = float(payload.get(M.groww_exchange_symbol(exchange, symbol), 0) or 0)
        return out

    async def historical(self, session: Session, req: dict) -> Candles:
        from flinttrade_core.models import Candles, OHLCV  # noqa: PLC0415

        symbol = str(req.get("symbol") or "")
        exchange = str(req.get("exchange") or "NSE")
        groww_exchange, segment = M.exchange_segment(exchange)
        start = M.normalise_date(req.get("start_time") or req.get("start") or req.get("from_date"))
        end = M.normalise_date(req.get("end_time") or req.get("end") or req.get("to_date"))
        interval = str(req.get("interval") or req.get("timeframe") or "1m")
        payload = await self._request(
            session,
            "GET",
            "/v1/historical/candle/range",
            params={
                "exchange": groww_exchange,
                "segment": segment,
                "trading_symbol": symbol,
                "start_time": start,
                "end_time": end,
                "interval_in_minutes": _interval_minutes(interval),
            },
            raw=True,
        )
        rows = M.candle_rows(payload)
        return Candles(
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            bars=[OHLCV(**M.from_candle_row(r)) for r in rows],
        )

    async def option_chain(self, session: Session, req: dict) -> OptionChain:
        exchange = str(req.get("exchange") or "NSE")
        groww_exchange, _segment = M.exchange_segment(exchange)
        underlying = str(req.get("underlying") or req.get("symbol") or "")
        expiry = str(req.get("expiry_date") or req.get("expiry") or "")
        return M.option_chain_rows(
            await self._request(
                session,
                "GET",
                f"/v1/option-chain/exchange/{groww_exchange}/underlying/{underlying}",
                params={"expiry_date": expiry},
                raw=True,
            )
        )  # type: ignore[return-value]

    async def greeks(self, session: Session, *, exchange: str, underlying: str, trading_symbol: str, expiry: str) -> dict:
        groww_exchange, _segment = M.exchange_segment(exchange)
        payload = await self._request(
            session,
            "GET",
            f"/v1/live-data/greeks/exchange/{groww_exchange}/underlying/{underlying}/trading_symbol/{trading_symbol}/expiry/{expiry}",
        )
        return payload if isinstance(payload, dict) else {}

    async def instruments_csv(self, session: Session) -> str:
        # Asset host is outside api.groww.in and does not require the API base.
        transport = self._transport(session)
        status, payload = await asyncio.to_thread(
            transport,
            "GET",
            "https://growwapi-assets.groww.in/instruments/instrument.csv",
            headers={"Accept": "text/csv"},
            params=None,
            json_body=None,
        )
        if status >= 400:
            raise M.map_error(status, payload, endpoint="instrument.csv")
        return payload if isinstance(payload, str) else str(payload)

    async def instruments(self, session: Session) -> list[dict[str, str]]:
        return M.parse_instruments_csv(await self.instruments_csv(session))

    async def subscribe(self, session: Session, symbols: list[str], mode: str = "FULL") -> None:
        return None

    async def unsubscribe(self, session: Session, symbols: list[str]) -> None:
        return None

    def stream(self, session: Session) -> AsyncIterator[Any]:
        return self._stream_impl(session)

    async def _stream_impl(self, session: Session) -> AsyncIterator[Any]:
        raise NotImplementedError("Groww streaming is documented but live FlintTrade socket wiring is not enabled yet")
        yield  # pragma: no cover

    async def reconcile(self, session: Session) -> ReconciliationReport:
        from flinttrade_gateway.reconciliation import EMPTY_LOCAL_STATE, build_report  # noqa: PLC0415

        generated_at = datetime.now(tz=timezone.utc)
        local = EMPTY_LOCAL_STATE if self._local_state_provider is None else self._local_state_provider(session)
        try:
            broker_orders = await self.order_book(session)
            broker_positions = await self.positions(session)
            broker_holdings = await self.holdings(session)
        except (BrokerError, ValueError) as exc:
            return build_report(
                adapter_id=self.broker_id,
                account_id=session.account_id,
                generated_at=generated_at,
                local_state=local,
                error=f"broker fetch failed: {exc}",
            )
        return build_report(
            adapter_id=self.broker_id,
            account_id=session.account_id,
            generated_at=generated_at,
            broker_orders=broker_orders,  # type: ignore[arg-type]
            broker_positions=broker_positions,  # type: ignore[arg-type]
            broker_holdings=broker_holdings,
            local_state=local,
        )


def _interval_minutes(interval: str) -> str:
    value = interval.strip().lower()
    if value.endswith("m"):
        return value[:-1] or "1"
    if value.endswith("h"):
        return str(int(value[:-1] or "1") * 60)
    if value in {"d", "1d"}:
        return "1440"
    if value in {"w", "1w"}:
        return "10080"
    return value or "1"


from ._base import ROUTER_TOKEN as _ROUTER_TOKEN  # noqa: E402  shared per-process token (§8.0c)
