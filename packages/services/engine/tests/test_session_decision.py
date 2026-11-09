"""One session answer, checked through the real callers.

The same IST instants go through safety.is_market_open, entry admission,
the runner session, square-off, and GET /api/v1/market/timings.
"""

from __future__ import annotations

import warnings
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import pytest
from flask import Flask

from flinttrade_engine.market_hours import STANDARD_HOURS
from flinttrade_engine.safety import MARKET_HOURS, is_market_open
from flinttrade_engine.scheduler import EXCHANGE_SCHEDULES, TimeScheduler
from flinttrade_historical.holidays_routes import holidays_bp

IST = timezone(timedelta(hours=5, minutes=30))

# 6 Dec 2026 is a Sunday, so admission is closed. Timings still publish the
# pre-revision close. 7 Dec 2026 is the first revised Monday.
_PRE_PHASE = {
    (15, 14): "continuous",
    (15, 15): "cas",
    (15, 20): "cas",
    (15, 30): "cas",
    (15, 40): "matching",
    (15, 45): "matching",
}
_REVISED_PHASE = {
    (15, 14): "continuous",
    (15, 15): "continuous",
    (15, 20): "continuous",
    (15, 30): "cas",
    (15, 40): "matching",
    (15, 45): "transition",
}


def _rows() -> list[tuple[str, int, int, int, bool, bool, bool, str | None, str | None]]:
    """exchange, day, hour, minute, safety, session, square-off, close, phase."""
    rows: list[tuple[str, int, int, int, bool, bool, bool, str | None, str | None]] = []
    afternoon = ((15, 14), (15, 15), (15, 20), (15, 30), (15, 40), (15, 45))
    for day, phases, nfo_close in ((6, _PRE_PHASE, "15:40"), (7, _REVISED_PHASE, "15:45")):
        sunday = day == 6
        for hour, minute in afternoon:
            phase = phases[(hour, minute)]
            if sunday:
                # A closed day does not advertise the ordinary close or a continuous phase.
                rows.append(("NSE", day, hour, minute, False, False, False, None, "closed"))
                rows.append(("NFO", day, hour, minute, False, False, False, None, "closed"))
                rows.append(("MCX", day, hour, minute, False, False, False, None, "closed"))
                rows.append(("NCDEX", day, hour, minute, False, False, False, None, "closed"))
                continue
            if (hour, minute) == (15, 14):
                nse = (True, True, False)
            elif (hour, minute) in {(15, 15), (15, 20)}:
                nse = (True, True, True)
            elif (hour, minute) == (15, 30):
                # Auction order entry is shut at the 15:30 reference. The runner
                # session still includes 15:30, so square-off is already due.
                nse = (False, True, True)
            else:
                nse = (False, False, False)
            rows.append(("NSE", day, hour, minute, *nse, "15:30", phase))
            if (hour, minute) < (15, 20):
                nfo = (True, True, False)
            elif (hour, minute) < (15, 45):
                nfo = (True, True, True)
            else:
                nfo = (False, False, False)
            rows.append(("NFO", day, hour, minute, *nfo, nfo_close, None))
            rows.append(("MCX", day, hour, minute, True, True, False, "23:30", None))
            rows.append(("NCDEX", day, hour, minute, True, True, False, "17:00", None))
        for hour, minute, safety, scheduler, square in ((23, 30, False, True, True), (23, 40, False, True, True)):
            if sunday:
                rows.append(("MCX", day, hour, minute, False, False, False, None, "closed"))
            else:
                rows.append(("MCX", day, hour, minute, safety, scheduler, square, "23:30", None))
        for hour, minute, safety, scheduler, square in ((17, 0, False, True, True), (18, 0, False, False, False)):
            if sunday:
                rows.append(("NCDEX", day, hour, minute, False, False, False, None, "closed"))
            else:
                rows.append(("NCDEX", day, hour, minute, safety, scheduler, square, "17:00", None))
    return rows


@pytest.fixture()
def client():  # type: ignore[no-untyped-def]
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(holidays_bp)
    return app.test_client()


def test_ncdex_standard_hours_and_mcx_runner_end_are_unchanged() -> None:
    """The timings close is the gate. The other two clocks stay where they are."""
    assert STANDARD_HOURS["NCDEX"] == (time(10, 0), time(23, 30))
    assert MARKET_HOURS["NCDEX"] == (time(10, 0), time(17, 0))
    assert MARKET_HOURS["MCX"] == (time(9, 0), time(23, 30))
    assert EXCHANGE_SCHEDULES["MCX"].market_close == time(23, 55)
    assert EXCHANGE_SCHEDULES["MCX"].square_off == time(23, 30)
    assert EXCHANGE_SCHEDULES["NCDEX"].market_close == time(17, 0)


