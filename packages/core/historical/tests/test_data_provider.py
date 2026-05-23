"""Tests for packages/core/historical/src/data_provider.py.

All external libraries (openchart, yfinance, openalgo) are mocked so these
tests run without any network access or broker API key.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# normalise_interval
# ---------------------------------------------------------------------------


class TestNormaliseInterval:
    """Test the interval normalisation helper."""

    def test_canonical_passthrough(self):
        from flinttrade_historical.data_provider import normalise_interval
        assert normalise_interval("1m") == "1m"
        assert normalise_interval("5m") == "5m"
        assert normalise_interval("1h") == "1h"
        assert normalise_interval("D") == "D"
        assert normalise_interval("1W") == "1W"

    def test_user_friendly_to_canonical(self):
        from flinttrade_historical.data_provider import normalise_interval
        assert normalise_interval("1d") == "D"

    def test_unsupported_raises(self):
        from flinttrade_historical.data_provider import normalise_interval
        import pytest
        with pytest.raises(ValueError, match="Unrecognised interval"):
            normalise_interval("2d")

    def test_all_mapped_intervals(self):
        from flinttrade_historical.data_provider import INTERVAL_MAP
        # Every key should map without error
        from flinttrade_historical.data_provider import normalise_interval
        for k in INTERVAL_MAP:
            assert normalise_interval(k) == INTERVAL_MAP[k]


# ---------------------------------------------------------------------------
# ProviderBar / ProviderResult
# ---------------------------------------------------------------------------


class TestProviderResult:
    """Test ProviderResult properties."""

    def test_success_with_bars(self):
        from flinttrade_historical.data_provider import ProviderBar, ProviderResult
        bars = [
            ProviderBar(timestamp="2026-03-16 09:15:00", open=100, high=101, low=99, close=100.5, volume=1000),
        ]
        result = ProviderResult(symbol="RELIANCE", exchange="NSE", interval="5m", bars=bars)
        assert result.success
        assert result.total_bars == 1

    def test_failure_with_error(self):
        from flinttrade_historical.data_provider import ProviderResult
        result = ProviderResult(symbol="X", exchange="NSE", interval="5m", error="API down")
        assert not result.success
        assert result.total_bars == 0

    def test_failure_no_bars(self):
        from flinttrade_historical.data_provider import ProviderResult
        result = ProviderResult(symbol="X", exchange="NSE", interval="5m")
        assert not result.success


# ---------------------------------------------------------------------------
# OpenAlgoProvider
# ---------------------------------------------------------------------------


class TestOpenAlgoProvider:
    """Test OpenAlgoProvider with a mocked downloader."""

    def _make_provider(self, bars=None, errors=None):
        from flinttrade_historical.data_provider import OpenAlgoProvider
        mock_client = MagicMock()
        provider = OpenAlgoProvider(mock_client)
        return provider, mock_client

    def test_supports_all_openalgo_exchanges(self):
        from flinttrade_historical.data_provider import OpenAlgoProvider, OPENALGO_EXCHANGES
        mock_client = MagicMock()
        provider = OpenAlgoProvider(mock_client)
        for exch in OPENALGO_EXCHANGES:
            assert provider.supports(exch), f"Should support {exch}"

    def test_name(self):
        from flinttrade_historical.data_provider import OpenAlgoProvider
        assert OpenAlgoProvider(MagicMock()).name == "openalgo"

    def test_does_not_support_unknown_exchange(self):
        from flinttrade_historical.data_provider import OpenAlgoProvider
        provider = OpenAlgoProvider(MagicMock())
        assert not provider.supports("UNKNOWN")

    def test_fetch_success(self):
        from flinttrade_historical.data_provider import OpenAlgoProvider
        from flinttrade_historical.downloader import DownloadResult
        from flinttrade_core.models import OHLCV

        mock_client = MagicMock()
        provider = OpenAlgoProvider(mock_client)

        dl_result = DownloadResult(
            symbol="RELIANCE", exchange="NSE", interval="5m",
            start_date="2026-03-01", end_date="2026-03-15",
            bars=[OHLCV(timestamp="2026-03-01T09:15:00", open=100, high=101, low=99, close=100.5, volume=1000)],
            chunks_fetched=1,
        )

        # Patch inside the downloader module where HistoricalDownloader is defined,
        # accessed via the lazy local import in OpenAlgoProvider.fetch()
        with patch("flinttrade_historical.downloader.HistoricalDownloader") as MockDL:
            MockDL.return_value.download.return_value = dl_result
            # Also patch the import inside data_provider so the local import resolves
            with patch.dict("sys.modules"):
                import flinttrade_historical.downloader as dl_mod
                original = dl_mod.HistoricalDownloader
                dl_mod.HistoricalDownloader = MockDL
                try:
                    result = provider.fetch("RELIANCE", "NSE", "5m", "2026-03-01", "2026-03-15")
                finally:
                    dl_mod.HistoricalDownloader = original

        assert result.success
        assert result.total_bars == 1
        assert result.bars[0].open == 100
        assert result.provider == "openalgo"

    def test_fetch_api_error_returns_error_result(self):
        from flinttrade_historical.data_provider import OpenAlgoProvider
        import flinttrade_historical.downloader as dl_mod

        mock_client = MagicMock()
        provider = OpenAlgoProvider(mock_client)

        original = dl_mod.HistoricalDownloader

        class BrokenDL:
            def __init__(self, *a, **kw):
                pass
            def download(self, *a, **kw):
                raise RuntimeError("Connection refused")

        dl_mod.HistoricalDownloader = BrokenDL
        try:
            result = provider.fetch("X", "NSE", "5m", "2026-03-01", "2026-03-15")
        finally:
            dl_mod.HistoricalDownloader = original

        assert not result.success
        assert "Connection refused" in result.error


# ---------------------------------------------------------------------------
# OpenChartProvider
# ---------------------------------------------------------------------------


class TestOpenChartProvider:
    """Test OpenChartProvider with mocked free_data.NSEData."""

    def test_supports_nse_nfo(self):
        from flinttrade_historical.data_provider import OpenChartProvider
        p = OpenChartProvider()
        assert p.supports("NSE")
        assert p.supports("NFO")

    def test_does_not_support_mcx(self):
        from flinttrade_historical.data_provider import OpenChartProvider
        assert not OpenChartProvider().supports("MCX")

    def test_name(self):
        from flinttrade_historical.data_provider import OpenChartProvider
        assert OpenChartProvider().name == "openchart"

    def test_fetch_success(self):
        from flinttrade_historical.data_provider import OpenChartProvider
        from flinttrade_historical.free_data import FreeDataResult, FreeBar
        import flinttrade_historical.free_data as fd_mod

        mock_result = FreeDataResult(symbol="RELIANCE", exchange="NSE", source="openchart")
        mock_result.bars = [
            FreeBar(timestamp="2026-03-16T09:15:00", open=100, high=101, low=99, close=100.5, volume=500, source="openchart"),
        ]

        original = fd_mod.NSEData

        class MockNSE:
            def historical(self, *a, **kw):
                return mock_result

        fd_mod.NSEData = MockNSE
        try:
            provider = OpenChartProvider()
            result = provider.fetch("RELIANCE", "NSE", "5m", "2026-03-01", "2026-03-16")
        finally:
            fd_mod.NSEData = original

        assert result.success
        assert result.provider == "openchart"
        assert result.bars[0].close == 100.5

    def test_fetch_import_error(self):
        from flinttrade_historical.data_provider import OpenChartProvider
        import flinttrade_historical.free_data as fd_mod

        original = fd_mod.NSEData

        def raising(*a, **kw):
            raise ImportError("no openchart")

        fd_mod.NSEData = raising
        try:
            provider = OpenChartProvider()
            result = provider.fetch("X", "NSE", "5m", "2026-03-01", "2026-03-16")
        finally:
            fd_mod.NSEData = original

        assert not result.success
        assert "openchart" in result.error.lower() or result.error


# ---------------------------------------------------------------------------
# YFinanceProvider
# ---------------------------------------------------------------------------


class TestYFinanceProvider:
    """Test YFinanceProvider with mocked CommodityData."""

    def test_supports_mcx(self):
        from flinttrade_historical.data_provider import YFinanceProvider
        assert YFinanceProvider().supports("MCX")

    def test_does_not_support_nse(self):
        from flinttrade_historical.data_provider import YFinanceProvider
        assert not YFinanceProvider().supports("NSE")

    def test_name(self):
        from flinttrade_historical.data_provider import YFinanceProvider
        assert YFinanceProvider().name == "yfinance"

    def test_fetch_success(self):
        from flinttrade_historical.data_provider import YFinanceProvider
        from flinttrade_historical.free_data import FreeDataResult, FreeBar
        import flinttrade_historical.free_data as fd_mod

        mock_result = FreeDataResult(symbol="GOLD", exchange="MCX", source="yfinance")
        mock_result.bars = [
            FreeBar(timestamp="2026-03-16 00:00:00", open=7000, high=7100, low=6950, close=7050, volume=100, source="yfinance"),
        ]

        original = fd_mod.CommodityData

        class MockMCX:
            def historical(self, *a, **kw):
                return mock_result

        fd_mod.CommodityData = MockMCX
        try:
            provider = YFinanceProvider()
            result = provider.fetch("GOLD", "MCX", "1d", "2026-03-01", "2026-03-16")
        finally:
            fd_mod.CommodityData = original

        assert result.success
        assert result.bars[0].close == 7050

    def test_fetch_failure(self):
        from flinttrade_historical.data_provider import YFinanceProvider
        from flinttrade_historical.free_data import FreeDataResult
        import flinttrade_historical.free_data as fd_mod

        mock_result = FreeDataResult(symbol="PLATINUM", exchange="MCX", source="yfinance",
                                      error="Unknown commodity: PLATINUM")

        original = fd_mod.CommodityData

        class MockMCX:
            def historical(self, *a, **kw):
                return mock_result

        fd_mod.CommodityData = MockMCX
        try:
            provider = YFinanceProvider()
            result = provider.fetch("PLATINUM", "MCX", "1d", "2026-03-01", "2026-03-16")
        finally:
            fd_mod.CommodityData = original

        assert not result.success


# ---------------------------------------------------------------------------
# ProviderRegistry
# ---------------------------------------------------------------------------


class TestProviderRegistry:
    """Test ProviderRegistry routing and fallback logic."""

    def _make_registry(self, openalgo_client=None):
        from flinttrade_historical.data_provider import ProviderRegistry
        return ProviderRegistry(openalgo_client)

    def test_no_client_still_has_free_providers(self):
        registry = self._make_registry()
        assert len(registry.providers) >= 2

    def test_with_client_has_three_providers(self):
        registry = self._make_registry(openalgo_client=MagicMock())
        assert len(registry.providers) >= 3

    def test_fetch_uses_first_supporting_provider(self):
        from flinttrade_historical.data_provider import ProviderRegistry, ProviderBar, ProviderResult

        # Mock provider that supports NSE and returns data
        mock_provider = MagicMock()
        mock_provider.supports.return_value = True
        mock_provider.name = "mock"
        mock_provider.fetch.return_value = ProviderResult(
            symbol="RELIANCE", exchange="NSE", interval="5m",
            provider="mock",
            bars=[ProviderBar(timestamp="2026-03-16 09:15:00", open=100, high=101, low=99, close=100, volume=500)],
        )

        registry = ProviderRegistry(extra_providers=[mock_provider])
        # Remove built-in providers to isolate mock
        registry._providers = [mock_provider]

        result = registry.fetch("RELIANCE", "NSE", "5m", "2026-03-01", "2026-03-16")
        assert result.success
        assert result.provider == "mock"
        mock_provider.fetch.assert_called_once()

    def test_fallback_to_next_provider_on_failure(self):
        from flinttrade_historical.data_provider import ProviderRegistry, ProviderBar, ProviderResult

        failing = MagicMock()
        failing.supports.return_value = True
        failing.name = "failing"
        failing.fetch.return_value = ProviderResult(
            symbol="X", exchange="NSE", interval="5m", error="API down",
        )

        succeeding = MagicMock()
        succeeding.supports.return_value = True
        succeeding.name = "succeeding"
        succeeding.fetch.return_value = ProviderResult(
            symbol="X", exchange="NSE", interval="5m", provider="succeeding",
            bars=[ProviderBar(timestamp="2026-03-16 09:15:00", open=100, high=101, low=99, close=100, volume=500)],
        )

        registry = ProviderRegistry()
        registry._providers = [failing, succeeding]

        result = registry.fetch("X", "NSE", "5m", "2026-03-01", "2026-03-16", fallback=True)
        assert result.success
        assert result.provider == "succeeding"

    def test_no_fallback_returns_first_error(self):
        from flinttrade_historical.data_provider import ProviderRegistry, ProviderResult

        failing = MagicMock()
        failing.supports.return_value = True
        failing.name = "failing"
        failing.fetch.return_value = ProviderResult(
            symbol="X", exchange="NSE", interval="5m", error="API down",
        )

        succeeding = MagicMock()
        succeeding.supports.return_value = True
        succeeding.name = "succeeding"
        from flinttrade_historical.data_provider import ProviderBar
        succeeding.fetch.return_value = ProviderResult(
            symbol="X", exchange="NSE", interval="5m", provider="succeeding",
            bars=[ProviderBar(timestamp="2026-03-16 09:15:00", open=100, high=101, low=99, close=100, volume=500)],
        )

        registry = ProviderRegistry()
        registry._providers = [failing, succeeding]

        result = registry.fetch("X", "NSE", "5m", "2026-03-01", "2026-03-16", fallback=False)
        assert not result.success
        succeeding.fetch.assert_not_called()

    def test_no_supporting_provider(self):
        from flinttrade_historical.data_provider import ProviderRegistry
        registry = ProviderRegistry()
        registry._providers = []
        result = registry.fetch("X", "WEIRD_EXCHANGE", "5m", "2026-03-01", "2026-03-16")
        assert not result.success
        assert "No providers" in result.error

    def test_register_extra_provider(self):
        from flinttrade_historical.data_provider import ProviderRegistry

        extra = MagicMock()
        extra.supports.return_value = True
        extra.name = "extra"

        registry = ProviderRegistry()
        initial_count = len(registry.providers)
        registry.register(extra)
        assert len(registry.providers) == initial_count + 1

    def test_register_provider_at_position_zero(self):
        from flinttrade_historical.data_provider import ProviderRegistry

        extra = MagicMock()
        extra.name = "first"
        registry = ProviderRegistry()
        registry.register(extra, position=0)
        assert registry.providers[0].name == "first"

    def test_fetch_batch(self):
        from flinttrade_historical.data_provider import ProviderRegistry, ProviderBar, ProviderResult

        mock_provider = MagicMock()
        mock_provider.supports.return_value = True
        mock_provider.name = "mock"
        mock_provider.fetch.return_value = ProviderResult(
            symbol="X", exchange="NSE", interval="5m", provider="mock",
            bars=[ProviderBar(timestamp="2026-03-16 09:15:00", open=100, high=101, low=99, close=100, volume=500)],
        )

        registry = ProviderRegistry()
        registry._providers = [mock_provider]

        results = registry.fetch_batch(
            [
                {"symbol": "RELIANCE", "exchange": "NSE"},
                {"symbol": "TCS", "exchange": "NSE"},
            ],
            interval="5m",
            start_date="2026-03-01",
            end_date="2026-03-16",
        )
        assert len(results) == 2
        assert mock_provider.fetch.call_count == 2

    def test_protocol_compliance(self):
        """Verify built-in providers implement the DataProvider protocol."""
        from flinttrade_historical.data_provider import (
            DataProvider,
            OpenAlgoProvider,
            OpenChartProvider,
            YFinanceProvider,
        )
        assert isinstance(OpenAlgoProvider(MagicMock()), DataProvider)
        assert isinstance(OpenChartProvider(), DataProvider)
        assert isinstance(YFinanceProvider(), DataProvider)
