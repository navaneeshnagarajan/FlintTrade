"""Order admission uses the dated derivatives close and the cash auction limit."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flinttrade_core.models import Order
from flinttrade_engine.safety import OrderValidation

IST = timezone(timedelta(hours=5, minutes=30))


def _order(symbol: str, exchange: str) -> Order:
    return Order(symbol=symbol, action="BUY", exchange=exchange, quantity="1")


def _at(day: int, hour: int, minute: int, month: int = 12) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=IST)


def test_admission_accepts_nfo_until_1545_only_from_dec_7() -> None:
    layer = OrderValidation()
    stock = _order("RELIANCE10DEC26FUT", "NFO")
    assert not layer.validate(stock, at=_at(4, 15, 42)).passed
    assert layer.validate(stock, at=_at(6, 15, 42)).passed is False
    assert layer.validate(stock, at=_at(7, 15, 40)).passed
    assert layer.validate(stock, at=_at(7, 15, 44)).passed
    assert not layer.validate(stock, at=_at(7, 15, 45)).passed
    assert layer.validate(_order("RELIANCE10DEC26FUT", "BFO"), at=_at(7, 15, 44)).passed


def test_admission_rejects_an_expiring_index_contract_after_1530() -> None:
    layer = OrderValidation()
    calendar = ["2026-12-10", "2026-12-17"]
    expiring = _order("NIFTY10DEC2624000CE", "NFO")
    later = _order("NIFTY17DEC2624000CE", "NFO")
    assert layer.validate(expiring, at=_at(10, 15, 29), expiry_calendar=calendar).passed
    assert not layer.validate(expiring, at=_at(10, 15, 30), expiry_calendar=calendar).passed
    assert layer.validate(later, at=_at(10, 15, 44), expiry_calendar=calendar).passed
    bse_index = _order("SENSEX10DEC2680000CE", "BFO")
    assert not layer.validate(bse_index, at=_at(10, 15, 31), expiry_calendar=calendar).passed
    assert layer.validate(expiring, at=_at(4, 15, 31), expiry_calendar=["2026-12-04"]).passed


def test_admission_fails_closed_when_the_index_expiry_is_unknown() -> None:
    layer = OrderValidation()
    dated = _order("NIFTY10DEC2624000CE", "NFO")
    assert layer.validate(dated, at=_at(10, 11, 0)).passed
    assert not layer.validate(dated, at=_at(10, 15, 30)).passed
    assert not layer.validate(dated, at=_at(10, 15, 44), expiry_calendar=["2026-12-17"]).passed
    assert not layer.validate(_order("NIFTY", "BFO"), at=_at(10, 11, 0)).passed


def test_cash_auction_entry_fails_closed_from_1538_and_derivatives_do_not() -> None:
    layer = OrderValidation()
    cash = _order("RELIANCE", "NSE")
    assert layer.validate(cash, at=_at(7, 15, 31)).passed
    assert layer.validate(cash, at=_at(7, 15, 37)).passed
    rejected = layer.validate(cash, at=_at(7, 15, 38))
    assert not rejected.passed
    assert "15:38" in rejected.reason
    assert not layer.validate(cash, at=_at(4, 15, 37)).passed
    assert layer.validate(_order("RELIANCE10DEC26FUT", "NFO"), at=_at(7, 15, 38)).passed
    assert layer.validate(_order("RELIANCE", "BSE"), at=_at(7, 15, 37)).passed
    assert not layer.validate(_order("RELIANCE", "BSE"), at=_at(7, 15, 38)).passed


def _system():
    from flinttrade_engine.safety import SafetyConfig, SafetySystem

    return SafetySystem(SafetyConfig(check_market_hours=True))


def _passed(results) -> bool:
    return all(result.passed for result in results)


def test_check_order_live_and_modify_use_the_symbol_expiry() -> None:
    from flinttrade_core.models import Position

    safety = _system()
    later = _order("NIFTY17DEC2624000CE", "NFO")
    expiring = _order("SENSEX10DEC2680000CE", "BFO")
    assert _passed(safety.check_order(
        later,
        selector="dhan:primary",
        at=_at(7, 15, 44),
        total_balance=100000,
        starting_capital=100000,
    ))
    assert not _passed(safety.check_order(
        later,
        selector="dhan:primary",
        at=_at(4, 15, 44),
        total_balance=100000,
        starting_capital=100000,
    ))
    assert _passed(safety.check_order(
        expiring,
        selector="dhan:primary",
        at=_at(10, 15, 29),
        total_balance=100000,
        starting_capital=100000,
    ))
    assert not _passed(safety.check_order(
        expiring,
        selector="dhan:primary",
        at=_at(10, 15, 30),
        total_balance=100000,
        starting_capital=100000,
    ))
    increased = _order("NIFTY17DEC2624000CE", "NFO")
    increased.quantity = "2"
    held = Position(
        symbol="NIFTY17DEC2624000CE",
        exchange="NFO",
        product="MIS",
        quantity="1",
    )
    assert _passed(safety.check_order(
        increased,
        selector="dhan:primary",
        positions=[held],
        at=_at(7, 15, 44),
        total_balance=100000,
        starting_capital=100000,
    ))
    assert not _passed(safety.check_order(
        _order("NIFTY", "NFO"),
        selector="dhan:primary",
        at=_at(7, 11, 0),
        total_balance=100000,
        starting_capital=100000,
    ))


def test_reduce_only_exit_is_not_blocked_by_a_missing_calendar() -> None:
    from flinttrade_core.models import Position

    safety = _system()
    exit_order = _order("NIFTY17DEC2624000CE", "NFO")
    exit_order.action = "SELL"
    held = Position(
        symbol="NIFTY17DEC2624000CE",
        exchange="NFO",
        product="MIS",
        quantity="1",
    )
    assert _passed(safety.check_order(
        exit_order,
        selector="dhan:primary",
        positions=[held],
        at=_at(10, 15, 44),
        total_balance=100000,
        starting_capital=100000,
    ))
    expiring_exit = _order("SENSEX10DEC2680000CE", "BFO")
    expiring_exit.action = "SELL"
    expiring_held = Position(
        symbol="SENSEX10DEC2680000CE",
        exchange="BFO",
        product="MIS",
        quantity="1",
    )
    assert _passed(safety.check_order(
        expiring_exit,
        selector="dhan:primary",
        positions=[expiring_held],
        at=_at(10, 15, 29),
        total_balance=100000,
        starting_capital=100000,
    ))
    assert not _passed(safety.check_order(
        expiring_exit,
        selector="dhan:primary",
        positions=[expiring_held],
        at=_at(10, 15, 31),
        total_balance=100000,
        starting_capital=100000,
    ))


def test_square_off_uses_the_symbol_expiry_without_a_calendar() -> None:
    from flinttrade_engine.scheduler import TimeScheduler

    scheduler = TimeScheduler()
    assert not scheduler.should_square_off(
        "NFO",
        at=_at(10, 14, 0),
        symbol="NIFTY17DEC2624000CE",
    )
    assert scheduler.should_square_off(
        "NFO",
        at=_at(10, 15, 25),
        symbol="NIFTY17DEC2624000CE",
    )
    assert scheduler.should_square_off(
        "BFO",
        at=_at(10, 15, 10),
        symbol="SENSEX10DEC2680000CE",
    )
    assert not scheduler.should_square_off(
        "BFO",
        at=_at(10, 14, 50),
        symbol="SENSEX10DEC2680000CE",
    )
    assert not scheduler.should_square_off(
        "NFO",
        at=_at(4, 15, 10),
        symbol="NIFTY17DEC2624000CE",
    )
    assert scheduler.should_square_off(
        "NFO",
        at=_at(4, 15, 15),
        symbol="NIFTY17DEC2624000CE",
    )


def test_safety_uses_muhurat_hours_and_stays_closed_outside_them() -> None:
    from flinttrade_engine.safety import is_market_open

    morning = datetime(2026, 11, 8, 10, 0, tzinfo=IST)
    during = datetime(2026, 11, 8, 15, 0, tzinfo=IST)
    assert not is_market_open("NFO", at=morning, symbol="RELIANCE10DEC26FUT")
    assert not is_market_open("NSE", at=morning)
    assert not _passed(_system().check_order(
        _order("RELIANCE", "NSE"),
        selector="dhan:primary",
        at=morning,
        total_balance=100000,
        starting_capital=100000,
    ))
    assert is_market_open("NFO", at=during, symbol="RELIANCE10DEC26FUT")
    assert _passed(_system().check_order(
        _order("RELIANCE10DEC26FUT", "NFO"),
        selector="dhan:primary",
        at=during,
        total_balance=100000,
        starting_capital=100000,
    ))


def test_check_order_stays_closed_on_an_ordinary_weekend_and_holiday() -> None:
    from flinttrade_core.models import Position
    from flinttrade_engine.safety import is_market_open
    from flinttrade_engine.scheduler import TimeScheduler

    sunday = datetime(2026, 11, 15, 11, 0, tzinfo=IST)
    monday = datetime(2026, 11, 16, 11, 0, tzinfo=IST)
    safety = _system()
    scheduler = TimeScheduler()
    for exchange, symbol in (
        ("NSE", "RELIANCE"),
        ("NFO", "RELIANCE26NOV26FUT"),
        ("BFO", "RELIANCE26NOV26FUT"),
    ):
        assert not scheduler.session_active(exchange, at=sunday, symbol=symbol)
        assert not is_market_open(exchange, at=sunday, symbol=symbol)
        fresh = _order(symbol, exchange)
        increased = _order(symbol, exchange)
        increased.quantity = "2"
        held = Position(symbol=symbol, exchange=exchange, product="MIS", quantity="1")
        assert not _passed(safety.check_order(
            fresh,
            selector="dhan:primary",
            at=sunday,
            total_balance=100000,
            starting_capital=100000,
        ))
        assert not _passed(safety.check_order(
            increased,
            selector="dhan:primary",
            positions=[held],
            at=sunday,
            total_balance=100000,
            starting_capital=100000,
        ))
        exit_order = _order(symbol, exchange)
        exit_order.action = "SELL"
        assert not _passed(safety.check_order(
            exit_order,
            selector="dhan:primary",
            positions=[held],
            at=sunday,
            total_balance=100000,
            starting_capital=100000,
        ))
        assert _passed(safety.check_order(
            fresh,
            selector="dhan:primary",
            at=monday,
            total_balance=100000,
            starting_capital=100000,
        ))

    holiday = TimeScheduler()
    holiday.set_holidays(
        {
            "data": [
                {
                    "date": "2026-11-16",
                    "holiday_type": "TRADING_HOLIDAY",
                    "closed_exchanges": ["NSE", "NFO", "BFO"],
                }
            ]
        },
        year="2026",
    )
    for exchange, symbol in (
        ("NSE", "RELIANCE"),
        ("NFO", "RELIANCE26NOV26FUT"),
        ("BFO", "RELIANCE26NOV26FUT"),
    ):
        assert not holiday.session_active(exchange, at=monday, symbol=symbol)
        assert not is_market_open(exchange, at=monday, symbol=symbol, market_calendar=holiday)
        assert not _passed(safety.check_order(
            _order(symbol, exchange),
            selector="dhan:primary",
            at=monday,
            total_balance=100000,
            starting_capital=100000,
            market_calendar=holiday,
        ))


def test_check_order_rejects_a_risk_increasing_order_after_expiry() -> None:
    safety = _system()
    expired = _order("NIFTY10DEC2624000CE", "NFO")
    for hour, minute in ((11, 0), (15, 44)):
        assert not _passed(safety.check_order(
            expired,
            selector="dhan:primary",
            at=_at(11, hour, minute),
            total_balance=100000,
            starting_capital=100000,
        ))
    assert _passed(safety.check_order(
        expired,
        selector="dhan:primary",
        at=_at(10, 11, 0),
        total_balance=100000,
        starting_capital=100000,
    ))
    stock = _order("RELIANCE10DEC26FUT", "NFO")
    assert not _passed(safety.check_order(
        stock,
        selector="dhan:primary",
        at=_at(11, 11, 0),
        total_balance=100000,
        starting_capital=100000,
    ))
