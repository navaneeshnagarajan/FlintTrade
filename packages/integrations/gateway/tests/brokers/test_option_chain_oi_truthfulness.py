"""Broker option-chain mappings must preserve whether OI was observed."""

from __future__ import annotations

from flinttrade_gateway.brokers import dhan_mapping, upstox_mapping


def test_dhan_mapping_does_not_materialise_missing_oi_as_zero() -> None:
    mapped = dhan_mapping.to_option_chain_dict(
        "NIFTY",
        "NSE_INDEX",
        {
            "status": "success",
            "data": {
                "last_price": 24_000,
                "oc": {
                    "24000": {
                        "ce": {"last_price": 100},
                        "pe": {"last_price": 90, "oi": 0},
                    }
                },
            },
        },
    )

    row = mapped["strikes"][0]
    assert "ce_oi" not in row
    assert row["pe_oi"] == 0


def test_upstox_mapping_does_not_materialise_missing_oi_as_zero() -> None:
    mapped = upstox_mapping.to_option_chain_dict(
        "NIFTY",
        "NSE_INDEX",
        {
            "status": "success",
            "data": [
                {
                    "expiry": "2025-06-26",
                    "underlying_key": "NSE_INDEX|Nifty 50",
                    "strike_price": 24_000,
                    "underlying_spot_price": 24_000,
                    "call_options": {"market_data": {"ltp": 100}},
                    "put_options": {"market_data": {"ltp": 90, "oi": 0}},
                }
            ],
        },
        requested_expiry="2025-06-26",
        requested_instrument_key="NSE_INDEX|Nifty 50",
    )

    row = mapped["strikes"][0]
    assert "ce_oi" not in row
    assert row["pe_oi"] == 0
