"""Kotak Neo v3 async feed ownership and lifecycle contracts."""

from __future__ import annotations

import asyncio
import gc
import weakref
from collections.abc import AsyncIterator, Mapping
from typing import Any

import pytest
from neo_api_client.websocket.feed.exceptions import NotConnectedError as FeedNotConnectedError
from neo_api_client.websocket.feed.models import (
    SFeedCasChange,
    SFeedIndex,
    SFeedMarketStatus,
    SFeedScrip,
    SFeedScripLite,
    WsToken,
)
from neo_api_client.websocket.orderfeed.exceptions import NotConnectedError as OrderNotConnectedError
from neo_api_client.websocket.orderfeed.models import OrderData, OrderUpdate, PositionData, PositionUpdate

from flinttrade_core.exceptions import BrokerError, BrokerInternal, NetworkError, SessionExpired
from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
from flinttrade_gateway.brokers.kotakneo_streaming import (
    STREAM_RUNTIME_KEY,
    KotakNeoStreamRuntime,
)

pytestmark = pytest.mark.unit


_END = object()


class _Feed:
    def __init__(
        self,
        *,
        connect_error: Exception | None = None,
        close_error: Exception | None = None,
        operation_errors: dict[str, Exception] | None = None,
    ) -> None:
        self.connect_error = connect_error
        self.close_error = close_error
        self.connect_calls = 0
        self.close_calls = 0
        self.close_called = asyncio.Event()
        self.calls: list[tuple[str, tuple[WsToken, ...]]] = []
        self.queue: asyncio.Queue[Any] = asyncio.Queue()
        self.on_connect = None
        self.on_disconnect = None
        self.on_error = None
        self.operation_errors = dict(operation_errors or {})
        self.anext_calls = 0
        self.input_drained = asyncio.Event()

    def _record(self, name: str, tokens: list[WsToken]) -> None:
        self.calls.append((name, tuple(tokens)))
        failure = self.operation_errors.get(name)
        if failure is not None:
            raise failure

    async def connect(self) -> None:
        self.connect_calls += 1
        if self.connect_error is not None:
            raise self.connect_error
        if self.on_connect is not None:
            self.on_connect()

    async def close(self) -> None:
        self.close_calls += 1
        self.close_called.set()
        if self.on_disconnect is not None:
            self.on_disconnect()
        if self.close_error is not None:
            raise self.close_error

    async def subscribe_scrips(self, tokens: list[WsToken]) -> None:
        self._record("subscribe_scrips", tokens)

    async def unsubscribe_scrips(self, tokens: list[WsToken]) -> None:
        self._record("unsubscribe_scrips", tokens)

    async def subscribe_depth(self, tokens: list[WsToken]) -> None:
        self._record("subscribe_depth", tokens)

    async def unsubscribe_depth(self, tokens: list[WsToken]) -> None:
        self._record("unsubscribe_depth", tokens)

    async def subscribe_index(self, tokens: list[WsToken]) -> None:
        self._record("subscribe_index", tokens)

    async def unsubscribe_index(self, tokens: list[WsToken]) -> None:
        self._record("unsubscribe_index", tokens)

    def __aiter__(self) -> AsyncIterator[Any]:
        return self

    async def __anext__(self) -> Any:
        value = await self.queue.get()
        self.anext_calls += 1
        if self.queue.empty():
            self.input_drained.set()
        if isinstance(value, BaseException):
            raise value
        if value is _END:
            raise StopAsyncIteration
        return value


class _BlockingConnectFeed(_Feed):
    def __init__(self) -> None:
        super().__init__()
        self.connect_started = asyncio.Event()
        self.connect_release = asyncio.Event()

    async def connect(self) -> None:
        self.connect_calls += 1
        self.connect_started.set()
        await self.connect_release.wait()


class _BlockingSubscribeFeed(_Feed):
    def __init__(self) -> None:
        super().__init__()
        self.subscribe_started = asyncio.Event()
        self.subscribe_release = asyncio.Event()

    async def subscribe_scrips(self, tokens: list[WsToken]) -> None:
        self.calls.append(("subscribe_scrips", tuple(tokens)))
        self.subscribe_started.set()
        await self.subscribe_release.wait()


class _BlockingFailingSubscribeFeed(_BlockingSubscribeFeed):
    async def subscribe_scrips(self, tokens: list[WsToken]) -> None:
        self.calls.append(("subscribe_scrips", tuple(tokens)))
        self.subscribe_started.set()
        await self.subscribe_release.wait()
        raise ConnectionError("mutation-secret")


class _CancellationBlockingFeed(_Feed):
    def __init__(self) -> None:
        super().__init__()
        self.iteration_started = asyncio.Event()
        self.cancellation_seen = asyncio.Event()
        self.cancellation_release = asyncio.Event()

    async def __anext__(self) -> Any:
        self.iteration_started.set()
        try:
            await self.cancellation_release.wait()
        except asyncio.CancelledError:
            self.cancellation_seen.set()
            current = asyncio.current_task()
            if current is not None:
                current.uncancel()
            await self.cancellation_release.wait()
            raise
        raise StopAsyncIteration


class _QueuedThenCancellationBlockingFeed(_CancellationBlockingFeed):
    def __init__(self) -> None:
        super().__init__()
        self.first_yielded = False

    async def __anext__(self) -> Any:
        if not self.first_yielded:
            self.first_yielded = True
            return await _Feed.__anext__(self)
        return await super().__anext__()


class _BlockingSecondSubscribeFeed(_Feed):
    def __init__(self) -> None:
        super().__init__()
        self.subscribe_started = asyncio.Event()
        self.subscribe_release = asyncio.Event()
        self._subscribe_count = 0

    async def subscribe_scrips(self, tokens: list[WsToken]) -> None:
        self.calls.append(("subscribe_scrips", tuple(tokens)))
        self._subscribe_count += 1
        if self._subscribe_count == 2:
            self.subscribe_started.set()
            await self.subscribe_release.wait()


class _BlockingSecondFailingSubscribeFeed(_BlockingSecondSubscribeFeed):
    async def subscribe_scrips(self, tokens: list[WsToken]) -> None:
        await super().subscribe_scrips(tokens)
        if self._subscribe_count == 2:
            raise ConnectionError("mutation-secret")


class _BlockingCloseErrorFeed(_Feed):
    def __init__(self) -> None:
        super().__init__()
        self.close_started = asyncio.Event()
        self.close_release = asyncio.Event()

    async def close(self) -> None:
        self.close_calls += 1
        self.close_called.set()
        self.close_started.set()
        await self.close_release.wait()
        raise RuntimeError("close-secret")


class _BlockingCloseFeed(_Feed):
    def __init__(self) -> None:
        super().__init__()
        self.close_started = asyncio.Event()
        self.close_release = asyncio.Event()
        self.close_finished = asyncio.Event()

    async def close(self) -> None:
        self.close_calls += 1
        self.close_called.set()
        self.close_started.set()
        await self.close_release.wait()
        self.close_finished.set()


class _OrderedCloseFeed(_Feed):
    def __init__(self, label: str, close_order: list[str], *, close_error: Exception | None = None) -> None:
        super().__init__(close_error=close_error)
        self.label = label
        self.close_order = close_order

    async def close(self) -> None:
        self.close_order.append(self.label)
        await super().close()


class _RejectingDisconnectCallbackFeed(_Feed):
    def __init__(self) -> None:
        self._reject_disconnect_callback = False
        super().__init__()
        self._reject_disconnect_callback = True

    def __setattr__(self, name: str, value: object) -> None:
        if name == "on_disconnect" and getattr(self, "_reject_disconnect_callback", False):
            raise RuntimeError("callback-secret")
        super().__setattr__(name, value)


class _Facade:
    def __init__(
        self,
        *,
        market_feeds: list[_Feed] | None = None,
        order_feeds: list[_Feed] | None = None,
        logout_error: Exception | None = None,
        rest_error: Exception | None = None,
    ) -> None:
        self.market_feeds = list(market_feeds or [_Feed()])
        self.order_feeds = list(order_feeds or [_Feed()])
        self.market_factory_calls = 0
        self.order_factory_calls = 0
        self.logout_calls = 0
        self.rest_close_calls = 0
        self.logout_error = logout_error
        self.rest_error = rest_error

    def create_websocket(self, url: str | None = None, **kwargs: Any) -> _Feed:
        assert url is None
        assert kwargs == {"max_connect_retries": 0, "max_reconnect_attempts": 0, "max_subscriptions": 3000}
        feed = self.market_feeds[self.market_factory_calls]
        self.market_factory_calls += 1
        return feed

    def create_order_feed(self, **kwargs: Any) -> _Feed:
        assert kwargs == {"max_connect_retries": 0, "max_reconnect_attempts": 0}
        feed = self.order_feeds[self.order_factory_calls]
        self.order_factory_calls += 1
        return feed

    def logout_sdk(self) -> None:
        self.logout_calls += 1
        if self.logout_error is not None:
            raise self.logout_error

    def close_rest(self) -> None:
        self.rest_close_calls += 1
        if self.rest_error is not None:
            raise self.rest_error


