"""Strict option-chain market-data provenance contracts."""

from __future__ import annotations


import pytest

from flinttrade_core.config import Settings
from flinttrade_core.models import OptionChain, OptionChainStrike
from flinttrade_core.broker_client import BrokerClient


def _client() -> BrokerClient:
    return BrokerClient(Settings(dhan_host="http://127.0.0.1", dhan_api_key="test-key"))


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
