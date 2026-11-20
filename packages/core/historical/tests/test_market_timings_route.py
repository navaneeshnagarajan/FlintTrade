"""Tests for GET /api/v1/market/timings endpoint.

Run with:
    python -m pytest packages/core/historical/tests/test_market_timings_route.py -v --import-mode=importlib
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from flask import Flask

from flinttrade_core.models import Order
from flinttrade_engine.safety import SafetyConfig, SafetySystem, is_market_open
from flinttrade_engine.scheduler import TimeScheduler
from flinttrade_historical.holidays_routes import holidays_bp

IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app() -> Flask:
    """Minimal Flask app with the holidays blueprint (contains market/timings)."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(holidays_bp)
    return flask_app


@pytest.fixture()
def client(app: Flask):  # type: ignore[no-untyped-def]
    return app.test_client()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMarketTimingsRoute:
    """Tests for GET /api/v1/market/timings."""

    def test_nse_returns_200(self, client) -> None:  # type: ignore[no-untyped-def]
        """NSE timings returns HTTP 200."""
        response = client.get("/api/v1/market/timings?exchange=NSE")
        assert response.status_code == 200

    def test_nse_response_shape(self, client) -> None:  # type: ignore[no-untyped-def]
        """NSE response has expected keys with correct market hours."""
        response = client.get(
            "/api/v1/market/timings?exchange=NSE&at=2026-12-04T10:00:00%2B05:30"
        )
        data = response.get_json()
        assert data["status"] == "success"
        assert data["exchange"] == "NSE"
        assert data["open"] == "09:15"
        assert data["close"] == "15:30"
        assert data["pre_open"] == "09:00"
        assert isinstance(data["special_sessions"], list)

    def test_mcx_timings(self, client) -> None:  # type: ignore[no-untyped-def]
        """MCX returns correct extended hours (09:00-23:30)."""
        response = client.get("/api/v1/market/timings?exchange=MCX&at=2026-12-04T16:00:00%2B05:30")
        data = response.get_json()
        assert response.status_code == 200
        assert data["open"] == "09:00"
        assert data["close"] == "23:30"

    def test_ncdex_timings_use_the_gate_close(self, client) -> None:  # type: ignore[no-untyped-def]
        """NCDEX timings publish the 17:00 gate close, not the 23:30 standard hours."""
        response = client.get(
            "/api/v1/market/timings?exchange=NCDEX&on=2026-12-07&at=2026-12-07T12:00:00%2B05:30"
        )
        data = response.get_json()
        assert response.status_code == 200
        assert data["open"] == "10:00"
        assert data["close"] == "17:00"
        assert data["phase"] is None

    def test_nse_timings_publish_the_cash_phase(self, client) -> None:  # type: ignore[no-untyped-def]
        before = client.get("/api/v1/market/timings?exchange=NSE&on=2026-12-06&at=2026-12-06T15:20:00%2B05:30")
        after = client.get("/api/v1/market/timings?exchange=BSE&on=2026-12-07&at=2026-12-07T15:20:00%2B05:30")
        assert before.get_json()["order_entry"] == "closed"
        assert before.get_json()["close"] is None
        assert before.get_json()["phase"] == "closed"
        assert before.get_json()["reason"] == "weekend"
        assert after.get_json()["order_entry"] == "open"
        assert after.get_json()["close"] == "15:30"
        assert after.get_json()["phase"] == "continuous"

    def test_unknown_exchange_returns_400(self, client) -> None:  # type: ignore[no-untyped-def]
        """Unrecognised exchange code returns HTTP 400 with supported list."""
        response = client.get("/api/v1/market/timings?exchange=INVALID")
        assert response.status_code == 400
        data = response.get_json()
        assert "supported" in data

    def test_derivative_close_and_expiry_exception_switch_on_dec_7(self, client) -> None:  # type: ignore[no-untyped-def]
        before = client.get(
            "/api/v1/market/timings?exchange=NFO&on=2026-12-04&at=2026-12-04T12:00:00%2B05:30"
        )
        after = client.get(
            "/api/v1/market/timings?exchange=BFO&on=2026-12-07&at=2026-12-07T12:00:00%2B05:30"
        )
        assert before.status_code == 200
        assert before.get_json()["close"] == "15:40"
        assert before.get_json()["expiring_index_close"] is None
        body = after.get_json()
        assert body["close"] == "15:45"
        assert body["expiring_index_close"] == "15:30"
        assert body["order_entry"] == "open"

    def test_timings_reads_the_symbol_expiry_and_fails_closed_when_unconfirmed(self, client) -> None:  # type: ignore[no-untyped-def]
        listed = client.get(
            "/api/v1/market/timings?exchange=NFO&on=2026-12-10&at=2026-12-10T11:00:00%2B05:30"
            "&symbol=NIFTY10DEC2624000CE&expiries=2026-12-10,2026-12-17"
        )
        from_symbol = client.get(
            "/api/v1/market/timings?exchange=NFO&on=2026-12-10&at=2026-12-10T11:00:00%2B05:30"
            "&symbol=NIFTY10DEC2624000CE"
        )
        unconfirmed = client.get(
            "/api/v1/market/timings?exchange=NFO&on=2026-12-10&at=2026-12-10T11:00:00%2B05:30"
            "&symbol=NIFTY10DEC2624000CE&expiries=2026-12-17"
        )
        ambiguous = client.get(
            "/api/v1/market/timings?exchange=NFO&on=2026-12-10&at=2026-12-10T11:00:00%2B05:30"
            "&symbol=NIFTY"
        )
        later = client.get(
            "/api/v1/market/timings?exchange=BFO&on=2026-12-10&at=2026-12-10T11:00:00%2B05:30"
            "&symbol=SENSEX17DEC2680000CE&expiries=2026-12-10,2026-12-17"
        )
        assert listed.get_json()["close"] == "15:30"
        assert listed.get_json()["order_entry"] == "open"
        assert from_symbol.get_json()["close"] == "15:30"
        assert from_symbol.get_json()["order_entry"] == "open"
        assert from_symbol.get_json()["expiring_index_close"] == "15:30"
        assert unconfirmed.get_json()["close"] is None
        assert unconfirmed.get_json()["order_entry"] == "closed"
        assert ambiguous.get_json()["close"] is None
        assert ambiguous.get_json()["order_entry"] == "closed"
        assert later.get_json()["close"] == "15:45"


