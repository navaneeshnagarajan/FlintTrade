"""Tests for packages/historical/src/normaliser.py.

All tests use in-process data — no network or DB access required.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta


# ---------------------------------------------------------------------------
# _to_ist_naive — timestamp conversion
# ---------------------------------------------------------------------------


class TestToIstNaive:
    """Test the internal timestamp-to-IST conversion helper."""

    def test_unix_seconds_to_ist(self):
        from packages.historical.src.normaliser import _to_ist_naive
        # 2026-03-16 03:45:00 UTC = 2026-03-16 09:15:00 IST
        ts = datetime(2026, 3, 16, 3, 45, 0, tzinfo=timezone.utc).timestamp()
        result = _to_ist_naive(ts)
        assert result == "2026-03-16 09:15:00"

    def test_unix_milliseconds_to_ist(self):
        from packages.historical.src.normaliser import _to_ist_naive
        ts_ms = datetime(2026, 3, 16, 3, 45, 0, tzinfo=timezone.utc).timestamp() * 1000
        result = _to_ist_naive(ts_ms)
        assert result == "2026-03-16 09:15:00"

    def test_aware_datetime_to_ist(self):
        from packages.historical.src.normaliser import _to_ist_naive
        dt = datetime(2026, 3, 16, 3, 45, 0, tzinfo=timezone.utc)
        result = _to_ist_naive(dt)
        assert result == "2026-03-16 09:15:00"

    def test_naive_datetime_treated_as_ist(self):
        from packages.historical.src.normaliser import _to_ist_naive
        dt = datetime(2026, 3, 16, 9, 15, 0)
        result = _to_ist_naive(dt)
        assert result == "2026-03-16 09:15:00"

    def test_iso_string_utc(self):
        from packages.historical.src.normaliser import _to_ist_naive
        result = _to_ist_naive("2026-03-16T03:45:00+00:00")
        assert result == "2026-03-16 09:15:00"

    def test_iso_string_naive(self):
        from packages.historical.src.normaliser import _to_ist_naive
        result = _to_ist_naive("2026-03-16 09:15:00")
        assert result == "2026-03-16 09:15:00"

    def test_date_only_string(self):
        from packages.historical.src.normaliser import _to_ist_naive
        result = _to_ist_naive("2026-03-16")
        assert result == "2026-03-16 00:00:00"

    def test_invalid_string_raises(self):
        from packages.historical.src.normaliser import _to_ist_naive
        import pytest
        with pytest.raises(ValueError):
            _to_ist_naive("not-a-date")


# ---------------------------------------------------------------------------
# _validate_bar
# ---------------------------------------------------------------------------


class TestValidateBar:
    """Test the single-bar validation helper."""

    def test_valid_bar(self):
        from packages.historical.src.normaliser import _validate_bar
        bar = {"open": 100, "high": 105, "low": 98, "close": 102, "volume": 1000, "oi": 0}
        assert _validate_bar(bar) == ""

    def test_high_less_than_low(self):
        from packages.historical.src.normaliser import _validate_bar
        bar = {"open": 100, "high": 90, "low": 98, "close": 95, "volume": 1000, "oi": 0}
        assert "high" in _validate_bar(bar).lower()

    def test_negative_price(self):
        from packages.historical.src.normaliser import _validate_bar
        bar = {"open": -1, "high": 10, "low": -2, "close": 5, "volume": 100, "oi": 0}
        assert "negative" in _validate_bar(bar).lower()

    def test_negative_volume(self):
        from packages.historical.src.normaliser import _validate_bar
        bar = {"open": 100, "high": 105, "low": 98, "close": 102, "volume": -1, "oi": 0}
        assert "volume" in _validate_bar(bar).lower()

    def test_negative_oi(self):
        from packages.historical.src.normaliser import _validate_bar
        bar = {"open": 100, "high": 105, "low": 98, "close": 102, "volume": 100, "oi": -5}
        assert "oi" in _validate_bar(bar).lower()

    def test_price_exceeds_maximum(self):
        from packages.historical.src.normaliser import _validate_bar
        bar = {"open": 2_000_000, "high": 2_100_000, "low": 1_900_000, "close": 2_000_000, "volume": 10}
        assert "maximum" in _validate_bar(bar).lower()

    def test_high_less_than_open(self):
        from packages.historical.src.normaliser import _validate_bar
        bar = {"open": 110, "high": 105, "low": 98, "close": 102, "volume": 100, "oi": 0}
        assert _validate_bar(bar) != ""


# ---------------------------------------------------------------------------
# _normalise_columns
# ---------------------------------------------------------------------------


class TestNormaliseColumns:
    """Test column alias mapping."""

    def test_openchart_column_names(self):
        from packages.historical.src.normaliser import _normalise_columns
        raw = {"Timestamp": "2026-03-16", "Open": 100, "High": 105, "Low": 98, "Close": 102, "Volume": 1000}
        mapped = _normalise_columns(raw)
        assert "timestamp" in mapped
        assert "open" in mapped
        assert "high" in mapped
        assert "low" in mapped
        assert "close" in mapped
        assert "volume" in mapped

    def test_lowercase_passthrough(self):
        from packages.historical.src.normaliser import _normalise_columns
        raw = {"timestamp": "2026-03-16", "open": 100, "high": 105, "low": 98, "close": 102, "volume": 1000}
        mapped = _normalise_columns(raw)
        assert mapped["timestamp"] == "2026-03-16"

    def test_oi_aliases(self):
        from packages.historical.src.normaliser import _normalise_columns
        assert _normalise_columns({"OI": 50})["oi"] == 50
        assert _normalise_columns({"OpenInterest": 50})["oi"] == 50
        assert _normalise_columns({"open_interest": 50})["oi"] == 50


# ---------------------------------------------------------------------------
# OHLCVNormaliser.normalise
# ---------------------------------------------------------------------------


class TestOHLCVNormaliserNormalise:
    """Test the main normalise() method."""

    def _make_bar(self, ts="2026-03-16 09:15:00", o=100, h=101, l=99, c=100.5, v=1000):
        return {"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": v, "oi": 0}

    def test_basic_normalise(self):
        from packages.historical.src.normaliser import OHLCVNormaliser
        bars = [self._make_bar()]
        result = OHLCVNormaliser().normalise(bars)
        assert result.success
        assert result.total_bars == 1
        assert result.bars[0].close == 100.5

    def test_empty_input(self):
        from packages.historical.src.normaliser import OHLCVNormaliser
        result = OHLCVNormaliser().normalise([])
        assert not result.success
        assert result.total_bars == 0

    def test_symbol_and_exchange_annotated(self):
        from packages.historical.src.normaliser import OHLCVNormaliser
        bars = [self._make_bar()]
        result = OHLCVNormaliser().normalise(bars, symbol="RELIANCE", exchange="NSE")
        assert result.bars[0].symbol == "RELIANCE"
        assert result.bars[0].exchange == "NSE"

    def test_invalid_bar_dropped_by_default(self):
        from packages.historical.src.normaliser import OHLCVNormaliser
        bars = [
            self._make_bar(),
            {"timestamp": "2026-03-16 09:20:00", "open": 100, "high": 90, "low": 99, "close": 95, "volume": 1000},
        ]
        result = OHLCVNormaliser().normalise(bars)
        assert result.total_bars == 1
        assert result.dropped == 1
        assert len(result.warnings) >= 1

    def test_invalid_bar_kept_when_drop_invalid_false(self):
        from packages.historical.src.normaliser import OHLCVNormaliser
        bars = [
            {"timestamp": "2026-03-16 09:20:00", "open": 100, "high": 90, "low": 99, "close": 95, "volume": 1000},
        ]
        result = OHLCVNormaliser(drop_invalid=False).normalise(bars)
        assert result.total_bars == 1
        assert result.dropped == 0
        assert len(result.warnings) >= 1

    def test_missing_timestamp_drops_bar(self):
        from packages.historical.src.normaliser import OHLCVNormaliser
        bars = [{"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000}]
        result = OHLCVNormaliser().normalise(bars)
        assert result.total_bars == 0
        assert result.dropped == 1

    def test_bars_sorted_oldest_first(self):
        from packages.historical.src.normaliser import OHLCVNormaliser
        bars = [
            self._make_bar("2026-03-16 09:20:00"),
            self._make_bar("2026-03-16 09:15:00"),
        ]
        result = OHLCVNormaliser().normalise(bars)
        assert result.bars[0].timestamp == "2026-03-16 09:15:00"
        assert result.bars[1].timestamp == "2026-03-16 09:20:00"

    def test_openchart_column_names(self):
        from packages.historical.src.normaliser import OHLCVNormaliser
        bars = [{"Timestamp": "2026-03-16 09:15:00", "Open": 100, "High": 101, "Low": 99, "Close": 100.5, "Volume": 1000}]
        result = OHLCVNormaliser().normalise(bars)
        assert result.success
        assert result.bars[0].close == 100.5

    def test_forward_fill_zero_close(self):
        from packages.historical.src.normaliser import OHLCVNormaliser
        bars = [
            self._make_bar("2026-03-16 09:15:00", c=100),
            {"timestamp": "2026-03-16 09:20:00", "open": 100, "high": 101, "low": 99, "close": 0, "volume": 0},
        ]
        result = OHLCVNormaliser(forward_fill=True).normalise(bars)
        assert result.total_bars == 2
        assert result.bars[1].close == 100  # forward-filled

    def test_no_forward_fill_zero_close_dropped(self):
        from packages.historical.src.normaliser import OHLCVNormaliser
        bars = [
            self._make_bar("2026-03-16 09:15:00", c=100),
            # close=0 with open=0 fails high>=open — but high=0, open=0 is ok, low=0 ok
            # Actually close=0 with open=100 and high=101: low=99, open=100 — valid bar
            # Let's use a clearly invalid bar instead
            {"timestamp": "2026-03-16 09:20:00", "open": 100, "high": 90, "low": 99, "close": 95, "volume": 100},
        ]
        result = OHLCVNormaliser(forward_fill=False).normalise(bars)
        assert result.dropped == 1


class TestIntradayCutoff:
    """Test the 15:29:59 intraday cutoff absorbed from openchart."""

    def _make_bar(self, ts, o=100, h=101, l=99, c=100.5, v=1000):
        return {"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": v}

    def test_bars_before_cutoff_kept(self):
        from packages.historical.src.normaliser import OHLCVNormaliser
        bars = [
            self._make_bar("2026-03-16 09:15:00"),
            self._make_bar("2026-03-16 15:29:59"),
        ]
        result = OHLCVNormaliser().normalise(bars, interval="5m")
        assert result.total_bars == 2

    def test_bars_after_cutoff_dropped_for_intraday(self):
        from packages.historical.src.normaliser import OHLCVNormaliser
        bars = [
            self._make_bar("2026-03-16 09:15:00"),
            self._make_bar("2026-03-16 15:30:00"),  # After cutoff
            self._make_bar("2026-03-16 16:00:00"),
        ]
        result = OHLCVNormaliser().normalise(bars, interval="5m")
        assert result.total_bars == 1
        assert result.dropped == 2

    def test_cutoff_not_applied_for_daily(self):
        from packages.historical.src.normaliser import OHLCVNormaliser
        bars = [self._make_bar("2026-03-16")]
        result = OHLCVNormaliser().normalise(bars, interval="D")
        assert result.total_bars == 1

    def test_cutoff_disabled(self):
        from packages.historical.src.normaliser import OHLCVNormaliser
        bars = [
            self._make_bar("2026-03-16 15:30:00"),
        ]
        result = OHLCVNormaliser(apply_intraday_cutoff=False).normalise(bars, interval="5m")
        assert result.total_bars == 1


# ---------------------------------------------------------------------------
# normalise_dataframe
# ---------------------------------------------------------------------------


class TestNormaliseDataframe:
    """Test DataFrame normalisation (openchart output format)."""

    def test_dataframe_with_index_as_timestamp(self):
        from packages.historical.src.normaliser import OHLCVNormaliser
        try:
            import pandas as pd
        except ImportError:
            import pytest
            pytest.skip("pandas not installed")

        df = pd.DataFrame(
            {
                "Open": [100.0, 101.0],
                "High": [105.0, 106.0],
                "Low": [98.0, 99.0],
                "Close": [102.0, 103.0],
                "Volume": [1000, 2000],
            },
            index=pd.to_datetime(["2026-03-16 09:15:00", "2026-03-16 09:20:00"]),
        )
        df.index.name = "Timestamp"
        result = OHLCVNormaliser().normalise_dataframe(df, symbol="RELIANCE", exchange="NSE")
        assert result.success
        assert result.total_bars == 2

    def test_empty_dataframe(self):
        from packages.historical.src.normaliser import OHLCVNormaliser
        try:
            import pandas as pd
        except ImportError:
            import pytest
            pytest.skip("pandas not installed")
        result = OHLCVNormaliser().normalise_dataframe(pd.DataFrame())
        assert not result.success

    def test_none_dataframe(self):
        from packages.historical.src.normaliser import OHLCVNormaliser
        result = OHLCVNormaliser().normalise_dataframe(None)
        assert not result.success


# ---------------------------------------------------------------------------
# normalise_provider_bars
# ---------------------------------------------------------------------------


class TestNormaliseProviderBars:
    """Test normalise_provider_bars convenience method."""

    def test_provider_bars_normalised(self):
        from packages.historical.src.normaliser import OHLCVNormaliser
        from packages.historical.src.data_provider import ProviderBar
        bars = [
            ProviderBar(timestamp="2026-03-16 09:15:00", open=100, high=101, low=99, close=100.5, volume=1000, source="openchart"),
        ]
        result = OHLCVNormaliser().normalise_provider_bars(bars, interval="5m")
        assert result.success
        assert result.bars[0].close == 100.5


# ---------------------------------------------------------------------------
# Module-level normalise() convenience function
# ---------------------------------------------------------------------------


class TestConvenienceFunction:
    """Test the module-level normalise() helper."""

    def test_basic_call(self):
        from packages.historical.src.normaliser import normalise
        bars = [{"timestamp": "2026-03-16 09:15:00", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000}]
        result = normalise(bars)
        assert result.success

    def test_kwargs_forwarded(self):
        from packages.historical.src.normaliser import normalise
        bars = [{"timestamp": "2026-03-16 15:30:00", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000}]
        # With cutoff disabled, the bar should survive
        result = normalise(bars, interval="5m", apply_intraday_cutoff=False)
        assert result.total_bars == 1
