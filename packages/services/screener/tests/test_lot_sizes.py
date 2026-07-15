"""Tests for dynamic lot size resolver.

Covers the built-in fallback table, cache behaviour, live-fetch path
(mocked), and the synchronous helper function.

No network calls are made — the OpenAlgoClient is mocked throughout.
Run with: python -m pytest packages/services/screener/tests/test_lot_sizes.py -v --import-mode=importlib
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from flinttrade_screener.lot_sizes import (
    FALLBACK_LOT_SIZES,
    LotResolution,
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

    def test_finnifty_lot_size_is_65(self):
        # Freshest value from the (formerly diverging) route table — the old
        # 40 here was stale.
        assert FALLBACK_LOT_SIZES["FINNIFTY"] == 65

    def test_midcpnifty_lot_size_is_120(self):
        # Freshest value from the (formerly diverging) route table — the old
        # 50 here was stale.
        assert FALLBACK_LOT_SIZES["MIDCPNIFTY"] == 120

    def test_sensex_lot_size_is_20(self):
        assert FALLBACK_LOT_SIZES["SENSEX"] == 20

    def test_merge_kept_the_union_of_both_tables(self):
        """The unification merged both tables — nothing was dropped.

        Every symbol the old route table served must still resolve, and the
        entries that only the fallback table had (NIFTYNXT50, MCX minis,
        agri) must survive the merge.
        """
        old_route_table = {
            "NIFTY": 75, "BANKNIFTY": 30, "FINNIFTY": 65, "MIDCPNIFTY": 120,
            "SENSEX": 20, "BANKEX": 30, "CRUDEOIL": 100, "NATURALGAS": 1250,
            "GOLD": 100, "SILVER": 30, "COPPER": 2500, "USDINR": 1000,
            "EURINR": 1000, "GBPINR": 1000, "JPYINR": 1000,
        }
        for sym, lot in old_route_table.items():
            assert FALLBACK_LOT_SIZES.get(sym) == lot, f"{sym} lost in merge"
        for fallback_only in ("NIFTYNXT50", "SENSEX50", "GOLDM", "SILVERMIC",
                              "CRUDEOILM", "ZINCMINI", "MENTHAOIL", "COTTON"):
            assert fallback_only in FALLBACK_LOT_SIZES, f"{fallback_only} lost in merge"

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
        rows = [{"exchange": "NFO", **instrument} for instrument in instruments]
        client.instruments.return_value = {"status": "success", "data": rows}
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
        client.instruments.return_value = {
            "status": "success",
            "data": [{"exchange": "NFO", **instrument}],
        }
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
        client.instruments.return_value = {
            "status": "success",
            "data": [{"exchange": "NFO", **instrument} for instrument in instruments],
        }
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
# LotSizeResolver.resolve — provenance-aware lookup
# ---------------------------------------------------------------------------


class TestLotSizeResolverResolve:
    def _make_resolver(self, instruments: list[dict]) -> LotSizeResolver:
        client = MagicMock()
        client.instruments.return_value = {
            "status": "success",
            "data": [{"exchange": "NFO", **instrument} for instrument in instruments],
        }
        return LotSizeResolver(client, cache_ttl=3600)

    def test_live_fetch_reports_live_source(self):
        resolver = self._make_resolver([{"symbol": "NIFTY", "lot_size": 75}])
        resolution = resolver.resolve("NIFTY", "NFO")
        assert resolution == LotResolution(75, "live")

    def test_cache_hit_preserves_live_source(self):
        resolver = self._make_resolver([{"symbol": "NIFTY", "lot_size": 75}])
        resolver.resolve("NIFTY", "NFO")
        assert resolver.resolve("NIFTY", "NFO").source == "live"
        assert resolver._client.instruments.call_count == 1

    def test_fallback_table_reports_fallback_source(self):
        resolver = self._make_resolver([])
        resolution = resolver.resolve("BANKNIFTY", "NFO")
        assert resolution.lot_size == FALLBACK_LOT_SIZES["BANKNIFTY"]
        assert resolution.source == "fallback"

    def test_unknown_symbol_reports_default_source(self):
        resolver = self._make_resolver([])
        resolution = resolver.resolve("NOTAREALSTOCK", "NSE")
        assert resolution == LotResolution(1, "default")

    def test_get_lot_size_delegates_to_resolve(self):
        resolver = self._make_resolver([{"symbol": "NIFTY", "lot_size": 75}])
        assert resolver.get_lot_size("NIFTY", "NFO") == resolver.resolve("NIFTY", "NFO").lot_size

    @pytest.mark.parametrize(
        "invalid_lot_size",
        [True, False, 75.9, "75.9", 0, -1, float("nan"), float("inf")],
    )
    def test_malformed_live_lot_size_never_receives_live_provenance(self, invalid_lot_size):
        resolver = self._make_resolver([{"symbol": "NIFTY", "lot_size": invalid_lot_size}])

        resolution = resolver.resolve("NIFTY", "NFO")

        assert resolution == LotResolution(FALLBACK_LOT_SIZES["NIFTY"], "fallback")

    @pytest.mark.parametrize("status", ["error", "failed", "", None])
    def test_non_success_envelope_never_receives_live_provenance(self, status):
        client = MagicMock()
        client.instruments.return_value = {
            "status": status,
            "data": [{"symbol": "NIFTY", "exchange": "NFO", "lot_size": 80}],
        }

        resolution = LotSizeResolver(client).resolve("NIFTY", "NFO")

        assert resolution == LotResolution(FALLBACK_LOT_SIZES["NIFTY"], "fallback")

    @pytest.mark.parametrize("row_exchange", ["NSE", "BFO", "", None])
    def test_wrong_or_missing_row_exchange_never_receives_live_provenance(self, row_exchange):
        client = MagicMock()
        client.instruments.return_value = {
            "status": "success",
            "data": [{"symbol": "NIFTY", "exchange": row_exchange, "lot_size": 80}],
        }

        resolution = LotSizeResolver(client).resolve("NIFTY", "NFO")

        assert resolution == LotResolution(FALLBACK_LOT_SIZES["NIFTY"], "fallback")

    def test_async_client_with_envelope_is_supported(self):
        """The REAL OpenAlgoClient.instruments is async and returns an
        envelope dict — the resolver must drive the coroutine and unwrap
        ``data`` (a sync list-returning fake was the only thing the old code
        handled, so the live path never worked against the real client)."""

        class FakeAsyncClient:
            def __init__(self) -> None:
                self.calls = 0

            async def instruments(self, exchange: str = "NSE") -> dict:
                self.calls += 1
                return {
                    "status": "success",
                    "data": [{"symbol": "NIFTY", "exchange": "NFO", "lotsize": 75}],
                }

        client = FakeAsyncClient()
        resolver = LotSizeResolver(client)  # type: ignore[arg-type]
        resolution = resolver.resolve("NIFTY", "NFO")
        assert resolution == LotResolution(75, "live")
        assert client.calls == 1


# ---------------------------------------------------------------------------
# __all__ export check
# ---------------------------------------------------------------------------


class TestModuleExports:
    def test_lot_sizes_exported_from_screener(self):
        from flinttrade_screener import FALLBACK_LOT_SIZES, LotSizeResolver, get_lot_size_sync
        assert callable(get_lot_size_sync)
        assert callable(LotSizeResolver)
        assert isinstance(FALLBACK_LOT_SIZES, dict)

    def test_lot_resolution_importable_from_module(self):
        from flinttrade_screener.lot_sizes import LotResolution as ImportedResolution
        assert ImportedResolution is LotResolution
