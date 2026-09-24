"""Session-scoped Kotak Neo v3 async market and order-feed runtime.

The pinned SDK's internal reconnect path publishes ``on_connect`` before its
subscription replay has settled and can overwrite its receive-task ownership.
FlintTrade therefore disables that path through the public factory argument
``max_reconnect_attempts=0``. A stopped public iterator is replaced with a
fresh SDK feed and the immutable desired subscription ledger is replayed under
the same mutation lock. Callbacks never reconnect or replay.
"""

from __future__ import annotations

import asyncio
import inspect
import math
import sys
import weakref
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

from flinttrade_core.exceptions import BrokerError, BrokerInternal, BrokerTimeout, NetworkError, SessionExpired
from flinttrade_core.models import TickEvent

from . import kotakneo_mapping as M
from .kotakneo_sdk import (
    canonical_stream_exception,
    make_ws_token,
    market_feed_message_kind,
    order_feed_message_kind,
)

STREAM_RUNTIME_KEY = "kotakneo_stream_runtime"
MAX_STREAM_TOKENS = 3000
STREAM_QUEUE_SIZE = 256
MAX_STREAM_REPLACEMENTS = 3
STREAM_RECONNECT_DELAY_SECONDS = 0.25

_Intent = Literal["scrips", "depth", "index"]
_TokenKey = tuple[str, str]
_Alias = tuple[str, str]
_SUBSCRIBE_METHODS: dict[_Intent, str] = {
    "scrips": "subscribe_scrips",
    "depth": "subscribe_depth",
    "index": "subscribe_index",
}
_UNSUBSCRIBE_METHODS: dict[_Intent, str] = {
    "scrips": "unsubscribe_scrips",
    "depth": "unsubscribe_depth",
    "index": "unsubscribe_index",
}
_INTENT_ORDER: tuple[_Intent, ...] = ("scrips", "depth", "index")
_INDEX_EXCHANGE = {"nse_cm": "NSE_INDEX", "bse_cm": "BSE_INDEX"}


async def _default_reconnect_wait() -> None:
    await asyncio.sleep(STREAM_RECONNECT_DELAY_SECONDS)


def _canonical_error(exc: Exception, operation: str) -> BrokerError:
    if isinstance(exc, BrokerError):
        return exc
    return canonical_stream_exception(exc, operation)


async def _invoke_async(target: object, method_name: str, *args: Any) -> Any:
    method = getattr(target, method_name, None)
    if not callable(method):
        raise BrokerInternal(f"Kotak Neo {method_name} is unavailable", broker_id="kotakneo")
    result = method(*args)
    if not inspect.isawaitable(result):
        raise BrokerInternal(f"Kotak Neo {method_name} is not asynchronous", broker_id="kotakneo")
    return await result


async def _close_feed(feed: object, operation: str) -> None:
    try:
        await _invoke_async(feed, "close")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        raise _canonical_error(exc, operation) from None


async def _complete_despite_cancellation(awaitable: Awaitable[Any]) -> tuple[BaseException | None, asyncio.CancelledError | None]:
    """Finish one cleanup stage even if its caller is cancelled."""
    task = asyncio.ensure_future(awaitable)
    cancellation: asyncio.CancelledError | None = None
    while True:
        try:
            await asyncio.shield(task)
            return None, cancellation
        except asyncio.CancelledError as exc:
            if task.cancelled():
                return exc, cancellation
            cancellation = cancellation or exc
            current = asyncio.current_task()
            if current is not None:
                current.uncancel()
        except BaseException as exc:  # cleanup retains the first error after all stages
            return exc, cancellation


def _validated_token_rows(tokens: list[dict[str, str]]) -> list[_TokenKey]:
    keys: list[_TokenKey] = []
    for row in tokens:
        if type(row) is not dict or set(row) != {"exchange_segment", "instrument_token"}:
            raise BrokerError("Kotak Neo stream token is malformed", broker_id="kotakneo")
        segment = row["exchange_segment"]
        token = row["instrument_token"]
        if type(segment) is not str or not segment or type(token) is not str or not token:
            raise BrokerError("Kotak Neo stream token is malformed", broker_id="kotakneo")
        keys.append((segment, token))
    return keys


def _validated_aliases(aliases: list[_Alias], expected: int) -> list[_Alias]:
    if len(aliases) != expected:
        raise BrokerError("Kotak Neo stream aliases differ from token count", broker_id="kotakneo")
    result: list[_Alias] = []
    for alias in aliases:
        if (
            type(alias) is not tuple
            or len(alias) != 2
            or type(alias[0]) is not str
            or type(alias[1]) is not str
            or not alias[0]
            or not alias[1]
        ):
            raise BrokerError("Kotak Neo stream alias is malformed", broker_id="kotakneo")
        result.append(alias)
    return result