class _EphemeralFacade(_Facade):
    def __init__(self) -> None:
        super().__init__()
        self.refs: list[weakref.ReferenceType[_Feed]] = []

    def create_websocket(self, url: str | None = None, **kwargs: Any) -> _Feed:
        assert url is None
        assert kwargs == {"max_connect_retries": 0, "max_reconnect_attempts": 0, "max_subscriptions": 3000}
        self.market_factory_calls += 1
        feed = _Feed()
        self.refs.append(weakref.ref(feed))
        return feed


async def _login(adapter: KotakNeoAdapter, ucc: str = "U1"):
    return await adapter.login(
        {
            "consumer_key": "synthetic-key",
            "mobile_number": "+910000000000",
            "ucc": ucc,
            "mpin": "123456",
            "totp": "000000",
        }
    )


def _lite(token: str = "14366", symbol: str = "IDEA-EQ") -> SFeedScripLite:
    return SFeedScripLite(
        exchange_segment="nse_cm",
        instrument_token=token,
        trading_symbol=symbol,
        last_traded_price=9.4,
        last_trade_time=1_727_000_000,
        last_trade_qty=1,
        close_price=9.3,
        net_change=0.1,
        net_change_percent=1.0,
        market_lot=1,
        precision=2,
        multiplier=1,
    )


def _scrip() -> SFeedScrip:
    # ``model_construct`` lets the test focus on the fields consumed by the
    # adapter while retaining the SDK's exact runtime type discriminator.
    return SFeedScrip.model_construct(
        exchange_segment="nse_cm",
        instrument_token="14366",
        trading_symbol="IDEA-EQ",
        last_traded_price=9.4,
        volume_traded_today=1000,
        open_interest=12,
        last_trade_time=1_727_000_001,
        buy=[type("Level", (), {"price": 9.39})()],
        sell=[type("Level", (), {"price": 9.41})()],
    )


def _index(*, token: str = "Nifty 50", name: str = "Nifty 50", symbol: str = "NIFTY 50") -> SFeedIndex:
    return SFeedIndex.model_construct(
        exchange_segment="nse_cm",
        instrument_token=token,
        trading_symbol=symbol,
        name=name,
        last_traded_price=24_050.5,
        last_trade_time=1_727_000_002,
    )


@pytest.mark.asyncio
async def test_login_owns_one_session_scoped_runtime_and_exact_lazy_factories() -> None:
    facade = _Facade()
    adapter = KotakNeoAdapter(client_factory=lambda _session: facade, token_resolver=lambda _s, _e: "14366")

    session = await _login(adapter)
    runtime = session.extra[STREAM_RUNTIME_KEY]
    assert isinstance(runtime, KotakNeoStreamRuntime)

    first, second = await asyncio.gather(runtime.market_feed(), runtime.market_feed())
    order_first, order_second = await asyncio.gather(runtime.order_feed(), runtime.order_feed())
    assert first is second is facade.market_feeds[0]
    assert order_first is order_second is facade.order_feeds[0]
    assert facade.market_factory_calls == facade.order_factory_calls == 1
    assert first.connect_calls == order_first.connect_calls == 1


@pytest.mark.asyncio
async def test_subscription_pairs_are_serialised_idempotent_and_conflicts_fail_before_transport() -> None:
    facade = _Facade()
    adapter = KotakNeoAdapter(client_factory=lambda _session: facade, token_resolver=lambda _s, _e: "14366")
    session = await _login(adapter)
    feed = facade.market_feeds[0]

    await asyncio.gather(
        adapter.subscribe(session, ["NSE:IDEA"], mode="FULL"),
        adapter.subscribe(session, ["NSE:IDEA"], mode="FULL"),
    )
    assert [name for name, _tokens in feed.calls] == ["subscribe_depth"]
    token = feed.calls[0][1][0]
    assert isinstance(token, WsToken)
    assert (token.exchange_segment, token.instrument_token) == ("nse_cm", "14366")

    with pytest.raises(BrokerError, match="different feed intent"):
        await adapter.subscribe(session, ["NSE:IDEA"], mode="LTP")
    assert [name for name, _tokens in feed.calls] == ["subscribe_depth"]

    await adapter.unsubscribe(session, ["NSE:IDEA"])
    await adapter.unsubscribe(session, ["NSE:IDEA"])
    await adapter.subscribe(session, ["NSE:IDEA"], mode="LTP")
    assert [name for name, _tokens in feed.calls] == [
        "subscribe_depth",
        "unsubscribe_depth",
        "subscribe_scrips",
    ]


@pytest.mark.asyncio
async def test_aliases_for_one_token_are_references_until_the_last_alias_is_removed() -> None:
    feed = _Feed()
    runtime = KotakNeoStreamRuntime(_Facade(market_feeds=[feed]))
    rows = [
        {"exchange_segment": "nse_cm", "instrument_token": "1"},
        {"exchange_segment": "nse_cm", "instrument_token": "1"},
    ]
    aliases = [("nse_cm", "ONE"), ("nse_cm", "ONE-EQ")]
    await runtime.add_subscriptions(rows, intent="scrips", aliases=aliases)
    assert runtime.subscription_count == 1
    assert [name for name, _tokens in feed.calls] == ["subscribe_scrips"]

    await runtime.remove_subscriptions([aliases[0]])
    assert runtime.subscription_count == 1
    assert [name for name, _tokens in feed.calls] == ["subscribe_scrips"]
    await runtime.remove_subscriptions([aliases[1]])
    assert runtime.subscription_count == 0
    assert [name for name, _tokens in feed.calls] == ["subscribe_scrips", "unsubscribe_scrips"]

    await runtime.add_subscriptions(rows, intent="scrips", aliases=aliases)
    await runtime.remove_subscriptions(aliases)
    assert runtime.subscription_count == 0
    assert [name for name, _tokens in feed.calls][-2:] == ["subscribe_scrips", "unsubscribe_scrips"]


@pytest.mark.asyncio
async def test_request_local_alias_collision_fails_before_feed_creation() -> None:
    facade = _Facade()
    runtime = KotakNeoStreamRuntime(facade)

    with pytest.raises(BrokerError, match="alias conflicts"):
        await runtime.add_subscriptions(
            [
                {"exchange_segment": "nse_cm", "instrument_token": "1"},
                {"exchange_segment": "nse_cm", "instrument_token": "2"},
            ],
            intent="scrips",
            aliases=[("nse_cm", "ONE"), ("nse_cm", "ONE")],
        )

    assert facade.market_factory_calls == 0


@pytest.mark.asyncio
async def test_adapter_rejects_alias_cap_before_resolution_and_deduplicates_raw_aliases() -> None:
    facade = _Facade()
    resolutions: list[tuple[str, str]] = []

    def resolve(symbol: str, exchange: str) -> str:
        resolutions.append((symbol, exchange))
        return "1"

    adapter = KotakNeoAdapter(client_factory=lambda _session: facade, token_resolver=resolve)
    session = await _login(adapter)
    with pytest.raises(BrokerError, match="3000"):
        await adapter.subscribe(session, [f"NSE:S{number}" for number in range(3001)], mode="LTP")
    assert resolutions == []
    assert facade.market_factory_calls == 0

    await adapter.subscribe(session, ["NSE:IDEA", "NSE:IDEA"], mode="LTP")
    assert resolutions == [("IDEA", "NSE")]
    assert len(facade.market_feeds[0].calls[0][1]) == 1


@pytest.mark.asyncio
async def test_empty_subscription_is_noop_without_feed_creation() -> None:
    facade = _Facade()
    adapter = KotakNeoAdapter(client_factory=lambda _session: facade, token_resolver=lambda _s, _e: "1")
    session = await _login(adapter)
    await adapter.subscribe(session, [], mode="LTP")
    assert facade.market_factory_calls == 0


@pytest.mark.asyncio
async def test_index_uses_index_pair_and_cap_is_aggregate_and_pretransport() -> None:
    facade = _Facade()
    runtime = KotakNeoStreamRuntime(facade)
    await runtime.add_subscriptions(
        [{"exchange_segment": "nse_cm", "instrument_token": "Nifty 50"}],
        intent="index",
        aliases=[("nse_cm", "NIFTY 50")],
    )
    await runtime.remove_subscriptions([("nse_cm", "NIFTY 50")])
    assert [name for name, _tokens in facade.market_feeds[0].calls] == [
        "subscribe_index",
        "unsubscribe_index",
    ]

    capped = _Facade()
    capped_runtime = KotakNeoStreamRuntime(capped)
    with pytest.raises(BrokerError, match="3000"):
        await capped_runtime.add_subscriptions(
            [
                {"exchange_segment": "nse_cm", "instrument_token": str(number)}
                for number in range(1, 3002)
            ],
            intent="scrips",
            aliases=[("nse_cm", str(number)) for number in range(1, 3002)],
        )
    assert capped.market_factory_calls == 0


