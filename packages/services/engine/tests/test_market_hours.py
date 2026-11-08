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

from datetime import date, datetime, time, timedelta, timezone

import pytest

from flinttrade_engine.market_hours import (
    SPECIAL_SESSIONS,
    STANDARD_HOURS,
    SpecialTradingSession,
    add_special_session,
    derivative_contract_close,
    fo_session_state,
    get_market_hours,
    get_standard_hours,
    is_special_session,
    list_upcoming_sessions,
    muhurat_amo_note,
    muhurat_equity_phase,
    muhurat_funds_note,
    nse_cash_phase,
)

_IST = timezone(timedelta(hours=5, minutes=30))


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
        # GLOBAL_INDEX (world reference feeds) were added in the broker
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

    def test_nfo_runs_to_1540(self) -> None:
        open_t, close_t = get_standard_hours("NFO")
        assert open_t == time(9, 15)
        assert close_t == time(15, 40)


class TestNseCashPhase:
    def test_phase_boundaries(self) -> None:
        assert nse_cash_phase(10 * 60) == "continuous"
        assert nse_cash_phase(15 * 60 + 14) == "continuous"
        assert nse_cash_phase(15 * 60 + 15) == "cas"
        assert nse_cash_phase(15 * 60 + 30) == "cas"
        assert nse_cash_phase(15 * 60 + 35) == "matching"
        assert nse_cash_phase(15 * 60 + 50) == "post-close"
        assert nse_cash_phase(16 * 60) == "closed"

    def test_cas_is_not_closed_or_continuous(self) -> None:
        assert nse_cash_phase(15 * 60 + 20) == "cas"
        assert nse_cash_phase(15 * 60 + 20) != "closed"
        assert nse_cash_phase(15 * 60 + 20) != "continuous"


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
        assert session.open_time == time(14, 20)
        assert session.close_time == time(15, 40)
        assert session.pre_open_time == time(14, 5)
        assert "NFO" in session.exchanges
        assert "NSE" not in session.exchanges
        assert "CDS" not in session.exchanges
        assert "MCX" not in session.exchanges
        equity = is_special_session(date(2026, 11, 8), exchange="NSE")
        assert equity is not None
        assert equity.close_time == time(15, 30)
        assert "NSE_INDEX" in equity.exchanges
        currency = is_special_session(date(2026, 11, 8), exchange="CDS")
        commodity = is_special_session(date(2026, 11, 8), exchange="MCX")
        assert currency is not None and currency.close_time == time(15, 30)
        assert commodity is not None and commodity.close_time == time(15, 30)

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

    def test_nfo_muhurat_2026_uses_the_afternoon_window(self) -> None:
        open_t, close_t = get_market_hours("NFO", date(2026, 11, 8))
        assert open_t == time(14, 20)
        assert close_t == time(15, 40)

    def test_equity_muhurat_2026_uses_the_non_cas_close(self) -> None:
        for exchange in ("NSE", "BSE", "NSE_INDEX", "BSE_INDEX"):
            open_t, close_t = get_market_hours(exchange, date(2026, 11, 8))
            assert open_t == time(14, 20)
            assert close_t == time(15, 30)

    def test_currency_and_commodity_muhurat_2026(self) -> None:
        for exchange in ("CDS", "MCX"):
            open_t, close_t = get_market_hours(exchange, date(2026, 11, 8))
            assert open_t == time(14, 20)
            assert close_t == time(15, 30)


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


def _at(hour: int, minute: int) -> datetime:
    return datetime(2026, 11, 8, hour, minute, tzinfo=_IST)