def _number(value: object, *, integer: bool = False) -> float | int | None:
    if isinstance(value, bool) or type(value) not in (int, float):
        return None
    if type(value) is int and (value >= 10**64 or value <= -(10**64)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    if integer:
        if number < 0 or not number.is_integer() or number > 2**63 - 1:
            return None
        return int(number)
    return number


def _text(value: object) -> str | None:
    if type(value) is not str or not value or len(value) > 4096:
        return None
    try:
        value.encode("utf-8")
    except UnicodeError:
        return None
    return value


def _level_price(message: object, side: str) -> float:
    levels = getattr(message, side, None)
    if type(levels) is not list or not levels:
        return 0.0
    price = _number(getattr(levels[0], "price", None))
    return float(price) if price is not None else 0.0


def _tick_from_message(message: object, *, fallback_symbol: str | None = None) -> TickEvent | None:
    kind = market_feed_message_kind(message)
    if kind is None:
        return None
    segment = _text(getattr(message, "exchange_segment", None))
    token = _text(getattr(message, "instrument_token", None))
    if segment is None or token is None:
        return None
    symbol = _text(getattr(message, "trading_symbol", None))
    if symbol is None and kind == "index":
        symbol = _text(getattr(message, "name", None))
    symbol = symbol or fallback_symbol
    ltp = _number(getattr(message, "last_traded_price", None))
    timestamp = _number(getattr(message, "last_trade_time", None), integer=True)
    if symbol is None or ltp is None or timestamp is None:
        return None
    # v3 SFeed models define ``last_trade_time`` as integer Unix epoch
    # seconds. TickEvent retains those exact seconds as canonical decimal text.
    timestamp_text = str(timestamp)
    if kind == "index":
        exchange = _INDEX_EXCHANGE.get(segment, M.KOTAK_TO_EXCHANGE.get(segment, segment))
        return TickEvent(symbol=symbol, exchange=exchange, ltp=float(ltp), timestamp=timestamp_text)
    volume = _number(getattr(message, "volume_traded_today", 0), integer=True)
    oi = _number(getattr(message, "open_interest", 0), integer=True)
    if volume is None or oi is None:
        return None
    return TickEvent(
        symbol=symbol,
        exchange=M.KOTAK_TO_EXCHANGE.get(segment, segment),
        ltp=float(ltp),
        volume=int(volume),
        bid=_level_price(message, "buy"),
        ask=_level_price(message, "sell"),
        oi=int(oi),
        timestamp=timestamp_text,
    )


@dataclass(frozen=True)
class _Subscription:
    token: Any
    intent: _Intent


def _message_matches_ledger(
    message: object,
    ledger: Mapping[_TokenKey, _Subscription],
) -> bool:
    """Accept typed price ingress only for a committed desired subscription."""
    kind = market_feed_message_kind(message)
    if kind is None:
        return False
    segment = _text(getattr(message, "exchange_segment", None))
    token = _text(getattr(message, "instrument_token", None))
    if segment is None or token is None:
        return False
    direct = ledger.get((segment, token))
    if kind != "index":
        return direct is not None and direct.intent in {"scrips", "depth"}
    if direct is not None and direct.intent == "index":
        return True

    # Index subscriptions use the human-readable name, while the binary wire
    # message carries a broker-resolved numeric instrument token. Match the
    # typed index name (or enriched trading symbol) to the immutable desired
    # index key; never treat an unrelated numeric scrip token as an index.
    names = {
        " ".join(value.split()).upper()
        for value in (
            _text(getattr(message, "name", None)),
            _text(getattr(message, "trading_symbol", None)),
        )
        if value is not None
    }
    return any(
        record.intent == "index"
        and key_segment == segment
        and " ".join(key_token.split()).upper() in names
        for (key_segment, key_token), record in ledger.items()
    )


@dataclass(frozen=True)
class _StreamEnd:
    error: BrokerError | None = None


class KotakNeoStreamRuntime:
    """One independently owned v3 streaming runtime for one concrete session."""

    def __init__(
        self,
        client: object,
        *,
        token_factory: Callable[[str, str], Any] = make_ws_token,
        reconnect_waiter: Callable[[], Awaitable[None]] = _default_reconnect_wait,
    ) -> None:
        self._client = client
        self._token_factory = token_factory
        self._reconnect_waiter = reconnect_waiter
        self._market_feed: object | None = None
        self._order_feed: object | None = None
        self._market_generation: int | None = None
        self._order_generation: int | None = None
        self._next_generation = 0
        self._live_generations: set[int] = set()
        self._disconnected_generations: set[int] = set()
        self._ledger: dict[_TokenKey, _Subscription] = {}
        self._aliases: dict[_Alias, _TokenKey] = {}
        self._fallback_symbols: dict[_TokenKey, str] = {}
        self._mutation_lock = asyncio.Lock()
        self._market_lock = asyncio.Lock()
        self._order_lock = asyncio.Lock()
        self._market_iterator_lock = asyncio.Lock()
        self._order_iterator_lock = asyncio.Lock()
        self._close_result_lock = asyncio.Lock()
        self._market_iterator_active = False
        self._order_iterator_active = False
        self._market_candidate: object | None = None
        self._order_candidate: object | None = None
        self._market_candidate_generation: int | None = None
        self._order_candidate_generation: int | None = None
        self._market_candidate_task: asyncio.Task[Any] | None = None
        self._order_candidate_task: asyncio.Task[None] | None = None
        self._market_candidate_queue: asyncio.Queue[TickEvent | _StreamEnd] | None = None
        self._owned_tasks: set[asyncio.Task[Any]] = set()
        self._mutation_tasks: set[asyncio.Task[Any]] = set()
        self._market_workers: set[asyncio.Task[Any]] = set()
        self._order_workers: set[asyncio.Task[Any]] = set()
        self._market_queue: asyncio.Queue[TickEvent | _StreamEnd] | None = None
        self._market_pump_task: asyncio.Task[Any] | None = None
        self._closed_feed_refs: dict[int, weakref.ReferenceType[Any]] = {}
        self._closed_nonweak_feeds: list[object] = []
        self._feed_close_tasks: dict[int, asyncio.Task[Any]] = {}
        self._closed = False
        self._cleanup_done = False
        self._cleanup_error_delivered = False
        self._cleanup_task: asyncio.Task[BrokerError | None] | None = None
        self._pending_cleanup_error: BrokerError | None = None

    @property
    def subscription_count(self) -> int:
        return len(self._ledger)

    def _require_open(self) -> None:
        if self._closed:
            raise SessionExpired("Kotak Neo stream runtime is closed", broker_id="kotakneo")

    def _tokens_for(self, keys: list[_TokenKey]) -> list[Any]:
        try:
            return [self._token_factory(segment, token) for segment, token in keys]
        except Exception as exc:
            raise _canonical_error(exc, "stream token construction") from None

    def _refresh_fallback_symbols(self) -> None:
        """Precompute deterministic O(1) token-to-symbol fallbacks after mutation."""
        fallbacks: dict[_TokenKey, str] = {}
        for alias, key in self._aliases.items():
            fallbacks.setdefault(key, alias[1])
        self._fallback_symbols = fallbacks

    def _spawn(self, awaitable: Awaitable[Any]) -> asyncio.Task[Any]:
        task = asyncio.create_task(awaitable)
        self._owned_tasks.add(task)
        task.add_done_callback(self._owned_tasks.discard)
        return task

    def _track_mutation_task(self) -> asyncio.Task[Any]:
        task = asyncio.current_task()
        if task is None:
            raise BrokerInternal("Kotak Neo stream operation has no task owner", broker_id="kotakneo")
        self._mutation_tasks.add(task)
        return task

    def _ensure_market_pump(self, feed: object) -> None:
        """Start bounded ingress as soon as a live market feed is usable."""
        self._require_open()
        current = self._market_pump_task
        if current is not None and not current.done():
            return
        if current is not None and self._market_iterator_active:
            # The active iterator still owns the completed pump's terminal
            # result. It must observe that result before a new feed can start.
            return
        queue = self._market_queue
        if queue is None:
            queue = asyncio.Queue(maxsize=STREAM_QUEUE_SIZE)
            self._market_queue = queue
        worker = self._spawn(self._market_worker(queue, feed))
        self._market_pump_task = worker
        self._market_workers.add(worker)
        worker.add_done_callback(self._market_workers.discard)

    async def _stop_market_pump(self) -> None:
        worker = self._market_pump_task
        if worker is None:
            return
        if not worker.done():
            worker.cancel()
        _worker_error, cancellation = await _complete_despite_cancellation(worker)
        if self._market_pump_task is worker and not self._market_iterator_active:
            self._market_pump_task = None
            self._market_queue = None
        if cancellation is not None:
            raise cancellation

    def _promote_candidate_ingress(self, candidate_queue: asyncio.Queue[TickEvent | _StreamEnd]) -> None:
        """Expose staged candidate ticks only after atomic publication."""
        current = self._market_pump_task
        target = self._market_queue
        if target is None or (current is not None and current.done() and not self._market_iterator_active):
            target = asyncio.Queue(maxsize=STREAM_QUEUE_SIZE)
            self._market_queue = target
        while not candidate_queue.empty():
            tick = candidate_queue.get_nowait()
            if target.full():
                target.get_nowait()
            target.put_nowait(tick)

    def _retire_generation(self, generation: int | None) -> None:
        if generation is None:
            return
        self._live_generations.discard(generation)
        self._disconnected_generations.discard(generation)

    async def _close_once(self, feed: object, operation: str) -> None:
        identity = id(feed)
        existing = self._closed_feed_refs.get(identity)
        close_task = self._feed_close_tasks.get(identity)
        already_owned = (
            existing is not None and existing() is feed
        ) or any(closed is feed for closed in self._closed_nonweak_feeds)
        if not already_owned or close_task is None:
            close_task = self._spawn(_close_feed(feed, operation))
            self._feed_close_tasks[identity] = close_task
            try:
                def discard(reference: weakref.ReferenceType[Any], *, key: int = identity) -> None:
                    if self._closed_feed_refs.get(key) is reference:
                        self._closed_feed_refs.pop(key, None)
                        self._feed_close_tasks.pop(key, None)

                self._closed_feed_refs[identity] = weakref.ref(feed, discard)
            except TypeError:
                # The pinned SDK clients and production fakes are weak-referenceable.
                # Conservatively retain an unusual non-weakref object to keep close
                # exactly-once rather than risk closing a transport twice.
                self._closed_nonweak_feeds.append(feed)

        error, cancellation = await _complete_despite_cancellation(close_task)
        if isinstance(error, asyncio.CancelledError):
            raise error
        if error is not None:
            if not isinstance(error, Exception):
                raise error
            canonical = error if isinstance(error, BrokerError) else _canonical_error(error, operation)
            self._pending_cleanup_error = self._pending_cleanup_error or canonical
            if cancellation is not None:
                raise cancellation
            raise canonical
        if cancellation is not None:
            raise cancellation

    def _new_market_feed(self) -> object:
        factory = getattr(self._client, "create_websocket", None)
        if not callable(factory):
            raise BrokerInternal("Kotak Neo create_websocket is unavailable", broker_id="kotakneo")
        try:
            return factory(max_connect_retries=0, max_reconnect_attempts=0, max_subscriptions=MAX_STREAM_TOKENS)
        except Exception as exc:
            raise _canonical_error(exc, "market feed creation") from None

    def _new_order_feed(self) -> object:
        factory = getattr(self._client, "create_order_feed", None)
        if not callable(factory):
            raise BrokerInternal("Kotak Neo create_order_feed is unavailable", broker_id="kotakneo")
        try:
            return factory(max_connect_retries=0, max_reconnect_attempts=0)
        except Exception as exc:
            raise _canonical_error(exc, "order feed creation") from None

    def _install_disconnect_marker(self, feed: object) -> int:
        """Mark only the generation whose public disconnect callback fired."""
        self._next_generation += 1
        generation = self._next_generation
        previous = getattr(feed, "on_disconnect", None)

        def disconnected() -> None:
            if generation in self._live_generations:
                self._disconnected_generations.add(generation)
            if callable(previous):
                previous()

        try:
            feed.on_disconnect = disconnected  # type: ignore[attr-defined]
        except Exception as exc:
            self._retire_generation(generation)
            raise _canonical_error(exc, "feed callback installation") from None
        self._live_generations.add(generation)
        return generation

    async def _drain_market_candidate(
        self,
        candidate: object,
        generation: int,
        queue: asyncio.Queue[TickEvent | _StreamEnd],
        ledger: Mapping[_TokenKey, _Subscription],
        fallback_symbols: Mapping[_TokenKey, str],
    ) -> None:
        """Bound SDK ingress while a connected candidate replays its ledger."""
        iterator = candidate.__aiter__()  # type: ignore[attr-defined]
        while not self._closed and self._market_candidate is candidate:
            try:
                message = await anext(iterator)
            except asyncio.CancelledError:
                raise
            except StopAsyncIteration:
                return
            except Exception as exc:
                raise _canonical_error(exc, "market candidate iteration") from None
            if generation in self._disconnected_generations:
                raise NetworkError("Kotak Neo market feed disconnected during replay", broker_id="kotakneo")
            if not _message_matches_ledger(message, ledger):
                continue
            try:
                tick = _tick_from_message(
                    message,
                    fallback_symbol=self._fallback_symbol_if_needed(message, fallback_symbols),
                )
            except Exception as exc:
                raise _canonical_error(exc, "market candidate message mapping") from None
            if tick is not None:
                if queue.full():
                    queue.get_nowait()
                queue.put_nowait(tick)

    async def _market_candidate_body(
        self,
        candidate: object,
        generation: int,
        ledger: Mapping[_TokenKey, _Subscription],
        fallback_symbols: Mapping[_TokenKey, str],
        candidate_queue: asyncio.Queue[TickEvent | _StreamEnd],
    ) -> asyncio.Queue[TickEvent | _StreamEnd]:
        drain: asyncio.Task[Any] | None = None
        try:
            await _invoke_async(candidate, "connect")
            if self._closed or self._market_candidate is not candidate:
                raise SessionExpired("Kotak Neo stream runtime is closed", broker_id="kotakneo")
            if generation in self._disconnected_generations:
                raise NetworkError("Kotak Neo market feed disconnected during connect", broker_id="kotakneo")
            drain = self._spawn(
                self._drain_market_candidate(
                    candidate,
                    generation,
                    candidate_queue,
                    ledger,
                    fallback_symbols,
                )
            )
            for intent in _INTENT_ORDER:
                tokens = [record.token for record in ledger.values() if record.intent == intent]
                if tokens:
                    await _invoke_async(candidate, _SUBSCRIBE_METHODS[intent], tokens)
                    if self._closed or self._market_candidate_generation != generation:
                        raise SessionExpired("Kotak Neo stream runtime is closed", broker_id="kotakneo")
                    if generation in self._disconnected_generations:
                        raise NetworkError("Kotak Neo market feed disconnected during replay", broker_id="kotakneo")
        finally:
            primary_exception = sys.exc_info()[1]
            if drain is not None:
                completed_before_stop = drain.done()
                if not completed_before_stop:
                    drain.cancel()
                drain_error, drain_cancellation = await _complete_despite_cancellation(drain)
                if drain_cancellation is not None:
                    raise drain_cancellation
                if primary_exception is None and completed_before_stop:
                    if drain_error is None:
                        raise NetworkError(
                            "Kotak Neo market candidate ended during replay",
                            broker_id="kotakneo",
                        )
                    if isinstance(drain_error, asyncio.CancelledError):
                        raise drain_error
                    if isinstance(drain_error, Exception):
                        raise _canonical_error(drain_error, "market candidate iteration") from None
                    raise drain_error
        return candidate_queue

    async def _order_candidate_body(self, candidate: object, generation: int) -> None:
        # The pinned SDK returns after socket open plus authentication send;
        # it exposes no acknowledgement wait beyond this transport success.
        await _invoke_async(candidate, "connect")
        if self._closed or self._order_candidate is not candidate:
            raise SessionExpired("Kotak Neo stream runtime is closed", broker_id="kotakneo")
        if generation in self._disconnected_generations:
            raise NetworkError("Kotak Neo order feed disconnected during connect", broker_id="kotakneo")

    async def _publish_market_candidate_locked(self) -> object:
        self._require_open()
        candidate = self._new_market_feed()
        try:
            generation = self._install_disconnect_marker(candidate)
        except Exception:
            await self._close_once(candidate, "market feed close")
            raise
        ledger = MappingProxyType(dict(self._ledger))
        fallback_symbols = MappingProxyType(dict(self._fallback_symbols))
        candidate_queue: asyncio.Queue[TickEvent | _StreamEnd] = asyncio.Queue(maxsize=STREAM_QUEUE_SIZE)
        task = self._spawn(
            self._market_candidate_body(
                candidate,
                generation,
                ledger,
                fallback_symbols,
                candidate_queue,
            )
        )
        self._market_candidate = candidate
        self._market_candidate_generation = generation
        self._market_candidate_task = task
        self._market_candidate_queue = candidate_queue
        try:
            candidate_queue = await task
            if self._closed or self._market_candidate is not candidate:
                raise SessionExpired("Kotak Neo stream runtime is closed", broker_id="kotakneo")
            if generation in self._disconnected_generations:
                raise NetworkError("Kotak Neo market feed disconnected before publication", broker_id="kotakneo")
        except asyncio.CancelledError:
            if not self._closed:
                self._market_candidate = None
                self._market_candidate_generation = None
                self._market_candidate_task = None
                self._market_candidate_queue = None
                self._retire_generation(generation)
                await _complete_despite_cancellation(self._close_once(candidate, "market feed close"))
            raise
        except Exception as exc:
            self._market_candidate = None
            self._market_candidate_generation = None
            self._market_candidate_task = None
            self._market_candidate_queue = None
            self._retire_generation(generation)
            close_error, close_cancellation = await _complete_despite_cancellation(
                self._close_once(candidate, "market feed close")
            )
            if isinstance(close_error, asyncio.CancelledError):
                raise close_error
            if close_cancellation is not None:
                raise close_cancellation
            raise _canonical_error(exc, "market feed connect") from None
        self._market_candidate = None
        self._market_candidate_generation = None
        self._market_candidate_task = None
        self._market_candidate_queue = None
        self._market_feed = candidate
        self._market_generation = generation
        self._promote_candidate_ingress(candidate_queue)
        return candidate

    async def _publish_order_candidate_locked(self) -> object:
        self._require_open()
        candidate = self._new_order_feed()
        try:
            generation = self._install_disconnect_marker(candidate)
        except Exception:
            await self._close_once(candidate, "order feed close")
            raise
        task = self._spawn(self._order_candidate_body(candidate, generation))
        self._order_candidate = candidate
        self._order_candidate_generation = generation
        self._order_candidate_task = task
        try:
            await task
            if self._closed or self._order_candidate is not candidate:
                raise SessionExpired("Kotak Neo stream runtime is closed", broker_id="kotakneo")
            if generation in self._disconnected_generations:
                raise NetworkError("Kotak Neo order feed disconnected before publication", broker_id="kotakneo")
        except asyncio.CancelledError:
            if not self._closed:
                self._order_candidate = None
                self._order_candidate_generation = None
                self._order_candidate_task = None
                self._retire_generation(generation)
                await _complete_despite_cancellation(self._close_once(candidate, "order feed close"))
            raise
        except Exception as exc:
            self._order_candidate = None
            self._order_candidate_generation = None
            self._order_candidate_task = None
            self._retire_generation(generation)
            close_error, close_cancellation = await _complete_despite_cancellation(
                self._close_once(candidate, "order feed close")
            )
            if isinstance(close_error, asyncio.CancelledError):
                raise close_error
            if close_cancellation is not None:
                raise close_cancellation
            raise _canonical_error(exc, "order feed connect") from None
        self._order_candidate = None
        self._order_candidate_generation = None
        self._order_candidate_task = None
        self._order_feed = candidate
        self._order_generation = generation
        return candidate

    async def _detach_market_locked(self, expected: object | None = None) -> None:
        if expected is not None and self._market_feed is not expected:
            return
        feed = self._market_feed
        generation = self._market_generation
        self._market_feed = None
        self._market_generation = None
        self._retire_generation(generation)
        if feed is not None:
            await self._close_once(feed, "market feed close")

    async def _detach_order_locked(self, expected: object | None = None) -> None:
        if expected is not None and self._order_feed is not expected:
            return
        feed = self._order_feed
        generation = self._order_generation
        self._order_feed = None
        self._order_generation = None
        self._retire_generation(generation)
        if feed is not None:
            await self._close_once(feed, "order feed close")

    async def _market_feed_locked(self) -> object:
        self._require_open()
        if self._market_feed is not None and self._market_generation in self._disconnected_generations:
            await self._stop_market_pump()
        async with self._market_lock:
            self._require_open()
            if self._market_feed is not None and self._market_generation in self._disconnected_generations:
                await self._detach_market_locked(self._market_feed)
            if self._market_feed is None:
                if (
                    self._market_iterator_active
                    and self._market_pump_task is not None
                    and self._market_pump_task.done()
                ):
                    raise BrokerInternal(
                        "Kotak Neo market stream termination is pending consumption",
                        broker_id="kotakneo",
                    )
                return await self._publish_market_candidate_locked()
            return self._market_feed

    async def market_feed(self) -> object:
        self._require_open()
        owner = self._track_mutation_task()
        try:
            async with self._mutation_lock:
                feed = await self._market_feed_locked()
                self._ensure_market_pump(feed)
                return feed
        finally:
            self._mutation_tasks.discard(owner)

    async def order_feed(self) -> object:
        self._require_open()
        async with self._order_lock:
            self._require_open()
            if self._order_feed is not None and self._order_generation in self._disconnected_generations:
                await self._detach_order_locked(self._order_feed)
            if self._order_feed is None:
                return await self._publish_order_candidate_locked()
            return self._order_feed

    async def _restore_market_after_ambiguous_mutation(
        self,
        expected: object,
        ledger: dict[_TokenKey, _Subscription],
        aliases: dict[_Alias, _TokenKey],
    ) -> None:
        """Replace an ambiguous socket from the unchanged pre-call intent."""
        self._ledger = dict(ledger)
        self._aliases = dict(aliases)
        self._refresh_fallback_symbols()
        await self._stop_market_pump()
        async with self._market_lock:
            if self._closed:
                # Whole-runtime cleanup owns the published market stage and
                # must retain any close error for its canonical first result.
                return
            if self._market_feed is expected:
                await self._detach_market_locked(expected)
            if self._closed:
                return
            if self._market_iterator_active:
                # Conservatively terminate the current iterator. Its terminal
                # sentinel remains in the old bounded queue; the next
                # iterator/operation will create and replay a fresh feed.
                return
            try:
                candidate = await self._publish_market_candidate_locked()
                self._ensure_market_pump(candidate)
            except BrokerError:
                return

    async def add_subscriptions(
        self,
        tokens: list[dict[str, str]],
        *,
        intent: _Intent,
        aliases: list[_Alias],
    ) -> None:
        self._require_open()
        if intent not in _INTENT_ORDER:
            raise BrokerError("Kotak Neo stream intent is unsupported", broker_id="kotakneo")
        keys = _validated_token_rows(tokens)
        resolved_aliases = _validated_aliases(aliases, len(keys))
        request = list(zip(resolved_aliases, keys))
        request_aliases: dict[_Alias, _TokenKey] = {}
        for alias, key in request:
            previous = request_aliases.get(alias)
            if previous is not None and previous != key:
                raise BrokerError("Kotak Neo stream alias conflicts within the request", broker_id="kotakneo")
            request_aliases[alias] = key
        owner = self._track_mutation_task()
        try:
            async with self._mutation_lock:
                self._require_open()
                for alias, key in request:
                    recorded_alias = self._aliases.get(alias)
                    if recorded_alias is not None and recorded_alias != key:
                        raise BrokerError(
                            "Kotak Neo stream alias conflicts with its existing token",
                            broker_id="kotakneo",
                        )
                    recorded = self._ledger.get(key)
                    if recorded is not None and recorded.intent != intent:
                        raise BrokerError(
                            "Kotak Neo token already has a different feed intent",
                            broker_id="kotakneo",
                        )
                new_keys = list(dict.fromkeys(key for _alias, key in request if key not in self._ledger))
                if len(self._ledger) + len(new_keys) > MAX_STREAM_TOKENS:
                    raise BrokerError(
                        f"Kotak Neo supports at most {MAX_STREAM_TOKENS} token intents per connection",
                        broker_id="kotakneo",
                    )
                new_records = {
                    key: _Subscription(self._tokens_for([key])[0], intent)
                    for key in new_keys
                }
                ledger_before = dict(self._ledger)
                aliases_before = dict(self._aliases)
                feed = await self._market_feed_locked()
                self._ensure_market_pump(feed)
                if new_records:
                    try:
                        await _invoke_async(
                            feed,
                            _SUBSCRIBE_METHODS[intent],
                            [record.token for record in new_records.values()],
                        )
                        if self._closed:
                            raise SessionExpired("Kotak Neo stream runtime is closed", broker_id="kotakneo")
                    except BaseException as exc:
                        restore = self._spawn(
                            self._restore_market_after_ambiguous_mutation(feed, ledger_before, aliases_before)
                        )
                        restore_error, restore_cancellation = await _complete_despite_cancellation(restore)
                        if isinstance(restore_error, asyncio.CancelledError):
                            raise restore_error
                        if restore_cancellation is not None:
                            raise restore_cancellation
                        if isinstance(exc, asyncio.CancelledError):
                            raise
                        if isinstance(exc, Exception):
                            raise _canonical_error(exc, "market feed subscribe") from None
                        raise
                    self._ledger.update(new_records)
                for alias, key in request:
                    self._aliases[alias] = key
                self._refresh_fallback_symbols()
                self._ensure_market_pump(feed)
        finally:
            self._mutation_tasks.discard(owner)

    async def remove_subscriptions(self, aliases: list[_Alias]) -> None:
        self._require_open()
        resolved_aliases = _validated_aliases(aliases, len(aliases))
        owner = self._track_mutation_task()
        try:
            async with self._mutation_lock:
                self._require_open()
                requested_aliases = list(dict.fromkeys(alias for alias in resolved_aliases if alias in self._aliases))
                if not requested_aliases:
                    return
                aliases_after = dict(self._aliases)
                selected_keys = list(dict.fromkeys(aliases_after.pop(alias) for alias in requested_aliases))
                retained_keys = set(aliases_after.values())
                keys = [key for key in selected_keys if key not in retained_keys]
                if not keys:
                    self._aliases = aliases_after
                    self._refresh_fallback_symbols()
                    return
                ledger_before = dict(self._ledger)
                aliases_before = dict(self._aliases)
                feed = await self._market_feed_locked()
                self._ensure_market_pump(feed)
                try:
                    for intent in _INTENT_ORDER:
                        records = [self._ledger[key] for key in keys if self._ledger[key].intent == intent]
                        if records:
                            await _invoke_async(
                                feed,
                                _UNSUBSCRIBE_METHODS[intent],
                                [record.token for record in records],
                            )
                            if self._closed:
                                raise SessionExpired("Kotak Neo stream runtime is closed", broker_id="kotakneo")
                except BaseException as exc:
                    restore = self._spawn(
                        self._restore_market_after_ambiguous_mutation(feed, ledger_before, aliases_before)
                    )
                    restore_error, restore_cancellation = await _complete_despite_cancellation(restore)
                    if isinstance(restore_error, asyncio.CancelledError):
                        raise restore_error
                    if restore_cancellation is not None:
                        raise restore_cancellation
                    if isinstance(exc, asyncio.CancelledError):
                        raise
                    if isinstance(exc, Exception):
                        raise _canonical_error(exc, "market feed unsubscribe") from None
                    raise
                for key in keys:
                    self._ledger.pop(key, None)
                self._aliases = aliases_after
                self._refresh_fallback_symbols()
                self._ensure_market_pump(feed)
        finally:
            self._mutation_tasks.discard(owner)

    async def _replace_market(self, expected: object | None) -> object | None:
        owner = self._track_mutation_task()
        try:
            async with self._mutation_lock:
                if self._closed:
                    return None
                async with self._market_lock:
                    if self._market_feed is not expected:
                        return self._market_feed
                    await self._detach_market_locked(expected)
                    if self._closed:
                        return None
                    return await self._publish_market_candidate_locked()
        finally:
            self._mutation_tasks.discard(owner)

    async def _replace_order(self, expected: object | None) -> object | None:
        if self._closed:
            return None
        async with self._order_lock:
            if self._order_feed is not expected:
                return self._order_feed
            await self._detach_order_locked(expected)
            if self._closed:
                return None
            return await self._publish_order_candidate_locked()

    def _fallback_symbol(
        self,
        message: object,
        fallback_symbols: Mapping[_TokenKey, str] | None = None,
    ) -> str | None:
        segment = _text(getattr(message, "exchange_segment", None))
        token = _text(getattr(message, "instrument_token", None))
        if segment is None or token is None:
            return None
        symbols = self._fallback_symbols if fallback_symbols is None else fallback_symbols
        return symbols.get((segment, token))

    def _fallback_symbol_if_needed(
        self,
        message: object,
        fallback_symbols: Mapping[_TokenKey, str] | None = None,
    ) -> str | None:
        if _text(getattr(message, "trading_symbol", None)) is not None:
            return None
        if market_feed_message_kind(message) == "index" and _text(getattr(message, "name", None)) is not None:
            return None
        return self._fallback_symbol(message, fallback_symbols)

    async def _market_worker(self, queue: asyncio.Queue[TickEvent | _StreamEnd], feed: object) -> None:
        error: BrokerError | None = None
        replacements = 0
        cleanup_cancellation: asyncio.CancelledError | None = None
        try:
            while feed is not None and not self._closed:
                generation = self._market_generation
                iterator = feed.__aiter__()  # type: ignore[attr-defined]
                while not self._closed:
                    try:
                        message = await anext(iterator)
                    except StopAsyncIteration:
                        break
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        if generation not in self._disconnected_generations:
                            error = _canonical_error(exc, "market feed iteration")
                        break
                    if self._market_feed is not feed or self._market_generation != generation:
                        continue
                    if not _message_matches_ledger(message, self._ledger):
                        continue
                    try:
                        tick = _tick_from_message(
                            message,
                            fallback_symbol=self._fallback_symbol_if_needed(message),
                        )
                        if tick is not None:
                            if queue.full():
                                queue.get_nowait()
                            queue.put_nowait(tick)
                    except Exception as exc:
                        error = _canonical_error(exc, "market feed message mapping")
                        break
                if error is not None:
                    break
                if self._closed:
                    break
                expected: object | None = feed
                while not self._closed:
                    replacements += 1
                    if replacements > MAX_STREAM_REPLACEMENTS:
                        error = BrokerInternal(
                            "Kotak Neo market feed replacement limit reached",
                            broker_id="kotakneo",
                        )
                        break
                    await self._reconnect_waiter()
                    try:
                        feed = await self._replace_market(expected)
                        break
                    except (BrokerTimeout, NetworkError):
                        # A failed candidate has already been closed and leaves
                        # no published feed. Consume the remaining runtime-owned
                        # budget; if a concurrent mutation publishes first,
                        # expecting None adopts it without detaching it.
                        expected = None
                if error is not None:
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self._closed:
                error = _canonical_error(exc, "market feed iteration")
        finally:
            if error is not None and feed is not None:
                cleanup = self._spawn(self._detach_market_for_iterator(feed))
                try:
                    await cleanup
                except asyncio.CancelledError as exc:
                    # A mutation may own the lock and be stopping this pump.
                    # Let that mutation own restoration instead of forming a
                    # mutation -> pump -> detach -> mutation lock cycle.
                    cleanup_cancellation = exc
                except Exception:
                    pass  # _close_once retains the canonical cleanup error
            if error is not None or self._closed:
                while not queue.empty():
                    queue.get_nowait()
            elif queue.full():
                queue.get_nowait()
            queue.put_nowait(_StreamEnd(error))
            if cleanup_cancellation is not None:
                raise cleanup_cancellation

    async def _order_worker(self, queue: asyncio.Queue[Any | _StreamEnd]) -> None:
        error: BrokerError | None = None
        replacements = 0
        feed: object | None = None
        cleanup_cancellation: asyncio.CancelledError | None = None
        try:
            feed = await self.order_feed()
            while feed is not None and not self._closed:
                generation = self._order_generation
                iterator = feed.__aiter__()  # type: ignore[attr-defined]
                while not self._closed:
                    try:
                        message = await anext(iterator)
                    except StopAsyncIteration:
                        break
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        if generation not in self._disconnected_generations:
                            error = _canonical_error(exc, "order feed iteration")
                        break
                    if self._order_feed is not feed or self._order_generation != generation:
                        continue
                    try:
                        if order_feed_message_kind(message) is not None:
                            if queue.qsize() >= STREAM_QUEUE_SIZE:
                                raise BrokerInternal(
                                    "Kotak Neo order feed buffer overflow",
                                    broker_id="kotakneo",
                                )
                            queue.put_nowait(message)
                    except Exception as exc:
                        error = _canonical_error(exc, "order feed message classification")
                        break
                if error is not None:
                    break
                if self._closed:
                    break
                expected = feed
                while not self._closed:
                    replacements += 1
                    if replacements > MAX_STREAM_REPLACEMENTS:
                        error = BrokerInternal(
                            "Kotak Neo order feed replacement limit reached",
                            broker_id="kotakneo",
                        )
                        break
                    await self._reconnect_waiter()
                    try:
                        feed = await self._replace_order(expected)
                        break
                    except (BrokerTimeout, NetworkError):
                        expected = None
                if error is not None:
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self._closed:
                error = _canonical_error(exc, "order feed iteration")
        finally:
            if error is not None and feed is not None:
                cleanup = self._spawn(self._detach_order_for_iterator(feed))
                try:
                    await cleanup
                except asyncio.CancelledError as exc:
                    cleanup_cancellation = exc
                except Exception:
                    pass  # _close_once retains the canonical cleanup error
            if self._closed:
                while not queue.empty():
                    queue.get_nowait()
            queue.put_nowait(_StreamEnd(error))
            if cleanup_cancellation is not None:
                raise cleanup_cancellation

    async def _detach_market_for_iterator(self, expected: object | None = None) -> None:
        try:
            async with self._mutation_lock:
                async with self._market_lock:
                    if self._closed:
                        return
                    await self._detach_market_locked(expected)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            canonical = _canonical_error(exc, "market feed close")
            self._pending_cleanup_error = self._pending_cleanup_error or canonical
            raise canonical

    async def _detach_order_for_iterator(self, expected: object | None = None) -> None:
        try:
            async with self._order_lock:
                if self._closed:
                    return
                await self._detach_order_locked(expected)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            canonical = _canonical_error(exc, "order feed close")
            self._pending_cleanup_error = self._pending_cleanup_error or canonical
            raise canonical

    def market_messages(self) -> AsyncIterator[TickEvent]:
        return self._market_messages_impl()

    async def _market_messages_impl(self) -> AsyncIterator[TickEvent]:
        claimed = False
        worker: asyncio.Task[Any] | None = None
        queue: asyncio.Queue[TickEvent | _StreamEnd] | None = None
        async with self._market_iterator_lock:
            self._require_open()
            if self._market_iterator_active:
                raise BrokerError("Kotak Neo market iterator is already active", broker_id="kotakneo")
            worker = self._market_pump_task
            queue = self._market_queue
            if worker is None or (worker.done() and (queue is None or queue.empty())):
                if worker is not None:
                    self._market_pump_task = None
                    self._market_queue = None
                await self.market_feed()
                worker = self._market_pump_task
                queue = self._market_queue
            if worker is None or queue is None:
                raise BrokerInternal("Kotak Neo market ingress pump is unavailable", broker_id="kotakneo")
            self._market_iterator_active = True
            claimed = True
        try:
            while True:
                item = await queue.get()
                if isinstance(item, _StreamEnd):
                    if item.error is not None:
                        raise item.error
                    return
                yield item
        finally:
            primary_exception = sys.exc_info()[1]
            worker_cancellation: asyncio.CancelledError | None = None
            if worker is not None:
                self._market_workers.discard(worker)
                if not worker.done():
                    worker.cancel()
                _, worker_cancellation = await _complete_despite_cancellation(worker)
            if claimed:
                cleanup = self._spawn(self._detach_market_for_iterator())
                cleanup_error, cleanup_cancellation = await _complete_despite_cancellation(cleanup)
                deferred_cleanup_error: BrokerError | None = None
                async with self._market_iterator_lock:
                    if self._market_pump_task is worker:
                        self._market_pump_task = None
                        self._market_queue = None
                    self._market_iterator_active = False
                if cleanup_error is not None and not isinstance(cleanup_error, asyncio.CancelledError):
                    canonical = (
                        cleanup_error
                        if isinstance(cleanup_error, BrokerError)
                        else _canonical_error(cleanup_error, "market feed close")
                    )
                    self._pending_cleanup_error = self._pending_cleanup_error or canonical
                    if primary_exception is None or isinstance(primary_exception, GeneratorExit):
                        deferred_cleanup_error = canonical
                if worker_cancellation is not None:
                    raise worker_cancellation
                if cleanup_cancellation is not None:
                    raise cleanup_cancellation
                if deferred_cleanup_error is not None:
                    raise deferred_cleanup_error

    def order_messages(self) -> AsyncIterator[Any]:
        return self._order_messages_impl()

    async def _order_messages_impl(self) -> AsyncIterator[Any]:
        claimed = False
        worker: asyncio.Task[Any] | None = None
        # Reserve one physical slot for the terminal sentinel so every
        # accepted order/position update is delivered before an overflow.
        queue: asyncio.Queue[Any | _StreamEnd] = asyncio.Queue(maxsize=STREAM_QUEUE_SIZE + 1)
        async with self._order_iterator_lock:
            self._require_open()
            if self._order_iterator_active:
                raise BrokerError("Kotak Neo order iterator is already active", broker_id="kotakneo")
            self._order_iterator_active = True
            claimed = True
        try:
            worker = self._spawn(self._order_worker(queue))
            self._order_workers.add(worker)
            while True:
                item = await queue.get()
                if isinstance(item, _StreamEnd):
                    if item.error is not None:
                        raise item.error
                    return
                yield item
        finally:
            primary_exception = sys.exc_info()[1]
            worker_cancellation: asyncio.CancelledError | None = None
            if worker is not None:
                self._order_workers.discard(worker)
                if not worker.done():
                    worker.cancel()
                _, worker_cancellation = await _complete_despite_cancellation(worker)
            if claimed:
                cleanup = self._spawn(self._detach_order_for_iterator())
                cleanup_error, cleanup_cancellation = await _complete_despite_cancellation(cleanup)
                deferred_cleanup_error: BrokerError | None = None
                async with self._order_iterator_lock:
                    self._order_iterator_active = False
                if cleanup_error is not None and not isinstance(cleanup_error, asyncio.CancelledError):
                    canonical = (
                        cleanup_error
                        if isinstance(cleanup_error, BrokerError)
                        else _canonical_error(cleanup_error, "order feed close")
                    )
                    self._pending_cleanup_error = self._pending_cleanup_error or canonical
                    if primary_exception is None or isinstance(primary_exception, GeneratorExit):
                        deferred_cleanup_error = canonical
                if worker_cancellation is not None:
                    raise worker_cancellation
                if cleanup_cancellation is not None:
                    raise cleanup_cancellation
                if deferred_cleanup_error is not None:
                    raise deferred_cleanup_error

    async def _run_cleanup(self) -> BrokerError | None:
        first_error: BrokerError | None = None

        current = asyncio.current_task()
        tasks = {
            *self._market_workers,
            *self._order_workers,
            *self._mutation_tasks,
            *(task for task in (self._market_candidate_task, self._order_candidate_task) if task is not None),
        }
        tasks.discard(current)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        async with self._mutation_lock:
            async with self._market_lock:
                market = self._market_feed
                market_candidate = self._market_candidate
                market_generation = self._market_generation
                market_candidate_generation = self._market_candidate_generation
                self._market_feed = None
                self._market_generation = None
                self._market_candidate = None
                self._market_candidate_generation = None
                self._market_candidate_task = None
                self._market_candidate_queue = None
                self._retire_generation(market_generation)
                self._retire_generation(market_candidate_generation)
            async with self._order_lock:
                order = self._order_feed
                order_candidate = self._order_candidate
                order_generation = self._order_generation
                order_candidate_generation = self._order_candidate_generation
                self._order_feed = None
                self._order_generation = None
                self._order_candidate = None
                self._order_candidate_generation = None
                self._order_candidate_task = None
                self._retire_generation(order_generation)
                self._retire_generation(order_candidate_generation)
            self._market_pump_task = None
            self._market_queue = None
            self._ledger.clear()
            self._aliases.clear()
            self._fallback_symbols.clear()

        # Iterator detachment is serialised by the same locks above. Read its
        # retained close error only after that barrier, not at task creation.
        first_error = self._pending_cleanup_error

        async def record(awaitable: Awaitable[Any], operation: str) -> None:
            nonlocal first_error
            try:
                await awaitable
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                first_error = first_error or _canonical_error(exc, operation)

        for feed in dict.fromkeys(item for item in (market, market_candidate) if item is not None):
            await record(self._close_once(feed, "market feed close"), "market feed close")
        for feed in dict.fromkeys(item for item in (order, order_candidate) if item is not None):
            await record(self._close_once(feed, "order feed close"), "order feed close")

        logout = getattr(self._client, "logout_sdk", None)
        if not callable(logout):
            logout = getattr(self._client, "logout", None)
        if callable(logout):
            async def logout_stage() -> None:
                result = logout()
                if inspect.isawaitable(result):
                    await result

            await record(logout_stage(), "logout")
        else:
            first_error = first_error or BrokerInternal(
                "Kotak Neo logout is unavailable",
                broker_id="kotakneo",
            )

        close_rest = getattr(self._client, "close_rest", None)
        if callable(close_rest):
            async def rest_stage() -> None:
                result = close_rest()
                if inspect.isawaitable(result):
                    await result

            await record(rest_stage(), "REST close")
        else:
            first_error = first_error or BrokerInternal(
                "Kotak Neo REST close is unavailable",
                broker_id="kotakneo",
            )

        self._cleanup_done = True
        return first_error

    async def close(self) -> None:
        """Own and finish market, order, SDK logout and REST teardown once."""
        self._closed = True
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._run_cleanup())
        cleanup_task = self._cleanup_task
        error, cancellation = await _complete_despite_cancellation(cleanup_task)
        if cancellation is not None:
            raise cancellation
        if error is not None:
            if isinstance(error, BrokerError):
                raise error
            raise _canonical_error(error, "stream runtime close") from None
        first_error = cleanup_task.result()
        if first_error is not None:
            async with self._close_result_lock:
                if not self._cleanup_error_delivered:
                    self._cleanup_error_delivered = True
                    raise first_error