@pytest.mark.asyncio
async def test_exact_cap_succeeds_unsubscribe_frees_capacity_and_concurrent_crossing_is_serialised() -> None:
    facade = _Facade()
    runtime = KotakNeoStreamRuntime(facade)
    rows = [{"exchange_segment": "nse_cm", "instrument_token": str(number)} for number in range(3000)]
    aliases = [("nse_cm", str(number)) for number in range(3000)]

    await runtime.add_subscriptions(rows, intent="scrips", aliases=aliases)
    assert runtime.subscription_count == 3000
    await runtime.remove_subscriptions([aliases[0]])
    assert runtime.subscription_count == 2999

    outcomes = await asyncio.gather(
        runtime.add_subscriptions(
            [{"exchange_segment": "nse_cm", "instrument_token": "new-a"}],
            intent="scrips",
            aliases=[("nse_cm", "NEW-A")],
        ),
        runtime.add_subscriptions(
            [{"exchange_segment": "nse_cm", "instrument_token": "new-b"}],
            intent="scrips",
            aliases=[("nse_cm", "NEW-B")],
        ),
        return_exceptions=True,
    )
    assert sum(outcome is None for outcome in outcomes) == 1
    assert sum(isinstance(outcome, BrokerError) for outcome in outcomes) == 1
    assert runtime.subscription_count == 3000


@pytest.mark.asyncio
async def test_two_accounts_and_same_account_sessions_have_isolated_runtime_ledgers() -> None:
    facades = {"U1": _Facade(market_feeds=[_Feed(), _Feed()]), "U2": _Facade()}
    adapter = KotakNeoAdapter(
        client_factory=lambda session: facades[session.account_id],
        token_resolver=lambda symbol, _exchange: {"IDEA": "14366", "TCS": "11536"}[symbol],
    )
    first = await _login(adapter, "U1")
    second = await _login(adapter, "U2")
    same_account = await _login(adapter, "U1")

    assert first.extra[STREAM_RUNTIME_KEY] is not same_account.extra[STREAM_RUNTIME_KEY]
    await adapter.subscribe(first, ["NSE:IDEA"], mode="LTP")
    await adapter.subscribe(second, ["NSE:TCS"], mode="FULL")
    # A distinct login for the same account owns a distinct connection too.
    await adapter.subscribe(same_account, ["NSE:IDEA"], mode="LTP")
    assert facades["U1"].market_factory_calls == 2
    assert facades["U2"].market_factory_calls == 1


@pytest.mark.asyncio
async def test_closing_one_same_account_session_never_stops_peer_market_or_order_streams() -> None:
    first_facade = _Facade()
    peer_facade = _Facade()
    facades = iter((first_facade, peer_facade))
    adapter = KotakNeoAdapter(
        client_factory=lambda _session: next(facades),
        token_resolver=lambda _symbol, _exchange: "14366",
    )
    first = await _login(adapter, "SAME")
    peer = await _login(adapter, "SAME")
    await adapter.subscribe(first, ["NSE:IDEA"], mode="LTP")
    await adapter.subscribe(peer, ["NSE:IDEA"], mode="LTP")
    peer_market = adapter.stream(peer)
    peer_order = adapter.order_stream(peer)
    peer_market_waiting = asyncio.create_task(anext(peer_market))
    peer_order_waiting = asyncio.create_task(anext(peer_order))
    while peer_facade.order_factory_calls < 1:
        await asyncio.sleep(0)

    await adapter.logout(first)
    await peer_facade.market_feeds[0].queue.put(_lite(symbol="PEER"))
    order = OrderUpdate(data=OrderData(nOrdNo="PEER-OID", ordSt="open", trdSym="IDEA-EQ"))
    await peer_facade.order_feeds[0].queue.put(order)

    assert (await peer_market_waiting).symbol == "PEER"
    assert await peer_order_waiting is order
    assert first_facade.logout_calls == first_facade.rest_close_calls == 1
    assert peer_facade.market_feeds[0].close_calls == peer_facade.order_feeds[0].close_calls == 0
    assert peer_facade.logout_calls == peer_facade.rest_close_calls == 0
    await peer_market.aclose()
    await peer_order.aclose()
    await adapter.logout(peer)


@pytest.mark.asyncio
async def test_candidate_is_closed_after_connect_failure_and_not_published() -> None:
    failed = _Feed(connect_error=ConnectionError("credential-fragment"))
    healthy = _Feed()
    facade = _Facade(market_feeds=[failed, healthy])
    runtime = KotakNeoStreamRuntime(facade)

    with pytest.raises(BrokerError) as raised:
        await runtime.market_feed()
    assert "credential-fragment" not in str(raised.value)
    assert failed.close_calls == 1
    assert await runtime.market_feed() is healthy


@pytest.mark.asyncio
async def test_cancellation_during_failed_candidate_close_wins_after_close_finishes() -> None:
    failed = _BlockingCloseFeed()
    failed.connect_error = ConnectionError("connect-secret")
    runtime = KotakNeoStreamRuntime(_Facade(market_feeds=[failed]))
    creating = asyncio.create_task(runtime.market_feed())
    await failed.close_started.wait()

    creating.cancel()
    failed.close_release.set()
    with pytest.raises(asyncio.CancelledError):
        await creating
    assert failed.close_finished.is_set()
    assert failed.close_calls == 1


@pytest.mark.asyncio
async def test_callback_install_failure_retires_generation_and_closes_candidate() -> None:
    failed = _RejectingDisconnectCallbackFeed()
    runtime = KotakNeoStreamRuntime(_Facade(market_feeds=[failed]))

    with pytest.raises(BrokerInternal):
        await runtime.market_feed()
    assert failed.close_calls == 1
    assert runtime._live_generations == set()
    assert runtime._disconnected_generations == set()


@pytest.mark.asyncio
async def test_market_stream_maps_only_typed_price_messages_and_skips_status_cas_and_raw() -> None:
    feed = _Feed()
    facade = _Facade(market_feeds=[feed])
    adapter = KotakNeoAdapter(
        client_factory=lambda _session: facade,
        token_resolver=lambda _symbol, _exchange: "14366",
    )
    session = await _login(adapter)
    await adapter.subscribe(session, ["NSE:IDEA"], mode="FULL")
    await adapter.subscribe(session, ["NSE:NIFTY 50"], mode="INDEX")
    stream = adapter.stream(session)

    await feed.queue.put(SFeedMarketStatus(exchange_segment="nse_cm", status_code=1, status="Market open"))
    await feed.queue.put(
        SFeedCasChange(
            exchange_segment="nse_cm",
            instrument_token="14366",
            trading_symbol="IDEA-EQ",
            ref_price=9.4,
            imbalance_qty=1,
            imbalance_qty_at_market=0,
        )
    )
    await feed.queue.put({"type": "raw", "credential": "must-not-surface"})
    await feed.queue.put(_scrip())
    first = await anext(stream)
    assert (first.symbol, first.exchange, first.ltp, first.volume, first.bid, first.ask, first.oi) == (
        "IDEA-EQ", "NSE", 9.4, 1000, 9.39, 9.41, 12,
    )
    assert first.timestamp == "1727000001"
    await feed.queue.put(_index())
    second = await anext(stream)
    assert (second.symbol, second.exchange, second.ltp, second.volume) == (
        "NIFTY 50", "NSE_INDEX", 24_050.5, 0,
    )
    assert second.timestamp == "1727000002"
    await stream.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent", "token", "alias", "message", "expected_symbol"),
    [
        ("scrips", "14366", "IDEA", _lite(), "IDEA-EQ"),
        ("depth", "14366", "IDEA", _scrip(), "IDEA-EQ"),
        ("index", "Nifty 50", "NIFTY 50", _index(token="999"), "NIFTY 50"),
    ],
)
async def test_market_ingress_accepts_only_committed_scrip_lite_depth_and_index_membership(
    intent: Any,
    token: str,
    alias: str,
    message: object,
    expected_symbol: str,
) -> None:
    feed = _Feed()
    runtime = KotakNeoStreamRuntime(_Facade(market_feeds=[feed]))
    await runtime.add_subscriptions(
        [{"exchange_segment": "nse_cm", "instrument_token": token}],
        intent=intent,
        aliases=[("nse_cm", alias)],
    )
    stream = runtime.market_messages()
    await feed.queue.put(message)

    assert (await anext(stream)).symbol == expected_symbol
    await stream.aclose()


def test_committed_scrip_membership_never_iterates_the_full_ledger() -> None:
    import flinttrade_gateway.brokers.kotakneo_streaming as streaming

    class NoLinearScan(dict):
        def items(self):
            raise AssertionError("ordinary tick membership must use direct key lookup")

    ledger = NoLinearScan(
        {
            ("nse_cm", "14366"): streaming._Subscription(  # noqa: SLF001
                WsToken("nse_cm", "14366"),
                "scrips",
            )
        }
    )

    assert streaming._message_matches_ledger(_lite(), ledger)  # noqa: SLF001


@pytest.mark.asyncio
async def test_enriched_tick_never_scans_aliases_for_an_unused_fallback() -> None:
    class NoLinearScan(dict):
        def items(self):
            raise AssertionError("enriched tick must not scan aliases")

    feed = _Feed()
    runtime = KotakNeoStreamRuntime(_Facade(market_feeds=[feed]))
    await runtime.add_subscriptions(
        [{"exchange_segment": "nse_cm", "instrument_token": "14366"}],
        intent="scrips",
        aliases=[("nse_cm", "IDEA")],
    )
    runtime._aliases = NoLinearScan(runtime._aliases)  # noqa: SLF001
    stream = runtime.market_messages()
    await feed.queue.put(_lite(symbol="IDEA-EQ"))

    assert (await anext(stream)).symbol == "IDEA-EQ"
    await stream.aclose()