@pytest.mark.parametrize(
    ("exchange", "day", "hour", "minute", "safety_open", "session_running", "square_off", "close", "phase"),
    _rows(),
)
def test_one_session_answer_across_callers(  # type: ignore[no-untyped-def]
    client,
    exchange: str,
    day: int,
    hour: int,
    minute: int,
    safety_open: bool,
    session_running: bool,
    square_off: bool,
    close: str | None,
    phase: str | None,
) -> None:
    at = datetime(2026, 12, day, hour, minute, tzinfo=IST)
    scheduler = TimeScheduler()
    assert is_market_open(exchange, at=at) is safety_open
    assert scheduler.accepts_new_entries(exchange, at=at) is safety_open
    assert scheduler.session_active(exchange, at=at) is session_running
    assert scheduler.should_square_off(exchange, at=at) is square_off

    response = client.get(
        "/api/v1/market/timings",
        query_string={"exchange": exchange, "on": at.date().isoformat(), "at": at.isoformat()},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["close"] == close
    assert body["phase"] == phase


def _stamp(day: int, hour: int, minute: int, *, month: int = 11) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=IST)


def _exit_window_rows() -> list[tuple[str, datetime, bool, bool, bool, str]]:
    """exchange, instant, entries, session, square-off, timings order_entry."""
    rows: list[tuple[str, datetime, bool, bool, bool, str]] = []
    for hour, minute, entries, active, square, order_entry in (
        (23, 29, True, True, False, "open"),
        (23, 30, False, True, True, "closed"),
        (23, 40, False, True, True, "closed"),
        (23, 55, False, True, True, "closed"),
        (23, 56, False, False, False, "closed"),
    ):
        rows.append(("MCX", _stamp(9, hour, minute), entries, active, square, order_entry))
    for hour, minute, entries, active, square, order_entry in (
        (16, 59, True, True, True, "open"),
        (17, 0, False, True, True, "closed"),
        (18, 0, False, False, False, "closed"),
    ):
        rows.append(("NCDEX", _stamp(9, hour, minute), entries, active, square, order_entry))
    for hour, minute, entries, active, square, order_entry in (
        (11, 0, True, True, False, "open"),
        (15, 20, True, True, True, "open"),
        (15, 30, False, True, True, "closed"),
        (15, 31, False, False, False, "closed"),
    ):
        rows.append(("NSE", _stamp(9, hour, minute), entries, active, square, order_entry))
    rows.append(("NSE", _stamp(7, 11, 0), False, False, False, "closed"))
    rows.append(("MCX", _stamp(7, 23, 40), False, False, False, "closed"))
    rows.append(("NSE", _stamp(16, 11, 0), False, False, False, "closed"))
    rows.append(("MCX", _stamp(16, 11, 0), False, False, False, "closed"))
    for exchange, hour, minute, entries, active, square, order_entry in (
        ("NSE", 14, 19, False, False, False, "closed"),
        ("NSE", 15, 0, True, True, False, "open"),
        ("NSE", 15, 30, True, True, True, "open"),
        ("NSE", 15, 31, False, False, False, "closed"),
        ("NFO", 15, 40, True, True, True, "open"),
        ("NFO", 15, 41, False, False, False, "closed"),
        ("MCX", 15, 0, True, True, False, "open"),
        ("MCX", 23, 40, False, False, False, "closed"),
    ):
        rows.append((exchange, _stamp(8, hour, minute), entries, active, square, order_entry))
    return rows


@pytest.fixture()
def entry_client():  # type: ignore[no-untyped-def]
    scheduler = TimeScheduler()
    scheduler.set_holidays(
        {
            "data": [
                {
                    "date": "2026-11-16",
                    "holiday_type": "TRADING_HOLIDAY",
                    "closed_exchanges": ["NSE", "MCX"],
                }
            ]
        },
        year="2026",
    )
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["TIME_SCHEDULER"] = scheduler
    app.register_blueprint(holidays_bp)
    return app.test_client(), scheduler


