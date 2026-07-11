"""Canonical OpenAlgo holiday-envelope normalisation tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from flinttrade_core.openalgo_client import (
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
    ],
)
def test_rejects_non_authoritative_market_calendar_envelopes(payload: Any) -> None:
    assert not is_authoritative_market_calendar(payload, expected_year=2026)


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "success", "year": 2026, "data": []},
        {"holidays": []},
        {"data": {"holidays": ["2026-01-26"]}},
        ["2026-01-26"],
    ],
)
def test_accepts_supported_authoritative_market_calendar_envelopes(payload: Any) -> None:
    assert is_authoritative_market_calendar(payload, expected_year=2026)


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


@pytest.mark.asyncio
async def test_holidays_uses_authenticated_current_post_endpoint() -> None:
    from flinttrade_core.config import Settings
    from flinttrade_core.openalgo_client import OpenAlgoClient

    client = OpenAlgoClient(
        Settings(openalgo_host="http://127.0.0.1", openalgo_api_key="calendar-key")
    )
    response = {"status": "success", "year": 2026, "data": []}
    client._post = AsyncMock(return_value=response)  # type: ignore[method-assign]
    client._get = AsyncMock()  # type: ignore[method-assign]

    try:
        result = await client.holidays(year="2026")
    finally:
        await client.close()

    assert result == response
    client._post.assert_awaited_once_with(
        "market/holidays",
        {"apikey": "calendar-key", "year": 2026},
    )
    client._get.assert_not_awaited()


@pytest.mark.asyncio
async def test_holidays_legacy_fallback_is_opt_in_and_only_for_missing_route() -> None:
    from flinttrade_core.config import Settings
    from flinttrade_core.exceptions import APIError
    from flinttrade_core.openalgo_client import OpenAlgoClient

    client = OpenAlgoClient(
        Settings(openalgo_host="http://127.0.0.1", openalgo_api_key="calendar-key")
    )
    legacy = {"holidays": ["2026-01-26"]}
    client._post = AsyncMock(  # type: ignore[method-assign]
        side_effect=APIError(404, "route not found", "market/holidays")
    )
    client._get = AsyncMock(return_value=legacy)  # type: ignore[method-assign]

    try:
        result = await client.holidays(year="2026", allow_legacy_fallback=True)
    finally:
        await client.close()

    assert result == legacy
    client._get.assert_awaited_once_with(
        "holidays",
        params={"year": "2026"},
        headers={"X-API-KEY": "calendar-key"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403, 500])
async def test_holidays_never_downgrades_auth_or_server_failures(status_code: int) -> None:
    from flinttrade_core.config import Settings
    from flinttrade_core.exceptions import APIError
    from flinttrade_core.openalgo_client import OpenAlgoClient

    client = OpenAlgoClient(
        Settings(openalgo_host="http://127.0.0.1", openalgo_api_key="calendar-key")
    )
    failure = APIError(status_code, "calendar failed", "market/holidays")
    client._post = AsyncMock(side_effect=failure)  # type: ignore[method-assign]
    client._get = AsyncMock()  # type: ignore[method-assign]

    try:
        with pytest.raises(APIError) as error:
            await client.holidays(year="2026", allow_legacy_fallback=True)
    finally:
        await client.close()

    assert error.value is failure
    client._get.assert_not_awaited()
