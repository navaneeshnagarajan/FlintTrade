"""Exchange-aware calendar contracts for ``TimeScheduler``."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone


IST = timezone(timedelta(hours=5, minutes=30))


def _calendar_payload() -> dict[str, object]:
    return {
        "status": "success",
        "year": 2026,
        "timezone": "Asia/Kolkata",
        "data": [
            {
                "date": "2026-03-03",
                "description": "Holi",
                "holiday_type": "TRADING_HOLIDAY",
                "closed_exchanges": ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD"],
                "open_exchanges": [
                    {
                        "exchange": "MCX",
                        "start_time": "17:00",
                        "end_time": "23:55",
                    }
                ],
            },
            {
                "date": "2026-11-08",
                "description": "Muhurat Trading",
                "holiday_type": "SPECIAL_SESSION",
                "closed_exchanges": ["NSE"],
                "open_exchanges": [
                    {
                        "exchange": "NSE",
                        "start_time": "18:00",
                        "end_time": "19:00",
                    }
                ],
            },
            {
                "date": "2026-12-12",
                "description": "Currency test session",
                "holiday_type": "SPECIAL_SESSION",
                "closed_exchanges": ["CDS"],
                "open_exchanges": [
                    {
                        "exchange": "CDS",
                        "symbols": ["EURUSD"],
                        "start_time": "18:00",
                        "end_time": "19:00",
                    }
                ],
            },
        ],
    }


def test_aware_at_time_is_converted_to_ist() -> None:
    from flinttrade_engine.scheduler import TimeScheduler

    scheduler = TimeScheduler()
    at_utc = datetime(2026, 3, 16, 4, 0, tzinfo=timezone.utc)

    assert scheduler.is_market_open("NSE", at=at_utc)
    assert scheduler.is_deploy_frozen(["NSE"], at=at_utc)


def test_partial_holiday_closes_equities_but_keeps_only_mcx_special_session() -> None:
    from flinttrade_engine.scheduler import TimeScheduler

    scheduler = TimeScheduler()
    scheduler.set_holidays(_calendar_payload(), year="2026")

    assert not scheduler.is_trading_day("NSE", on=date(2026, 3, 3))
    assert scheduler.is_trading_day("MCX", on=date(2026, 3, 3))
    assert not scheduler.is_market_open(
        "MCX",
        at=datetime(2026, 3, 3, 12, 0, tzinfo=IST),
    )
    assert scheduler.is_market_open(
        "MCX",
        at=datetime(2026, 3, 3, 18, 0, tzinfo=IST),
    )


def test_weekend_special_session_overrides_closure_only_inside_session() -> None:
    from flinttrade_engine.scheduler import TimeScheduler

    scheduler = TimeScheduler()
    scheduler.set_holidays(_calendar_payload(), year="2026")

    session_date = date(2026, 11, 8)
    assert session_date.weekday() == 6
    assert scheduler.get_market_session("NSE", on=session_date) == (
        time(18, 0),
        time(19, 0),
    )
    assert scheduler.is_market_open(
        "NSE",
        at=datetime(2026, 11, 8, 18, 30, tzinfo=IST),
    )
    assert not scheduler.is_market_open(
        "NSE",
        at=datetime(2026, 11, 8, 10, 0, tzinfo=IST),
    )


def test_symbol_scoped_special_session_does_not_open_other_contracts() -> None:
    from flinttrade_engine.scheduler import TimeScheduler

    scheduler = TimeScheduler()
    scheduler.set_holidays(_calendar_payload(), year="2026")
    at = datetime(2026, 12, 12, 18, 30, tzinfo=IST)

    assert scheduler.is_market_open("CDS", at=at, symbol="EURUSD29JUL26FUT")
    assert not scheduler.is_market_open("CDS", at=at, symbol="USDINR29JUL26FUT")


def test_malformed_declared_special_session_fails_closed() -> None:
    from flinttrade_engine.scheduler import TimeScheduler

    scheduler = TimeScheduler()
    scheduler.set_holidays(
        {
            "data": [
                {
                    "date": "2026-03-03",
                    "holiday_type": "TRADING_HOLIDAY",
                    "closed_exchanges": ["NSE"],
                    "open_exchanges": [
                        {
                            "exchange": "MCX",
                            "start_time": "not-a-time",
                            "end_time": "23:55",
                        }
                    ],
                }
            ]
        },
        year="2026",
    )

    assert not scheduler.is_trading_day("MCX", on=date(2026, 3, 3))