@pytest.mark.parametrize(
    ("exchange", "at", "entries", "active", "square_off", "order_entry"),
    _exit_window_rows(),
)
def test_entry_admission_and_runner_session_at_each_instant(  # type: ignore[no-untyped-def]
    entry_client,
    exchange: str,
    at: datetime,
    entries: bool,
    active: bool,
    square_off: bool,
    order_entry: str,
) -> None:
    client, scheduler = entry_client
    admitted = is_market_open(exchange, at=at, market_calendar=scheduler)
    assert scheduler.accepts_new_entries(exchange, at=at) is entries
    assert scheduler.accepts_new_entries(exchange, at=at) is admitted
    assert scheduler.session_active(exchange, at=at) is active
    assert scheduler.should_square_off(exchange, at=at) is square_off
    response = client.get(
        "/api/v1/market/timings",
        query_string={"exchange": exchange, "at": at.isoformat()},
    )
    assert response.status_code == 200
    published = response.get_json()["order_entry"]
    assert published == order_entry
    assert (published in {"open", "auction_entry"}) is admitted


def _practice_tick_rows() -> list[tuple[int, int, int, bool]]:
    """December day, hour, minute, and whether the practice tick may place an order.

    15:20 is inside both the runner session and admission. 15:30 is still inside
    the session and already closed to a new order. On 7 Dec 2026, 15:31 and
    15:37 are cash auction entry, which is outside the runner session. 15:38
    is closed on both clocks. 4 Dec 2026 has no auction entry.
    """
    rows: list[tuple[int, int, int, bool]] = []
    for day in (4, 7):
        rows.append((day, 15, 20, True))
        for minute in (30, 31, 37, 38):
            rows.append((day, 15, minute, False))
    return rows


@pytest.mark.parametrize(("day", "hour", "minute", "places"), _practice_tick_rows())
async def test_practice_tick_places_an_order_only_inside_session_and_admission(
    day: int,
    hour: int,
    minute: int,
    places: bool,
) -> None:
    from contextlib import contextmanager

    from flinttrade_core.execution_strategy import _BoundStrategyRunner
    from flinttrade_core.models import Order
    from flinttrade_core.practice_agent_adapter import PracticeAgentAdapter

    at = datetime(2026, 12, day, hour, minute, tzinfo=IST)
    scheduler = TimeScheduler()
    scheduler.now_ist = lambda: at  # type: ignore[method-assign]
    generated: list[Order] = []
    retired: list[object] = []
    routed: list[Order] = []

    adapter = object.__new__(PracticeAgentAdapter)
    adapter.validate_session = lambda: None  # type: ignore[method-assign]

    async def quotes(*, symbol: str, exchange: str) -> dict[str, dict[str, float]]:
        return {"data": {"ltp": 2500.0}}

    async def route_order(order: Order) -> object:
        routed.append(order)
        return type("Result", (), {"passed": True})()

    adapter.quotes = quotes  # type: ignore[method-assign]
    adapter.route_order = route_order  # type: ignore[method-assign]

    class _Strategy:
        exchange = "NSE"
        symbol = "RELIANCE"

        def on_tick(self, quote: object) -> None:
            del quote

        def generate_orders(self) -> list[Order]:
            order = Order(symbol="RELIANCE", exchange="NSE", product="MIS", action="BUY", quantity="1")
            generated.append(order)
            return [order]

    @contextmanager
    def _fence():  # type: ignore[no-untyped-def]
        yield

    owner = type("Owner", (), {})()
    owner.run = type("Run", (), {})()
    owner.run.adapter = adapter
    owner.run.config = {"exchange": "NSE", "product": "MIS", "max_position_size": 10}
    owner.sandbox = type("Sandbox", (), {"get_positions": staticmethod(lambda: [])})()
    owner.execution_binding = type("Binding", (), {})()
    owner.execution_binding.fence = _fence
    owner.execution_binding.scope = "practice-tick"
    owner.execution_binding.registry = type(
        "Registry",
        (),
        {"retire_entries": staticmethod(lambda scope: retired.append(scope))},
    )()

    runner = object.__new__(_BoundStrategyRunner)
    runner.owner = owner
    runner.scheduler = scheduler
    runner.strategy = _Strategy()
    runner.symbol = "RELIANCE"
    runner._task = None
    runner._tick_count = 0

    await runner._tick()

    assert scheduler.session_active("NSE") is scheduler.session_active("NSE", at=at)
    assert scheduler.accepts_new_entries("NSE") is scheduler.accepts_new_entries("NSE", at=at)
    session = scheduler.session_active("NSE", at=at)
    if places:
        assert session is True
        assert scheduler.accepts_new_entries("NSE", at=at) is True
        assert len(generated) == 1
        assert [str(order.action) for order in routed] == ["BUY"]
        assert retired == []
    elif not session:
        assert generated == []
        assert routed == []
        assert retired == []
    else:
        assert scheduler.accepts_new_entries("NSE", at=at) is False
        assert generated != []
        assert routed == []
        assert retired == []