@pytest.mark.asyncio
async def test_unenriched_tick_uses_constant_time_committed_fallback() -> None:
    class NoLinearScan(dict):
        def items(self):
            raise AssertionError("unenriched tick fallback must not scan aliases")

    feed = _Feed()
    runtime = KotakNeoStreamRuntime(_Facade(market_feeds=[feed]))
    await runtime.add_subscriptions(
        [{"exchange_segment": "nse_cm", "instrument_token": "14366"}],
        intent="scrips",
        aliases=[("nse_cm", "IDEA")],
    )
    runtime._aliases = NoLinearScan(runtime._aliases)  # noqa: SLF001
    stream = runtime.market_messages()
    await feed.queue.put(_lite(symbol=""))

    assert (await anext(stream)).symbol == "IDEA"
    await stream.aclose()


@pytest.mark.asyncio
async def test_candidate_uses_mapping_snapshot_and_constant_time_unenriched_fallback(monkeypatch) -> None:
    import flinttrade_gateway.brokers.kotakneo_streaming as streaming

    class NoLinearScan(dict):
        def items(self):
            raise AssertionError("candidate fallback must not scan aliases")

    initial = _Feed()
    candidate = _BlockingSubscribeFeed()
    runtime = KotakNeoStreamRuntime(_Facade(market_feeds=[initial, candidate]))
    await runtime.add_subscriptions(
        [{"exchange_segment": "nse_cm", "instrument_token": "14366"}],
        intent="scrips",
        aliases=[("nse_cm", "IDEA")],
    )
    runtime._aliases = NoLinearScan(runtime._aliases)  # noqa: SLF001

    original = streaming._message_matches_ledger  # noqa: SLF001
    snapshots: list[Mapping[object, object]] = []

    def require_mapping_snapshot(message: object, ledger: Mapping[object, object]) -> bool:
        assert isinstance(ledger, Mapping)
        snapshots.append(ledger)
        return original(message, ledger)

    monkeypatch.setattr(streaming, "_message_matches_ledger", require_mapping_snapshot)
    initial.on_disconnect()
    replacing = asyncio.create_task(runtime.market_feed())
    await candidate.subscribe_started.wait()
    await candidate.queue.put(_lite(symbol=""))
    await candidate.input_drained.wait()
    candidate.subscribe_release.set()

    assert await replacing is candidate
    stream = runtime.market_messages()
    assert (await anext(stream)).symbol == "IDEA"
    assert snapshots
    await stream.aclose()


@pytest.mark.asyncio
async def test_failed_in_place_add_never_exposes_precommit_tick_to_active_iterator() -> None:
    feed = _BlockingSecondFailingSubscribeFeed()
    runtime = KotakNeoStreamRuntime(_Facade(market_feeds=[feed]))
    await runtime.add_subscriptions(
        [{"exchange_segment": "nse_cm", "instrument_token": "1"}],
        intent="scrips",
        aliases=[("nse_cm", "ONE")],
    )
    stream = runtime.market_messages()
    waiting = asyncio.create_task(anext(stream))
    adding = asyncio.create_task(
        runtime.add_subscriptions(
            [{"exchange_segment": "nse_cm", "instrument_token": "2"}],
            intent="scrips",
            aliases=[("nse_cm", "TWO")],
        )
    )
    await feed.subscribe_started.wait()

    feed.input_drained.clear()
    await feed.queue.put(_lite(token="2", symbol="TWO"))
    await feed.input_drained.wait()
    await asyncio.sleep(0)
    assert not waiting.done()

    feed.input_drained.clear()
    await feed.queue.put(_lite(token="1", symbol="ONE"))
    assert (await waiting).symbol == "ONE"
    feed.subscribe_release.set()
    with pytest.raises(NetworkError):
        await adding
    assert runtime.subscription_count == 1
    await stream.aclose()
    await runtime.close()


@pytest.mark.asyncio
async def test_runtime_reconnects_fresh_feed_and_replays_atomically_with_sdk_reconnect_disabled() -> None:
    first_feed = _Feed()
    second_feed = _Feed()
    facade = _Facade(market_feeds=[first_feed, second_feed])
    runtime = KotakNeoStreamRuntime(facade)
    await runtime.add_subscriptions(
        [{"exchange_segment": "nse_cm", "instrument_token": "14366"}],
        intent="scrips",
        aliases=[("nse_cm", "IDEA")],
    )
    stream = runtime.market_messages()
    await first_feed.queue.put(_lite())
    initial_tick = await anext(stream)
    assert initial_tick.ltp == 9.4
    assert initial_tick.timestamp == "1727000000"

    await first_feed.queue.put(_END)
    resumed = asyncio.create_task(anext(stream))
    while facade.market_factory_calls < 2:
        await asyncio.sleep(0)
    await second_feed.queue.put(_lite(symbol="IDEA-RECONNECTED"))
    assert (await asyncio.wait_for(resumed, 1)).symbol == "IDEA-RECONNECTED"
    assert first_feed.connect_calls == second_feed.connect_calls == 1
    assert [name for name, _tokens in first_feed.calls] == ["subscribe_scrips"]
    assert [name for name, _tokens in second_feed.calls] == ["subscribe_scrips"]
    assert first_feed.calls[0][1][0] is second_feed.calls[0][1][0]
    await stream.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["market", "order"])
async def test_failed_reconnect_candidate_uses_remaining_budget_and_recovers(kind: str) -> None:
    async def no_wait() -> None:
        await asyncio.sleep(0)

    first = _Feed()
    failed = _Feed(connect_error=ConnectionError("private-connect-detail"))
    healthy = _Feed()
    facade = _Facade(
        market_feeds=[first, failed, healthy] if kind == "market" else None,
        order_feeds=[first, failed, healthy] if kind == "order" else None,
    )
    runtime = KotakNeoStreamRuntime(facade, reconnect_waiter=no_wait)
    if kind == "market":
        await runtime.add_subscriptions(
            [{"exchange_segment": "nse_cm", "instrument_token": "14366"}],
            intent="scrips",
            aliases=[("nse_cm", "IDEA")],
        )
    stream = runtime.market_messages() if kind == "market" else runtime.order_messages()
    initial = (
        _lite(symbol="FIRST")
        if kind == "market"
        else OrderUpdate(data=OrderData(nOrdNo="OID-1", ordSt="open", trdSym="IDEA-EQ"))
    )
    await first.queue.put(initial)
    assert await anext(stream) is initial or kind == "market"

    await first.queue.put(_END)
    resumed = asyncio.create_task(anext(stream))
    factory_attribute = "market_factory_calls" if kind == "market" else "order_factory_calls"

    async def wait_for_recovery() -> None:
        while getattr(facade, factory_attribute) < 3:
            await asyncio.sleep(0)

    await asyncio.wait_for(wait_for_recovery(), 1)
    recovered = (
        _lite(symbol="RECOVERED")
        if kind == "market"
        else OrderUpdate(data=OrderData(nOrdNo="OID-2", ordSt="open", trdSym="IDEA-EQ"))
    )
    await healthy.queue.put(recovered)

    received = await asyncio.wait_for(resumed, 1)
    if kind == "market":
        assert received.symbol == "RECOVERED"
    else:
        assert received is recovered
    assert first.close_calls == failed.close_calls == 1
    assert healthy.close_calls == 0
    await stream.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["market", "order"])
async def test_marked_sdk_not_connected_iteration_replaces_fresh_feed(kind: str) -> None:
    async def no_wait() -> None:
        await asyncio.sleep(0)

    first = _Feed()
    second = _Feed()
    facade = _Facade(
        market_feeds=[first, second] if kind == "market" else None,
        order_feeds=[first, second] if kind == "order" else None,
    )
    runtime = KotakNeoStreamRuntime(facade, reconnect_waiter=no_wait)
    if kind == "market":
        await runtime.add_subscriptions(
            [{"exchange_segment": "nse_cm", "instrument_token": "14366"}],
            intent="scrips",
            aliases=[("nse_cm", "IDEA")],
        )
    stream = runtime.market_messages() if kind == "market" else runtime.order_messages()
    first_message = (
        _lite(symbol="FIRST")
        if kind == "market"
        else OrderUpdate(data=OrderData(nOrdNo="OID-1", ordSt="open", trdSym="IDEA-EQ"))
    )
    await first.queue.put(first_message)
    assert await anext(stream) is first_message or kind == "market"

    first.on_disconnect()
    await first.queue.put(
        FeedNotConnectedError("not connected")
        if kind == "market"
        else OrderNotConnectedError("not connected")
    )
    resumed = asyncio.create_task(anext(stream))
    factory_attribute = "market_factory_calls" if kind == "market" else "order_factory_calls"

    async def wait_for_replacement() -> None:
        while getattr(facade, factory_attribute) < 2:
            await asyncio.sleep(0)

    await asyncio.wait_for(wait_for_replacement(), 1)
    second_message = (
        _lite(symbol="SECOND")
        if kind == "market"
        else OrderUpdate(data=OrderData(nOrdNo="OID-2", ordSt="open", trdSym="IDEA-EQ"))
    )
    await second.queue.put(second_message)

    received = await asyncio.wait_for(resumed, 1)
    if kind == "market":
        assert received.symbol == "SECOND"
    else:
        assert received is second_message
    assert first.close_calls == 1
    await stream.aclose()


