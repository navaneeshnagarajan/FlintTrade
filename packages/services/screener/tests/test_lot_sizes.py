"""Tests for dynamic lot size resolver.

Covers the built-in fallback table, cache behaviour, live-fetch path
(mocked), and the synchronous helper function.

No network calls are made — the OpenAlgoClient is mocked throughout.
Run with: python -m pytest packages/services/screener/tests/test_lot_sizes.py -v --import-mode=importlib
"""

from __future__ import annotations

from unittest.mock import MagicMock


from flinttrade_screener.lot_sizes import (
    FALLBACK_LOT_SIZES,
    LotSizeResolver,
    get_lot_size_sync,
)


# ---------------------------------------------------------------------------
# Fallback table
# ---------------------------------------------------------------------------


class TestFallbackTable:
    def test_nifty_lot_size_is_75(self):
        assert FALLBACK_LOT_SIZES["NIFTY"] == 75

    def test_banknifty_lot_size_is_30(self):
        assert FALLBACK_LOT_SIZES["BANKNIFTY"] == 30

    def test_finnifty_lot_size_is_40(self):
        assert FALLBACK_LOT_SIZES["FINNIFTY"] == 40

    def test_sensex_lot_size_is_20(self):
        assert FALLBACK_LOT_SIZES["SENSEX"] == 20

    def test_gold_mcx_lot_size_is_100(self):
        assert FALLBACK_LOT_SIZES["GOLD"] == 100

    def test_crudeoil_lot_size_is_100(self):
        assert FALLBACK_LOT_SIZES["CRUDEOIL"] == 100

    def test_usdinr_lot_size(self):
        assert FALLBACK_LOT_SIZES["USDINR"] == 1_000

    def test_all_values_are_positive_ints(self):
        for sym, lot in FALLBACK_LOT_SIZES.items():
            assert isinstance(lot, int), f"{sym} lot size must be int"
            assert lot >= 1, f"{sym} lot size must be >= 1"


# ---------------------------------------------------------------------------
# get_lot_size_sync (synchronous, fallback-only)
# ---------------------------------------------------------------------------


class TestGetLotSizeSync:
    def test_known_symbol_case_insensitive(self):
        assert get_lot_size_sync("nifty") == FALLBACK_LOT_SIZES["NIFTY"]
        assert get_lot_size_sync("NIFTY") == FALLBACK_LOT_SIZES["NIFTY"]
        assert get_lot_size_sync("Nifty") == FALLBACK_LOT_SIZES["NIFTY"]

    def test_unknown_symbol_returns_1(self):
        assert get_lot_size_sync("UNKNOWN_XYZ") == 1

    def test_empty_symbol_returns_1(self):
        assert get_lot_size_sync("") == 1

    def test_whitespace_stripped(self):
        assert get_lot_size_sync("  NIFTY  ") == FALLBACK_LOT_SIZES["NIFTY"]

    def test_exchange_arg_accepted_but_ignored(self):
        # exchange is reserved for future use but must not raise
        result = get_lot_size_sync("BANKNIFTY", exchange="NFO")
        assert result == FALLBACK_LOT_SIZES["BANKNIFTY"]


# ---------------------------------------------------------------------------
# LotSizeResolver — cache hit
# ---------------------------------------------------------------------------