def _exit_window_practice_rows() -> list[tuple[str, str, int, int]]:
    """Exchange, symbol, hour, minute on Monday 9 Nov 2026."""
    return [("MCX", "GOLD", 23, 40), ("NCDEX", "GUARSEED", 17, 0)]


@pytest.mark.parametrize(("exchange", "symbol", "hour", "minute"), _exit_window_practice_rows())
async def test_practice_tick_squares_off_without_a_new_entry(
    exchange: str,
    symbol: str,
    hour: int,
    minute: int,
) -> None:
    from contextlib import contextmanager

    from flinttrade_core.execution_strategy import _BoundStrategyRunner
    from flinttrade_core.models import Order
    from flinttrade_core.practice_agent_adapter import PracticeAgentAdapter

    at = datetime(2026, 11, 9, hour, minute, tzinfo=IST)
    scheduler = TimeScheduler()
    scheduler.now_ist = lambda: at  # type: ignore[method-assign]
    assert scheduler.session_active(exchange, at=at, symbol=symbol) is True
    assert scheduler.accepts_new_entries(exchange, at=at, symbol=symbol) is False
    assert scheduler.should_square_off(exchange, at=at, symbol=symbol) is True
    routed: list[Order] = []
    retired: list[object] = []

    adapter = object.__new__(PracticeAgentAdapter)
    adapter.validate_session = lambda: None  # type: ignore[method-assign]

    async def quotes(*, symbol: str, exchange: str) -> dict[str, dict[str, float]]:
        del symbol, exchange
        return {"data": {"ltp": 2500.0}}

    async def route_order(order: Order) -> object:
        routed.append(order)
        return type("Result", (), {"passed": True})()

    adapter.quotes = quotes  # type: ignore[method-assign]
    adapter.route_order = route_order  # type: ignore[method-assign]

    class _Strategy:
        def __init__(self) -> None:
            self.exchange = exchange

        def on_tick(self, quote: object) -> None:
            del quote

        def generate_orders(self) -> list[Order]:
            return [Order(symbol=symbol, exchange=exchange, product="MIS", action="BUY", quantity="1")]

    @contextmanager
    def _fence():  # type: ignore[no-untyped-def]
        yield

    owner = type("Owner", (), {})()
    owner.run = type("Run", (), {})()
    owner.run.adapter = adapter
    owner.run.config = {"exchange": exchange, "product": "MIS", "max_position_size": 10}
    owner.sandbox = type(
        "Sandbox",
        (),
        {"get_positions": staticmethod(lambda: [{
            "symbol": symbol, "exchange": exchange, "product": "MIS", "net_qty": 2,
        }])},
    )()
    owner.execution_binding = type("Binding", (), {})()
    owner.execution_binding.fence = _fence
    owner.execution_binding.scope = "practice-exit"
    owner.execution_binding.registry = type(
        "Registry",
        (),
        {"retire_entries": staticmethod(lambda scope: retired.append(scope))},
    )()

    runner = object.__new__(_BoundStrategyRunner)
    runner.owner = owner
    runner.scheduler = scheduler
    runner.strategy = _Strategy()
    runner.symbol = symbol
    runner._task = None
    runner._tick_count = 0

    await runner._tick()

    assert retired == []
    assert [(str(order.action), order.quantity) for order in routed] == [("SELL", "2")]


def test_deprecated_open_alias_maps_to_the_runner_session() -> None:
    """The old name is the runner session, and internal code does not call it."""
    at = datetime(2026, 11, 9, 23, 40, tzinfo=IST)
    scheduler = TimeScheduler()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        reported = scheduler.is_market_open("MCX", at=at)
    assert reported is True
    assert scheduler.session_active("MCX", at=at) is True
    assert scheduler.accepts_new_entries("MCX", at=at) is False
    assert any(item.category is DeprecationWarning for item in caught)

    root = Path(__file__).resolve().parents[4]
    allowed = {
        Path("packages/services/engine/src/flinttrade_engine/scheduler.py"),
        Path("packages/services/engine/tests/test_session_decision.py"),
    }
    offenders: list[str] = []
    for base in (root / "packages", root / "tests"):
        for path in base.rglob("*.py"):
            relative = path.relative_to(root)
            if relative in allowed or "__pycache__" in relative.parts:
                continue
            text = path.read_text(encoding="utf-8").replace("safety.is_market_open", "")
            if ".is_market_open" in text or "is_market_open=" in text:
                offenders.append(str(relative))
    assert offenders == []