@pytest.mark.asyncio
async def test_replacement_limit_counts_raw_generations_and_closes_every_feed(monkeypatch) -> None:
    import flinttrade_gateway.brokers.kotakneo_streaming as streaming

    monkeypatch.setattr(streaming, "STREAM_RECONNECT_DELAY_SECONDS", 0)
    feeds = [_Feed() for _ in range(4)]
    for feed in feeds:
        await feed.queue.put({"raw": "not-price"})
        await feed.queue.put(_END)
    runtime = KotakNeoStreamRuntime(_Facade(market_feeds=feeds))
    stream = runtime.market_messages()

    with pytest.raises(BrokerInternal, match="replacement limit"):
        await anext(stream)
    assert [feed.close_calls for feed in feeds] == [1, 1, 1, 1]


@pytest.mark.asyncio
async def test_close_cancels_owned_reconnect_backoff_and_wakes_iterator() -> None:
    backoff_started = asyncio.Event()
    backoff_release = asyncio.Event()

    async def blocked_backoff() -> None:
        backoff_started.set()
        await backoff_release.wait()

    feed = _Feed()
    runtime = KotakNeoStreamRuntime(_Facade(market_feeds=[feed]), reconnect_waiter=blocked_backoff)
    stream = runtime.market_messages()
    waiting = asyncio.create_task(anext(stream))
    await feed.queue.put(_END)
    await backoff_started.wait()

    await runtime.close()
    with pytest.raises(StopAsyncIteration):
        await waiting
    assert feed.close_calls == 1


@pytest.mark.asyncio
async def test_close_waits_for_shared_feed_close_cancelled_during_replacement() -> None:
    first = _BlockingCloseFeed()
    facade = _Facade(market_feeds=[first, _Feed()])
    runtime = KotakNeoStreamRuntime(facade)
    await runtime.market_feed()
    first.on_disconnect()
    replacing = asyncio.create_task(runtime.market_feed())
    await first.close_started.wait()

    closing = asyncio.create_task(runtime.close())
    await asyncio.sleep(0)
    assert not closing.done()
    assert not first.close_finished.is_set()

    first.close_release.set()
    await closing
    result = await asyncio.gather(replacing, return_exceptions=True)
    assert isinstance(result[0], (asyncio.CancelledError, BrokerError))
    assert first.close_finished.is_set()
    assert first.close_calls == 1
    assert facade.market_factory_calls == 1
    assert facade.logout_calls == facade.rest_close_calls == 1


@pytest.mark.asyncio
async def test_market_overflow_drops_oldest_without_stopping_sdk_queue_drain(monkeypatch) -> None:
    import flinttrade_gateway.brokers.kotakneo_streaming as streaming

    monkeypatch.setattr(streaming, "STREAM_QUEUE_SIZE", 2)
    feed = _Feed()
    runtime = KotakNeoStreamRuntime(_Facade(market_feeds=[feed]))
    await runtime.add_subscriptions(
        [{"exchange_segment": "nse_cm", "instrument_token": "1"}],
        intent="scrips",
        aliases=[("nse_cm", "ONE")],
    )
    stream = runtime.market_messages()
    for number in range(6):
        await feed.queue.put(_lite(token="1", symbol=f"S{number}"))

    first = await anext(stream)
    await asyncio.wait_for(feed.input_drained.wait(), 1)
    assert feed.queue.empty()
    second = await anext(stream)
    assert [first.symbol, second.symbol] == ["S4", "S5"]
    await stream.aclose()


@pytest.mark.asyncio
async def test_subscribed_market_feed_drains_into_bounded_runtime_queue_before_iterator(monkeypatch) -> None:
    import flinttrade_gateway.brokers.kotakneo_streaming as streaming

    monkeypatch.setattr(streaming, "STREAM_QUEUE_SIZE", 2)
    feed = _Feed()
    runtime = KotakNeoStreamRuntime(_Facade(market_feeds=[feed]))
    await runtime.add_subscriptions(
        [{"exchange_segment": "nse_cm", "instrument_token": "1"}],
        intent="scrips",
        aliases=[("nse_cm", "ONE")],
    )
    for number in range(6):
        await feed.queue.put(_lite(token="1", symbol=f"S{number}"))

    await asyncio.wait_for(feed.input_drained.wait(), 1)
    assert feed.queue.empty()
    assert runtime._market_queue is not None
    assert runtime._market_queue.qsize() == 2

    stream = runtime.market_messages()
    assert [(await anext(stream)).symbol, (await anext(stream)).symbol] == ["S4", "S5"]
    await stream.aclose()
    assert feed.close_calls == 1
    assert runtime._market_workers == set()


@pytest.mark.asyncio
async def test_market_ingress_is_bounded_while_first_subscribe_ack_is_pending(monkeypatch) -> None:
    import flinttrade_gateway.brokers.kotakneo_streaming as streaming

    monkeypatch.setattr(streaming, "STREAM_QUEUE_SIZE", 2)
    feed = _BlockingSubscribeFeed()
    runtime = KotakNeoStreamRuntime(_Facade(market_feeds=[feed]))
    subscribing = asyncio.create_task(
        runtime.add_subscriptions(
            [{"exchange_segment": "nse_cm", "instrument_token": "1"}],
            intent="scrips",
            aliases=[("nse_cm", "ONE")],
        )
    )
    await feed.subscribe_started.wait()
    for number in range(6):
        await feed.queue.put(_lite(token=str(number), symbol=f"S{number}"))

    await asyncio.wait_for(feed.input_drained.wait(), 1)
    assert runtime._market_queue is not None
    assert runtime._market_queue.qsize() == 0
    feed.subscribe_release.set()
    await subscribing
    await runtime.close()


@pytest.mark.asyncio
async def test_market_ingress_is_bounded_during_candidate_subscription_replay(monkeypatch) -> None:
    import flinttrade_gateway.brokers.kotakneo_streaming as streaming

    monkeypatch.setattr(streaming, "STREAM_QUEUE_SIZE", 2)
    initial = _Feed()
    replay = _BlockingSubscribeFeed()
    runtime = KotakNeoStreamRuntime(_Facade(market_feeds=[initial, replay]))
    await runtime.add_subscriptions(
        [{"exchange_segment": "nse_cm", "instrument_token": "1"}],
        intent="scrips",
        aliases=[("nse_cm", "ONE")],
    )
    initial.on_disconnect()
    replacing = asyncio.create_task(runtime.market_feed())
    await replay.subscribe_started.wait()
    for number in range(6):
        await replay.queue.put(_lite(token="1", symbol=f"R{number}"))

    await asyncio.wait_for(replay.input_drained.wait(), 1)
    assert runtime._market_candidate_queue is not None
    assert runtime._market_candidate_queue.qsize() == 2
    replay.subscribe_release.set()
    assert await replacing is replay
    await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("replay_fails", [False, True])
async def test_candidate_ticks_are_private_until_atomic_replay_publication(replay_fails: bool) -> None:
    initial = _Feed()
    candidate = _BlockingFailingSubscribeFeed() if replay_fails else _BlockingSubscribeFeed()
    runtime = KotakNeoStreamRuntime(_Facade(market_feeds=[initial, candidate]))
    await runtime.add_subscriptions(
        [{"exchange_segment": "nse_cm", "instrument_token": "1"}],
        intent="scrips",
        aliases=[("nse_cm", "ONE")],
    )
    stream = runtime.market_messages()
    await initial.queue.put(_lite(token="1", symbol="PUBLISHED"))
    assert (await anext(stream)).symbol == "PUBLISHED"
    await initial.queue.put(_END)
    pending = asyncio.create_task(anext(stream))
    await candidate.subscribe_started.wait()

    await candidate.queue.put(_lite(token="2", symbol="UNSOLICITED"))
    await candidate.queue.put(_lite(token="1", symbol="CANDIDATE"))
    await candidate.input_drained.wait()
    await asyncio.sleep(0)
    assert not pending.done()
    candidate.subscribe_release.set()

    if replay_fails:
        with pytest.raises(NetworkError):
            await pending
    else:
        assert (await pending).symbol == "CANDIDATE"
    await stream.aclose()


@pytest.mark.asyncio
async def test_failed_candidate_buffer_never_leaks_into_later_healthy_generation() -> None:
    initial = _Feed()
    failed = _BlockingFailingSubscribeFeed()
    healthy = _Feed()
    runtime = KotakNeoStreamRuntime(_Facade(market_feeds=[initial, failed, healthy]))
    await runtime.add_subscriptions(
        [{"exchange_segment": "nse_cm", "instrument_token": "1"}],
        intent="scrips",
        aliases=[("nse_cm", "ONE")],
    )
    initial.on_disconnect()
    replacing = asyncio.create_task(runtime.market_feed())
    await failed.subscribe_started.wait()
    await failed.queue.put(_lite(token="1", symbol="FAILED-CANDIDATE"))
    await failed.input_drained.wait()
    failed.subscribe_release.set()
    with pytest.raises(NetworkError):
        await replacing

    assert await runtime.market_feed() is healthy
    stream = runtime.market_messages()
    await healthy.queue.put(_lite(token="1", symbol="HEALTHY"))
    assert (await anext(stream)).symbol == "HEALTHY"
    await stream.aclose()


