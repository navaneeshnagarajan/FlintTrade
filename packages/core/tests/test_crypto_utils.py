"""Tests for CryptoUtils — Delta Exchange trading utilities.

Covers exchange identification, symbol metadata lookups, price formatting,
fee retrieval, order rounding, and convenience list helpers.
"""

import pytest

from packages.core.src.crypto_utils import (
    CRYPTO_PAIRS,
    CryptoUtils,
)


# ===========================================================================
# is_crypto_exchange()
# ===========================================================================


class TestIsCryptoExchange:
    """Exchange identifier detection."""

    def test_delta_uppercase_is_crypto(self):
        assert CryptoUtils.is_crypto_exchange("DELTA") is True

    def test_delta_lowercase_is_crypto(self):
        assert CryptoUtils.is_crypto_exchange("delta") is True

    def test_deltaexchange_is_crypto(self):
        assert CryptoUtils.is_crypto_exchange("DELTAEXCHANGE") is True

    def test_crypto_alias_is_crypto(self):
        assert CryptoUtils.is_crypto_exchange("CRYPTO") is True

    def test_nse_is_not_crypto(self):
        assert CryptoUtils.is_crypto_exchange("NSE") is False

    def test_bse_is_not_crypto(self):
        assert CryptoUtils.is_crypto_exchange("BSE") is False

    def test_mcx_is_not_crypto(self):
        assert CryptoUtils.is_crypto_exchange("MCX") is False

    def test_empty_string_is_not_crypto(self):
        assert CryptoUtils.is_crypto_exchange("") is False

    def test_mixed_case_deltaexchange(self):
        assert CryptoUtils.is_crypto_exchange("DeltaExchange") is True


# ===========================================================================
# is_crypto_pair()
# ===========================================================================


class TestIsCryptoPair:
    """Pair membership check."""

    def test_known_usd_pair(self):
        assert CryptoUtils.is_crypto_pair("BTCUSD") is True

    def test_known_inr_pair(self):
        assert CryptoUtils.is_crypto_pair("ETHINR") is True

    def test_case_insensitive(self):
        assert CryptoUtils.is_crypto_pair("btcusd") is True
        assert CryptoUtils.is_crypto_pair("EthInr") is True

    def test_equity_symbol_is_not_crypto(self):
        assert CryptoUtils.is_crypto_pair("RELIANCE") is False

    def test_unknown_pair(self):
        assert CryptoUtils.is_crypto_pair("DOGEUSD") is False


# ===========================================================================
# get_pair_info()
# ===========================================================================


class TestGetPairInfo:
    """Full metadata retrieval."""

    def test_btcusd_info(self):
        info = CryptoUtils.get_pair_info("BTCUSD")
        assert info is not None
        assert info.base == "BTC"
        assert info.quote == "USD"
        assert info.lot_size == 0.001
        assert info.tick_size == 0.5

    def test_ethinr_info(self):
        info = CryptoUtils.get_pair_info("ETHINR")
        assert info is not None
        assert info.base == "ETH"
        assert info.quote == "INR"

    def test_unknown_returns_none(self):
        assert CryptoUtils.get_pair_info("DOGEUSD") is None

    def test_case_insensitive(self):
        assert CryptoUtils.get_pair_info("btcusd") is not None


# ===========================================================================
# get_lot_size()
# ===========================================================================


class TestGetLotSize:
    """Lot size lookup."""

    def test_btcusd_lot_size(self):
        assert CryptoUtils.get_lot_size("BTCUSD") == 0.001

    def test_ethusd_lot_size(self):
        assert CryptoUtils.get_lot_size("ETHUSD") == 0.01

    def test_btcinr_lot_size(self):
        assert CryptoUtils.get_lot_size("BTCINR") == 0.0001

    def test_xrpusd_lot_size(self):
        assert CryptoUtils.get_lot_size("XRPUSD") == 1.0

    def test_case_insensitive(self):
        assert CryptoUtils.get_lot_size("btcusd") == 0.001

    def test_unknown_symbol_returns_btc_default(self):
        assert CryptoUtils.get_lot_size("DOGEUSD") == 0.001


