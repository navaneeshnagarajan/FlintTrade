"""Canonical OpenAlgo holiday-envelope normalisation tests."""

from __future__ import annotations

from typing import Any

import pytest

from flinttrade_core.openalgo_client import normalise_holiday_dates


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