@pytest.mark.asyncio
async def test_failed_mutation_stops_fatal_pump_without_mutation_lock_cycle() -> None:
    first = _BlockingFailingSubscribeFeed()
    restored = _Feed()
    facade = _Facade(market_feeds=[first, restored])
    runtime = KotakNeoStreamRuntime(facade)
    subscribing = asyncio.create_task(
        runtime.add_subscriptions(
            [{"exchange_segment": "nse_cm", "instrument_token": "1"}],
            intent="scrips",
            aliases=[("nse_cm", "ONE")],
        )
    )
    await first.subscribe_started.wait()
    await first.queue.put(ConnectionError("iteration-secret"))
    await first.input_drained.wait()
    await asyncio.sleep(0)

    first.subscribe_release.set()
    with pytest.raises(NetworkError):
        await asyncio.wait_for(subscribing, 1)
    assert first.close_calls == 1
    assert facade.market_factory_calls == 2
    assert runtime.subscription_count == 0
    await runtime.close()


@pytest.mark.asyncio
async def test_cancellation_while_stopping_disconnected_pump_is_preserved() -> None:
    feed = _CancellationBlockingFeed()
    runtime = KotakNeoStreamRuntime(_Facade(market_feeds=[feed]))
    await runtime.market_feed()
    await feed.iteration_started.wait()
    feed.on_disconnect()
    replacing = asyncio.create_task(runtime.market_feed())
    await feed.cancellation_seen.wait()

    replacing.cancel()
    feed.cancellation_release.set()
    with pytest.raises(asyncio.CancelledError):
        await replacing
    await runtime.close()
    assert feed.close_calls == 1


@pytest.mark.asyncio
async def test_order_overflow_closes_promptly_then_delivers_accepted_updates_before_error(monkeypatch) -> None:
    import flinttrade_gateway.brokers.kotakneo_streaming as streaming

    monkeypatch.setattr(streaming, "STREAM_QUEUE_SIZE", 2)
    feed = _Feed()
    runtime = KotakNeoStreamRuntime(_Facade(order_feeds=[feed]))
    stream = runtime.order_messages()
    await feed.queue.put(OrderUpdate(data=OrderData(nOrdNo="OID-0", ordSt="open", trdSym="IDEA-EQ")))
    assert (await anext(stream)).data.order_id == "OID-0"

    for number in range(1, 5):
        await feed.queue.put(OrderUpdate(data=OrderData(nOrdNo=f"OID-{number}", ordSt="open", trdSym="IDEA-EQ")))

    await asyncio.wait_for(feed.close_called.wait(), 1)
    assert runtime._order_feed is None
    assert (await anext(stream)).data.order_id == "OID-1"
    assert (await anext(stream)).data.order_id == "OID-2"
    with pytest.raises(BrokerInternal, match="buffer overflow"):
        await anext(stream)
    assert feed.close_calls == 1


@pytest.mark.asyncio
async def test_disconnect_replacement_waits_for_inflight_mutation_and_late_old_callback_is_ignored() -> None:
    first = _BlockingSubscribeFeed()
    second = _Feed()
    third = _Feed()
    facade = _Facade(market_feeds=[first, second, third])
    runtime = KotakNeoStreamRuntime(facade)
    await runtime.market_feed()

    mutation = asyncio.create_task(
        runtime.add_subscriptions(
            [{"exchange_segment": "nse_cm", "instrument_token": "1"}],
            intent="scrips",
            aliases=[("nse_cm", "ONE")],
        )
    )
    await first.subscribe_started.wait()
    old_callback = first.on_disconnect
    assert callable(old_callback)
    old_callback()
    replacement = asyncio.create_task(runtime.market_feed())
    await asyncio.sleep(0)
    assert facade.market_factory_calls == 1
    assert first.close_calls == 0

    first.subscribe_release.set()
    await mutation
    assert await replacement is second
    assert [name for name, _tokens in second.calls] == ["subscribe_scrips"]
    old_callback()
    assert await runtime.market_feed() is second
    assert facade.market_factory_calls == 2


@pytest.mark.asyncio
async def test_cancelled_ambiguous_mutation_rebuilds_from_unchanged_pre_call_ledger() -> None:
    initial = _Feed()
    blocked = _BlockingSecondSubscribeFeed()
    restored = _Feed()
    facade = _Facade(market_feeds=[initial, blocked, restored])
    runtime = KotakNeoStreamRuntime(facade)
    await runtime.add_subscriptions(
        [{"exchange_segment": "nse_cm", "instrument_token": "1"}],
        intent="scrips",
        aliases=[("nse_cm", "ONE")],
    )
    initial.on_disconnect()
    assert await runtime.market_feed() is blocked
    blocked.calls.clear()

    mutation = asyncio.create_task(
        runtime.add_subscriptions(
            [{"exchange_segment": "nse_cm", "instrument_token": "2"}],
            intent="scrips",
            aliases=[("nse_cm", "TWO")],
        )
    )
    await blocked.subscribe_started.wait()
    mutation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await mutation

    assert blocked.close_calls == 1
    assert runtime.subscription_count == 1
    assert [tuple((token.exchange_segment, token.instrument_token) for token in tokens) for _name, tokens in restored.calls] == [
        (("nse_cm", "1"),)
    ]
    await runtime.add_subscriptions(
        [{"exchange_segment": "nse_cm", "instrument_token": "1"}],
        intent="scrips",
        aliases=[("nse_cm", "ONE")],
    )
    assert facade.market_factory_calls == 3


@pytest.mark.asyncio
async def test_ambiguous_mutation_error_stays_primary_and_close_error_is_retained_for_logout() -> None:
    feed = _Feed(
        close_error=RuntimeError("close-secret"),
        operation_errors={"subscribe_scrips": ConnectionError("mutation-secret")},
    )
    facade = _Facade(market_feeds=[feed])
    runtime = KotakNeoStreamRuntime(facade)
    with pytest.raises(NetworkError) as raised:
        await runtime.add_subscriptions(
            [{"exchange_segment": "nse_cm", "instrument_token": "1"}],
            intent="scrips",
            aliases=[("nse_cm", "ONE")],
        )
    assert type(raised.value) is NetworkError
    with pytest.raises(BrokerInternal):
        await runtime.close()
    assert facade.logout_calls == facade.rest_close_calls == 1


@pytest.mark.asyncio
async def test_close_during_ambiguous_restore_never_publishes_a_post_close_candidate() -> None:
    first = _BlockingCloseFeed()
    first.operation_errors["subscribe_scrips"] = ConnectionError("mutation-secret")
    facade = _Facade(market_feeds=[first, _Feed()])
    runtime = KotakNeoStreamRuntime(facade)
    mutation = asyncio.create_task(
        runtime.add_subscriptions(
            [{"exchange_segment": "nse_cm", "instrument_token": "1"}],
            intent="scrips",
            aliases=[("nse_cm", "ONE")],
        )
    )
    await first.close_started.wait()

    closing = asyncio.create_task(runtime.close())
    await asyncio.sleep(0)
    first.close_release.set()
    await asyncio.wait_for(closing, 1)
    result = await asyncio.gather(mutation, return_exceptions=True)

    assert isinstance(result[0], asyncio.CancelledError)
    assert facade.market_factory_calls == 1
    assert facade.logout_calls == facade.rest_close_calls == 1


@pytest.mark.asyncio
async def test_cancellation_during_failed_mutation_restore_wins_after_restore_finishes() -> None:
    first = _BlockingCloseFeed()
    first.operation_errors["subscribe_scrips"] = ConnectionError("mutation-secret")
    restored = _Feed()
    facade = _Facade(market_feeds=[first, restored])
    runtime = KotakNeoStreamRuntime(facade)
    mutation = asyncio.create_task(
        runtime.add_subscriptions(
            [{"exchange_segment": "nse_cm", "instrument_token": "1"}],
            intent="scrips",
            aliases=[("nse_cm", "ONE")],
        )
    )
    await first.close_started.wait()

    mutation.cancel()
    first.close_release.set()
    with pytest.raises(asyncio.CancelledError):
        await mutation
    assert first.close_finished.is_set()
    assert facade.market_factory_calls == 2
    assert runtime.subscription_count == 0


