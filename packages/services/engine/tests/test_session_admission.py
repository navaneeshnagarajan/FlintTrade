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
    unknown = _order("NIFTY10DEC2624000CE", "NFO")
    assert not layer.validate(unknown, at=_at(10, 11, 0)).passed
    assert not layer.validate(unknown, at=_at(10, 15, 44), expiry_calendar=["2026-12-17"]).passed
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