class TestMuhurat2026Window:
    def test_open_during_the_fo_window(self) -> None:
        assert fo_session_state(_at(14, 20), SPECIAL_SESSIONS, "NFO") == "open"
        assert fo_session_state(_at(15, 0), SPECIAL_SESSIONS, "NFO") == "open"
        assert fo_session_state(_at(15, 40), SPECIAL_SESSIONS, "NFO") == "open"
        assert fo_session_state(_at(15, 0), SPECIAL_SESSIONS, "NSE") == "open"
        assert fo_session_state(_at(15, 30), SPECIAL_SESSIONS, "NSE") == "open"
        assert fo_session_state(_at(15, 40), SPECIAL_SESSIONS, "NSE") == "closed"
        assert fo_session_state(_at(15, 0), SPECIAL_SESSIONS, "CDS") == "open"
        assert fo_session_state(_at(15, 0), SPECIAL_SESSIONS, "MCX") == "open"
        assert fo_session_state(_at(15, 31), SPECIAL_SESSIONS, "CDS") == "closed"
        assert fo_session_state(_at(15, 31), SPECIAL_SESSIONS, "MCX") == "closed"

    def test_equity_phase_follows_the_bulletin(self) -> None:
        assert muhurat_equity_phase(14 * 60 + 20) == "continuous"
        assert muhurat_equity_phase(15 * 60 + 14) == "continuous"
        assert muhurat_equity_phase(15 * 60 + 16) == "non-cas"
        assert muhurat_equity_phase(15 * 60 + 20) == "cas"
        assert muhurat_equity_phase(15 * 60 + 35) == "cas"
        assert muhurat_equity_phase(15 * 60 + 36) == "closed"
        assert muhurat_equity_phase(15 * 60 + 40) == "closed"

    def test_closed_outside_the_fo_window_on_that_sunday(self) -> None:
        assert date(2026, 11, 8).weekday() == 6
        assert fo_session_state(_at(10, 0), SPECIAL_SESSIONS, "NFO") == "closed"
        assert fo_session_state(_at(14, 10), SPECIAL_SESSIONS, "NFO") == "closed"
        assert fo_session_state(_at(14, 19), SPECIAL_SESSIONS, "NFO") == "closed"
        assert fo_session_state(_at(15, 41), SPECIAL_SESSIONS, "NFO") == "closed"
        assert fo_session_state(_at(18, 30), SPECIAL_SESSIONS, "NFO") == "closed"

    def test_missing_special_session_data_fails_closed(self) -> None:
        assert fo_session_state(_at(15, 0), None, "NFO") == "absent"
        assert fo_session_state(_at(15, 0), [], "NFO") == "absent"
        assert muhurat_amo_note(_at(14, 0), []) is None
        assert muhurat_funds_note(_at(15, 0), []) is None

    def test_amo_and_funds_notes_follow_the_window(self) -> None:
        early = muhurat_amo_note(_at(14, 0), SPECIAL_SESSIONS)
        assert early is not None
        assert "14:02 IST, 3 minutes before pre-open" in early
        assert "14:16 IST, 4 minutes before the 14:20 normal open" in early
        assert "14:03 IST, 2 minutes before the 14:05 equity pre-open" in early

        at_pre_cutoff = muhurat_amo_note(_at(14, 2), SPECIAL_SESSIONS)
        assert at_pre_cutoff is not None
        assert "3 minutes before pre-open" in at_pre_cutoff

        after_pre_cutoff = muhurat_amo_note(_at(14, 3), SPECIAL_SESSIONS)
        assert after_pre_cutoff is not None
        assert "pre-open have closed" in after_pre_cutoff
        assert "until 14:16 IST" in after_pre_cutoff

        normal_only = muhurat_amo_note(_at(14, 10), SPECIAL_SESSIONS)
        assert normal_only is not None
        assert "Equity after-market orders for the Muhurat session have closed" in normal_only
        assert "until 14:16 IST" in normal_only

        closed_collection = muhurat_amo_note(_at(14, 17), SPECIAL_SESSIONS)
        assert closed_collection == "After-market orders for the Muhurat session have closed. F&O opens at 14:20 IST."

        assert muhurat_amo_note(_at(15, 0), SPECIAL_SESSIONS) is None
        assert muhurat_amo_note(_at(16, 0), SPECIAL_SESSIONS) is None

        funds = muhurat_funds_note(_at(15, 0), SPECIAL_SESSIONS)
        assert funds is not None
        assert "6 November 2026" in funds
        assert "not included in available funds" in funds
        assert "settlement holiday" in funds
        assert muhurat_funds_note(_at(14, 0), SPECIAL_SESSIONS) is None
        assert muhurat_funds_note(_at(15, 41), SPECIAL_SESSIONS) is None


# ---------------------------------------------------------------------------
# Schedule from 7 Dec 2026 (NSE/CMTR/77355, NSE/FAOP/77356)
# ---------------------------------------------------------------------------


