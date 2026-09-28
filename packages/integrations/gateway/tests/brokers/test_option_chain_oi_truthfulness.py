"""Broker option-chain mappings must preserve whether OI was observed."""

from __future__ import annotations

from flinttrade_gateway.brokers import dhan_mapping, kotakneo_mapping, upstox_mapping


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


def test_kotak_mapping_preserves_absent_null_and_zero_oi() -> None:
    mapped = kotakneo_mapping.from_kotak_option_chain(
        {
            "data": {
                "common_data": {
                    "unlSymbol": "NIFTY",
                    "exSeg": "nse_fo",
                    "expiryDt": "2026-06-23",
                },
                "call": [
                    {
                        "instrument": {
                            "neoSymbol": "nse_fo|100",
                            "optionType": "CE",
                            "strikePrice": "22000",
                        }
                    },
                    {
                        "instrument": {
                            "neoSymbol": "nse_fo|101",
                            "optionType": "CE",
                            "strikePrice": "22100",
                        },
                        "openInterest": {"current": None},
                    },
                    {
                        "instrument": {
                            "neoSymbol": "nse_fo|102",
                            "optionType": "CE",
                            "strikePrice": "22200",
                        },
                        "openInterest": {"current": 0},
                    },
                ],
                "put": [],
            }
        },
        underlying="NIFTY",
        exchange="NSE_INDEX",
        sdk_exchange="nse_fo",
        requested_expiry="2026-06-23",
    )

    absent, explicit_null, zero = mapped["strikes"]
    assert "ce_oi" not in absent
    assert explicit_null["ce_oi"] is None
    assert zero["ce_oi"] == 0
