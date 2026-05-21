"""Tests for market_hours -- special trading sessions and market hours lookup.

Covers:
- SpecialTradingSession dataclass
- Standard exchange hours
- Muhurat Trading detection
- get_market_hours with special session override
- Dynamic session registration
- Upcoming session listing
"""

from __future__ import annotations

from datetime import date, time

import pytest

from packages.engine.src.market_hours import (
    SPECIAL_SESSIONS,
    STANDARD_HOURS,
    SpecialTradingSession,
    add_special_session,
    get_market_hours,
    get_standard_hours,
    is_special_session,
    list_upcoming_sessions,
)


# ---------------------------------------------------------------------------
# SpecialTradingSession dataclass
# ---------------------------------------------------------------------------


class TestSpecialTradingSession:
    def test_creates_frozen_instance(self) -> None:
        session = SpecialTradingSession(
            session_date=date(2025, 10, 20),
            name="Muhurat Trading 2025",
            open_time=time(18, 15),
            close_time=time(19, 15),
        )
        assert session.session_date == date(2025, 10, 20)
        assert session.name == "Muhurat Trading 2025"
        assert session.open_time == time(18, 15)
        assert session.close_time == time(19, 15)
        assert session.exchanges == ()

    def test_frozen_raises_on_mutation(self) -> None:
        session = SpecialTradingSession(
            session_date=date(2025, 10, 20),
            name="Test",
            open_time=time(18, 0),
            close_time=time(19, 0),
        )
        with pytest.raises(AttributeError):
            session.name = "Changed"  # type: ignore[misc]

    def test_custom_exchanges(self) -> None:
        session = SpecialTradingSession(
            session_date=date(2025, 10, 20),
            name="MCX Special",
            open_time=time(18, 0),
            close_time=time(20, 0),
            exchanges=("MCX",),
        )
        assert session.exchanges == ("MCX",)


# ---------------------------------------------------------------------------
# Standard hours
# ---------------------------------------------------------------------------


class TestStandardHours:
    def test_nse_hours(self) -> None:
        open_t, close_t = get_standard_hours("NSE")
        assert open_t == time(9, 15)
        assert close_t == time(15, 30)

    def test_mcx_hours(self) -> None:
        open_t, close_t = get_standard_hours("MCX")
        assert open_t == time(9, 0)
        assert close_t == time(23, 30)

    def test_cds_hours(self) -> None:
        open_t, close_t = get_standard_hours("CDS")
        assert open_t == time(9, 0)
        assert close_t == time(17, 0)

    def test_all_exchanges_present(self) -> None:
        # NCO (NSE Commodities), MCX_INDEX (commodity indices), and
        # GLOBAL_INDEX (world reference feeds) were added in the OpenAlgo
        # v2.0.0.7 sync; keep this list in lock-step with STANDARD_HOURS
        # so any future addition trips the assertion.
        expected = {
            "NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX", "NCDEX",
            "NCO", "NSE_INDEX", "BSE_INDEX", "MCX_INDEX", "GLOBAL_INDEX",
        }
        assert set(STANDARD_HOURS.keys()) == expected

    def test_unknown_exchange_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown exchange"):
            get_standard_hours("INVALID")


# ---------------------------------------------------------------------------
# is_special_session
# ---------------------------------------------------------------------------


class TestIsSpecialSession:
    def test_muhurat_2025_detected(self) -> None:
        session = is_special_session(date(2025, 10, 20))
        assert session is not None
        assert "Muhurat" in session.name
        assert session.open_time == time(18, 15)
        assert session.close_time == time(19, 15)

    def test_muhurat_2026_detected(self) -> None:
        session = is_special_session(date(2026, 11, 8))
        assert session is not None
        assert "2026" in session.name

    def test_muhurat_2027_detected(self) -> None:
        session = is_special_session(date(2027, 10, 29))
        assert session is not None
        assert "2027" in session.name

    def test_normal_day_returns_none(self) -> None:
        assert is_special_session(date(2025, 6, 15)) is None

    def test_exchange_filter_nse(self) -> None:
        session = is_special_session(date(2025, 10, 20), exchange="NSE")
        assert session is not None

    def test_exchange_filter_mcx_returns_none(self) -> None:
        """MCX does not participate in Muhurat Trading."""
        session = is_special_session(date(2025, 10, 20), exchange="MCX")
        assert session is None


# ---------------------------------------------------------------------------
# get_market_hours
# ---------------------------------------------------------------------------


class TestGetMarketHours:
    def test_normal_day_nse(self) -> None:
        open_t, close_t = get_market_hours("NSE", date(2025, 6, 15))
        assert open_t == time(9, 15)
        assert close_t == time(15, 30)

    def test_muhurat_day_nse(self) -> None:
        open_t, close_t = get_market_hours("NSE", date(2025, 10, 20))
        assert open_t == time(18, 15)
        assert close_t == time(19, 15)

    def test_muhurat_day_mcx_uses_standard(self) -> None:
        """MCX should use standard hours even on Muhurat day."""
        open_t, close_t = get_market_hours("MCX", date(2025, 10, 20))
        assert open_t == time(9, 0)
        assert close_t == time(23, 30)

    def test_unknown_exchange_raises(self) -> None:
        with pytest.raises(ValueError):
            get_market_hours("UNKNOWN", date(2025, 6, 15))

    def test_bse_on_muhurat(self) -> None:
        open_t, close_t = get_market_hours("BSE", date(2025, 10, 20))
        assert open_t == time(18, 15)

    def test_nfo_on_muhurat(self) -> None:
        open_t, close_t = get_market_hours("NFO", date(2025, 10, 20))
        assert open_t == time(18, 15)


# ---------------------------------------------------------------------------
# add_special_session
# ---------------------------------------------------------------------------


class TestAddSpecialSession:
    def test_dynamic_registration(self) -> None:
        custom_date = date(2030, 1, 1)
        # Ensure no session exists before
        assert is_special_session(custom_date) is None

        session = SpecialTradingSession(
            session_date=custom_date,
            name="New Year Special",
            open_time=time(10, 0),
            close_time=time(12, 0),
            exchanges=("NSE", "BSE"),
        )
        add_special_session(session)

        found = is_special_session(custom_date)
        assert found is not None
        assert found.name == "New Year Special"

        # Clean up
        SPECIAL_SESSIONS.remove(session)


# ---------------------------------------------------------------------------
# list_upcoming_sessions
# ---------------------------------------------------------------------------


class TestListUpcomingSessions:
    def test_returns_sorted_list(self) -> None:
        sessions = list_upcoming_sessions(from_date=date(2025, 1, 1))
        assert len(sessions) >= 1
        dates = [s.session_date for s in sessions]
        assert dates == sorted(dates)

    def test_respects_limit(self) -> None:
        sessions = list_upcoming_sessions(from_date=date(2025, 1, 1), limit=1)
        assert len(sessions) <= 1

    def test_filters_past_dates(self) -> None:
        sessions = list_upcoming_sessions(from_date=date(2028, 1, 1))
        for s in sessions:
            assert s.session_date >= date(2028, 1, 1)

    def test_from_far_future_returns_empty(self) -> None:
        sessions = list_upcoming_sessions(from_date=date(2050, 1, 1))
        assert sessions == []