def _at(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=IST)


def _holiday_calendar() -> TimeScheduler:
    calendar = TimeScheduler()
    calendar.set_holidays(
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
    return calendar


def _check_order_admits(exchange: str, at: datetime, calendar: TimeScheduler | None) -> bool:
    safety = SafetySystem(SafetyConfig(check_market_hours=True))
    symbol = "RELIANCE" if exchange == "NSE" else "GOLD"
    order = Order(symbol=symbol, action="BUY", exchange=exchange, quantity="1")
    results = safety.check_order(
        order,
        selector="dhan:primary",
        at=at,
        total_balance=100000,
        starting_capital=100000,
        market_calendar=calendar,
    )
    return not any("Market closed" in result.reason for result in results)


class TestTimingsMatchAdmission:
    """Timings order_entry, phase, and close follow the live admission decision."""

    @pytest.fixture()
    def app(self) -> Flask:
        flask_app = Flask(__name__)
        flask_app.config["TESTING"] = True
        flask_app.config["TIME_SCHEDULER"] = _holiday_calendar()
        flask_app.register_blueprint(holidays_bp)
        return flask_app

    @pytest.mark.parametrize("exchange", ["NSE", "MCX"])
    @pytest.mark.parametrize(
        ("at", "reason"),
        [
            (_at(2026, 12, 5, 10, 0), "weekend"),
            (_at(2026, 12, 6, 10, 0), "weekend"),
            (_at(2026, 11, 16, 11, 0), "holiday"),
            (_at(2026, 12, 4, 23, 40), "after_close"),
        ],
    )
    def test_closed_instants_match_admission(
        self,
        client,
        app: Flask,
        exchange: str,
        at: datetime,
        reason: str,
    ) -> None:
        calendar = app.config["TIME_SCHEDULER"]
        response = client.get(
            "/api/v1/market/timings",
            query_string={"exchange": exchange, "at": at.isoformat()},
        )
        assert response.status_code == 200
        body = response.get_json()
        admitted = is_market_open(exchange, at=at, market_calendar=calendar)
        assert _check_order_admits(exchange, at, calendar) is admitted
        assert admitted is False
        assert body["order_entry"] == "closed"
        assert (body["order_entry"] in {"open", "auction_entry"}) is admitted
        assert body["reason"] == reason
        if reason == "after_close":
            assert body["close"] == ("15:30" if exchange == "NSE" else "23:30")
            assert body["phase"] == ("closed" if exchange == "NSE" else None)
        else:
            assert body["close"] is None
            assert body["phase"] == "closed"

    @pytest.mark.parametrize("exchange", ["NSE", "MCX"])
    def test_weekday_after_the_cash_close_uses_that_exchanges_gate(self, client, exchange: str) -> None:
        at = _at(2026, 12, 4, 15, 40)
        calendar = TimeScheduler()
        response = client.get(
            "/api/v1/market/timings",
            query_string={"exchange": exchange, "at": at.isoformat()},
        )
        body = response.get_json()
        admitted = is_market_open(exchange, at=at, market_calendar=calendar)
        assert _check_order_admits(exchange, at, calendar) is admitted
        assert (body["order_entry"] in {"open", "auction_entry"}) is admitted
        if exchange == "NSE":
            assert admitted is False
            assert body["order_entry"] == "closed"
            assert body["phase"] == "matching"
            assert body["close"] == "15:30"
            assert body["reason"] == "after_close"
        else:
            assert admitted is True
            assert body["order_entry"] == "open"
            assert body["close"] == "23:30"
            assert body["phase"] is None

    @pytest.mark.parametrize("exchange", ["NSE", "MCX"])
    @pytest.mark.parametrize(
        ("label", "at", "admitted", "phase"),
        [
            ("before the window", _at(2026, 11, 8, 14, 19), False, "closed"),
            ("at the open", _at(2026, 11, 8, 14, 20), True, "continuous"),
            ("mid session", _at(2026, 11, 8, 15, 0), True, "continuous"),
            ("just after the close", _at(2026, 11, 8, 15, 31), False, None),
        ],
    )
    def test_muhurat_window_follows_the_special_session(
        self,
        client,
        exchange: str,
        label: str,
        at: datetime,
        admitted: bool,
        phase: str | None,
    ) -> None:
        del label
        calendar = TimeScheduler()
        response = client.get(
            "/api/v1/market/timings",
            query_string={"exchange": exchange, "at": at.isoformat()},
        )
        body = response.get_json()
        gate_open = is_market_open(exchange, at=at, market_calendar=calendar)
        assert _check_order_admits(exchange, at, calendar) is gate_open
        assert gate_open is admitted
        assert (body["order_entry"] in {"open", "auction_entry"}) is gate_open
        assert body["close"] == "15:30"
        assert body["close"] != "23:30" or exchange == "NSE"
        if phase == "closed":
            assert body["phase"] == "closed"
            assert body["reason"] == "before_open"
        elif admitted:
            assert body["phase"] == "continuous"
            assert body["reason"] == "special_session"
            assert body["open"] == "14:20"
        else:
            assert body["order_entry"] == "closed"
            assert body["reason"] == "after_close"
            assert body["phase"] != "continuous"
