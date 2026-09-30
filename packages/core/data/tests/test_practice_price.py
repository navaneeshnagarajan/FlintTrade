"""Tests for the single Practice market pricing rule."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flinttrade_data.practice_price import (
    OPTION_PRICE_STALE,
    PRICE_SOURCE_LAST_CLOSE,
    PRICE_SOURCE_LTP,
    StoredClose,
    format_price_age,
    last_close_fill_label,
    lookup_stored_last_close,
    practice_market_is_open,
    practice_price_unavailable,
    resolve_practice_market_price,
)

_IST = ZoneInfo("Asia/Kolkata")
_NOW = datetime(2026, 9, 28, 18, 0, tzinfo=_IST)
_TWO_DAYS = 2 * 86_400


def test_price_age_uses_min_then_hours_then_days() -> None:
    assert format_price_age(60) == "1 min old"
    assert format_price_age(120) == "2 min old"
    assert format_price_age(3_600) == "1 hour old"
    assert format_price_age(7_200) == "2 hours old"
    assert format_price_age(86_400) == "1 day old"
    assert format_price_age(172_800) == "2 days old"
    assert last_close_fill_label(812.40, 172_800) == "Simulated at last close ₹812.40 (2 days old)"


def test_live_ltp_is_the_fill_and_is_not_labelled_simulated() -> None:
    resolved = resolve_practice_market_price(
        symbol="SBIN",
        exchange="NSE",
        request_price=801.5,
        price_basis="ltp",
        stored_close=StoredClose(price=812.40, age_s=_TWO_DAYS),
    )
    assert not isinstance(resolved, str)
    assert resolved.price == 801.5
    assert resolved.price_source == PRICE_SOURCE_LTP
    assert resolved.price_age_s is None
    assert resolved.label is None


def test_stored_close_is_labelled_with_its_age_and_ignores_a_typed_price() -> None:
    resolved = resolve_practice_market_price(
        symbol="SBIN",
        exchange="NSE",
        request_price=800,
        price_basis=None,
        stored_close=StoredClose(price=812.40, age_s=_TWO_DAYS),
    )
    assert not isinstance(resolved, str)
    assert resolved.price == 812.40
    assert resolved.price_source == PRICE_SOURCE_LAST_CLOSE
    assert resolved.price_age_s == _TWO_DAYS
    assert resolved.label == "Simulated at last close ₹812.40 (2 days old)"
    assert resolved.label == last_close_fill_label(812.40, _TWO_DAYS)


def test_missing_price_is_a_plain_refusal_with_no_sample_fallback() -> None:
    for posted in (0, 800, 780):
        message = resolve_practice_market_price(
            symbol="SBIN",
            exchange="NSE",
            request_price=posted,
            price_basis=None,
            stored_close=None,
        )
        assert message == practice_price_unavailable("SBIN")
        assert message == "No price for SBIN right now. Practice needs a live price or a recent close."
        assert "LTP" not in message
        assert "400" not in message
        assert "780" not in message


def test_option_outside_market_hours_is_refused_even_with_a_price() -> None:
    option = "NIFTY24APR25500CE"
    for basis, posted, stored in (
        ("ltp", 12.5, StoredClose(price=11.0, age_s=60)),
        (None, 800, StoredClose(price=11.0, age_s=60)),
        (None, 0, None),
    ):
        message = resolve_practice_market_price(
            symbol=option,
            exchange="NFO",
            request_price=posted,
            price_basis=basis,
            stored_close=stored,
            market_open=lambda exchange, symbol: False,
        )
        assert message == OPTION_PRICE_STALE


def test_option_during_market_hours_follows_the_equity_rule() -> None:
    option = "NIFTY24APR25500CE"
    live = resolve_practice_market_price(
        symbol=option,
        exchange="NFO",
        request_price=12.5,
        price_basis="ltp",
        market_open=lambda exchange, symbol: True,
    )
    assert not isinstance(live, str)
    assert live.price == 12.5
    assert live.price_source == PRICE_SOURCE_LTP

    stored = resolve_practice_market_price(
        symbol=option,
        exchange="NFO",
        request_price=800,
        price_basis=None,
        stored_close=StoredClose(price=11.25, age_s=3_600),
        market_open=lambda exchange, symbol: True,
    )
    assert not isinstance(stored, str)
    assert stored.label == "Simulated at last close ₹11.25 (1 hour old)"

    missing = resolve_practice_market_price(
        symbol=option,
        exchange="NFO",
        request_price=0,
        price_basis=None,
        market_open=lambda exchange, symbol: True,
    )
    assert missing == practice_price_unavailable(option)


def test_a_future_outside_hours_can_still_use_the_stored_close() -> None:
    resolved = resolve_practice_market_price(
        symbol="NIFTY24APRFUT",
        exchange="NFO",
        request_price=0,
        price_basis=None,
        stored_close=StoredClose(price=24_150.0, age_s=86_400),
        market_open=lambda exchange, symbol: False,
    )
    assert not isinstance(resolved, str)
    assert resolved.price_source == PRICE_SOURCE_LAST_CLOSE
    assert resolved.label == "Simulated at last close ₹24150.00 (1 day old)"


def test_stored_close_prefers_previous_close_and_requires_a_timestamp() -> None:
    class _Store:
        def get_ticks(self, symbol, exchange, start, end, limit=None):
            return [{"ts": _NOW - timedelta(days=2), "prev_close": 0, "close": 0, "ltp": 799.0}]

    found = lookup_stored_last_close("SBIN", "NSE", storage=_Store(), now=_NOW)
    assert found is not None
    assert found.price == 799.0
    assert found.age_s == _TWO_DAYS

    class _Close:
        def get_ticks(self, symbol, exchange, start, end, limit=None):
            return [{
                "ts": _NOW - timedelta(days=2),
                "prev_close": 812.40,
                "close": 810.0,
                "ltp": 799.0,
            }]

    preferred = lookup_stored_last_close("SBIN", "NSE", storage=_Close(), now=_NOW)
    assert preferred is not None
    assert preferred.price == 812.40
    assert preferred.age_s == _TWO_DAYS

    class _Untimed:
        def get_ticks(self, symbol, exchange, start, end, limit=None):
            return [{"prev_close": 812.40, "close": 810.0, "ltp": 799.0}]

    assert lookup_stored_last_close("SBIN", "NSE", storage=_Untimed(), now=_NOW) is None


def test_missing_storage_is_not_an_error() -> None:
    assert lookup_stored_last_close("SBIN", "NSE", storage=None, now=_NOW) is None


def _positions_last_close_tag(age_s: int) -> str:
    """Positions row tag. Days, else hours, else minutes."""
    seconds = max(0, int(age_s))
    if seconds >= 86_400:
        return f"Last close · {seconds // 86_400}d"
    if seconds >= 3_600:
        return f"Last close · {seconds // 3_600}h"
    return f"Last close · {seconds // 60}m"


def test_real_storage_close_forty_minutes_ago_reads_as_forty_minutes() -> None:
    """A zone-less UTC close from DuckDB is 40m, not 5h30m older."""
    from flinttrade_data.storage import StorageManager

    now = datetime(2026, 9, 28, 18, 0, tzinfo=_IST)
    storage = StorageManager(":memory:")
    storage.initialise()
    try:
        storage.insert_tick(
            ts=now - timedelta(minutes=40),
            symbol="SBIN",
            exchange="NSE",
            mode="quote",
            ltp=812.40,
            close=810.0,
            prev_close=812.40,
        )
        stored = storage.get_ticks("SBIN", "NSE", "2026-09-28", "2026-09-28", limit=1)
        assert len(stored) == 1
        assert stored[0]["ts"].tzinfo is None
        found = lookup_stored_last_close("SBIN", "NSE", storage=storage, now=now)
    finally:
        storage.close()

    assert found is not None
    assert found.price == 812.40
    assert found.age_s == 40 * 60
    assert _positions_last_close_tag(found.age_s) == "Last close · 40m"


def test_broker_ist_wall_clock_is_stored_as_utc_and_ages_as_forty_minutes() -> None:
    """An IST candle string is 10:00 UTC, and a 40-minute-old close is 40m."""
    from datetime import UTC

    from flinttrade_data.storage import IST, StorageManager, read_stored_timestamp

    now = datetime(2026, 9, 29, 16, 10, tzinfo=_IST)
    storage = StorageManager(":memory:")
    storage.initialise()
    try:
        storage.record_broker_quote(
            "2026-09-29 15:30:00",
            "SBIN",
            "NSE",
            source_tz=IST,
            ltp=812.40,
            close=810.0,
            prev_close=812.40,
        )
        stored = storage.get_ticks("SBIN", "NSE", "2026-09-29", "2026-09-29", limit=1)
        assert len(stored) == 1
        assert stored[0]["ts"].tzinfo is None
        assert read_stored_timestamp(stored[0]["ts"]) == datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
        found = lookup_stored_last_close("SBIN", "NSE", storage=storage, now=now)
    finally:
        storage.close()

    assert found is not None
    assert found.age_s == 40 * 60
    assert _positions_last_close_tag(found.age_s) == "Last close · 40m"


def test_zone_less_timestamp_without_a_source_zone_is_refused() -> None:
    """Storage does not guess IST or UTC for a zone-less timestamp."""
    import pytest

    from flinttrade_data.storage import StorageManager

    storage = StorageManager(":memory:")
    storage.initialise()
    try:
        with pytest.raises(ValueError, match="zone"):
            storage.insert_tick(
                datetime(2026, 9, 29, 15, 30),
                "SBIN",
                "NSE",
                "quote",
                prev_close=812.40,
            )
    finally:
        storage.close()


def test_close_outside_the_seven_session_window_is_refused() -> None:
    """A close before the window stays refused when its IST digits would look inside.

    The lookup window opens at 2026-09-22 00:00 IST (2026-09-21 18:30 UTC).
    ``2026-09-21 23:30:00`` IST is 2026-09-21 18:00 UTC, thirty minutes earlier.
    Stored as those digits and read as UTC, 23:30 is inside the window.
    """
    from flinttrade_data.storage import IST, StorageManager

    now = datetime(2026, 9, 29, 16, 0, tzinfo=_IST)
    storage = StorageManager(":memory:")
    storage.initialise()
    try:
        storage.record_broker_quote(
            "2026-09-21 23:30:00",
            "SBIN",
            "NSE",
            source_tz=IST,
            prev_close=800.0,
        )
        found = lookup_stored_last_close("SBIN", "NSE", storage=storage, now=now)
    finally:
        storage.close()

    assert found is None
    refused = resolve_practice_market_price(
        symbol="SBIN",
        exchange="NSE",
        request_price=0,
        price_basis=None,
        stored_close=found,
    )
    assert refused == practice_price_unavailable("SBIN")


def test_tick_recorder_stores_an_ist_wall_clock_as_utc(monkeypatch) -> None:
    """A live quote whose broker time has no zone is stored as UTC."""
    from datetime import UTC

    import flinttrade_data.tick_recorder as recorder_module
    from flinttrade_data.storage import StorageManager, read_stored_timestamp
    from flinttrade_data.tick_recorder import TickRecorder

    received = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return received if tz is not None else received.replace(tzinfo=None)

    monkeypatch.setattr(recorder_module, "datetime", FixedDateTime)
    storage = StorageManager(":memory:")
    storage.initialise()
    try:
        recorder = TickRecorder(storage=storage)
        recorder.add_symbols([{"exchange": "NSE", "symbol": "SBIN"}], mode="quote")
        recorder._process_tick(
            {
                "exchange": "NSE",
                "symbol": "SBIN",
                "ltp": 812.40,
                "close": 810.0,
                "prev_close": 812.40,
                "timestamp": "2026-09-29 15:30:00",
            }
        )
        assert recorder._flush(force=True) is True
        stored = storage.get_ticks("SBIN", "NSE", "2026-09-29", "2026-09-29", limit=1)
        assert len(stored) == 1
        assert read_stored_timestamp(stored[0]["ts"]) == received
    finally:
        storage.close()


def test_option_session_uses_the_runtime_scheduler_holiday() -> None:
    """A holiday on the running scheduler closes an option a fresh clock would fill."""
    from datetime import date

    from flask import Flask

    import flinttrade_engine.scheduler as scheduler_mod
    from flinttrade_engine.scheduler import TimeScheduler

    session = datetime(2026, 3, 3, 12, 0, tzinfo=_IST)
    assert date(2026, 3, 3).weekday() < 5

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return session.replace(tzinfo=None)
            return session.astimezone(tz)

    original = scheduler_mod.datetime
    scheduler_mod.datetime = FixedDateTime
    try:
        fresh = TimeScheduler()
        runtime = TimeScheduler()
        runtime.set_holidays(
            {
                "status": "success",
                "year": 2026,
                "timezone": "Asia/Kolkata",
                "data": [
                    {
                        "date": "2026-03-03",
                        "description": "Holi",
                        "holiday_type": "TRADING_HOLIDAY",
                        "closed_exchanges": ["NSE", "BSE", "NFO", "BFO"],
                        "open_exchanges": [],
                    }
                ],
            },
            year="2026",
        )
        option = "NIFTY24APR25500CE"
        assert fresh.is_market_open("NFO", symbol=option) is True
        assert runtime.is_market_open("NFO", symbol=option) is False
        app = Flask(__name__)
        app.config["TIME_SCHEDULER"] = runtime
        with app.app_context():
            assert practice_market_is_open("NFO", option) is False
            refused = resolve_practice_market_price(
                symbol=option,
                exchange="NFO",
                request_price=12.5,
                price_basis="ltp",
                stored_close=StoredClose(price=11.0, age_s=60),
            )
        assert refused == OPTION_PRICE_STALE
    finally:
        scheduler_mod.datetime = original


def test_option_session_honours_a_runtime_special_session() -> None:
    """A weekend special session on the running scheduler stays open."""
    from datetime import date

    from flask import Flask

    import flinttrade_engine.scheduler as scheduler_mod
    from flinttrade_engine.scheduler import TimeScheduler

    session = datetime(2026, 11, 8, 18, 30, tzinfo=_IST)
    assert date(2026, 11, 8).weekday() == 6

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return session.replace(tzinfo=None)
            return session.astimezone(tz)

    original = scheduler_mod.datetime
    scheduler_mod.datetime = FixedDateTime
    try:
        fresh = TimeScheduler()
        runtime = TimeScheduler()
        runtime.set_holidays(
            {
                "status": "success",
                "year": 2026,
                "timezone": "Asia/Kolkata",
                "data": [
                    {
                        "date": "2026-11-08",
                        "description": "Muhurat",
                        "holiday_type": "SPECIAL_SESSION",
                        "closed_exchanges": ["NFO"],
                        "open_exchanges": [
                            {
                                "exchange": "NFO",
                                "start_time": "18:00",
                                "end_time": "19:00",
                            }
                        ],
                    }
                ],
            },
            year="2026",
        )
        option = "NIFTY24APR25500CE"
        assert fresh.is_market_open("NFO", symbol=option) is False
        assert runtime.is_market_open("NFO", symbol=option) is True
        app = Flask(__name__)
        app.config["TIME_SCHEDULER"] = runtime
        with app.app_context():
            assert practice_market_is_open("NFO", option) is True
            filled = resolve_practice_market_price(
                symbol=option,
                exchange="NFO",
                request_price=12.5,
                price_basis="ltp",
            )
        assert not isinstance(filled, str)
        assert filled.price == 12.5
        assert filled.price_source == PRICE_SOURCE_LTP
    finally:
        scheduler_mod.datetime = original


def test_option_session_fails_closed_without_a_runtime_scheduler() -> None:
    """No populated scheduler means the option session is closed."""
    from flask import Flask

    app = Flask(__name__)
    option = "NIFTY24APR25500CE"
    assert practice_market_is_open("NFO", option) is False
    with app.app_context():
        assert practice_market_is_open("NFO", option) is False
        refused = resolve_practice_market_price(
            symbol=option,
            exchange="NFO",
            request_price=12.5,
            price_basis="ltp",
        )
    assert refused == OPTION_PRICE_STALE


def test_configured_tick_store_reads_naive_utc_under_the_shared_lock() -> None:
    """Production tick rows are naive UTC, and the lookup holds the store lock."""
    import threading

    from flask import Flask

    from flinttrade_data.storage import StorageManager

    now = datetime(2026, 9, 29, 16, 10, tzinfo=_IST)
    storage = StorageManager(":memory:")
    storage.initialise()
    lock = threading.Lock()
    seen = {"locked": False}

    class LockedStore:
        def get_ticks(self, symbol: str, exchange: str, start: str, end: str, limit: int = 1):
            seen["locked"] = lock.locked()
            return storage.get_ticks(symbol, exchange, start, end, limit=limit)

    app = Flask(__name__)
    app.config["TICK_STORAGE"] = LockedStore()
    app.config["TICK_STORAGE_LOCK"] = lock
    try:
        storage.insert_tick(
            ts=now - timedelta(minutes=40),
            symbol="SBIN",
            exchange="NSE",
            mode="quote",
            prev_close=812.40,
        )
        with app.app_context():
            found = lookup_stored_last_close("SBIN", "NSE", now=now)
    finally:
        storage.close()

    assert seen["locked"] is True
    assert found is not None
    assert found.age_s == 40 * 60
    assert _positions_last_close_tag(found.age_s) == "Last close · 40m"


def test_last_close_lookup_skips_a_replaced_tick_store() -> None:
    """A store unpublished while the lock is taken is not read."""
    from flask import Flask

    calls: list[str] = []

    class Store:
        def get_ticks(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
            calls.append("read")
            return [{"ts": datetime(2026, 9, 29, 10, 0), "prev_close": 812.40}]

    class SwapOnEnter:
        def __enter__(self) -> "SwapOnEnter":
            app.config["TICK_STORAGE"] = object()
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    app = Flask(__name__)
    app.config["TICK_STORAGE"] = Store()
    app.config["TICK_STORAGE_LOCK"] = SwapOnEnter()
    with app.app_context():
        found = lookup_stored_last_close(
            "SBIN",
            "NSE",
            now=datetime(2026, 9, 29, 16, 10, tzinfo=_IST),
        )
    assert found is None
    assert calls == []
