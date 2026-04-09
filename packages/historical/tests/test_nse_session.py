"""Tests for NSESession — NSE charting API with cookie pre-warming.

DO NOT RUN live — all HTTP calls are mocked. No NSE credentials required.
"""

from __future__ import annotations

import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch


# ======================================================================
# _parse_chart_response — unit tests for the parser (no I/O)
# ======================================================================


class TestParseChartResponse:
    """Test NSESession._parse_chart_response with various payload shapes."""

    def _parser(self):
        from packages.historical.src.nse_session import NSESession
        return NSESession._parse_chart_response

    def test_bare_list_of_arrays(self):
        parse = self._parser()
        payload = [
            ["1704067800000", 19500.0, 19550.5, 19480.0, 19520.0, 12345],
            ["1704071400000", 19520.0, 19600.0, 19510.0, 19580.0, 23456],
        ]
        bars = parse(payload)
        assert len(bars) == 2
        assert bars[0].open == 19500.0
        assert bars[0].high == 19550.5
        assert bars[0].volume == 12345
        assert bars[1].close == 19580.0

    def test_wrapped_data_key(self):
        parse = self._parser()
        payload = {"data": [
            ["1704067800000", 100.0, 105.0, 98.0, 102.0, 500],
        ]}
        bars = parse(payload)
        assert len(bars) == 1
        assert bars[0].low == 98.0

    def test_dict_candle_format(self):
        parse = self._parser()
        payload = [
            {"t": "1704067800000", "o": 200.0, "h": 210.0, "l": 198.0, "c": 205.0, "v": 1000},
        ]
        bars = parse(payload)
        assert len(bars) == 1
        assert bars[0].open == 200.0
        assert bars[0].volume == 1000

    def test_malformed_candle_is_skipped(self):
        parse = self._parser()
        payload = [
            ["1704067800000", 100.0],  # only 2 elements, needs 5
            ["1704071400000", 200.0, 210.0, 198.0, 205.0, 0],  # valid
        ]
        bars = parse(payload)
        assert len(bars) == 1
        assert bars[0].open == 200.0

    def test_empty_payload_returns_empty(self):
        parse = self._parser()
        assert parse(None) == []
        assert parse([]) == []
        assert parse({}) == []


# ======================================================================
# _parse_search_response — unit tests for search parser
# ======================================================================


class TestParseSearchResponse:
    """Test NSESession._parse_search_response."""

    def _parser(self):
        from packages.historical.src.nse_session import NSESession
        return NSESession._parse_search_response

    def test_wrapped_symbols_key(self):
        parse = self._parser()
        payload = {"symbols": [
            {"symbol": "NIFTY 50", "symbolName": "Nifty 50", "identifier": "INDEX"},
            {"symbol": "NIFTY BANK", "symbolName": "Bank Nifty", "identifier": "INDEX"},
        ]}
        matches = parse(payload)
        assert len(matches) == 2
        assert matches[0]["symbol"] == "NIFTY 50"
        assert matches[1]["name"] == "Bank Nifty"

    def test_bare_list(self):
        parse = self._parser()
        payload = [{"symbol": "RELIANCE", "symbolName": "Reliance Industries", "identifier": "EQ"}]
        matches = parse(payload)
        assert len(matches) == 1
        assert matches[0]["type"] == "EQ"

    def test_empty_returns_empty(self):
        parse = self._parser()
        assert parse(None) == []
        assert parse([]) == []


# ======================================================================
# NSESession — interval validation (no I/O)
# ======================================================================


class TestIntervalValidation:
    """Test that unsupported intervals return an error result without HTTP."""

    def test_unsupported_interval_returns_error(self):
        from packages.historical.src.nse_session import NSESession
        sess = NSESession(pre_warm=False)

        async def run():
            result = await sess.get_nse_data(
                "NIFTY 50", "2h", date(2025, 1, 1), date(2025, 1, 31)
            )
            await sess.close()
            return result

        result = asyncio.run(run())
        assert not result.success
        assert "2h" in result.error
        assert "Unsupported" in result.error

    def test_empty_search_query_returns_error(self):
        from packages.historical.src.nse_session import NSESession
        sess = NSESession(pre_warm=False)

        async def run():
            result = await sess.search_symbol("   ")
            await sess.close()
            return result

        result = asyncio.run(run())
        assert not result.success
        assert "Empty" in result.error


# ======================================================================
# NSESession — HTTP mocking (pre-warm + data fetch)
# ======================================================================


class TestNSESessionHTTP:
    """Test pre-warm and data fetch with mocked httpx.AsyncClient."""

    def _make_mock_response(self, json_data, status_code=200):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_data
        resp.raise_for_status = MagicMock()
        return resp

    def test_pre_warm_hits_nse_homepage(self):
        from packages.historical.src.nse_session import NSESession, _NSE_HOME

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=self._make_mock_response({}))
        mock_client.cookies = {}
        mock_client.aclose = AsyncMock()

        async def run():
            sess = NSESession(pre_warm=True)
            with patch("httpx.AsyncClient", return_value=mock_client):
                await sess._ensure_client()
                return mock_client.get.call_args_list

        calls = asyncio.run(run())
        # First call should be to NSE homepage for pre-warming
        assert any(_NSE_HOME in str(c) for c in calls)

    def test_get_nse_data_returns_parsed_bars(self):
        from packages.historical.src.nse_session import NSESession

        chart_payload = [
            ["1704067800000", 19500.0, 19550.0, 19480.0, 19520.0, 10000],
            ["1704071400000", 19520.0, 19600.0, 19510.0, 19580.0, 20000],
        ]
        mock_client = MagicMock()
        # First call: homepage pre-warm, second call: chart data
        mock_client.get = AsyncMock(side_effect=[
            self._make_mock_response({}),          # pre-warm
            self._make_mock_response(chart_payload),  # chart data
        ])
        mock_client.cookies = {}
        mock_client.aclose = AsyncMock()

        async def run():
            sess = NSESession(pre_warm=True)
            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await sess.get_nse_data(
                    "NIFTY 50", "1d",
                    date(2025, 1, 1), date(2025, 1, 31),
                )
                await sess.close()
            return result

        result = asyncio.run(run())
        assert result.success
        assert result.total_bars == 2
        assert result.bars[0].open == 19500.0
        assert result.bars[1].volume == 20000

    def test_context_manager_closes_client(self):
        from packages.historical.src.nse_session import NSESession

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=self._make_mock_response({}))
        mock_client.cookies = {}
        mock_client.aclose = AsyncMock()

        async def run():
            with patch("httpx.AsyncClient", return_value=mock_client):
                async with NSESession(pre_warm=True) as sess:
                    assert sess._client is not None
                # After __aexit__ the client reference should be cleared
                assert sess._client is None

        asyncio.run(run())
        mock_client.aclose.assert_called_once()
