"""Strict OpenAlgo option-Greek response contracts."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from flinttrade_core.config import Settings
from flinttrade_core.exceptions import APIError
from flinttrade_core.openalgo_client import OpenAlgoClient


def _client() -> OpenAlgoClient:
    return OpenAlgoClient(
        Settings(openalgo_host="http://127.0.0.1", openalgo_api_key="test-key")
    )


@pytest.mark.asyncio
async def test_portfolio_greeks_parses_documented_nested_batch_shape() -> None:
    client = _client()
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "status": "success",
            "data": [
                {
                    "status": "success",
                    "symbol": "NIFTY30JUL2625000CE",
                    "exchange": "NFO",
                    "implied_volatility": 15.25,
                    "greeks": {
                        "delta": 0.52,
                        "gamma": 0.0001,
                        "theta": -4.97,
                        "vega": 30.76,
                        "rho": 0.001,
                    },
                }
            ],
            "summary": {"total": 1, "success": 1, "failed": 0},
        }
    )
    positions = [
        {
            "symbol": "NIFTY30JUL2625000CE",
            "instrument_id": "",
            "exchange": "NFO",
            "quantity": 75.0,
            "option_type": "CE",
            "expiry": "",
            "strike_price": 25_000.0,
            "underlying": "NIFTY",
        }
    ]

    try:
        greeks = await client.portfolio_greeks(positions)
    finally:
        await client.close()

    assert greeks == [
        {
            "symbol": "NIFTY30JUL2625000CE",
            "instrument_id": "",
            "exchange": "NFO",
            "delta": 0.52,
            "vega": 30.76,
        }
    ]


@pytest.mark.asyncio
async def test_multi_option_greeks_rejects_partial_batch_failure() -> None:
    client = _client()
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "status": "success",
            "data": [
                {
                    "status": "error",
                    "symbol": "NIFTY30JUL2625000CE",
                    "exchange": "NFO",
                    "message": "quote unavailable",
                }
            ],
            "summary": {"total": 1, "success": 0, "failed": 1},
        }
    )

    try:
        with pytest.raises(APIError, match="incomplete option Greek batch"):
            await client.multi_option_greeks(
                [{"symbol": "NIFTY30JUL2625000CE", "exchange": "NFO"}]
            )
    finally:
        await client.close()