# ===========================================================================
# get_tick_size()
# ===========================================================================


class TestGetTickSize:
    """Tick size lookup."""

    def test_btcusd_tick_size(self):
        assert CryptoUtils.get_tick_size("BTCUSD") == 0.5

    def test_ethusd_tick_size(self):
        assert CryptoUtils.get_tick_size("ETHUSD") == 0.05

    def test_xrpusd_tick_size(self):
        assert CryptoUtils.get_tick_size("XRPUSD") == 0.0001

    def test_unknown_symbol_returns_default(self):
        assert CryptoUtils.get_tick_size("DOGEUSD") == 0.01


# ===========================================================================
# format_crypto_price()
# ===========================================================================


class TestFormatCryptoPrice:
    """Price formatting with quote-currency decimal precision."""

    def test_usd_pair_two_decimal_places(self):
        assert CryptoUtils.format_crypto_price(67432.5, "BTCUSD") == "67432.50"

    def test_inr_pair_two_decimal_places(self):
        assert CryptoUtils.format_crypto_price(5000000.0, "BTCINR") == "5000000.00"

    def test_small_eth_price(self):
        assert CryptoUtils.format_crypto_price(0.05, "ETHUSD") == "0.05"

    def test_zero_price(self):
        assert CryptoUtils.format_crypto_price(0.0, "BTCUSD") == "0.00"

    def test_unknown_symbol_falls_back_to_two_dp(self):
        assert CryptoUtils.format_crypto_price(1.23456, "DOGEUSD") == "1.23"

    def test_negative_price_raises(self):
        with pytest.raises(ValueError, match="negative"):
            CryptoUtils.format_crypto_price(-1.0, "BTCUSD")

    def test_case_insensitive(self):
        assert CryptoUtils.format_crypto_price(100.0, "btcusd") == "100.00"


# ===========================================================================
# get_trading_fee()
# ===========================================================================


class TestGetTradingFee:
    """Fee schedule retrieval."""

    def test_btcusd_standard_fees(self):
        fees = CryptoUtils.get_trading_fee("BTCUSD")
        assert fees == {"maker": 0.0002, "taker": 0.0005}

    def test_ethusd_standard_fees(self):
        fees = CryptoUtils.get_trading_fee("ETHUSD")
        assert fees["maker"] == 0.0002
        assert fees["taker"] == 0.0005

    def test_unknown_symbol_returns_standard_tier(self):
        fees = CryptoUtils.get_trading_fee("DOGEUSD")
        assert fees == {"maker": 0.0002, "taker": 0.0005}

    def test_taker_fee_greater_than_maker_fee(self):
        fees = CryptoUtils.get_trading_fee("BTCUSD")
        assert fees["taker"] > fees["maker"]

    def test_all_pairs_have_fees(self):
        for symbol in CRYPTO_PAIRS:
            fees = CryptoUtils.get_trading_fee(symbol)
            assert "maker" in fees
            assert "taker" in fees


# ===========================================================================
# round_to_lot_size()
# ===========================================================================


class TestRoundToLotSize:
    """Quantity snapping to nearest valid lot increment."""

    def test_exact_lot_unchanged(self):
        assert CryptoUtils.round_to_lot_size(0.003, "BTCUSD") == pytest.approx(0.003)

    def test_rounds_down_to_lot(self):
        # 0.0037 → floor to 0.003 (lot_size=0.001)
        result = CryptoUtils.round_to_lot_size(0.0037, "BTCUSD")
        assert result == pytest.approx(0.003)

    def test_large_quantity(self):
        result = CryptoUtils.round_to_lot_size(1.2345, "BTCUSD")
        assert result == pytest.approx(1.234)

    def test_xrp_whole_lot(self):
        # lot_size=1.0, so 5.9 → 5
        result = CryptoUtils.round_to_lot_size(5.9, "XRPUSD")
        assert result == pytest.approx(5.0)

    def test_zero_quantity_raises(self):
        with pytest.raises(ValueError, match="positive"):
            CryptoUtils.round_to_lot_size(0.0, "BTCUSD")

    def test_negative_quantity_raises(self):
        with pytest.raises(ValueError, match="positive"):
            CryptoUtils.round_to_lot_size(-1.0, "BTCUSD")


