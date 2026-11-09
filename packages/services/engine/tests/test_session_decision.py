"""One session answer, checked through the real callers.

The same IST instants go through safety.is_market_open, the scheduler's
session window, square-off, and GET /api/v1/market/timings.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

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
    """exchange, day, hour, minute, safety, scheduler, square-off, close, phase."""
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
                # window still includes 15:30, so square-off is already due.
                nse = (False, False, True)
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
    ("exchange", "day", "hour", "minute", "safety_open", "scheduler_open", "square_off", "close", "phase"),
    _rows(),
)
def test_one_session_answer_across_callers(  # type: ignore[no-untyped-def]
    client,
    exchange: str,
    day: int,
    hour: int,
    minute: int,
    safety_open: bool,
    scheduler_open: bool,
    square_off: bool,
    close: str | None,
    phase: str | None,
) -> None:
    at = datetime(2026, 12, day, hour, minute, tzinfo=IST)
    scheduler = TimeScheduler()
    assert is_market_open(exchange, at=at) is safety_open
    assert scheduler.is_market_open(exchange, at=at) is scheduler_open
    assert scheduler.should_square_off(exchange, at=at) is square_off

    response = client.get(
        "/api/v1/market/timings",
        query_string={"exchange": exchange, "on": at.date().isoformat(), "at": at.isoformat()},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["close"] == close
    assert body["phase"] == phase
