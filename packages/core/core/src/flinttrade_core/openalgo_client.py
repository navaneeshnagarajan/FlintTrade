"""Async OpenAlgo v1 API client with retry, rate-limiting, and typed responses."""

from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from concurrent.futures import TimeoutError as FuturesTimeoutError
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from .config import Settings, openalgo_rest_base_url
from .exceptions import APIError, OpenAlgoAuthError, OpenAlgoRateLimitError
from .models import (
    OHLCV,
    BasketOrder,
    CancelGttOrder,
    Depth,
    DepthLevel,
    Fund,
    GttOrder,
    GttTrigger,
    Holding,
    ModifyGttOrder,
    ModifyOrder,
    OptionChain,
    OptionChainStrike,
    OptionGreek,
    OptionsMultiOrder,
    OptionsOrder,
    Order,
    OrderResponse,
    OrderStatus,
    Position,
    Quote,
    SmartOrder,
    SplitOrder,
    Trade,
)

logger = logging.getLogger("flinttrade.core")

_CALENDAR_EXCHANGE_ALIASES = {
    "NSE_INDEX": "NSE",
    "BSE_INDEX": "BSE",
    "MCX_INDEX": "MCX",
}
_OPENING_RISK_CAPITAL_FIELDS = (
    "opening_risk_capital",
    "openingcashlimit",
    "opening_balance",
    "openingbalance",
    "sod_balance",
    "sodbalance",
    "start_of_day_balance",
    "starting_capital",
)


def _sum_fund_components(*values: Any) -> str:
    """Return an exact finite sum for string-valued OpenAlgo fund fields."""
    try:
        total = sum((Decimal(str(value)) for value in values), start=Decimal())
    except (InvalidOperation, TypeError, ValueError):
        return "0"
    return format(total, "f") if total.is_finite() else "0"


def _normalise_history_timestamp(value: Any) -> str:
    """Convert OpenAlgo epoch seconds/milliseconds to an aware UTC ISO value."""
    if isinstance(value, bool):
        raise ValueError("history timestamp must be an ISO string or numeric epoch")
    if isinstance(value, int | float):
        epoch = float(value)
        if not math.isfinite(epoch):
            raise ValueError("history timestamp must be finite")
        if abs(epoch) >= 100_000_000_000:
            epoch /= 1000.0
        try:
            return datetime.fromtimestamp(epoch, tz=UTC).isoformat()
        except (OSError, OverflowError, ValueError) as exc:
            raise ValueError("history timestamp is outside the supported range") from exc
    if isinstance(value, str):
        return value
    raise ValueError("history timestamp must be an ISO string or numeric epoch")


_OPTION_EXPIRY_FORMATS = (
    "%Y-%m-%d",
    "%Y%m%d",
    "%d%b%y",
    "%d%b%Y",
    "%d-%b-%y",
    "%d-%b-%Y",
)
_OPTION_EXPIRY_MONTHS = (
    "JAN",
    "FEB",
    "MAR",
    "APR",
    "MAY",
    "JUN",
    "JUL",
    "AUG",
    "SEP",
    "OCT",
    "NOV",
    "DEC",
)


def _normalise_option_expiry_identity(value: Any) -> str | None:
    """Normalise an explicit broker expiry without coercing non-strings."""
    if not isinstance(value, str) or not (text := value.strip()):
        return None
    for expiry_format in _OPTION_EXPIRY_FORMATS:
        try:
            return datetime.strptime(text.upper(), expiry_format).date().isoformat()
        except ValueError:
            continue
    return None


def _openalgo_option_expiry_date(value: str) -> str:
    """Format an expiry as OpenAlgo OptionChainSchema DDMMMYY (e.g. 26MAR26)."""
    identity = _normalise_option_expiry_identity(value)
    if identity is None:
        return value.strip()
    year, month, day = identity.split("-")
    return f"{int(day):02d}{_OPTION_EXPIRY_MONTHS[int(month) - 1]}{year[2:]}"


def _openalgo_option_offset(value: str) -> str:
    """Return an official OptionSymbolSchema offset (ATM / ITM1-50 / OTM1-50)."""
    offset = str(value or "").strip().upper()
    if offset == "ATM":
        return offset
    if offset.startswith(("ITM", "OTM")):
        suffix = offset[3:]
        if suffix.isdigit():
            number = int(suffix)
            if 1 <= number <= 50:
                return f"{offset[:3]}{number}"
    raise ValueError("offset must be ATM, ITM1-ITM50, or OTM1-OTM50")


def _validated_openalgo_option_expiry_identity(
    data: dict[str, Any],
    requested_expiry: str,
) -> dict[str, str]:
    """Return broker-observed expiry fields only when they identify one request."""
    observed = {
        key: data[key]
        for key in ("expiry", "expiry_date")
        if key in data
    }
    if not observed:
        raise ValueError("OpenAlgo option-chain expiry identity is missing")

    normalised: dict[str, str] = {}
    preserved: dict[str, str] = {}
    for key, value in observed.items():
        identity = _normalise_option_expiry_identity(value)
        if identity is None:
            raise ValueError(f"OpenAlgo option-chain {key} expiry identity is invalid")
        normalised[key] = identity
        preserved[key] = value.strip()

    if len(set(normalised.values())) != 1:
        raise ValueError("OpenAlgo option-chain expiry identity fields conflict")

    if requested_expiry:
        requested_identity = _normalise_option_expiry_identity(requested_expiry)
        if requested_identity is None:
            raise ValueError("requested OpenAlgo option-chain expiry identity is invalid")
        if next(iter(normalised.values())) != requested_identity:
            raise ValueError("OpenAlgo option-chain expiry identity conflicts with the request")
    return preserved