# ===========================================================================
# round_to_tick_size()
# ===========================================================================


class TestRoundToTickSize:
    """Price snapping to nearest valid tick increment."""

    def test_exact_tick_unchanged(self):
        assert CryptoUtils.round_to_tick_size(67432.5, "BTCUSD") == pytest.approx(67432.5)

    def test_rounds_to_nearest_tick(self):
        # tick_size=0.5 for BTCUSD: 67432.3 → 67432.5
        result = CryptoUtils.round_to_tick_size(67432.3, "BTCUSD")
        assert result == pytest.approx(67432.5)

    def test_eth_tick_rounding(self):
        # tick_size=0.05 for ETHUSD: 3200.07 → 3200.05
        result = CryptoUtils.round_to_tick_size(3200.07, "ETHUSD")
        assert result == pytest.approx(3200.05)

    def test_zero_price_raises(self):
        with pytest.raises(ValueError, match="positive"):
            CryptoUtils.round_to_tick_size(0.0, "BTCUSD")

    def test_negative_price_raises(self):
        with pytest.raises(ValueError, match="positive"):
            CryptoUtils.round_to_tick_size(-100.0, "BTCUSD")


# ===========================================================================
# all_pairs() / usd_pairs() / inr_pairs()
# ===========================================================================


class TestConvenienceLists:
    """Catalogue enumeration helpers."""

    def test_all_pairs_returns_sorted_list(self):
        pairs = CryptoUtils.all_pairs()
        assert pairs == sorted(pairs)
        assert "BTCUSD" in pairs
        assert "ETHINR" in pairs

    def test_usd_pairs_all_quote_usd(self):
        for symbol in CryptoUtils.usd_pairs():
            info = CRYPTO_PAIRS[symbol]
            assert info.quote == "USD"

    def test_inr_pairs_all_quote_inr(self):
        for symbol in CryptoUtils.inr_pairs():
            info = CRYPTO_PAIRS[symbol]
            assert info.quote == "INR"

    def test_usd_and_inr_are_disjoint(self):
        assert set(CryptoUtils.usd_pairs()).isdisjoint(set(CryptoUtils.inr_pairs()))

    def test_usd_plus_inr_equals_all(self):
        all_set = set(CryptoUtils.all_pairs())
        combined = set(CryptoUtils.usd_pairs()) | set(CryptoUtils.inr_pairs())
        assert combined == all_set


# ===========================================================================
# CRYPTO_PAIRS catalogue integrity
# ===========================================================================


class TestCataloguIntegrity:
    """Data completeness checks across the full catalogue."""

    def test_all_pairs_have_positive_lot_size(self):
        for symbol, info in CRYPTO_PAIRS.items():
            assert info.lot_size > 0, f"{symbol}: lot_size must be positive"

    def test_all_pairs_have_positive_tick_size(self):
        for symbol, info in CRYPTO_PAIRS.items():
            assert info.tick_size > 0, f"{symbol}: tick_size must be positive"

    def test_all_pairs_have_description(self):
        for symbol, info in CRYPTO_PAIRS.items():
            assert info.description, f"{symbol}: description must not be empty"

    def test_taker_fee_not_negative(self):
        for symbol, info in CRYPTO_PAIRS.items():
            assert info.taker_fee >= 0, f"{symbol}: taker_fee must not be negative"

    def test_btcusd_in_catalogue(self):
        assert "BTCUSD" in CRYPTO_PAIRS

    def test_btcinr_in_catalogue(self):
        assert "BTCINR" in CRYPTO_PAIRS

    def test_ethusd_in_catalogue(self):
        assert "ETHUSD" in CRYPTO_PAIRS

    def test_ethinr_in_catalogue(self):
        assert "ETHINR" in CRYPTO_PAIRS