class TestCasRevisionBoundary:
    def test_dec_6_keeps_the_current_cash_phases(self) -> None:
        on = date(2026, 12, 6)
        assert nse_cash_phase(15 * 60 + 14, on=on) == "continuous"
        assert nse_cash_phase(15 * 60 + 15, on=on) == "cas"
        assert nse_cash_phase(15 * 60 + 34, on=on) == "cas"
        assert nse_cash_phase(15 * 60 + 35, on=on) == "matching"
        assert nse_cash_phase(15 * 60 + 49, on=on) == "matching"
        assert nse_cash_phase(15 * 60 + 50, on=on) == "post-close"

    def test_dec_7_uses_the_revised_cash_phases(self) -> None:
        on = date(2026, 12, 7)
        assert nse_cash_phase(15 * 60 + 29, on=on) == "continuous"
        assert nse_cash_phase(15 * 60 + 30, on=on) == "cas"
        assert nse_cash_phase(15 * 60 + 39, on=on) == "cas"
        assert nse_cash_phase(15 * 60 + 40, on=on) == "matching"
        assert nse_cash_phase(15 * 60 + 44, on=on) == "matching"
        assert nse_cash_phase(15 * 60 + 45, on=on) == "transition"
        assert nse_cash_phase(15 * 60 + 49, on=on) == "transition"
        assert nse_cash_phase(15 * 60 + 50, on=on) == "post-close"
        assert nse_cash_phase(16 * 60, on=on) == "closed"

    def test_nfo_close_moves_on_dec_7_and_bfo_does_not(self) -> None:
        assert get_market_hours("NFO", date(2026, 12, 6)) == (time(9, 15), time(15, 40))
        assert get_market_hours("NFO", date(2026, 12, 7)) == (time(9, 15), time(15, 45))
        assert get_market_hours("BFO", date(2026, 12, 6)) == (time(9, 15), time(15, 40))
        assert get_market_hours("BFO", date(2026, 12, 7)) == (time(9, 15), time(15, 45))

    def test_expiring_index_contract_closes_at_1530(self) -> None:
        calendar = [date(2026, 12, 10), date(2026, 12, 17)]
        assert derivative_contract_close(
            "NFO",
            date(2026, 12, 10),
            symbol="NIFTY10DEC2624000CE",
            expiry_calendar=calendar,
        ) == time(15, 30)
        assert derivative_contract_close(
            "NFO",
            date(2026, 12, 10),
            symbol="NIFTY17DEC2624000CE",
            expiry_calendar=calendar,
        ) == time(15, 45)

    def test_stock_derivatives_run_until_1545_including_expiry_day(self) -> None:
        calendar = [date(2026, 12, 10)]
        assert derivative_contract_close(
            "NFO",
            date(2026, 12, 10),
            symbol="RELIANCE10DEC26FUT",
            expiry_calendar=calendar,
        ) == time(15, 45)
        assert derivative_contract_close(
            "NFO",
            date(2026, 12, 8),
            symbol="RELIANCE10DEC26FUT",
            expiry_calendar=calendar,
        ) == time(15, 45)

    def test_unknown_index_expiry_fails_closed(self) -> None:
        session = date(2026, 12, 10)
        symbol = "NIFTY10DEC2624000CE"
        assert derivative_contract_close("NFO", session, symbol=symbol, expiry_calendar=None) == time(15, 30)
        assert derivative_contract_close(
            "NFO",
            session,
            symbol="NIFTY17DEC2624000CE",
            expiry_calendar=None,
        ) == time(15, 45)
        assert derivative_contract_close("NFO", session, symbol=symbol, expiry_calendar=[]) is None
        assert (
            derivative_contract_close(
                "NFO",
                session,
                symbol=symbol,
                expiry_calendar=[date(2026, 12, 17)],
            )
            is None
        )
        assert (
            derivative_contract_close(
                "NFO",
                session,
                symbol="NIFTY",
                expiry_calendar=[date(2026, 12, 10)],
            )
            is None
        )
        assert derivative_contract_close("NFO", session, symbol="NOT A CONTRACT") is None
        assert (
            derivative_contract_close(
                "NFO",
                date(2026, 12, 11),
                symbol="NIFTY10DEC2624000CE",
            )
            is None
        )
        assert (
            derivative_contract_close(
                "NFO",
                date(2026, 12, 11),
                symbol="NIFTY10DEC2624000CE",
                risk_increasing=False,
            )
            == time(15, 45)
        )

    def test_every_listed_index_closes_at_1530_on_its_expiry_day(self) -> None:
        from flinttrade_core.symbol_utils import INDEX_UNDERLYINGS, detect_instrument_type

        session = date(2026, 12, 10)
        earlier = date(2026, 12, 9)
        for name in sorted(INDEX_UNDERLYINGS):
            assert detect_instrument_type(name) == "index"
            symbol = f"{name}10DEC26FUT"
            assert derivative_contract_close("NFO", session, symbol=symbol) == time(15, 30), name
            assert derivative_contract_close("BFO", session, symbol=symbol) == time(15, 30), name
            assert derivative_contract_close("NFO", earlier, symbol=symbol) == time(15, 45), name

    def test_bfo_uses_the_same_expiry_close_as_nse(self) -> None:
        assert derivative_contract_close(
            "BFO",
            date(2026, 12, 10),
            symbol="SENSEX10DEC2680000CE",
            expiry_calendar=[date(2026, 12, 10)],
        ) == time(15, 30)
        assert derivative_contract_close(
            "BFO",
            date(2026, 12, 10),
            symbol="RELIANCE10DEC26FUT",
            expiry_calendar=[date(2026, 12, 10)],
        ) == time(15, 45)
        assert derivative_contract_close(
            "BFO",
            date(2026, 12, 4),
            symbol="SENSEX04DEC2680000CE",
            expiry_calendar=[date(2026, 12, 4)],
        ) == time(15, 40)

    def test_muhurat_still_overrides(self) -> None:
        open_t, close_t = get_market_hours("NFO", date(2026, 11, 8))
        assert open_t == time(14, 20)
        assert close_t == time(15, 40)
        assert derivative_contract_close(
            "NFO",
            date(2026, 11, 8),
            symbol="NIFTY08NOV2624000CE",
            expiry_calendar=[date(2026, 11, 8)],
        ) == time(15, 40)
        assert nse_cash_phase(15 * 60 + 20, on=date(2026, 11, 8)) == "cas"

    def test_index_expiry_before_the_revision_does_not_close_early(self) -> None:
        assert derivative_contract_close(
            "NFO",
            date(2026, 12, 4),
            symbol="NIFTY04DEC2624000CE",
            expiry_calendar=[date(2026, 12, 4)],
        ) == time(15, 40)