def _normalise_calendar_date(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _normalise_open_exchange(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    exchange = str(value.get("exchange") or "").strip().upper()
    if not exchange:
        return None
    session: dict[str, Any] = {"exchange": exchange}
    for field_name in ("start_time", "end_time"):
        if field_name in value:
            session[field_name] = value[field_name]
    symbol = str(value.get("symbol") or "").strip().upper()
    if symbol:
        session["symbol"] = symbol
    raw_symbols = value.get("symbols")
    if isinstance(raw_symbols, list | tuple | set):
        symbols = sorted(
            {
                str(candidate).strip().upper()
                for candidate in raw_symbols
                if str(candidate).strip()
            }
        )
        if symbols:
            session["symbols"] = symbols
    return session


def is_authoritative_market_calendar(
    payload: Any,
    *,
    expected_year: int | None = None,
) -> bool:
    """Return whether a calendar response is complete enough to replace live state."""
    data = payload
    for _ in range(4):
        if not isinstance(data, dict):
            break
        if "status" in data:
            if str(data["status"]).strip().lower() not in {"ok", "success"}:
                return False
        if "year" in data:
            try:
                response_year = int(data["year"])
            except (TypeError, ValueError):
                return False
            if expected_year is not None and response_year != expected_year:
                return False
        if "data" in data:
            data = data["data"]
            continue
        if "holidays" in data:
            data = data["holidays"]
            continue
        break

    candidates: list[Any]
    if isinstance(data, list | tuple | set):
        candidates = list(data)
    elif isinstance(data, dict):
        if not data:
            return False
        candidates = []
        for values in data.values():
            if not isinstance(values, list | tuple | set):
                return False
            candidates.extend(values)
    else:
        return False

    if not candidates:
        # An HTTP-success envelope with no calendar rows is indistinguishable
        # from OpenAlgo's pre-authentication placeholder. It must not replace a
        # fail-closed year with an all-open calendar.
        return False

    for candidate in candidates:
        if isinstance(candidate, dict):
            raw_date = candidate.get("date") or candidate.get("holiday_date") or candidate.get(
                "trading_date"
            )
            if _normalise_calendar_date(raw_date) is None:
                return False
            if "holiday_type" in candidate:
                holiday_type = str(candidate["holiday_type"] or "").strip().upper()
                if holiday_type not in {
                    "SETTLEMENT_HOLIDAY",
                    "SPECIAL_SESSION",
                    "TRADING_HOLIDAY",
                }:
                    return False
            raw_closed = candidate.get("closed_exchanges", [])
            if "closed_exchanges" in candidate and not isinstance(
                raw_closed, list | tuple | set
            ):
                return False
            if any(not isinstance(value, str) or not value.strip() for value in raw_closed):
                return False
            raw_open = candidate.get("open_exchanges", [])
            if "open_exchanges" in candidate and not isinstance(raw_open, list | tuple):
                return False
            if any(_normalise_open_exchange(value) is None for value in raw_open):
                return False
        elif _normalise_calendar_date(candidate) is None:
            return False
    return True


def normalise_market_calendar(payload: Any) -> list[dict[str, Any]]:
    """Return validated calendar rows without discarding exchange semantics."""
    data = payload
    for _ in range(3):
        if not isinstance(data, dict) or "data" not in data:
            break
        data = data["data"]

    records: dict[str, dict[str, Any]] = {}

    def add_entry(entry: Any, *, default_exchange: str = "*") -> None:
        if isinstance(entry, dict):
            raw_date = entry.get("date") or entry.get("holiday_date") or entry.get(
                "trading_date"
            )
        else:
            raw_date = entry
        holiday_date = _normalise_calendar_date(raw_date)
        if holiday_date is None:
            return

        current_contract = isinstance(entry, dict) and any(
            field_name in entry
            for field_name in ("holiday_type", "closed_exchanges", "open_exchanges")
        )
        description = str(entry.get("description") or "") if isinstance(entry, dict) else ""
        holiday_type = (
            str(entry.get("holiday_type") or "TRADING_HOLIDAY").strip().upper()
            if isinstance(entry, dict)
            else "TRADING_HOLIDAY"
        )
        closed_exchanges: set[str]
        open_exchanges: list[dict[str, Any]] = []
        if current_contract:
            raw_closed = entry.get("closed_exchanges", [])
            closed_exchanges = (
                {
                    str(candidate).strip().upper()
                    for candidate in raw_closed
                    if str(candidate).strip()
                }
                if isinstance(raw_closed, list | tuple | set)
                else set()
            )
            raw_open = entry.get("open_exchanges", [])
            if isinstance(raw_open, list | tuple):
                open_exchanges = [
                    session
                    for candidate in raw_open
                    if (session := _normalise_open_exchange(candidate)) is not None
                ]
            if holiday_type != "SETTLEMENT_HOLIDAY" and not closed_exchanges:
                closed_exchanges = {"*"}
        else:
            closed_exchanges = {default_exchange}

        record = records.setdefault(
            holiday_date,
            {
                "date": holiday_date,
                "description": description,
                "holiday_type": holiday_type,
                "closed_exchanges": set(),
                "open_exchanges": [],
            },
        )
        if description and not record["description"]:
            record["description"] = description
        if holiday_type == "SPECIAL_SESSION" or record["holiday_type"] == "SETTLEMENT_HOLIDAY":
            record["holiday_type"] = holiday_type
        record["closed_exchanges"].update(closed_exchanges)
        for session in open_exchanges:
            if session not in record["open_exchanges"]:
                record["open_exchanges"].append(session)

    if isinstance(data, dict) and "holidays" in data:
        data = data["holidays"]

    if isinstance(data, list | tuple | set):
        for candidate in data:
            add_entry(candidate)
    elif isinstance(data, dict):
        for exchange, candidates in data.items():
            exchange_key = str(exchange).strip().upper()
            if not exchange_key or not isinstance(candidates, list | tuple | set):
                continue
            for candidate in candidates:
                add_entry(candidate, default_exchange=exchange_key)

    normalised: list[dict[str, Any]] = []
    for holiday_date in sorted(records):
        record = records[holiday_date]
        normalised.append(
            {
                **record,
                "closed_exchanges": sorted(record["closed_exchanges"]),
                "open_exchanges": list(record["open_exchanges"]),
            }
        )
    return normalised


def normalise_holiday_dates(payload: Any, exchange: str = "NSE") -> list[str]:
    """Return full-closure dates for one exchange from old/current envelopes."""
    exchange_key = str(exchange or "NSE").strip().upper() or "NSE"
    calendar_exchange = _CALENDAR_EXCHANGE_ALIASES.get(exchange_key, exchange_key)
    dates: list[str] = []
    for row in normalise_market_calendar(payload):
        closed = set(row["closed_exchanges"])
        has_open_session = any(
            session.get("exchange") == calendar_exchange
            for session in row["open_exchanges"]
        )
        if not has_open_session and ("*" in closed or calendar_exchange in closed):
            dates.append(row["date"])
    return dates


# ---------------------------------------------------------------------------
# Token-bucket rate limiter (async-compatible)
# ---------------------------------------------------------------------------

class _RateLimiter:
    """Simple token-bucket rate limiter with async acquire."""

    def __init__(self, rate: float, per: float = 1.0) -> None:
        self.rate = rate
        self.per = per
        self.tokens = rate
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._last = now
            self.tokens = min(self.rate, self.tokens + elapsed * self.rate / self.per)
            if self.tokens < 1:
                sleep_time = (1 - self.tokens) * self.per / self.rate
                await asyncio.sleep(sleep_time)
                self.tokens = 0
            else:
                self.tokens -= 1


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class OpenAlgoClient:
    """Async client for all OpenAlgo v1 REST endpoints.

    Features:
    - Automatic retry with exponential backoff (3 attempts)
    - Per-category rate limiting (orders: 10/s, smart: 2/s, general: 50/s)
    - Typed request/response models
    - Structured logging
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self._base = f"{openalgo_rest_base_url(self.settings)}/api/v1"
        self._http = httpx.AsyncClient(timeout=30.0)
        self._api_key = self.settings.openalgo_api_key

        # Rate limiters per category
        self._order_limiter = _RateLimiter(10, 1.0)
        self._smart_limiter = _RateLimiter(2, 1.0)
        self._general_limiter = _RateLimiter(50, 1.0)

        # Owner event loop for sync callers (created lazily by run_sync).
        # httpx pools keep-alive connections that are AFFINE to the loop they
        # were created on; driving one shared client from a fresh
        # asyncio.run()/new_event_loop() per request reuses a connection whose
        # transport belongs to an already-closed loop and fails with
        # "Event loop is closed" on alternating requests. All sync entry
        # points must marshal onto this single persistent loop instead.
        self._owner_loop: asyncio.AbstractEventLoop | None = None
        self._owner_thread: threading.Thread | None = None
        self._owner_guard = threading.RLock()
        self._close_guard = threading.Lock()
        self._config_guard = threading.RLock()
        self._closing = False
        self._closed = False

    def reconfigure(self, settings: Settings) -> OpenAlgoClient:
        """Atomically update endpoint and credentials without replacing this client.

        The broker router, schedulers, cron jobs and Telegram all retain this
        object. Updating it in place keeps every caller on one connection owner
        instead of closing an object that those live services still reference.
        """
        base = f"{openalgo_rest_base_url(settings)}/api/v1"
        api_key = settings.openalgo_api_key
        with self._config_guard:
            self.settings = settings
            self._base = base
            self._api_key = api_key
        return self

    def _ensure_owner_loop(self) -> asyncio.AbstractEventLoop:
        """Start (once) and return the client's dedicated event loop."""
        with self._owner_guard:
            if self._closing:
                raise RuntimeError("OpenAlgo client is shutting down")
            if self._owner_loop is None or self._owner_loop.is_closed():
                loop = asyncio.new_event_loop()
                thread = threading.Thread(
                    target=loop.run_forever,
                    daemon=True,
                    name="openalgo-client-loop",
                )
                thread.start()
                self._owner_loop = loop
                self._owner_thread = thread
            return self._owner_loop

    def run_sync(self, coro: Any, timeout: float = 45.0) -> Any:
        """Run one of THIS client's coroutines from synchronous code.

        The coroutine executes on the client's own persistent event loop, so
        pooled connections always live and die on one loop — never drive this
        client through ad-hoc ``asyncio.run()`` loops. Thread-safe; for Flask
        request threads, cron jobs and background schedulers.

        Args:
            coro: A coroutine created from this client's async API.
            timeout: Seconds to wait for completion.

        Returns:
            The coroutine's result.

        Raises:
            TimeoutError: When the call does not finish within ``timeout``
                (the underlying task is cancelled).
        """
        try:
            with self._owner_guard:
                owner_loop = self._ensure_owner_loop()
                future = asyncio.run_coroutine_threadsafe(coro, owner_loop)
        except Exception:
            close_coro = getattr(coro, "close", None)
            if callable(close_coro):
                close_coro()
            raise
        try:
            return future.result(timeout)
        except FuturesTimeoutError as exc:
            future.cancel()
            raise TimeoutError(f"OpenAlgo call timed out after {timeout:.0f}s") from exc

    async def _run_on_owner(self, coro: Any) -> Any:
        """Await one HTTP operation on this client's dedicated owner loop."""
        current_loop = asyncio.get_running_loop()
        run_directly = False
        future: Any | None = None
        try:
            with self._owner_guard:
                owner_loop = self._owner_loop
                owner_active = owner_loop is not None and not owner_loop.is_closed()
                if owner_active and current_loop is owner_loop:
                    run_directly = True
                else:
                    owner_loop = self._ensure_owner_loop()
                    future = asyncio.run_coroutine_threadsafe(coro, owner_loop)
        except Exception:
            close_coro = getattr(coro, "close", None)
            if callable(close_coro):
                close_coro()
            raise
        if run_directly:
            return await coro
        assert future is not None
        try:
            return await asyncio.wrap_future(future)
        except asyncio.CancelledError:
            future.cancel()
            raise

    async def _drain_owner_and_close(self, drain_timeout: float) -> None:
        """Finish active owner work, cancel overdue tasks, then close HTTP."""
        current = asyncio.current_task()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.0, drain_timeout)
        while True:
            pending = [
                task
                for task in asyncio.all_tasks(loop)
                if task is not current and not task.done()
            ]
            if not pending:
                break
            remaining = deadline - loop.time()
            if remaining <= 0:
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                break
            await asyncio.wait(pending, timeout=remaining)
        await self._http.aclose()

    async def close(self) -> None:
        """Close the client on its HTTP owner loop."""
        await self.shutdown()

    async def shutdown(self) -> None:
        """Close on the loop that owns active connections and stop sync ownership."""
        with self._owner_guard:
            if self._closed:
                return
            self._closing = True
            owner_loop = self._owner_loop
            owner_loop_active = owner_loop is not None and not owner_loop.is_closed()
        if owner_loop_active and asyncio.get_running_loop() is owner_loop:
            raise RuntimeError("OpenAlgo owner-loop shutdown must be initiated externally")
        await asyncio.to_thread(self.close_sync)

    def close_sync(self, timeout: float = 50.0) -> None:
        """Close from synchronous code, tearing down the owner loop if any.

        Short-lived clients used by sync callers (``resolve_openalgo_client``
        fallbacks) must close on the SAME loop that served their requests —
        closing on a second fresh loop is the same cross-loop bug in reverse.
        """
        with self._close_guard:
            with self._owner_guard:
                if self._closed:
                    return
                self._closing = True
                loop = self._owner_loop
                thread = self._owner_thread
            if loop is not None and not loop.is_closed():
                if threading.current_thread() is thread:
                    raise RuntimeError("close_sync cannot run on the OpenAlgo owner thread")
                future = asyncio.run_coroutine_threadsafe(
                    self._drain_owner_and_close(max(0.0, timeout - 5.0)),
                    loop,
                )
                try:
                    future.result(timeout)
                except Exception:
                    future.cancel()
                    raise
                loop.call_soon_threadsafe(loop.stop)
                if thread is not None:
                    thread.join(timeout=5)
                    if thread.is_alive():
                        raise RuntimeError("OpenAlgo owner loop did not stop")
                loop.close()
                with self._owner_guard:
                    if self._owner_loop is loop:
                        self._owner_loop = None
                        self._owner_thread = None
            else:
                # No HTTP operation has claimed an owner loop yet.
                asyncio.run(self._http.aclose())
            with self._owner_guard:
                self._closed = True

    async def __aenter__(self) -> OpenAlgoClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _body(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """Build request body with apikey injected."""
        with self._config_guard:
            api_key = self._api_key
        payload: dict[str, Any] = {"apikey": api_key}
        if extra:
            payload.update(extra)
        return payload

    @staticmethod
    def _unwrap(data: Any) -> Any:
        """Unwrap OpenAlgo's nested response format.

        OpenAlgo wraps responses as {"status": "success", "data": <payload>}.
        This extracts the "data" value if present, otherwise returns as-is.
        """
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return data

    async def _post(
        self,
        endpoint: str,
        payload: dict[str, Any],
        *,
        limiter: _RateLimiter | None = None,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """POST with retry + exponential backoff."""
        return await self._run_on_owner(
            self._post_on_owner(
                endpoint,
                payload,
                limiter=limiter,
                max_retries=max_retries,
            )
        )

    async def _post_on_owner(
        self,
        endpoint: str,
        payload: dict[str, Any],
        *,
        limiter: _RateLimiter | None = None,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """Execute one POST on the dedicated HTTP owner loop."""
        with self._config_guard:
            url = f"{self._base}/{endpoint}"
            request_payload = dict(payload)
            if "apikey" in request_payload:
                request_payload["apikey"] = self._api_key
        rl = limiter or self._general_limiter
        await rl.acquire()

        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                logger.debug("POST %s attempt=%d", endpoint, attempt)
                resp = await self._http.post(url, json=request_payload)

                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", "1"))
                    raise OpenAlgoRateLimitError(endpoint, retry_after)
                if resp.status_code in (401, 403):
                    data = resp.json() if resp.content else {}
                    raise OpenAlgoAuthError(
                        endpoint,
                        data.get("message", "Authentication failed"),
                        status_code=resp.status_code,
                    )
                if resp.status_code >= 400:
                    data = resp.json() if resp.content else {}
                    raise APIError(resp.status_code, data.get("message", resp.text), endpoint)

                data = resp.json()
                if isinstance(data, dict) and data.get("status") == "error":
                    raise APIError(resp.status_code, data.get("message", "Unknown error"), endpoint)
                return data

            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < max_retries:
                    wait = 2 ** (attempt - 1)
                    logger.warning("Retry %s in %ds: %s", endpoint, wait, exc)
                    await asyncio.sleep(wait)
            except OpenAlgoRateLimitError:
                last_exc = None
                if attempt < max_retries:
                    wait = 2 ** (attempt - 1)
                    logger.warning("Rate limited on %s, retry in %ds", endpoint, wait)
                    await asyncio.sleep(wait)
                else:
                    raise

        raise APIError(0, f"Failed after {max_retries} retries: {last_exc}", endpoint)

    async def _get(self, endpoint: str, *, params: dict[str, str] | None = None, headers: dict[str, str] | None = None) -> Any:
        """Marshal one GET onto the dedicated HTTP owner loop."""
        return await self._run_on_owner(
            self._get_on_owner(endpoint, params=params, headers=headers)
        )

    async def _get_on_owner(
        self,
        endpoint: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Execute one GET with retry on the dedicated HTTP owner loop."""
        with self._config_guard:
            url = f"{self._base}/{endpoint}"
            request_headers = dict(headers or {})
            for name in tuple(request_headers):
                if name.lower() in {"x-api-key", "x-api_key"}:
                    request_headers[name] = self._api_key
        await self._general_limiter.acquire()

        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                resp = await self._http.get(url, params=params, headers=request_headers)
                if resp.status_code >= 400:
                    raise APIError(resp.status_code, resp.text, endpoint)
                return resp.json()
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < 3:
                    await asyncio.sleep(2 ** (attempt - 1))
        raise APIError(0, f"GET failed after 3 retries: {last_exc}", endpoint)

    # ==================================================================
    # Order APIs
    # ==================================================================

    async def place_order(self, order: Order) -> OrderResponse:
        """POST /api/v1/placeorder"""
        extras: dict[str, Any] = {
            "strategy": order.strategy,
            "symbol": order.symbol,
            "action": order.action.value,
            "exchange": order.exchange.value,
            "pricetype": order.pricetype.value,
            "product": order.product.value,
            "quantity": order.quantity,
            "price": order.price,
            "trigger_price": order.trigger_price,
            "disclosed_quantity": order.disclosed_quantity,
        }
        payload = self._body(extras)
        data = await self._post("placeorder", payload, limiter=self._order_limiter)
        return OrderResponse(**data)

    async def place_smart_order(self, order: SmartOrder) -> OrderResponse:
        """POST /api/v1/placesmartorder"""
        extras: dict[str, Any] = {
            "strategy": order.strategy,
            "symbol": order.symbol,
            "action": order.action.value,
            "exchange": order.exchange.value,
            "pricetype": order.pricetype.value,
            "product": order.product.value,
            "quantity": order.quantity,
            "price": order.price,
            "trigger_price": order.trigger_price,
            "disclosed_quantity": order.disclosed_quantity,
            "position_size": order.position_size,
        }
        payload = self._body(extras)
        data = await self._post("placesmartorder", payload, limiter=self._smart_limiter)
        return OrderResponse(**data)

    async def place_options_order(self, order: OptionsOrder) -> OrderResponse:
        """POST /api/v1/optionsorder"""
        payload = self._body({
            "strategy": order.strategy,
            "underlying": order.underlying,
            "exchange": order.exchange.value,
            "expiry_date": order.expiry_date,
            "offset": order.offset,
            "option_type": order.option_type.value,
            "action": order.action.value,
            "quantity": order.quantity,
            "pricetype": order.pricetype.value,
            "product": order.product.value,
            "splitsize": order.splitsize,
        })
        data = await self._post("optionsorder", payload, limiter=self._order_limiter)
        return OrderResponse(**data)

    async def place_options_multi_order(self, order: OptionsMultiOrder) -> OrderResponse:
        """POST /api/v1/optionsmultiorder"""
        legs = [
            {
                "offset": leg.offset,
                "option_type": leg.option_type.value,
                "action": leg.action.value,
                "quantity": leg.quantity,
                "pricetype": order.pricetype.value,
                "product": order.product.value,
            }
            for leg in order.legs
        ]
        payload = self._body({
            "strategy": order.strategy,
            "underlying": order.underlying,
            "exchange": order.exchange.value,
            "expiry_date": order.expiry_date,
            "legs": legs,
        })
        data = await self._post("optionsmultiorder", payload, limiter=self._order_limiter)
        return OrderResponse(**data)

    async def place_basket_order(self, basket: BasketOrder) -> OrderResponse:
        """POST /api/v1/basketorder"""
        orders = [
            {
                "symbol": o.symbol,
                "exchange": o.exchange.value,
                "action": o.action.value,
                "quantity": o.quantity,
                "pricetype": o.pricetype.value,
                "product": o.product.value,
            }
            for o in basket.orders
        ]
        payload = self._body({"strategy": basket.strategy, "orders": orders})
        data = await self._post("basketorder", payload, limiter=self._order_limiter)
        return OrderResponse(**data)

    async def place_split_order(self, order: SplitOrder) -> OrderResponse:
        """POST /api/v1/splitorder"""
        payload = self._body({
            "strategy": order.strategy,
            "symbol": order.symbol,
            "action": order.action.value,
            "exchange": order.exchange.value,
            "pricetype": order.pricetype.value,
            "product": order.product.value,
            "quantity": order.quantity,
            "price": order.price,
            "trigger_price": order.trigger_price,
            "disclosed_quantity": order.disclosed_quantity,
            "splitsize": order.splitsize,
        })
        data = await self._post("splitorder", payload, limiter=self._order_limiter)
        return OrderResponse(**data)

    async def modify_order(self, order: ModifyOrder) -> OrderResponse:
        """POST /api/v1/modifyorder"""
        payload = self._body({
            "strategy": order.strategy,
            "orderid": order.orderid,
            "symbol": order.symbol,
            "exchange": order.exchange.value,
            "action": order.action.value,
            "pricetype": order.pricetype.value,
            "product": order.product.value,
            "quantity": order.quantity,
            "price": order.price,
            "trigger_price": order.trigger_price,
            "disclosed_quantity": order.disclosed_quantity,
        })
        data = await self._post("modifyorder", payload, limiter=self._order_limiter)
        return OrderResponse(**data)

    async def cancel_order(self, orderid: str, strategy: str = "Flint") -> OrderResponse:
        """POST /api/v1/cancelorder"""
        payload = self._body({"strategy": strategy, "orderid": orderid})
        data = await self._post("cancelorder", payload, limiter=self._order_limiter)
        return OrderResponse(**data)

    async def cancel_all_orders(self, strategy: str = "Flint") -> OrderResponse:
        """POST /api/v1/cancelallorder"""
        payload = self._body({"strategy": strategy})
        data = await self._post("cancelallorder", payload, limiter=self._order_limiter)
        return OrderResponse(**data)

    async def close_position(self, strategy: str = "Flint") -> OrderResponse:
        """POST /api/v1/closeposition"""
        payload = self._body({"strategy": strategy})
        data = await self._post("closeposition", payload, limiter=self._order_limiter)
        return OrderResponse(**data)

    async def order_status(self, orderid: str, strategy: str = "Flint") -> OrderStatus:
        """POST /api/v1/orderstatus"""
        payload = self._body({"strategy": strategy, "orderid": orderid})
        data = self._unwrap(await self._post("orderstatus", payload))
        return OrderStatus(**data) if isinstance(data, dict) else OrderStatus()

    async def open_position(
        self, symbol: str, exchange: str = "NSE", product: str = "MIS", strategy: str = "Flint"
    ) -> dict[str, Any]:
        """POST /api/v1/openposition"""
        payload = self._body({
            "strategy": strategy,
            "symbol": symbol,
            "exchange": exchange,
            "product": product,
        })
        return await self._post("openposition", payload)

    # ==================================================================
    # Data APIs
    # ==================================================================

    async def quotes(self, symbol: str, exchange: str = "NSE") -> Quote:
        """POST /api/v1/quotes"""
        payload = self._body({"symbol": symbol, "exchange": exchange})
        data = self._unwrap(await self._post("quotes", payload))
        return Quote(**data) if isinstance(data, dict) else Quote()

    async def multi_quotes(self, symbols: list[dict[str, str]]) -> list[Quote]:
        """POST /api/v1/multiquotes — symbols=[{"symbol": "X", "exchange": "NSE"}, ...]"""
        payload = self._body({"symbols": symbols})
        raw = await self._post("multiquotes", payload)
        data = raw.get("results") if isinstance(raw, dict) and "results" in raw else self._unwrap(raw)
        if not isinstance(data, list):
            return []

        quotes: list[Quote] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            nested = item.get("data")
            if isinstance(nested, dict):
                normalised = dict(nested)
                for field in ("symbol", "exchange"):
                    if field in item:
                        normalised[field] = item[field]
            elif "data" in item or "error" in item:
                continue
            else:
                normalised = dict(item)
            quotes.append(Quote(**normalised))
        return quotes

    async def depth(self, symbol: str, exchange: str = "NSE") -> Depth:
        """POST /api/v1/depth"""
        payload = self._body({"symbol": symbol, "exchange": exchange})
        data = self._unwrap(await self._post("depth", payload))
        if not isinstance(data, dict):
            return Depth()
        bids = [DepthLevel(**b) for b in data.get("bids", [])]
        asks = [DepthLevel(**a) for a in data.get("asks", [])]
        return Depth(
            symbol=data.get("symbol", symbol),
            exchange=data.get("exchange", exchange),
            bids=bids,
            asks=asks,
        )

    async def history(
        self,
        symbol: str,
        exchange: str = "NSE",
        interval: str = "5m",
        start_date: str = "",
        end_date: str = "",
    ) -> list[OHLCV]:
        """POST /api/v1/history"""
        payload = self._body({
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "start_date": start_date,
            "end_date": end_date,
        })
        data = self._unwrap(await self._post("history", payload))
        if isinstance(data, list):
            bars: list[OHLCV] = []
            for bar in data:
                if not isinstance(bar, dict):
                    continue
                normalised = dict(bar)
                normalised["timestamp"] = _normalise_history_timestamp(
                    normalised.get("timestamp")
                )
                bars.append(OHLCV(**normalised))
            return bars
        return []

    async def intervals(self) -> dict[str, Any]:
        """POST /api/v1/intervals"""
        data = self._unwrap(await self._post("intervals", self._body()))
        return data if isinstance(data, dict) else {}

    async def option_chain(self, symbol: str, exchange: str = "NFO", expiry: str = "") -> OptionChain:
        """POST /api/v1/optionchain"""
        expiry_date = str(expiry or "").strip()
        if not expiry_date:
            raise ValueError("expiry_date is required")
        payload_data: dict[str, Any] = {
            "underlying": symbol,
            "exchange": exchange,
            "expiry_date": _openalgo_option_expiry_date(expiry_date),
        }
        payload = self._body(payload_data)
        data = self._unwrap(await self._post("optionchain", payload))
        if isinstance(data, dict):
            expiry_identity = _validated_openalgo_option_expiry_identity(data, expiry)
            raw_strikes = data.get("strikes", data.get("chain", []))
            if not isinstance(raw_strikes, list):
                raise ValueError("OpenAlgo option-chain rows must be a list")
            normalised_strikes: list[dict[str, Any]] = []
            for strike in raw_strikes:
                if not isinstance(strike, dict):
                    raise ValueError("OpenAlgo option-chain source row is not an object")
                if "ce" in strike or "pe" in strike:
                    if any(side in strike and not isinstance(strike[side], dict) for side in ("ce", "pe")):
                        raise ValueError("OpenAlgo option-chain leg is not an object")
                    ce = strike.get("ce") if isinstance(strike.get("ce"), dict) else {}
                    pe = strike.get("pe") if isinstance(strike.get("pe"), dict) else {}
                    normalised: dict[str, Any] = {
                        "strike_price": strike.get("strike", strike.get("strike_price", 0.0)),
                    }
                    aliases = {
                        "ltp": ("ltp", "last_price"),
                        "oi": ("oi", "open_interest"),
                        "volume": ("volume",),
                        "iv": ("iv", "implied_volatility"),
                    }
                    for prefix, leg in (("ce", ce), ("pe", pe)):
                        for field, source_names in aliases.items():
                            for source_name in source_names:
                                if source_name in leg:
                                    normalised[f"{prefix}_{field}"] = leg[source_name]
                                    break
                    normalised_strikes.append(normalised)
                else:
                    normalised_strikes.append(strike)
            strikes = [OptionChainStrike(**s) for s in normalised_strikes]
            option_chain: dict[str, Any] = {
                "underlying": data.get("underlying", data.get("symbol", symbol)),
                "exchange": data.get("exchange", exchange),
                "strikes": strikes,
            }
            option_chain.update(expiry_identity)
            for spot_field in ("spot_price", "spot", "underlying_spot_price", "underlying_ltp"):
                if spot_field in data:
                    option_chain["spot_price"] = data[spot_field]
                    break
            return OptionChain(**option_chain)
        return OptionChain()

    async def option_greeks(self, symbol: str, exchange: str = "NFO") -> OptionGreek:
        """POST /api/v1/optiongreeks"""
        payload = self._body({"symbol": symbol, "exchange": exchange})
        data = self._unwrap(await self._post("optiongreeks", payload))
        return self._parse_option_greek(data, endpoint="optiongreeks")

    async def multi_option_greeks(self, symbols: list[dict[str, str]]) -> list[OptionGreek]:
        """POST /api/v1/multioptiongreeks"""
        payload = self._body({"symbols": symbols})
        data = self._unwrap(await self._post("multioptiongreeks", payload))
        if not isinstance(data, list) or len(data) != len(symbols):
            raise APIError(502, "incomplete option Greek batch", "multioptiongreeks")
        parsed = [
            self._parse_option_greek(item, endpoint="multioptiongreeks")
            for item in data
        ]
        expected = {
            (str(item.get("exchange") or "").upper(), str(item.get("symbol") or ""))
            for item in symbols
        }
        actual = {(item.exchange.upper(), item.symbol) for item in parsed}
        if len(expected) != len(symbols) or actual != expected:
            raise APIError(502, "incomplete option Greek batch", "multioptiongreeks")
        return parsed

    @staticmethod
    def _parse_option_greek(data: Any, *, endpoint: str) -> OptionGreek:
        if not isinstance(data, dict) or str(data.get("status") or "success").lower() != "success":
            raise APIError(502, "incomplete option Greek batch", endpoint)
        greeks = data.get("greeks") if isinstance(data.get("greeks"), dict) else data
        required = ("delta", "gamma", "theta", "vega")
        if any(name not in greeks or greeks[name] is None for name in required):
            raise APIError(502, "incomplete option Greek batch", endpoint)
        try:
            values = {name: float(greeks[name]) for name in required}
            rho = float(greeks.get("rho", 0.0))
            iv = float(data.get("implied_volatility", data.get("iv", 0.0)))
        except (TypeError, ValueError) as exc:
            raise APIError(502, "invalid option Greek values", endpoint) from exc
        if not all(math.isfinite(value) for value in (*values.values(), rho, iv)):
            raise APIError(502, "invalid option Greek values", endpoint)
        symbol = str(data.get("symbol") or "")
        exchange = str(data.get("exchange") or "").upper()
        if not symbol or not exchange:
            raise APIError(502, "incomplete option Greek identity", endpoint)
        return OptionGreek(
            symbol=symbol,
            exchange=exchange,
            delta=values["delta"],
            gamma=values["gamma"],
            theta=values["theta"],
            vega=values["vega"],
            iv=iv,
            rho=rho,
        )

    async def portfolio_greeks(
        self,
        positions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Return complete per-contract Delta/Vega rows for portfolio admission."""
        requested = [
            {
                "symbol": str(position.get("symbol") or ""),
                "exchange": str(position.get("exchange") or "").upper(),
            }
            for position in positions
        ]
        parsed = await self.multi_option_greeks(requested)
        by_key = {(item.exchange.upper(), item.symbol): item for item in parsed}
        return [
            {
                "symbol": request["symbol"],
                "instrument_id": str(position.get("instrument_id") or ""),
                "exchange": request["exchange"],
                "delta": by_key[(request["exchange"], request["symbol"])].delta,
                "vega": by_key[(request["exchange"], request["symbol"])].vega,
            }
            for position, request in zip(positions, requested, strict=True)
        ]

    async def option_symbol(
        self,
        symbol: str,
        exchange: str = "NFO",
        expiry_date: str = "",
        offset: str = "0",
        option_type: str = "CE",
    ) -> dict[str, Any]:
        """POST /api/v1/optionsymbol"""
        expiry = str(expiry_date or "").strip()
        if not expiry:
            raise ValueError("expiry_date is required")
        payload = self._body({
            "underlying": symbol,
            "exchange": exchange,
            "expiry_date": _openalgo_option_expiry_date(expiry),
            "offset": _openalgo_option_offset(offset),
            "option_type": option_type,
        })
        return await self._post("optionsymbol", payload)

    async def synthetic_future(self, symbol: str, exchange: str = "NFO", expiry_date: str = "") -> dict[str, Any]:
        """POST /api/v1/syntheticfuture"""
        expiry = str(expiry_date or "").strip()
        if not expiry:
            raise ValueError("expiry_date is required")
        payload = self._body({
            "underlying": symbol,
            "exchange": exchange,
            "expiry_date": _openalgo_option_expiry_date(expiry),
        })
        return await self._post("syntheticfuture", payload)

    async def expiry(self, symbol: str, exchange: str = "NFO", instrumenttype: str = "") -> dict[str, Any]:
        """POST /api/v1/expiry"""
        kind = str(instrumenttype or "").strip().lower()
        if kind not in {"futures", "options"}:
            raise ValueError("instrumenttype is required")
        payload = self._body({"symbol": symbol, "exchange": exchange, "instrumenttype": kind})
        return await self._post("expiry", payload)

    async def symbol(self, symbol: str, exchange: str = "NSE") -> dict[str, Any]:
        """POST /api/v1/symbol"""
        payload = self._body({"symbol": symbol, "exchange": exchange})
        return await self._post("symbol", payload)

    async def search(
        self,
        query: str,
        exchange: str | None = None,
    ) -> dict[str, Any]:
        """POST /api/v1/search.

        Args:
            query: Search query / symbol prefix.
            exchange: Optional exchange filter. Upstream accepts a single
                exchange code (e.g. ``"NSE"``) and validates it against
                ``VALID_EXCHANGES``. Pass ``None`` (default) to search
                across all exchanges; this preserves the v0.5.0 behaviour.
                Mirrors the upstream OpenAlgo v2.0.1.x ``SearchSchema``.
        """
        body: dict[str, Any] = {"query": query}
        if exchange:
            body["exchange"] = exchange
        return await self._post("search", self._body(body))

    async def ticker(self, exchange: str, symbol: str, interval: str = "5m", from_date: str = "", to_date: str = "") -> Any:
        """GET /api/v1/ticker/{exchange}:{symbol}"""
        start = str(from_date or "").strip()
        end = str(to_date or "").strip()
        if not start or not end:
            raise ValueError("from and to dates are required")
        endpoint = f"ticker/{exchange}:{symbol}"
        with self._config_guard:
            api_key = self._api_key
        params: dict[str, str] = {
            "apikey": api_key,
            "interval": interval,
            "from": start,
            "to": end,
        }
        return await self._get(endpoint, params=params)

    # ==================================================================
    # Account APIs
    # ==================================================================

    async def funds(self) -> Fund:
        """POST /api/v1/funds"""
        raw = await self._post("funds", self._body())
        data = self._unwrap(raw)
        if isinstance(data, dict):
            # Current OpenAlgo uses ``utiliseddebits``; retain the older aliases
            # accepted by FlintTrade's bridge for backwards compatibility.
            avail = data.get("availablecash", data.get("available_balance", "0"))
            used = data.get("utiliseddebits", data.get("usedmargin", data.get("used_margin", "0")))
            total = data.get("totalbalance", data.get("total_balance"))
            if total in (None, ""):
                # This inferred balance is only the L2 margin-utilisation
                # denominator. It must not become start-of-day risk capital.
                total = _sum_fund_components(avail, used)
            opening_risk_capital = "0"
            for field in _OPENING_RISK_CAPITAL_FIELDS:
                value = data.get(field)
                if value not in (None, ""):
                    opening_risk_capital = str(value)
                    break
            known = {
                "availablecash",
                "utiliseddebits",
                "usedmargin",
                "totalbalance",
                "available_balance",
                "used_margin",
                "total_balance",
                "status",
            }
            return Fund(
                available_balance=str(avail),
                used_margin=str(used),
                total_balance=str(total),
                opening_risk_capital=opening_risk_capital,
                extra={k: v for k, v in data.items() if k not in known},
            )
        return Fund()

    async def margin(self, positions: list[dict[str, Any]]) -> dict[str, Any]:
        """POST /api/v1/margin"""
        payload = self._body({"positions": positions})
        return await self._post("margin", payload)

    async def orderbook(self) -> list[OrderStatus]:
        """POST /api/v1/orderbook"""
        data = self._unwrap(await self._post("orderbook", self._body()))
        if isinstance(data, list):
            return [OrderStatus(**o) for o in data]
        return []

    async def tradebook(self) -> list[Trade]:
        """POST /api/v1/tradebook"""
        data = self._unwrap(await self._post("tradebook", self._body()))
        if not isinstance(data, list):
            return []

        trades: list[Trade] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            normalised = dict(item)
            if "quantity" in normalised:
                normalised["quantity"] = str(normalised["quantity"])
            if "average_price" in normalised:
                normalised["price"] = str(normalised["average_price"])
            elif "price" in normalised:
                normalised["price"] = str(normalised["price"])
            trades.append(Trade(**normalised))
        return trades

    async def positionbook(self) -> list[Position]:
        """POST /api/v1/positionbook"""
        data = self._unwrap(await self._post("positionbook", self._body()))
        if isinstance(data, list):
            return [Position(**p) for p in data]
        return []

    async def holdings(self) -> list[Holding]:
        """POST /api/v1/holdings"""
        data = self._unwrap(await self._post("holdings", self._body()))
        if isinstance(data, list):
            return [Holding(**h) for h in data]
        return []

    # ==================================================================
    # Utility APIs
    # ==================================================================

    async def ping(self) -> dict[str, Any]:
        """POST /api/v1/ping — health check."""
        return await self._post("ping", self._body())

    async def holidays(
        self,
        year: str = "2026",
        *,
        allow_legacy_fallback: bool = False,
    ) -> dict[str, Any]:
        """Fetch the authenticated market calendar, optionally probing legacy GET."""
        if isinstance(year, bool):
            raise ValueError("holiday year must be between 2020 and 2050")
        try:
            numeric_year = int(year)
        except (TypeError, ValueError) as exc:
            raise ValueError("holiday year must be between 2020 and 2050") from exc
        if not 2020 <= numeric_year <= 2050:
            raise ValueError("holiday year must be between 2020 and 2050")

        try:
            return await self._post(
                "market/holidays",
                self._body({"year": numeric_year}),
            )
        except APIError as exc:
            if not allow_legacy_fallback or exc.status_code not in {404, 405}:
                raise
            with self._config_guard:
                api_key = self._api_key
            if not api_key:
                raise
            logger.warning("OpenAlgo market calendar route missing; trying authenticated legacy endpoint")
            return await self._get(
                "holidays",
                params={"year": str(numeric_year)},
                headers={"X-API-KEY": api_key},
            )

    async def timings(self, date: str = "") -> dict[str, Any]:
        """POST /api/v1/market/timings"""
        timing_date = str(date or "").strip()
        if not timing_date:
            raise ValueError("date is required")
        return await self._post("market/timings", self._body({"date": timing_date}))

    async def telegram(self, message: str, username: str = "") -> dict[str, Any]:
        """POST /api/v1/telegram/notify"""
        name = str(username or "").strip()
        if not name:
            raise ValueError("username is required")
        return await self._post(
            "telegram/notify",
            self._body({"username": name, "message": message}),
        )

    async def instruments(self, exchange: str = "NSE") -> dict[str, Any]:
        """GET /api/v1/instruments"""
        with self._config_guard:
            api_key = self._api_key
        return await self._get("instruments", params={"apikey": api_key, "exchange": exchange})

    async def analyzer_status(self) -> dict[str, Any]:
        """POST /api/v1/analyzer/status — check whether sandbox trading
        mode is active on the connected OpenAlgo instance.

        Upstream renamed "virtual / paper trading" to "sandbox trading"
        in v2.0.0.6; route slugs (``analyzer/status``, ``analyzer/toggle``)
        and response keys (``analyzer_status``, ``analyzer_update``) were
        kept stable so this wrapper is unchanged.
        """
        return await self._post("analyzer/status", self._body())

    async def analyzer_toggle(self) -> dict[str, Any]:
        """POST /api/v1/analyzer/toggle — toggle between sandbox trading
        mode and live mode on the connected OpenAlgo instance.

        See :meth:`analyzer_status` for the v2.0.0.6 terminology note.
        """
        return await self._post("analyzer/toggle", self._body())

    # NOTE (HG1, removed 2026-07-06): eight wrappers formerly here (health, gex,
    # iv_smile, max_pain, oi_profile, broker_capabilities, pnl_symbols,
    # leverage_settings) called OpenAlgo routes that do not exist upstream
    # (verified against the pinned clone's restx_api) — guaranteed 404s with
    # zero callers. The analytics capabilities live natively in
    # flinttrade_screener (OIAnalysis, IV smile, GEX, max pain, OI profile) and
    # broker capability metadata is served by the unified catalogue routes.

    # ==================================================================
    # GTT (Good Till Triggered) — added in OpenAlgo v2.0.0.9
    # ==================================================================
    #
    # Live broker support upstream: Dhan + Zerodha. Other brokers return
    # a clean 501 ("GTT orders are not supported for broker 'X' yet").
    # FlintTrade forwards whatever OpenAlgo replies; we do NOT gate
    # client-side because broker support can change between releases.

    async def place_gtt(self, gtt: GttOrder) -> OrderResponse:
        """POST /api/v1/placegttorder — place a Good Till Triggered order.

        Single or two-leg OCO depending on ``gtt.trigger_type``. Upstream
        validates ``triggerprice_sl`` / ``triggerprice_tg`` against the
        trigger type and rejects ``MIS`` product at the schema layer.
        """
        payload = self._body(gtt.model_dump(exclude_none=True))
        raw = await self._post("placegttorder", payload)
        data = self._unwrap(raw)
        if isinstance(data, dict):
            return OrderResponse(
                status=str(data.get("status", "")),
                orderid=str(data.get("orderid", data.get("trigger_id", ""))),
                message=str(data.get("message", "")),
            )
        return OrderResponse(status="error", message=str(data))

    async def modify_gtt(self, gtt: ModifyGttOrder) -> OrderResponse:
        """POST /api/v1/modifygttorder — modify an active GTT.

        Modify is a full replacement: the broker's PUT semantics replace
        trigger prices, last price, and order params atomically.
        """
        payload = self._body(gtt.model_dump(exclude_none=True))
        raw = await self._post("modifygttorder", payload)
        data = self._unwrap(raw)
        if isinstance(data, dict):
            return OrderResponse(
                status=str(data.get("status", "")),
                orderid=str(data.get("orderid", data.get("trigger_id", ""))),
                message=str(data.get("message", "")),
            )
        return OrderResponse(status="error", message=str(data))

    async def cancel_gtt(self, cancel: CancelGttOrder) -> OrderResponse:
        """POST /api/v1/cancelgttorder — cancel an active GTT by ``trigger_id``."""
        payload = self._body(cancel.model_dump(exclude_none=True))
        raw = await self._post("cancelgttorder", payload)
        data = self._unwrap(raw)
        if isinstance(data, dict):
            return OrderResponse(
                status=str(data.get("status", "")),
                orderid=str(data.get("orderid", cancel.trigger_id)),
                message=str(data.get("message", "")),
            )
        return OrderResponse(status="error", message=str(data))

    async def gtt_orderbook(self) -> list[GttTrigger]:
        """POST /api/v1/gttorderbook — list active GTT triggers.

        Upstream broker mappers drop terminal-state rows (Dhan filters
        TRADED/EXPIRED/CANCELLED/REJECTED; Zerodha drops triggered/
        disabled/expired/cancelled/rejected/deleted) so the returned list
        reflects only live, waiting triggers.
        """
        raw = await self._post("gttorderbook", self._body())
        data = self._unwrap(raw)
        if isinstance(data, list):
            triggers: list[GttTrigger] = []
            for row in data:
                if isinstance(row, dict):
                    # Coerce non-string fields to str so the model never
                    # rejects a numeric payload from a broker SDK.
                    safe = {k: ("" if v is None else str(v)) for k, v in row.items()}
                    try:
                        triggers.append(GttTrigger(**{
                            k: safe[k] for k in safe
                            if k in GttTrigger.model_fields
                        }))
                    except Exception:  # pragma: no cover - tolerant boundary
                        triggers.append(GttTrigger())
            return triggers
        if isinstance(data, dict):
            inner = data.get("data") if isinstance(data.get("data"), list) else None
            if isinstance(inner, list):
                return [
                    GttTrigger(**{
                        k: ("" if v is None else str(v))
                        for k, v in row.items()
                        if k in GttTrigger.model_fields
                    })
                    for row in inner
                    if isinstance(row, dict)
                ]
        return []


def _configured_app_client(app: Any | None = None) -> Any | None:
    """Return the Flask app-owned OpenAlgo client when one is configured."""
    if app is None:
        try:
            from flask import current_app  # noqa: PLC0415

            app = current_app._get_current_object()
        except Exception:  # pragma: no cover - no Flask app context available
            return None

    try:
        return app.config.get("CLIENT")
    except AttributeError:
        return None


def resolve_openalgo_client(app: Any | None = None) -> tuple[Any, bool]:
    """Return an OpenAlgo client plus whether the caller owns its lifecycle.

    Flask routes should prefer the client held in ``app.config["CLIENT"]`` so
    workspace/UI OpenAlgo settings are honoured. Standalone imports and tests
    without an app context still receive a short-lived env/workspace-backed
    client and should close it after use.
    """
    configured_client = _configured_app_client(app)
    if configured_client is not None:
        return configured_client, False
    return OpenAlgoClient(Settings.from_env()), True


def get_openalgo_client(app: Any | None = None) -> Any:
    """Return the configured OpenAlgo client, falling back to Settings.from_env()."""
    client, _owns_client = resolve_openalgo_client(app)
    return client


def client_call_sync(client: Any, coro: Any, timeout: float = 45.0) -> Any:
    """Run a client coroutine from sync code on the client's OWNER loop.

    The one safe way to drive an :class:`OpenAlgoClient` from a Flask request
    thread or scheduler job — pooled httpx connections are loop-affine, so a
    fresh ``asyncio.run()`` per call poisons the shared pool ("Event loop is
    closed" on alternating requests). Falls back to ``asyncio.run`` only for
    duck-typed test fakes that expose no ``run_sync``.
    """
    if isinstance(client, OpenAlgoClient):
        return client.run_sync(coro, timeout)
    # Duck-typed fakes/mocks in tests: a plain fresh loop is correct there
    # (single call, no shared pool). getattr-probing is NOT safe here because
    # MagicMock fabricates a run_sync attribute.
    return asyncio.run(coro)


def client_close_sync(client: Any) -> None:
    """Close a client from sync code on the SAME loop that served its calls."""
    if isinstance(client, OpenAlgoClient):
        client.close_sync()
        return
    asyncio.run(client.close())
