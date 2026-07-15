"""Strict option-chain market-data provenance contracts."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from flinttrade_core.config import Settings
from flinttrade_core.models import OptionChain, OptionChainStrike
from flinttrade_core.openalgo_client import OpenAlgoClient


def _client() -> OpenAlgoClient:
    return OpenAlgoClient(
        Settings(openalgo_host="http://127.0.0.1", openalgo_api_key="test-key")
    )


def test_option_chain_strike_preserves_missing_oi() -> None:
    strike = OptionChainStrike(strike_price=24_000)

    assert strike.ce_oi is None
    assert strike.pe_oi is None


def test_option_chain_preserves_explicit_expiry_identity() -> None:
    chain = OptionChain(expiry="30JUL26", expiry_date="2026-07-30")

    assert chain.expiry == "30JUL26"
    assert chain.expiry_date == "2026-07-30"
    assert chain.model_dump(exclude_unset=True) == {
        "expiry": "30JUL26",
        "expiry_date": "2026-07-30",
    }


@pytest.mark.parametrize("strike", [True, False])
def test_option_chain_strike_rejects_boolean_identity(strike: bool) -> None:
    with pytest.raises(ValueError, match="strike_price must be numeric"):
        OptionChainStrike(strike_price=strike)


@pytest.mark.parametrize("oi", [True, False, -1, float("nan"), float("inf")])
def test_option_chain_strike_rejects_non_authoritative_oi(oi: object) -> None:
    with pytest.raises(ValueError, match="OI must be a finite non-negative number"):
        OptionChainStrike(strike_price=24_000, ce_oi=oi)


@pytest.mark.asyncio
async def test_openalgo_option_chain_does_not_materialise_missing_oi_as_zero() -> None:
    client = _client()
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "status": "success",
            "data": {
                "underlying": "NIFTY",
                "exchange": "NSE_INDEX",
                "expiry": "2026-07-30",
                "expiry_date": "30JUL26",
                "spot_price": 24_000,
                "chain": [
                    {
                        "strike": 24_000,
                        "ce": {"ltp": 100},
                        "pe": {"ltp": 90, "oi": 0},
                    }
                ],
            },
        }
    )

    try:
        chain = await client.option_chain("NIFTY", "NSE_INDEX", "2026-07-30")
    finally:
        await client.close()

    assert chain.strikes[0].ce_oi is None
    assert chain.strikes[0].pe_oi == 0
    assert chain.expiry == "2026-07-30"
    assert chain.expiry_date == "30JUL26"


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed_row", ["bad-row", 7, None, []])
async def test_openalgo_option_chain_rejects_the_whole_payload_on_a_non_object_row(
    malformed_row: object,
) -> None:
    client = _client()
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "status": "success",
            "data": {
                "underlying": "NIFTY",
                "exchange": "NSE_INDEX",
                "expiry_date": "30JUL26",
                "spot_price": 24_000,
                "chain": [
                    {"strike": 24_000, "ce": {"ltp": 100}, "pe": {"ltp": 90}},
                    malformed_row,
                ],
            },
        }
    )

    try:
        with pytest.raises(ValueError, match="option-chain source row is not an object"):
            await client.option_chain("NIFTY", "NSE_INDEX", "2026-07-30")
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "identity",
    [
        {},
        {"expiry_date": "31JUL26"},
        {"expiry": "30JUL26", "expiry_date": "31JUL26"},
        {"expiry_date": True},
    ],
)
async def test_openalgo_option_chain_rejects_missing_or_conflicting_expiry_identity(
    identity: dict[str, object],
) -> None:
    client = _client()
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "status": "success",
            "data": {
                "underlying": "NIFTY",
                "exchange": "NSE_INDEX",
                "spot_price": 24_000,
                "chain": [
                    {"strike": 24_000, "ce": {"ltp": 100}, "pe": {"ltp": 90}},
                ],
                **identity,
            },
        }
    )

    try:
        with pytest.raises(ValueError, match="expiry identity"):
            await client.option_chain("NIFTY", "NSE_INDEX", "2026-07-30")
    finally:
        await client.close()