@pytest.mark.asyncio
async def test_mixed_unsubscribe_failure_restores_all_pre_call_intents_on_fresh_feed() -> None:
    first = _Feed(operation_errors={"unsubscribe_depth": RuntimeError("ambiguous-secret")})
    restored = _Feed()
    facade = _Facade(market_feeds=[first, restored])
    runtime = KotakNeoStreamRuntime(facade)
    await runtime.add_subscriptions(
        [{"exchange_segment": "nse_cm", "instrument_token": "1"}],
        intent="scrips",
        aliases=[("nse_cm", "ONE")],
    )
    await runtime.add_subscriptions(
        [{"exchange_segment": "nse_cm", "instrument_token": "2"}],
        intent="depth",
        aliases=[("nse_cm", "TWO")],
    )

    with pytest.raises(BrokerError) as raised:
        await runtime.remove_subscriptions([("nse_cm", "ONE"), ("nse_cm", "TWO")])
    assert "ambiguous-secret" not in str(raised.value)
    assert runtime.subscription_count == 2
    assert [name for name, _tokens in restored.calls] == ["subscribe_scrips", "subscribe_depth"]
    assert first.close_calls == 1


@pytest.mark.asyncio
async def test_concurrent_conflicting_intents_have_one_transport_winner() -> None:
    facade = _Facade()
    runtime = KotakNeoStreamRuntime(facade)
    row = [{"exchange_segment": "nse_cm", "instrument_token": "1"}]
    alias = [("nse_cm", "ONE")]
    outcomes = await asyncio.gather(
        runtime.add_subscriptions(row, intent="scrips", aliases=alias),
        runtime.add_subscriptions(row, intent="depth", aliases=alias),
        return_exceptions=True,
    )

    assert sum(outcome is None for outcome in outcomes) == 1
    assert sum(isinstance(outcome, BrokerError) for outcome in outcomes) == 1
    assert len(facade.market_feeds[0].calls) == 1


@pytest.mark.asyncio
async def test_close_cancels_unpublished_candidate_and_never_publishes_after_close() -> None:
    candidate = _BlockingConnectFeed()
    facade = _Facade(market_feeds=[candidate])
    runtime = KotakNeoStreamRuntime(facade)
    creating = asyncio.create_task(runtime.market_feed())
    await candidate.connect_started.wait()

    await runtime.close()
    result = await asyncio.gather(creating, return_exceptions=True)
    assert isinstance(result[0], (asyncio.CancelledError, BrokerError))
    assert candidate.close_calls == 1
    assert facade.logout_calls == facade.rest_close_calls == 1
    with pytest.raises(BrokerError):
        await runtime.market_feed()


@pytest.mark.asyncio
async def test_close_cancels_order_candidate_connect_and_market_candidate_replay() -> None:
    order_candidate = _BlockingConnectFeed()
    market_initial = _Feed()
    market_replay = _BlockingSubscribeFeed()
    facade = _Facade(market_feeds=[market_initial, market_replay], order_feeds=[order_candidate])
    runtime = KotakNeoStreamRuntime(facade)
    await runtime.add_subscriptions(
        [{"exchange_segment": "nse_cm", "instrument_token": "1"}],
        intent="scrips",
        aliases=[("nse_cm", "ONE")],
    )
    market_initial.on_disconnect()
    replaying = asyncio.create_task(runtime.market_feed())
    await market_replay.subscribe_started.wait()
    order_connecting = asyncio.create_task(runtime.order_feed())
    await order_candidate.connect_started.wait()

    await runtime.close()
    results = await asyncio.gather(replaying, order_connecting, return_exceptions=True)
    assert all(isinstance(result, (asyncio.CancelledError, BrokerError)) for result in results)
    assert market_replay.close_calls == order_candidate.close_calls == 1
    assert facade.logout_calls == facade.rest_close_calls == 1


@pytest.mark.asyncio
async def test_candidate_disconnected_during_market_replay_is_never_published() -> None:
    initial = _Feed()
    candidate = _BlockingSubscribeFeed()
    facade = _Facade(market_feeds=[initial, candidate])
    runtime = KotakNeoStreamRuntime(facade)
    await runtime.add_subscriptions(
        [{"exchange_segment": "nse_cm", "instrument_token": "1"}],
        intent="scrips",
        aliases=[("nse_cm", "ONE")],
    )
    initial.on_disconnect()
    replacing = asyncio.create_task(runtime.market_feed())
    await candidate.subscribe_started.wait()

    candidate.on_disconnect()
    candidate.subscribe_release.set()
    with pytest.raises(BrokerError):
        await replacing
    assert runtime._market_feed is None
    assert candidate.close_calls == 1


@pytest.mark.asyncio
async def test_candidate_disconnected_during_order_connect_is_never_published() -> None:
    candidate = _BlockingConnectFeed()
    facade = _Facade(order_feeds=[candidate])
    runtime = KotakNeoStreamRuntime(facade)
    creating = asyncio.create_task(runtime.order_feed())
    await candidate.connect_started.wait()

    candidate.on_disconnect()
    candidate.connect_release.set()
    with pytest.raises(BrokerError):
        await creating
    assert runtime._order_feed is None
    assert candidate.close_calls == 1


@pytest.mark.asyncio
async def test_cancelled_close_caller_still_completes_one_whole_cleanup_task() -> None:
    market = _BlockingSubscribeFeed()
    order = _Feed()
    facade = _Facade(market_feeds=[market], order_feeds=[order])
    runtime = KotakNeoStreamRuntime(facade)
    await runtime.order_feed()
    mutation = asyncio.create_task(
        runtime.add_subscriptions(
            [{"exchange_segment": "nse_cm", "instrument_token": "1"}],
            intent="scrips",
            aliases=[("nse_cm", "ONE")],
        )
    )
    await market.subscribe_started.wait()

    closing = asyncio.create_task(runtime.close())
    await asyncio.sleep(0)
    closing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await closing
    await asyncio.gather(mutation, return_exceptions=True)

    assert (market.close_calls, order.close_calls, facade.logout_calls, facade.rest_close_calls) == (1, 1, 1, 1)
    await runtime.close()
    assert (market.close_calls, order.close_calls, facade.logout_calls, facade.rest_close_calls) == (1, 1, 1, 1)


@pytest.mark.asyncio
async def test_concurrent_close_callers_share_one_cleanup_and_deliver_first_error_once() -> None:
    market = _BlockingCloseErrorFeed()
    order = _Feed()
    facade = _Facade(market_feeds=[market], order_feeds=[order])
    runtime = KotakNeoStreamRuntime(facade)
    await runtime.market_feed()
    await runtime.order_feed()
    first = asyncio.create_task(runtime.close())
    await market.close_started.wait()
    second = asyncio.create_task(runtime.close())
    market.close_release.set()

    results = await asyncio.gather(first, second, return_exceptions=True)
    assert sum(isinstance(result, BrokerInternal) for result in results) == 1
    assert sum(result is None for result in results) == 1
    assert (market.close_calls, order.close_calls, facade.logout_calls, facade.rest_close_calls) == (1, 1, 1, 1)
    assert runtime._owned_tasks == set()
    await runtime.close()


@pytest.mark.asyncio
async def test_active_iterators_leave_whole_cleanup_to_market_first_four_stage_owner() -> None:
    close_order: list[str] = []
    market = _OrderedCloseFeed("market", close_order, close_error=RuntimeError("market-secret"))
    order = _OrderedCloseFeed("order", close_order, close_error=RuntimeError("order-secret"))
    facade = _Facade(market_feeds=[market], order_feeds=[order])
    runtime = KotakNeoStreamRuntime(facade)
    market_stream = runtime.market_messages()
    order_stream = runtime.order_messages()
    market_waiting = asyncio.create_task(anext(market_stream))
    order_waiting = asyncio.create_task(anext(order_stream))
    while facade.market_factory_calls < 1 or facade.order_factory_calls < 1:
        await asyncio.sleep(0)

    await runtime._mutation_lock.acquire()
    closing = asyncio.create_task(runtime.close())
    pre_release_order: list[str] = []
    try:
        try:
            await asyncio.wait_for(asyncio.shield(order_waiting), 1)
        except (StopAsyncIteration, BrokerError):
            pass
        pre_release_order = list(close_order)
    finally:
        runtime._mutation_lock.release()

    close_result = await asyncio.gather(closing, return_exceptions=True)
    await asyncio.gather(market_waiting, order_waiting, return_exceptions=True)
    assert pre_release_order == []
    assert close_order == ["market", "order"]
    assert isinstance(close_result[0], BrokerInternal)
    assert "market feed close" in str(close_result[0])
    assert facade.logout_calls == facade.rest_close_calls == 1


@pytest.mark.asyncio
async def test_one_market_iterator_and_cancellation_resets_only_market_socket() -> None:
    market = _Feed()
    order = _Feed()
    facade = _Facade(market_feeds=[market], order_feeds=[order])
    runtime = KotakNeoStreamRuntime(facade)
    await runtime.order_feed()
    first = runtime.market_messages()
    pending = asyncio.create_task(anext(first))
    await asyncio.sleep(0)

    second = runtime.market_messages()
    with pytest.raises(BrokerError, match="already active"):
        await anext(second)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    await first.aclose()
    assert market.close_calls == 1
    assert order.close_calls == 0
    assert facade.logout_calls == facade.rest_close_calls == 0


