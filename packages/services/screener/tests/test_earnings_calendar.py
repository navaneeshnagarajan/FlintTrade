"""Tests for EarningsCalendar and earnings routes.

Run with:
    python -m pytest packages/services/screener/tests/test_earnings_calendar.py -v --import-mode=importlib
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest


# ---------------------------------------------------------------------------
# EarningsEvent model
# ---------------------------------------------------------------------------


class TestEarningsEvent:
    """Test the EarningsEvent Pydantic model."""

    def _make_event(self, **kwargs):
        from flinttrade_screener.earnings_calendar import EarningsEvent

        defaults = dict(
            symbol="RELIANCE",
            company_name="Reliance Industries Ltd",
            date=date(2026, 4, 20),
            quarter="Q4",
            financial_year="FY2026",
        )
        defaults.update(kwargs)
        return EarningsEvent(**defaults)

    def test_minimal_event_creation(self):
        event = self._make_event()
        assert event.symbol == "RELIANCE"
        assert event.quarter == "Q4"
        assert event.financial_year == "FY2026"
        assert event.estimated_eps is None
        assert event.actual_eps is None
        assert event.surprise_pct is None
        assert event.result is None

    def test_full_event_creation(self):
        event = self._make_event(
            estimated_eps=67.5,
            actual_eps=72.0,
            surprise_pct=6.67,
            result="beat",
        )
        assert event.estimated_eps == 67.5
        assert event.actual_eps == 72.0
        assert event.result == "beat"

    def test_result_values_valid(self):
        from flinttrade_screener.earnings_calendar import EarningsEvent

        for result in ("beat", "miss", "meet"):
            event = EarningsEvent(
                symbol="TCS",
                company_name="TCS",
                date=date(2026, 4, 1),
                quarter="Q4",
                financial_year="FY2026",
                result=result,
            )
            assert event.result == result

    def test_result_invalid_raises(self):
        from pydantic import ValidationError
        from flinttrade_screener.earnings_calendar import EarningsEvent

        with pytest.raises(ValidationError):
            EarningsEvent(
                symbol="TCS",
                company_name="TCS",
                date=date(2026, 4, 1),
                quarter="Q4",
                financial_year="FY2026",
                result="unknown",
            )

    def test_to_dict_date_is_iso_string(self):
        event = self._make_event(date=date(2026, 7, 15))
        d = event.to_dict()
        assert d["date"] == "2026-07-15"
        assert isinstance(d["date"], str)

    def test_to_dict_contains_all_fields(self):
        event = self._make_event(estimated_eps=55.0, actual_eps=58.0)
        d = event.to_dict()
        for key in (
            "symbol",
            "company_name",
            "date",
            "quarter",
            "financial_year",
            "estimated_eps",
            "actual_eps",
            "surprise_pct",
            "result",
        ):
            assert key in d, f"Missing field: {key}"

    def test_symbol_preserved_as_given(self):
        event = self._make_event(symbol="HDFCBANK")
        assert event.symbol == "HDFCBANK"


# ---------------------------------------------------------------------------
# EarningsCalendar — core methods
# ---------------------------------------------------------------------------


class TestEarningsCalendar:
    """Test EarningsCalendar with a pre-seeded calendar."""

    @pytest.fixture
    def cal(self):
        from flinttrade_screener.earnings_calendar import EarningsCalendar

        c = EarningsCalendar()
        c.generate_sample_data(months=3)
        return c

    # --- generate_sample_data ---

    def test_generate_produces_events(self, cal):
        assert cal.event_count() > 0

    def test_generate_covers_nifty50_symbols(self, cal):
        found_symbols = {
            e.symbol
            for events in cal._cache.values()
            for e in events
        }
        # At least half of NIFTY 50 should appear in a 3-month window
        assert len(found_symbols) >= 25

    def test_generate_creates_past_events_with_actuals(self, cal):
        today = date.today()
        past_events = [
            e
            for events in cal._cache.values()
            for e in events
            if e.date < today
        ]
        # Past events should have actual_eps set
        with_actuals = [e for e in past_events if e.actual_eps is not None]
        assert len(with_actuals) > 0

    def test_generate_creates_future_events_without_actuals(self, cal):
        today = date.today()
        future_events = [
            e
            for events in cal._cache.values()
            for e in events
            if e.date > today
        ]
        # Future events must not have actual_eps
        with_actuals = [e for e in future_events if e.actual_eps is not None]
        assert len(with_actuals) == 0

    def test_generate_three_month_window_bridges_quarter_gap(self, monkeypatch):
        import flinttrade_screener.earnings_calendar as earnings_calendar

        class FixedDate(date):
            @classmethod
            def today(cls):
                return cls(2026, 5, 29)

        monkeypatch.setattr(earnings_calendar, "date", FixedDate)

        c = earnings_calendar.EarningsCalendar()
        events = c.generate_sample_data(months=3)
        today = FixedDate.today()

        assert any(e.date < today and e.actual_eps is not None for e in events)
        assert any(e.date > today and e.actual_eps is None for e in events)

    def test_generate_clamps_months_low(self):
        from flinttrade_screener.earnings_calendar import EarningsCalendar

        c = EarningsCalendar()
        events = c.generate_sample_data(months=0)
        # 0 → clamped to 1 — should still produce some events
        assert isinstance(events, list)

    def test_generate_clears_previous_cache(self):
        from flinttrade_screener.earnings_calendar import EarningsCalendar

        c = EarningsCalendar()
        c.generate_sample_data(months=3)
        count1 = c.event_count()
        c.generate_sample_data(months=3)
        count2 = c.event_count()
        # Cache is cleared then repopulated — counts should be equal (deterministic)
        assert count1 == count2

    def test_event_quarters_are_valid(self, cal):
        valid_quarters = {"Q1", "Q2", "Q3", "Q4"}
        for events in cal._cache.values():
            for e in events:
                assert e.quarter in valid_quarters

    def test_financial_year_format(self, cal):
        for events in cal._cache.values():
            for e in events:
                fy = e.financial_year
                assert fy.startswith("FY"), f"Bad FY format: {fy}"
                assert len(fy) == 6  # e.g. FY2026

    # --- get_upcoming ---

    def test_get_upcoming_returns_list(self, cal):
        result = cal.get_upcoming(days=30)
        assert isinstance(result, list)

    def test_get_upcoming_all_in_future(self, cal):
        today = date.today()
        result = cal.get_upcoming(days=30)
        for e in result:
            assert e.date >= today

    def test_get_upcoming_within_window(self, cal):
        today = date.today()
        days = 30
        cutoff = today + timedelta(days=days)
        result = cal.get_upcoming(days=days)
        for e in result:
            assert e.date <= cutoff

    def test_get_upcoming_sorted_by_date(self, cal):
        result = cal.get_upcoming(days=60)
        dates = [e.date for e in result]
        assert dates == sorted(dates)

    def test_get_upcoming_clamps_days(self, cal):
        # days=0 should be clamped to 1 — returns today's events only
        result_zero = cal.get_upcoming(days=0)
        result_one = cal.get_upcoming(days=1)
        assert result_zero == result_one

    def test_get_upcoming_large_window_includes_more(self, cal):
        small = cal.get_upcoming(days=7)
        large = cal.get_upcoming(days=60)
        assert len(large) >= len(small)

    # --- get_by_date ---

    def test_get_by_date_returns_list(self, cal):
        result = cal.get_by_date(date.today())
        assert isinstance(result, list)

    def test_get_by_date_empty_for_no_events(self, cal):
        far_future = date(2099, 1, 1)
        result = cal.get_by_date(far_future)
        assert result == []

    def test_get_by_date_only_matching_date(self, cal):
        # Find a date that has events
        for iso_date, events in cal._cache.items():
            if events:
                target = date.fromisoformat(iso_date)
                result = cal.get_by_date(target)
                assert len(result) == len(events)
                assert all(e.date == target for e in result)
                break

    def test_get_by_date_sorted_by_symbol(self, cal):
        # Load multiple events on a single date
        from flinttrade_screener.earnings_calendar import EarningsEvent, EarningsCalendar

        c = EarningsCalendar()
        d = date(2026, 4, 20)
        c.load_from_list([
            EarningsEvent(symbol="TCS", company_name="TCS", date=d, quarter="Q4", financial_year="FY2026"),
            EarningsEvent(symbol="RELIANCE", company_name="Reliance", date=d, quarter="Q4", financial_year="FY2026"),
            EarningsEvent(symbol="INFY", company_name="Infosys", date=d, quarter="Q4", financial_year="FY2026"),
        ])
        result = c.get_by_date(d)
        symbols = [e.symbol for e in result]
        assert symbols == sorted(symbols)

    # --- get_by_symbol ---

    def test_get_by_symbol_returns_list(self, cal):
        result = cal.get_by_symbol("RELIANCE")
        assert isinstance(result, list)

    def test_get_by_symbol_case_insensitive(self, cal):
        upper = cal.get_by_symbol("RELIANCE")
        lower = cal.get_by_symbol("reliance")
        assert len(upper) == len(lower)

    def test_get_by_symbol_all_match_symbol(self, cal):
        result = cal.get_by_symbol("TCS")
        assert all(e.symbol == "TCS" for e in result)

    def test_get_by_symbol_sorted_by_date(self, cal):
        result = cal.get_by_symbol("INFY")
        dates = [e.date for e in result]
        assert dates == sorted(dates)

    def test_get_by_symbol_unknown_returns_empty(self, cal):
        result = cal.get_by_symbol("NONEXISTENT_XYZ")
        assert result == []

    # --- load_from_list ---

    def test_load_from_list_replaces_cache(self):
        from flinttrade_screener.earnings_calendar import EarningsEvent, EarningsCalendar

        c = EarningsCalendar()
        c.generate_sample_data(months=3)
        assert c.event_count() > 0

        c.load_from_list([
            EarningsEvent(
                symbol="RELIANCE",
                company_name="Reliance",
                date=date(2026, 4, 20),
                quarter="Q4",
                financial_year="FY2026",
            )
        ])
        assert c.event_count() == 1

    def test_load_from_empty_list_clears_cache(self):
        from flinttrade_screener.earnings_calendar import EarningsCalendar

        c = EarningsCalendar()
        c.generate_sample_data(months=3)
        c.load_from_list([])
        assert c.event_count() == 0

    # --- event_count ---

    def test_event_count_zero_on_new_calendar(self):
        from flinttrade_screener.earnings_calendar import EarningsCalendar

        c = EarningsCalendar()
        assert c.event_count() == 0

    def test_event_count_matches_generate_output(self):
        from flinttrade_screener.earnings_calendar import EarningsCalendar

        c = EarningsCalendar()
        events = c.generate_sample_data(months=3)
        assert c.event_count() == len(events)


# ---------------------------------------------------------------------------
# Earnings routes
# ---------------------------------------------------------------------------

_TEST_API_KEY = "test-earnings-route-key"


@pytest.fixture(scope="module")
def _restore_env():
    original = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(original)


@pytest.fixture(scope="module")
def route_client(_restore_env):
    """Flask test client with a pre-seeded earnings calendar."""
    os.environ["OPENALGO_API_KEY"] = _TEST_API_KEY
    from flinttrade_core.app import create_flask_app
    from flinttrade_screener.earnings_calendar import EarningsCalendar
    import flinttrade_screener.earnings_routes as _mod

    app = create_flask_app()
    app.config["TESTING"] = True

    # Inject a fresh calendar into the module-level singleton
    cal = EarningsCalendar()
    cal.generate_sample_data(months=6)
    _mod._calendar = cal

    with app.test_client() as c:
        yield c


def _get(client, path: str, **params):
    """Issue an authenticated GET with optional query params."""
    from urllib.parse import urlencode

    qs = urlencode(params)
    url = f"{path}?{qs}" if qs else path
    return client.get(url, headers={"X-API-Key": _TEST_API_KEY})


class TestEarningsCalendarRoute:
    """Test GET /ft-api/v1/earnings/calendar."""

    def test_returns_200(self, route_client):
        resp = _get(route_client, "/api/v1/earnings/calendar")
        assert resp.status_code == 200

    def test_response_shape(self, route_client):
        resp = _get(route_client, "/api/v1/earnings/calendar")
        data = resp.get_json()
        assert data["status"] == "success"
        assert "events" in data["data"]
        assert "count" in data["data"]
        assert "days" in data["data"]

    def test_default_days_is_30(self, route_client):
        resp = _get(route_client, "/api/v1/earnings/calendar")
        data = resp.get_json()
        assert data["data"]["days"] == 30

    def test_custom_days_param(self, route_client):
        resp = _get(route_client, "/api/v1/earnings/calendar", days=60)
        data = resp.get_json()
        assert data["data"]["days"] == 60

    def test_year_month_params_filter_events_and_entries_alias(self, route_client):
        from datetime import date as _date

        today = _date.today()
        resp = _get(route_client, "/api/v1/earnings/calendar", year=today.year, month=today.month)
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["year"] == today.year
        assert data["month"] == today.month
        assert data["entries"] == data["events"]
        assert data["count"] == len(data["entries"])
        for row in data["entries"]:
            assert row["date"].startswith(f"{today.year:04d}-{today.month:02d}-")

    def test_invalid_days_returns_400(self, route_client):
        resp = _get(route_client, "/api/v1/earnings/calendar", days="abc")
        assert resp.status_code == 400

    def test_count_matches_events_length(self, route_client):
        resp = _get(route_client, "/api/v1/earnings/calendar", days=90)
        data = resp.get_json()
        assert data["data"]["count"] == len(data["data"]["events"])

    def test_event_fields_present(self, route_client):
        resp = _get(route_client, "/api/v1/earnings/calendar", days=90)
        events = resp.get_json()["data"]["events"]
        if events:
            e = events[0]
            for field in (
                "symbol",
                "company_name",
                "date",
                "quarter",
                "financial_year",
                "estimated_eps",
                "actual_eps",
                "surprise_pct",
                "result",
            ):
                assert field in e, f"Missing field: {field}"

    def test_is_sample_data_flag(self, route_client):
        resp = _get(route_client, "/api/v1/earnings/calendar")
        data = resp.get_json()
        assert data["is_sample_data"] is True


class TestEarningsByDateRoute:
    """Test GET /ft-api/v1/earnings/by-date."""

    def test_returns_200_for_valid_date(self, route_client):
        # Use a date that will have events in the generated sample (±3 months)
        target = (date.today() + timedelta(days=15)).isoformat()
        resp = _get(route_client, "/api/v1/earnings/by-date", date=target)
        assert resp.status_code == 200

    def test_missing_date_returns_400(self, route_client):
        resp = _get(route_client, "/api/v1/earnings/by-date")
        assert resp.status_code == 400

    def test_invalid_date_format_returns_400(self, route_client):
        resp = _get(route_client, "/api/v1/earnings/by-date", date="not-a-date")
        assert resp.status_code == 400

    def test_response_contains_date_field(self, route_client):
        target = (date.today() + timedelta(days=15)).isoformat()
        resp = _get(route_client, "/api/v1/earnings/by-date", date=target)
        data = resp.get_json()
        assert data["data"]["date"] == target

    def test_empty_list_for_date_with_no_events(self, route_client):
        resp = _get(route_client, "/api/v1/earnings/by-date", date="2099-01-01")
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["count"] == 0
        assert data["data"]["events"] == []


class TestEarningsBySymbolRoute:
    """Test GET /ft-api/v1/earnings/by-symbol."""

    def test_returns_200_for_valid_symbol(self, route_client):
        resp = _get(route_client, "/api/v1/earnings/by-symbol", symbol="RELIANCE")
        assert resp.status_code == 200

    def test_missing_symbol_returns_400(self, route_client):
        resp = _get(route_client, "/api/v1/earnings/by-symbol")
        assert resp.status_code == 400

    def test_response_contains_symbol_field(self, route_client):
        resp = _get(route_client, "/api/v1/earnings/by-symbol", symbol="TCS")
        data = resp.get_json()
        assert data["data"]["symbol"] == "TCS"

    def test_case_insensitive_symbol(self, route_client):
        upper = _get(route_client, "/api/v1/earnings/by-symbol", symbol="INFY")
        lower = _get(route_client, "/api/v1/earnings/by-symbol", symbol="infy")
        assert upper.get_json()["data"]["count"] == lower.get_json()["data"]["count"]

    def test_unknown_symbol_returns_empty_events(self, route_client):
        resp = _get(route_client, "/api/v1/earnings/by-symbol", symbol="XYZABCFAKE")
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["count"] == 0
        assert data["data"]["events"] == []

    def test_count_matches_events_length(self, route_client):
        resp = _get(route_client, "/api/v1/earnings/by-symbol", symbol="TCS")
        data = resp.get_json()
        assert data["data"]["count"] == len(data["data"]["events"])

    def test_events_sorted_by_date(self, route_client):
        resp = _get(route_client, "/api/v1/earnings/by-symbol", symbol="RELIANCE")
        events = resp.get_json()["data"]["events"]
        dates = [e["date"] for e in events]
        assert dates == sorted(dates)
