"""Canonical native broker holiday-envelope normalisation tests."""

from __future__ import annotations

from typing import Any

import pytest

from flinttrade_core.broker_client import (
    is_authoritative_market_calendar,
    normalise_holiday_dates,
    normalise_market_calendar,
)


pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("payload", "exchange", "expected"),
    [
        (["2026-01-26", "2026-08-15"], "NSE", ["2026-01-26", "2026-08-15"]),
        ({"holidays": ["2026-01-26"]}, "NSE", ["2026-01-26"]),
        ({"data": {"holidays": ["2026-03-04"]}}, "NSE", ["2026-03-04"]),
        ({"data": {"MCX": ["2026-10-20"]}}, "MCX", ["2026-10-20"]),
        ({"NSE": [{"date": "2026-04-14"}]}, "NSE", ["2026-04-14"]),
        (
            {"holidays": [{"holiday_date": "2026-12-25T00:00:00+05:30"}]},
            "NSE",
            ["2026-12-25"],
        ),
    ],
)
def test_normalises_supported_holiday_payloads(
    payload: Any,
    exchange: str,
    expected: list[str],
) -> None:
    assert normalise_holiday_dates(payload, exchange=exchange) == expected


def test_rejects_invalid_dates_and_unrelated_envelope_metadata() -> None:
    payload = {
        "status": "success",
        "holidays": ["not-a-date", "2026-02-30", {"message": "closed"}],
    }

    assert normalise_holiday_dates(payload) == []


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "error", "year": 2026, "data": []},
        {"status": "success", "year": 2025, "data": []},
        {"status": "success", "year": 2026, "data": "not-a-calendar"},
        {
            "status": "success",
            "year": 2026,
            "data": [{"date": "not-a-date", "holiday_type": "TRADING_HOLIDAY"}],
        },
        {
            "status": "success",
            "year": 2026,
            "data": [
                {
                    "date": "2026-01-26",
                    "holiday_type": "TRADING_HOLIDAY",
                    "closed_exchanges": "NSE",
                }
            ],
        },
        {"status": "success", "year": 2026, "data": []},
        {"status": "success", "year": 2026, "data": {}},
        {"holidays": []},
        {"status": "success", "year": 2026, "data": ["2025-01-26"]},
        {
            "status": "success",
            "year": 2026,
            "data": [{"date": "2025-01-26", "holiday_type": "TRADING_HOLIDAY"}],
        },
        ["2025-01-26"],
        {
            "status": "success",
            "year": 2026,
            "data": [
                {
                    "date": "2026-01-26",
                    "holiday_type": "SPECIAL_SESSION",
                    "closed_exchanges": [],
                    "open_exchanges": [
                        {"exchange": "NSE", "start_time": "bad", "end_time": 1_772_562_300_000},
                    ],
                }
            ],
        },
        {
            "status": "success",
            "year": 2026,
            "data": [
                {
                    "date": "2026-01-26",
                    "holiday_type": "SPECIAL_SESSION",
                    "closed_exchanges": [],
                    "open_exchanges": [
                        {
                            "exchange": "NSE",
                            "start_time": 1_772_562_300_000,
                            "end_time": 1_772_537_400_000,
                        },
                    ],
                }
            ],
        },
    ],
)
def test_rejects_non_authoritative_market_calendar_envelopes(payload: Any) -> None:
    assert not is_authoritative_market_calendar(payload, expected_year=2026)


@pytest.mark.parametrize(
    "payload",
    [
        {"data": {"holidays": ["2026-01-26"]}},
        ["2026-01-26"],
    ],
)
def test_accepts_supported_authoritative_market_calendar_envelopes(payload: Any) -> None:
    assert is_authoritative_market_calendar(payload, expected_year=2026)


def test_clock_time_special_session_is_authoritative() -> None:
    payload = {
        "status": "success",
        "year": 2026,
        "data": [
            {
                "date": "2026-11-08",
                "holiday_type": "SPECIAL_SESSION",
                "closed_exchanges": ["NSE"],
                "open_exchanges": [
                    {"exchange": "NSE", "start_time": "18:00", "end_time": "19:00"},
                ],
            }
        ],
    }

    assert is_authoritative_market_calendar(payload, expected_year=2026)
    rows = normalise_market_calendar(payload)
    assert rows[0]["open_exchanges"] == [
        {"exchange": "NSE", "start_time": "18:00", "end_time": "19:00"},
    ]


def test_cross_midnight_clock_session_is_authoritative() -> None:
    payload = {
        "status": "success",
        "year": 2026,
        "data": [
            {
                "date": "2026-04-17",
                "holiday_type": "SPECIAL_SESSION",
                "closed_exchanges": ["MCX"],
                "open_exchanges": [
                    {"exchange": "MCX", "start_time": "18:00", "end_time": "00:15"},
                ],
            }
        ],
    }

    assert is_authoritative_market_calendar(payload, expected_year=2026)
    assert normalise_market_calendar(payload)[0]["open_exchanges"][0]["end_time"] == "00:15"


def test_malformed_declared_session_closes_that_exchange() -> None:
    rows = normalise_market_calendar(
        {
            "status": "success",
            "year": 2026,
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
            ],
        }
    )

    assert rows[0]["closed_exchanges"] == ["MCX", "NSE"]
    assert rows[0]["open_exchanges"] == []


def test_incomplete_trading_holiday_row_fails_closed_for_all_exchanges() -> None:
    rows = normalise_market_calendar(
        {
            "status": "success",
            "year": 2026,
            "data": [
                {
                    "date": "2026-01-26",
                    "holiday_type": "TRADING_HOLIDAY",
                    "closed_exchanges": [],
                    "open_exchanges": [],
                }
            ],
        }
    )

    assert rows[0]["closed_exchanges"] == ["*"]
    assert normalise_holiday_dates(rows, exchange="NSE") == ["2026-01-26"]


def test_current_calendar_preserves_exchange_closures_and_open_sessions() -> None:
    payload = {
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
                        "start_time": 1_772_537_400_000,
                        "end_time": 1_772_562_300_000,
                    }
                ],
            },
            {
                "date": "2026-03-31",
                "description": "Settlement only",
                "holiday_type": "SETTLEMENT_HOLIDAY",
                "closed_exchanges": [],
                "open_exchanges": [],
            },
        ],
    }

    rows = normalise_market_calendar(payload)

    assert rows[0]["closed_exchanges"] == ["BCD", "BFO", "BSE", "CDS", "NFO", "NSE"]
    assert rows[0]["open_exchanges"] == [
        {
            "exchange": "MCX",
            "start_time": 1_772_537_400_000,
            "end_time": 1_772_562_300_000,
        }
    ]
    assert normalise_holiday_dates(payload, exchange="NSE") == ["2026-03-03"]
    assert normalise_holiday_dates(payload, exchange="NSE_INDEX") == ["2026-03-03"]
    assert normalise_holiday_dates(payload, exchange="MCX") == []