@pytest.mark.asyncio
async def test_one_order_iterator_cancellation_resets_only_order_socket_and_close_wakes_market_waiter() -> None:
    market = _Feed()
    order = _Feed()
    facade = _Facade(market_feeds=[market], order_feeds=[order])
    runtime = KotakNeoStreamRuntime(facade)
    await runtime.market_feed()
    first = runtime.order_messages()
    pending = asyncio.create_task(anext(first))
    await asyncio.sleep(0)
    second = runtime.order_messages()
    with pytest.raises(BrokerError, match="already active"):
        await anext(second)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    await first.aclose()
    assert order.close_calls == 1
    assert market.close_calls == 0

    market_stream = runtime.market_messages()
    waiting = asyncio.create_task(anext(market_stream))
    await asyncio.sleep(0)
    await runtime.close()
    with pytest.raises(StopAsyncIteration):
        await waiting


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["market", "order"])
async def test_iterator_aclose_preserves_caller_cancellation_while_worker_finishes(kind: str) -> None:
    first_message = (
        _lite(symbol="FIRST")
        if kind == "market"
        else OrderUpdate(data=OrderData(nOrdNo="OID-1", ordSt="open", trdSym="IDEA-EQ"))
    )
    feed = _QueuedThenCancellationBlockingFeed()
    feed.close_error = RuntimeError("close-secret")
    facade = _Facade(
        market_feeds=[feed] if kind == "market" else None,
        order_feeds=[feed] if kind == "order" else None,
    )
    runtime = KotakNeoStreamRuntime(facade)
    if kind == "market":
        await runtime.add_subscriptions(
            [{"exchange_segment": "nse_cm", "instrument_token": "14366"}],
            intent="scrips",
            aliases=[("nse_cm", "IDEA")],
        )
    stream = runtime.market_messages() if kind == "market" else runtime.order_messages()
    await feed.queue.put(first_message)
    await anext(stream)
    await feed.iteration_started.wait()

    closing = asyncio.create_task(stream.aclose())
    await feed.cancellation_seen.wait()
    closing.cancel()
    feed.cancellation_release.set()

    with pytest.raises(asyncio.CancelledError):
        await closing
    assert feed.close_calls == 1
    with pytest.raises(BrokerInternal):
        await runtime.close()
    assert facade.logout_calls == facade.rest_close_calls == 1


@pytest.mark.asyncio
async def test_iterators_fail_closed_without_creating_tasks_or_feeds_after_runtime_close() -> None:
    facade = _Facade()
    runtime = KotakNeoStreamRuntime(facade)
    await runtime.close()

    for stream in (runtime.market_messages(), runtime.order_messages()):
        with pytest.raises(SessionExpired):
            await anext(stream)
    assert facade.market_factory_calls == facade.order_factory_calls == 0
    assert runtime._owned_tasks == set()


@pytest.mark.asyncio
async def test_retired_generations_are_not_strongly_retained_by_close_once_tracking() -> None:
    facade = _EphemeralFacade()
    runtime = KotakNeoStreamRuntime(facade)
    current = await runtime.market_feed()
    for _ in range(8):
        current.on_disconnect()
        current = await runtime.market_feed()
    gc.collect()
    assert all(reference() is None for reference in facade.refs[:-1])

    await runtime.close()
    del current
    gc.collect()
    assert all(reference() is None for reference in facade.refs)


@pytest.mark.asyncio
async def test_raw_feed_iteration_error_is_canonicalised() -> None:
    feed = _Feed()
    runtime = KotakNeoStreamRuntime(_Facade(market_feeds=[feed]))
    stream = runtime.market_messages()
    await feed.queue.put(ConnectionError("transport-secret"))
    with pytest.raises(BrokerError) as raised:
        await anext(stream)
    assert "transport-secret" not in str(raised.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["market", "order"])
async def test_iterator_close_failure_is_canonical_and_retained_for_full_teardown(kind: str) -> None:
    market = _Feed(close_error=RuntimeError("market-close-secret") if kind == "market" else None)
    order = _Feed(close_error=RuntimeError("order-close-secret") if kind == "order" else None)
    facade = _Facade(market_feeds=[market], order_feeds=[order])
    runtime = KotakNeoStreamRuntime(facade)
    if kind == "market":
        await runtime.add_subscriptions(
            [{"exchange_segment": "nse_cm", "instrument_token": "14366"}],
            intent="scrips",
            aliases=[("nse_cm", "IDEA")],
        )
        stream = runtime.market_messages()
        await market.queue.put(_lite())
    else:
        stream = runtime.order_messages()
        await order.queue.put(OrderUpdate(data=OrderData(nOrdNo="OID-1", ordSt="open", trdSym="IDEA-EQ")))
    await anext(stream)

    with pytest.raises(BrokerInternal) as raised:
        await stream.aclose()
    assert "secret" not in str(raised.value)
    with pytest.raises(BrokerInternal):
        await runtime.close()
    assert facade.logout_calls == facade.rest_close_calls == 1


@pytest.mark.asyncio
async def test_iteration_error_remains_primary_over_close_error() -> None:
    feed = _Feed(close_error=RuntimeError("close-secret"))
    runtime = KotakNeoStreamRuntime(_Facade(market_feeds=[feed]))
    stream = runtime.market_messages()
    await feed.queue.put(ConnectionError("iteration-secret"))

    with pytest.raises(NetworkError) as raised:
        await anext(stream)
    assert type(raised.value) is NetworkError
    with pytest.raises(BrokerInternal):
        await runtime.close()


@pytest.mark.asyncio
async def test_whole_cleanup_observes_racing_iterator_detach_error() -> None:
    feed = _BlockingCloseErrorFeed()
    facade = _Facade(market_feeds=[feed])
    runtime = KotakNeoStreamRuntime(facade)
    await runtime.add_subscriptions(
        [{"exchange_segment": "nse_cm", "instrument_token": "14366"}],
        intent="scrips",
        aliases=[("nse_cm", "IDEA")],
    )
    stream = runtime.market_messages()
    await feed.queue.put(_lite())
    await anext(stream)
    iterator_close = asyncio.create_task(stream.aclose())
    await feed.close_started.wait()
    runtime_close = asyncio.create_task(runtime.close())
    await asyncio.sleep(0)
    feed.close_release.set()

    with pytest.raises(BrokerInternal):
        await iterator_close
    with pytest.raises(BrokerInternal):
        await runtime_close
    assert facade.logout_calls == facade.rest_close_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["logout", "rest"])
async def test_missing_required_teardown_stage_is_canonical_and_other_stage_runs(missing: str) -> None:
    facade = _Facade()
    if missing == "logout":
        facade.logout_sdk = None  # type: ignore[method-assign]
    else:
        facade.close_rest = None  # type: ignore[method-assign]
    runtime = KotakNeoStreamRuntime(facade)

    with pytest.raises(BrokerInternal):
        await runtime.close()
    assert facade.logout_calls == (0 if missing == "logout" else 1)
    assert facade.rest_close_calls == (0 if missing == "rest" else 1)


@pytest.mark.asyncio
async def test_order_stream_emits_only_typed_discriminated_updates() -> None:
    order_feed = _Feed()
    facade = _Facade(order_feeds=[order_feed])
    runtime = KotakNeoStreamRuntime(facade)
    stream = runtime.order_messages()
    await order_feed.queue.put({"type": "order", "data": {"nOrdNo": "raw-must-not-surface"}})
    await order_feed.queue.put("garbage")
    order = OrderUpdate(data=OrderData(nOrdNo="OID-1", ordSt="open", trdSym="IDEA-EQ"))
    position = PositionUpdate(data=PositionData(actId="U1", sym="IDEA", exSeg="nse_cm", prod="MIS"))
    await order_feed.queue.put(order)
    await order_feed.queue.put(position)

    assert await anext(stream) is order
    assert await anext(stream) is position
    await stream.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["market", "order", "logout", "rest"])
async def test_teardown_attempts_all_four_stages_keeps_first_error_and_is_idempotent(failure: str) -> None:
    market = _Feed(close_error=RuntimeError("market-secret") if failure == "market" else None)
    order = _Feed(close_error=RuntimeError("order-secret") if failure == "order" else None)
    facade = _Facade(
        market_feeds=[market],
        order_feeds=[order],
        logout_error=RuntimeError("logout-secret") if failure == "logout" else None,
        rest_error=RuntimeError("rest-secret") if failure == "rest" else None,
    )
    runtime = KotakNeoStreamRuntime(facade)
    await runtime.market_feed()
    await runtime.order_feed()

    with pytest.raises(BrokerInternal) as raised:
        await runtime.close()
    assert "secret" not in str(raised.value)
    assert (market.close_calls, order.close_calls, facade.logout_calls, facade.rest_close_calls) == (1, 1, 1, 1)
    await runtime.close()
    assert (market.close_calls, order.close_calls, facade.logout_calls, facade.rest_close_calls) == (1, 1, 1, 1)


def test_production_streaming_module_never_imports_sdk_namespace_directly() -> None:
    import inspect
    import flinttrade_gateway.brokers.kotakneo_streaming as streaming

    source = inspect.getsource(streaming)
    assert "from neo_api_client" not in source
    assert "import neo_api_client" not in source
    assert "asyncio.all_tasks" not in source
    for private_name in ("_receive_task", "._ws", "._connected", "._subscriptions", "._reconnect_count"):
        assert private_name not in source