class TestLotSizeResolverCache:
    def _make_resolver(self, instruments: list[dict]) -> LotSizeResolver:
        client = MagicMock()
        client.instruments.return_value = instruments
        return LotSizeResolver(client, cache_ttl=3600)

    def test_first_call_fetches_from_openalgo(self):
        instruments = [{"symbol": "NIFTY", "exchange": "NFO", "lot_size": 75}]
        resolver = self._make_resolver(instruments)
        lot = resolver.get_lot_size("NIFTY", "NFO")
        assert lot == 75
        resolver._client.instruments.assert_called_once_with(exchange="NFO")

    def test_second_call_uses_cache(self):
        instruments = [{"symbol": "NIFTY", "exchange": "NFO", "lot_size": 75}]
        resolver = self._make_resolver(instruments)
        resolver.get_lot_size("NIFTY", "NFO")
        resolver.get_lot_size("NIFTY", "NFO")
        # instruments() must have been called only once (cache hit on second call)
        assert resolver._client.instruments.call_count == 1

    def test_cache_size_increments(self):
        instruments = [
            {"symbol": "NIFTY", "exchange": "NFO", "lot_size": 75},
            {"symbol": "BANKNIFTY", "exchange": "NFO", "lot_size": 30},
        ]
        resolver = self._make_resolver(instruments)
        resolver.get_lot_size("NIFTY", "NFO")
        assert resolver.cache_size >= 1

    def test_stale_cache_refetches(self):
        """After TTL expiry, the resolver must re-fetch from OpenAlgo."""
        instruments = [{"symbol": "NIFTY", "exchange": "NFO", "lot_size": 75}]
        resolver = self._make_resolver(instruments)
        resolver._cache_ttl = 0  # expire immediately

        resolver.get_lot_size("NIFTY", "NFO")
        resolver.get_lot_size("NIFTY", "NFO")
        # Both calls should have gone to the network
        assert resolver._client.instruments.call_count >= 2

    def test_unknown_symbol_falls_back_to_table(self):
        resolver = self._make_resolver([])  # empty instruments list
        lot = resolver.get_lot_size("NIFTY", "NFO")
        assert lot == FALLBACK_LOT_SIZES["NIFTY"]

    def test_truly_unknown_symbol_returns_1(self):
        resolver = self._make_resolver([])
        lot = resolver.get_lot_size("NOTAREALSTOCK", "NSE")
        assert lot == 1

    def test_network_error_falls_back_gracefully(self):
        client = MagicMock()
        client.instruments.side_effect = ConnectionError("network down")
        resolver = LotSizeResolver(client)
        lot = resolver.get_lot_size("NIFTY", "NFO")
        # Must fall back to built-in table, not raise
        assert lot == FALLBACK_LOT_SIZES["NIFTY"]

    def test_instruments_returns_non_list_falls_back(self):
        client = MagicMock()
        client.instruments.return_value = {"error": "bad response"}
        resolver = LotSizeResolver(client)
        lot = resolver.get_lot_size("NIFTY", "NFO")
        assert lot == FALLBACK_LOT_SIZES["NIFTY"]


# ---------------------------------------------------------------------------
# LotSizeResolver — instrument field name variants
# ---------------------------------------------------------------------------


class TestLotSizeResolverFieldNames:
    def _resolver_with(self, instrument: dict) -> LotSizeResolver:
        client = MagicMock()
        client.instruments.return_value = [instrument]
        return LotSizeResolver(client)

    def test_lot_size_field(self):
        r = self._resolver_with({"symbol": "NIFTY", "lot_size": 75})
        assert r.get_lot_size("NIFTY", "NFO") == 75

    def test_lotsize_field(self):
        r = self._resolver_with({"symbol": "NIFTY", "lotsize": 75})
        assert r.get_lot_size("NIFTY", "NFO") == 75

    def test_lot_field(self):
        r = self._resolver_with({"symbol": "NIFTY", "lot": 75})
        assert r.get_lot_size("NIFTY", "NFO") == 75

    def test_symbol_normalised_to_upper(self):
        r = self._resolver_with({"symbol": "nifty", "lot_size": 75})
        assert r.get_lot_size("NIFTY", "NFO") == 75


# ---------------------------------------------------------------------------
# LotSizeResolver — cache invalidation
# ---------------------------------------------------------------------------


class TestLotSizeResolverInvalidation:
    def _resolver_primed(self) -> LotSizeResolver:
        instruments = [
            {"symbol": "NIFTY", "lot_size": 75},
            {"symbol": "BANKNIFTY", "lot_size": 30},
        ]
        client = MagicMock()
        client.instruments.return_value = instruments
        r = LotSizeResolver(client)
        r.get_lot_size("NIFTY", "NFO")
        r.get_lot_size("BANKNIFTY", "NFO")
        return r

    def test_invalidate_all(self):
        r = self._resolver_primed()
        r.invalidate()
        assert r.cache_size == 0

    def test_invalidate_specific_symbol(self):
        r = self._resolver_primed()
        before = r.cache_size
        r.invalidate(symbol="NIFTY", exchange="NFO")
        assert r.cache_size == before - 1

    def test_invalidate_by_exchange(self):
        r = self._resolver_primed()
        r.invalidate(exchange="NFO")
        assert r.cache_size == 0  # both were in NFO

    def test_invalidate_unknown_symbol_no_error(self):
        r = self._resolver_primed()
        r.invalidate(symbol="DOESNOTEXIST")
        # Should not raise


# ---------------------------------------------------------------------------
# __all__ export check
# ---------------------------------------------------------------------------


class TestModuleExports:
    def test_lot_sizes_exported_from_screener(self):
        from flinttrade_screener import FALLBACK_LOT_SIZES, LotSizeResolver, get_lot_size_sync
        assert callable(get_lot_size_sync)
        assert callable(LotSizeResolver)
        assert isinstance(FALLBACK_LOT_SIZES, dict)
