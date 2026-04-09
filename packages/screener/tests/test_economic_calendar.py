"""Tests for EconomicCalendarProvider and economic calendar route.

Run with:
    python -m pytest packages/screener/tests/test_economic_calendar.py -v --import-mode=importlib
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest


# ---------------------------------------------------------------------------
# EconomicEvent model
# ---------------------------------------------------------------------------


class TestEconomicEvent:
    """Test the EconomicEvent Pydantic model."""

    def _make_event(self, **kwargs):
        from packages.screener.src.economic_calendar import EconomicEvent

        defaults = dict(
            date=date(2026, 4, 10),
            time="10:00",
            event="RBI Monetary Policy Decision",
            country="IN",
            impact="high",
            category="interest_rate",
        )
        defaults.update(kwargs)
        return EconomicEvent(**defaults)

    def test_minimal_event_creation(self):
        event = self._make_event()
        assert event.country == "IN"
        assert event.impact == "high"
        assert event.actual is None
        assert event.forecast is None
        assert event.previous is None

    def test_full_event_creation(self):
        event = self._make_event(
            previous="6.50%",
            forecast="6.50%",
            actual="6.50%",
        )
        assert event.previous == "6.50%"
        assert event.forecast == "6.50%"
        assert event.actual == "6.50%"

    def test_impact_high_valid(self):
        event = self._make_event(impact="high")
        assert event.impact == "high"

    def test_impact_medium_valid(self):
        event = self._make_event(impact="medium")
        assert event.impact == "medium"

    def test_impact_low_valid(self):
        event = self._make_event(impact="low")
        assert event.impact == "low"

    def test_impact_invalid_raises(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            self._make_event(impact="critical")

    def test_category_interest_rate_valid(self):
        event = self._make_event(category="interest_rate")
        assert event.category == "interest_rate"

    def test_category_invalid_raises(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            self._make_event(category="unknown_category")

    def test_time_pattern_valid(self):
        event = self._make_event(time="09:15")
        assert event.time == "09:15"

    def test_time_pattern_invalid_raises(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            self._make_event(time="9:15")  # missing leading zero

    def test_to_dict_date_is_iso_string(self):
        event = self._make_event(date=date(2026, 4, 10))
        d = event.to_dict()
        assert d["date"] == "2026-04-10"
        assert isinstance(d["date"], str)

    def test_to_dict_contains_all_fields(self):
        event = self._make_event()
        d = event.to_dict()
        for key in (
            "date", "time", "event", "country", "impact",
            "previous", "forecast", "actual", "category",
        ):
            assert key in d, f"Missing field: {key}"

    @pytest.mark.parametrize("category", [
        "interest_rate", "gdp", "cpi", "employment",
        "trade", "pmi", "industrial", "other",
    ])
    def test_all_valid_categories(self, category):
        event = self._make_event(category=category)
        assert event.category == category


# ---------------------------------------------------------------------------
# EconomicCalendarProvider — core methods
# ---------------------------------------------------------------------------


class TestEconomicCalendarProvider:
    """Test EconomicCalendarProvider with a pre-seeded provider."""

    @pytest.fixture
    def provider(self):
        from packages.screener.src.economic_calendar import EconomicCalendarProvider

        p = EconomicCalendarProvider()
        p.generate_sample_data(months=2)
        return p

    # --- generate_sample_data ---

    def test_generate_produces_events(self, provider):
        assert provider.event_count() > 0

    def test_generate_includes_india_events(self, provider):
        india = [e for e in provider._events if e.country == "IN"]
        assert len(india) > 0, "Expected India events"

    def test_generate_includes_us_events(self, provider):
        us = [e for e in provider._events if e.country == "US"]
        assert len(us) > 0, "Expected US events"

    def test_generate_includes_china_events(self, provider):
        cn = [e for e in provider._events if e.country == "CN"]
        assert len(cn) > 0, "Expected China events"

    def test_generate_includes_multiple_countries(self, provider):
        countries = {e.country for e in provider._events}
        assert len(countries) >= 3

    def test_generate_includes_high_impact_events(self, provider):
        high = [e for e in provider._events if e.impact == "high"]
        assert len(high) > 0

    def test_generate_clears_previous_cache(self):
        from packages.screener.src.economic_calendar import EconomicCalendarProvider

        p = EconomicCalendarProvider()
        p.generate_sample_data(months=2)
        count1 = p.event_count()
        p.generate_sample_data(months=2)
        count2 = p.event_count()
        assert count1 == count2  # deterministic

    def test_generate_clamps_months_low(self):
        from packages.screener.src.economic_calendar import EconomicCalendarProvider

        p = EconomicCalendarProvider()
        events = p.generate_sample_data(months=0)
        assert isinstance(events, list)

    def test_generate_clamps_months_high(self):
        from packages.screener.src.economic_calendar import EconomicCalendarProvider

        p = EconomicCalendarProvider()
        events = p.generate_sample_data(months=999)
        assert isinstance(events, list)

    def test_generate_past_events_have_actual(self, provider):
        today = date.today()
        past = [e for e in provider._events if e.date < today]
        with_actual = [e for e in past if e.actual is not None]
        assert len(with_actual) > 0, "Past events should have actual values"

    def test_generate_future_events_no_actual(self, provider):
        today = date.today()
        future = [e for e in provider._events if e.date > today]
        with_actual = [e for e in future if e.actual is not None]
        assert len(with_actual) == 0, "Future events must not have actual values"

    def test_all_events_have_valid_impact(self, provider):
        for event in provider._events:
            assert event.impact in ("high", "medium", "low")

    def test_all_events_have_valid_categories(self, provider):
        valid = {
            "interest_rate", "gdp", "cpi", "employment",
            "trade", "pmi", "industrial", "other",
        }
        for event in provider._events:
            assert event.category in valid, f"Invalid category: {event.category}"

    def test_rbi_event_present(self, provider):
        rbi_events = [e for e in provider._events if "RBI" in e.event]
        assert len(rbi_events) > 0, "RBI Monetary Policy events expected"

    def test_fed_event_present(self, provider):
        fed_events = [e for e in provider._events if "FOMC" in e.event or "Fed" in e.event]
        assert len(fed_events) > 0, "US Fed rate decision expected"

    def test_india_cpi_present(self, provider):
        india_cpi = [
            e for e in provider._events
            if e.country == "IN" and e.category == "cpi"
        ]
        assert len(india_cpi) > 0

    def test_nfp_present(self, provider):
        nfp = [e for e in provider._events if "Non-Farm" in e.event]
        assert len(nfp) > 0, "US Non-Farm Payrolls expected"

    def test_china_pmi_present(self, provider):
        cn_pmi = [
            e for e in provider._events
            if e.country == "CN" and e.category == "pmi"
        ]
        assert len(cn_pmi) > 0

    # --- get_upcoming ---

    def test_get_upcoming_returns_list(self, provider):
        assert isinstance(provider.get_upcoming(days=14), list)

    def test_get_upcoming_all_in_future(self, provider):
        today = date.today()
        for ev in provider.get_upcoming(days=30):
            assert ev.date >= today

    def test_get_upcoming_within_window(self, provider):
        today = date.today()
        days = 30
        cutoff = today + timedelta(days=days)
        for ev in provider.get_upcoming(days=days):
            assert ev.date <= cutoff

    def test_get_upcoming_sorted_by_date(self, provider):
        result = provider.get_upcoming(days=60)
        dates = [e.date for e in result]
        assert dates == sorted(dates)

    def test_get_upcoming_country_filter(self, provider):
        result = provider.get_upcoming(days=60, countries=["IN"])
        for ev in result:
            assert ev.country == "IN"

    def test_get_upcoming_multi_country_filter(self, provider):
        result = provider.get_upcoming(days=60, countries=["IN", "US"])
        for ev in result:
            assert ev.country in ("IN", "US")

    def test_get_upcoming_country_filter_case_insensitive(self, provider):
        upper = provider.get_upcoming(days=60, countries=["IN"])
        lower = provider.get_upcoming(days=60, countries=["in"])
        assert len(upper) == len(lower)

    def test_get_upcoming_impact_filter_high_only(self, provider):
        result = provider.get_upcoming(days=60, min_impact="high")
        for ev in result:
            assert ev.impact == "high"

    def test_get_upcoming_impact_filter_medium_includes_high(self, provider):
        result_med = provider.get_upcoming(days=60, min_impact="medium")
        result_high = provider.get_upcoming(days=60, min_impact="high")
        assert len(result_med) >= len(result_high)
        for ev in result_med:
            assert ev.impact in ("medium", "high")

    def test_get_upcoming_low_includes_all(self, provider):
        all_events = provider.get_upcoming(days=60, min_impact="low")
        high_only = provider.get_upcoming(days=60, min_impact="high")
        assert len(all_events) >= len(high_only)

    def test_get_upcoming_no_country_filter_returns_all_countries(self, provider):
        result = provider.get_upcoming(days=60)
        countries = {e.country for e in result}
        assert len(countries) >= 2

    def test_get_upcoming_large_window_more_than_small(self, provider):
        small = provider.get_upcoming(days=7)
        large = provider.get_upcoming(days=60)
        assert len(large) >= len(small)

    def test_get_upcoming_clamps_days(self, provider):
        result_zero = provider.get_upcoming(days=0)
        result_one = provider.get_upcoming(days=1)
        assert isinstance(result_zero, list)
        assert isinstance(result_one, list)

    # --- get_by_country ---

    def test_get_by_country_returns_list(self, provider):
        assert isinstance(provider.get_by_country("IN"), list)

    def test_get_by_country_only_matching(self, provider):
        result = provider.get_by_country("US")
        for ev in result:
            assert ev.country == "US"

    def test_get_by_country_case_insensitive(self, provider):
        upper = provider.get_by_country("IN")
        lower = provider.get_by_country("in")
        assert len(upper) == len(lower)

    def test_get_by_country_unknown_returns_empty(self, provider):
        result = provider.get_by_country("ZZ")
        assert result == []

    def test_get_by_country_sorted_by_date(self, provider):
        result = provider.get_by_country("IN")
        dates = [e.date for e in result]
        assert dates == sorted(dates)

    # --- event_count ---

    def test_event_count_zero_on_new_provider(self):
        from packages.screener.src.economic_calendar import EconomicCalendarProvider

        p = EconomicCalendarProvider()
        assert p.event_count() == 0

    def test_event_count_matches_generate_output(self):
        from packages.screener.src.economic_calendar import EconomicCalendarProvider

        p = EconomicCalendarProvider()
        events = p.generate_sample_data(months=2)
        assert p.event_count() == len(events)

    # --- load_from_list ---

    def test_load_from_list_replaces_cache(self):
        from packages.screener.src.economic_calendar import (
            EconomicCalendarProvider,
            EconomicEvent,
        )

        p = EconomicCalendarProvider()
        p.generate_sample_data(months=2)
        assert p.event_count() > 0

        p.load_from_list([
            EconomicEvent(
                date=date(2026, 4, 10),
                time="10:00",
                event="Test Event",
                country="IN",
                impact="high",
                category="interest_rate",
            )
        ])
        assert p.event_count() == 1

    def test_load_from_empty_list_clears_cache(self):
        from packages.screener.src.economic_calendar import EconomicCalendarProvider

        p = EconomicCalendarProvider()
        p.generate_sample_data(months=2)
        p.load_from_list([])
        assert p.event_count() == 0


# ---------------------------------------------------------------------------
# Economic calendar route
# ---------------------------------------------------------------------------

_TEST_API_KEY = "test-economic-route-key"


@pytest.fixture(scope="module")
def _restore_env():
    original = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(original)


@pytest.fixture(scope="module")
def route_client(_restore_env):
    """Flask test client with a pre-seeded economic calendar provider."""
    os.environ["OPENALGO_API_KEY"] = _TEST_API_KEY
    from packages.core.src.app import create_flask_app
    from packages.screener.src.economic_calendar import EconomicCalendarProvider
    import packages.screener.src.economic_routes as _mod

    app = create_flask_app()
    app.config["TESTING"] = True

    provider = EconomicCalendarProvider()
    provider.generate_sample_data(months=4)
    _mod._provider = provider

    with app.test_client() as c:
        yield c


def _get(client, path: str, **params):
    """Issue an authenticated GET with optional query params."""
    from urllib.parse import urlencode

    qs = urlencode(params)
    url = f"{path}?{qs}" if qs else path
    return client.get(url, headers={"X-API-Key": _TEST_API_KEY})


class TestEconomicCalendarRoute:
    """Test GET /ft-api/v1/economic/calendar."""

    def test_returns_200(self, route_client):
        resp = _get(route_client, "/ft-api/v1/economic/calendar")
        assert resp.status_code == 200

    def test_response_shape(self, route_client):
        resp = _get(route_client, "/ft-api/v1/economic/calendar")
        data = resp.get_json()
        assert data["status"] == "success"
        assert "events" in data["data"]
        assert "count" in data["data"]
        assert "days" in data["data"]
        assert "filters" in data["data"]

    def test_default_days_is_14(self, route_client):
        resp = _get(route_client, "/ft-api/v1/economic/calendar")
        data = resp.get_json()
        assert data["data"]["days"] == 14

    def test_custom_days_param(self, route_client):
        resp = _get(route_client, "/ft-api/v1/economic/calendar", days=30)
        data = resp.get_json()
        assert data["data"]["days"] == 30

    def test_invalid_days_returns_400(self, route_client):
        resp = _get(route_client, "/ft-api/v1/economic/calendar", days="abc")
        assert resp.status_code == 400

    def test_invalid_impact_returns_400(self, route_client):
        resp = _get(route_client, "/ft-api/v1/economic/calendar", impact="critical")
        assert resp.status_code == 400

    def test_count_matches_events_length(self, route_client):
        resp = _get(route_client, "/ft-api/v1/economic/calendar", days=60)
        data = resp.get_json()
        assert data["data"]["count"] == len(data["data"]["events"])

    def test_is_sample_data_flag(self, route_client):
        resp = _get(route_client, "/ft-api/v1/economic/calendar")
        data = resp.get_json()
        assert data["is_sample_data"] is True

    def test_country_filter_single(self, route_client):
        resp = _get(route_client, "/ft-api/v1/economic/calendar", days=60, country="IN")
        events = resp.get_json()["data"]["events"]
        for ev in events:
            assert ev["country"] == "IN"

    def test_country_filter_multiple(self, route_client):
        resp = _get(route_client, "/ft-api/v1/economic/calendar", days=60, country="IN,US")
        events = resp.get_json()["data"]["events"]
        for ev in events:
            assert ev["country"] in ("IN", "US")

    def test_impact_filter_high_only(self, route_client):
        resp = _get(route_client, "/ft-api/v1/economic/calendar", days=60, impact="high")
        events = resp.get_json()["data"]["events"]
        for ev in events:
            assert ev["impact"] == "high"

    def test_impact_filter_medium_includes_high(self, route_client):
        med = _get(route_client, "/ft-api/v1/economic/calendar", days=60, impact="medium")
        high = _get(route_client, "/ft-api/v1/economic/calendar", days=60, impact="high")
        assert med.get_json()["data"]["count"] >= high.get_json()["data"]["count"]

    def test_event_fields_present(self, route_client):
        resp = _get(route_client, "/ft-api/v1/economic/calendar", days=90)
        events = resp.get_json()["data"]["events"]
        if events:
            ev = events[0]
            for field in (
                "date", "time", "event", "country", "impact",
                "previous", "forecast", "actual", "category",
            ):
                assert field in ev, f"Missing field: {field}"

    def test_filters_object_in_response(self, route_client):
        resp = _get(route_client, "/ft-api/v1/economic/calendar", country="IN", impact="high")
        filters = resp.get_json()["data"]["filters"]
        assert filters["min_impact"] == "high"
        assert "IN" in filters["countries"]

    def test_no_filter_includes_multiple_countries(self, route_client):
        resp = _get(route_client, "/ft-api/v1/economic/calendar", days=90)
        events = resp.get_json()["data"]["events"]
        countries = {ev["country"] for ev in events}
        assert len(countries) >= 2
