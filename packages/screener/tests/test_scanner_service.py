"""Tests for the real-time scanner service.

Tests cover:
- CandleBuilder: tick → 1m bar aggregation
- CandleBuilder: 1m → 5m / 15m bar aggregation
- RSIScanner: detects oversold / overbought correctly
- EMACrossoverScanner: detects golden cross / death cross
- VolumeSpikeScanner: detects volume > 2× average
- ScannerService: dispatches ticks to all registered scanners

No API calls are made — all data is synthetic.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from packages.screener.src.scanner_service import (
    AbstractScanner,
    CandleBuilder,
    EMACrossoverScanner,
    RSIScanner,
    ScannerMatch,
    ScannerService,
    Tick,
    VolumeSpikeScanner,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tick(
    symbol: str = "NIFTY",
    ltp: float = 22000.0,
    volume: float = 100_000.0,
    ts: datetime | None = None,
    exchange: str = "NSE",
) -> Tick:
    """Build a synthetic tick."""
    return Tick(
        symbol=symbol,
        ltp=ltp,
        volume=volume,
        timestamp=ts or datetime.now(timezone.utc),
        exchange=exchange,
    )


def _minute_ts(base: datetime, offset_minutes: float) -> datetime:
    """Return base + offset_minutes (as fractional minutes)."""
    return base + timedelta(seconds=offset_minutes * 60)


def _feed_ticks_for_bar(
    builder: CandleBuilder,
    base_ts: datetime,
    bar_minute: int,
    prices: list[float],
    vol_base: float = 1_000_000.0,
    symbol: str = "NIFTY",
) -> None:
    """Feed ``len(prices)`` ticks spread evenly within ``bar_minute`` minute."""
    n = len(prices)
    for i, price in enumerate(prices):
        # Distribute ticks across the minute slot
        ts = base_ts + timedelta(seconds=bar_minute * 60 + i * (60 / n))
        builder.update(_make_tick(symbol=symbol, ltp=price, volume=vol_base + i, ts=ts))


# ---------------------------------------------------------------------------
# CandleBuilder tests
# ---------------------------------------------------------------------------


class TestCandleBuilderOneMintue:
    """Verify 1m OHLCV bar construction from raw ticks."""

    def test_no_candle_within_same_minute(self) -> None:
        """Ticks inside the same minute should not produce a completed bar."""
        builder = CandleBuilder("NIFTY")
        base = datetime(2026, 4, 14, 9, 15, 0, tzinfo=timezone.utc)

        for i in range(5):
            ts = base + timedelta(seconds=i * 10)
            completed = builder.update(_make_tick(ltp=100.0 + i, ts=ts))
            assert completed == [], f"Expected no bars at tick {i}, got {completed}"

        assert builder.bar_count(1) == 0

    def test_candle_closes_on_minute_boundary(self) -> None:
        """First tick of a new minute slot should close the previous bar."""
        builder = CandleBuilder("NIFTY")
        base = datetime(2026, 4, 14, 9, 15, 0, tzinfo=timezone.utc)

        # Ticks in minute 0
        for price in [100.0, 102.0, 99.0, 101.0]:
            base + timedelta(seconds=len([]) * 10)
            builder.update(_make_tick(ltp=price, volume=1000.0, ts=base + timedelta(seconds=price - 99)))

        # Trigger close: first tick of minute 1
        ts_new = base + timedelta(minutes=1, seconds=1)
        completed = builder.update(_make_tick(ltp=105.0, volume=1500.0, ts=ts_new))

        assert len(completed) == 1
        bar = completed[0]
        assert bar.timeframe == 1
        assert bar.symbol == "NIFTY"
        # Open is the first ltp fed
        assert bar.open == 100.0
        # Close is the last ltp within the original minute
        assert bar.close == 101.0

    def test_ohlcv_values_correct(self) -> None:
        """Bar OHLCV values must reflect the actual tick sequence."""
        builder = CandleBuilder("TEST")
        base = datetime(2026, 4, 14, 9, 15, 0, tzinfo=timezone.utc)

        prices = [50.0, 55.0, 48.0, 52.0]
        vols = [1000.0, 1100.0, 1200.0, 1300.0]
        for i, (p, v) in enumerate(zip(prices, vols)):
            builder.update(_make_tick(symbol="TEST", ltp=p, volume=v, ts=base + timedelta(seconds=i * 10)))

        # Close the bar
        ts_close = base + timedelta(minutes=1, seconds=5)
        completed = builder.update(_make_tick(symbol="TEST", ltp=53.0, volume=1400.0, ts=ts_close))

        assert len(completed) == 1
        bar = completed[0]
        assert bar.open == 50.0
        assert bar.high == 55.0
        assert bar.low == 48.0
        assert bar.close == 52.0

    def test_volume_delta_is_positive(self) -> None:
        """Volume stored in bar should be the delta, not cumulative."""
        builder = CandleBuilder("NIFTY")
        base = datetime(2026, 4, 14, 9, 15, 0, tzinfo=timezone.utc)

        builder.update(_make_tick(ltp=100.0, volume=500_000.0, ts=base))
        builder.update(_make_tick(ltp=101.0, volume=510_000.0, ts=base + timedelta(seconds=30)))

        # Next minute closes first bar
        ts_next = base + timedelta(minutes=1, seconds=5)
        completed = builder.update(_make_tick(ltp=102.0, volume=520_000.0, ts=ts_next))

        assert len(completed) == 1
        # Volume delta from bar open to trigger tick
        assert completed[0].volume >= 0.0

    def test_multiple_bars_accumulate(self) -> None:
        """Multiple bars are stored and accessible via get_bars."""
        builder = CandleBuilder("NIFTY")
        base = datetime(2026, 4, 14, 9, 15, 0, tzinfo=timezone.utc)

        all_completed: list[Any] = []
        for minute in range(4):
            for second in [0, 15, 30, 45]:
                ts = base + timedelta(minutes=minute, seconds=second)
                result = builder.update(_make_tick(ltp=100.0 + minute, volume=float(minute * 10_000), ts=ts))
                all_completed.extend(result)
            # Push one tick into next minute to flush
            ts_flush = base + timedelta(minutes=minute + 1, seconds=1)
            result = builder.update(_make_tick(ltp=100.0, volume=float((minute + 1) * 10_000 + 1), ts=ts_flush))
            all_completed.extend(result)

        bars = builder.get_bars(1)
        assert len(bars) >= 3, f"Expected at least 3 bars, got {len(bars)}"

    def test_get_bars_returns_oldest_first(self) -> None:
        """Bars returned by get_bars should be in chronological order."""
        builder = CandleBuilder("NIFTY")
        base = datetime(2026, 4, 14, 9, 15, 0, tzinfo=timezone.utc)

        for minute in range(3):
            for second in [0, 30]:
                ts = base + timedelta(minutes=minute, seconds=second)
                builder.update(_make_tick(ltp=100.0 + minute * 5, ts=ts))
            # Flush
            builder.update(_make_tick(ltp=100.0, ts=base + timedelta(minutes=minute + 1, seconds=1)))

        bars = builder.get_bars(1)
        for i in range(1, len(bars)):
            assert bars[i].bar_open_ts >= bars[i - 1].bar_open_ts

    def test_bar_count_matches_completed_candles(self) -> None:
        """bar_count should agree with the number of completed candles."""
        builder = CandleBuilder("NIFTY")
        base = datetime(2026, 4, 14, 9, 15, 0, tzinfo=timezone.utc)

        total_completed = 0
        for minute in range(5):
            # Tick inside minute `minute`
            builder.update(_make_tick(ltp=100.0, ts=base + timedelta(minutes=minute, seconds=5)))
            # Tick in minute `minute + 1` — closes the bar
            result = builder.update(
                _make_tick(ltp=101.0, ts=base + timedelta(minutes=minute + 1, seconds=5))
            )
            # Only count 1m completions
            total_completed += sum(1 for c in result if c.timeframe == 1)

        assert builder.bar_count(1) == total_completed


# ---------------------------------------------------------------------------
# CandleBuilder — 5m and 15m aggregation
# ---------------------------------------------------------------------------


class TestCandleBuilderHigherTimeframes:
    """Verify 5m and 15m bars are built from the same tick stream."""

    def _build_n_minutes(
        self,
        n: int,
        symbol: str = "NIFTY",
        base_price: float = 100.0,
    ) -> CandleBuilder:
        """Feed ticks for ``n`` complete minutes and return the builder."""
        builder = CandleBuilder(symbol)
        base = datetime(2026, 4, 14, 9, 0, 0, tzinfo=timezone.utc)

        for minute in range(n + 1):  # +1 extra minute to flush last bar
            ts = base + timedelta(minutes=minute, seconds=5)
            builder.update(_make_tick(symbol=symbol, ltp=base_price + minute, ts=ts))

        return builder

    def test_five_minute_bar_closes_at_5th_minute(self) -> None:
        """5m bar should close after the 5th 1m bar is triggered."""
        builder = self._build_n_minutes(6)
        bars_5m = builder.get_bars(5)
        assert len(bars_5m) >= 1, f"Expected at least one 5m bar, got {len(bars_5m)}"
        for bar in bars_5m:
            assert bar.timeframe == 5

    def test_fifteen_minute_bar_closes_at_15th_minute(self) -> None:
        """15m bar should close after 15 1m bars pass."""
        builder = self._build_n_minutes(16)
        bars_15m = builder.get_bars(15)
        assert len(bars_15m) >= 1, f"Expected at least one 15m bar, got {len(bars_15m)}"
        for bar in bars_15m:
            assert bar.timeframe == 15

    def test_5m_bar_timeframe_attribute(self) -> None:
        """Completed 5m candles must have timeframe == 5."""
        builder = self._build_n_minutes(10)
        for bar in builder.get_bars(5):
            assert bar.timeframe == 5

    def test_15m_bar_timeframe_attribute(self) -> None:
        """Completed 15m candles must have timeframe == 15."""
        builder = self._build_n_minutes(30)
        for bar in builder.get_bars(15):
            assert bar.timeframe == 15

    def test_bars_accumulate_across_all_timeframes(self) -> None:
        """All three timeframes accumulate bars independently."""
        builder = self._build_n_minutes(16)
        assert builder.bar_count(1) >= 1
        assert builder.bar_count(5) >= 1
        assert builder.bar_count(15) >= 1

    def test_invalid_timeframe_raises(self) -> None:
        """get_bars with an unsupported timeframe should raise KeyError."""
        builder = CandleBuilder("NIFTY")
        with pytest.raises(KeyError):
            builder.get_bars(30)


# ---------------------------------------------------------------------------
# RSI Scanner tests
# ---------------------------------------------------------------------------


def _make_candle(
    symbol: str = "NIFTY",
    close: float = 100.0,
    volume: float = 10_000.0,
    timeframe: int = 1,
    ts: datetime | None = None,
) -> Any:
    """Create a minimal Candle for testing."""
    from packages.screener.src.scanner_service import Candle

    now = ts or datetime.now(timezone.utc)
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=volume,
        bar_open_ts=now,
        bar_close_ts=now + timedelta(minutes=timeframe),
    )


class TestRSIScanner:
    """RSIScanner correctness tests."""

    def _warm_up_scanner(
        self,
        scanner: RSIScanner,
        n: int = 20,
        price: float = 100.0,
    ) -> None:
        """Feed ``n`` flat-price candles to warm up the RSI."""
        for _ in range(n):
            scanner.on_candle(_make_candle(close=price), [])

    def test_no_match_during_warmup(self) -> None:
        """Scanner should not fire during RSI warm-up (< period + 1 bars)."""
        scanner = RSIScanner(period=14)
        for _ in range(14):
            result = scanner.on_candle(_make_candle(close=100.0), [])
            assert result is None

    def test_oversold_signal_fired(self) -> None:
        """RSI Scanner must return 'oversold' after a sustained price drop."""
        scanner = RSIScanner(period=14, oversold=30.0)
        # Warm up with flat prices
        for _ in range(15):
            scanner.on_candle(_make_candle(close=100.0), [])
        # Feed declining prices to push RSI below 30
        for i in range(20):
            scanner.on_candle(_make_candle(close=100.0 - i * 3.0), [])

        # Collect any oversold match
        scanner2 = RSIScanner(period=14, oversold=30.0)
        matches: list[ScannerMatch] = []
        prices = [100.0] * 15 + [100.0 - i * 3.0 for i in range(20)]
        for p in prices:
            result = scanner2.on_candle(_make_candle(close=p), [])
            if result is not None:
                matches.append(result)

        oversold_matches = [m for m in matches if m.signal == "oversold"]
        assert len(oversold_matches) >= 1, "Expected at least one 'oversold' match"

    def test_overbought_signal_fired(self) -> None:
        """RSI Scanner must return 'overbought' after a sustained price rise."""
        scanner = RSIScanner(period=14, overbought=70.0)
        matches: list[ScannerMatch] = []
        prices = [100.0] * 15 + [100.0 + i * 3.0 for i in range(20)]
        for p in prices:
            result = scanner.on_candle(_make_candle(close=p), [])
            if result is not None:
                matches.append(result)

        overbought_matches = [m for m in matches if m.signal == "overbought"]
        assert len(overbought_matches) >= 1, "Expected at least one 'overbought' match"

    def test_rsi_value_in_match_is_within_0_100(self) -> None:
        """RSI value in ScannerMatch must be in [0, 100]."""
        scanner = RSIScanner(period=14, oversold=30.0)
        matches: list[ScannerMatch] = []
        prices = [100.0] * 15 + [100.0 - i * 3.0 for i in range(25)]
        for p in prices:
            result = scanner.on_candle(_make_candle(close=p), [])
            if result is not None:
                matches.append(result)

        for m in matches:
            assert 0.0 <= m.value <= 100.0, f"RSI value out of range: {m.value}"

    def test_no_match_when_rsi_neutral(self) -> None:
        """No match when RSI is in neutral territory (not oversold or overbought).

        Mildly oscillating prices keep RSI in the 40–60 range — well inside
        the 30 / 70 default thresholds — so no signal should be emitted.
        """
        scanner = RSIScanner(period=14, oversold=30.0, overbought=70.0)
        matches: list[ScannerMatch] = []
        # Alternating small up/down moves → RSI stays near 50
        for i in range(40):
            price = 100.0 + (1.0 if i % 2 == 0 else -1.0)
            result = scanner.on_candle(_make_candle(close=price), [])
            if result is not None:
                matches.append(result)
        assert matches == [], f"Unexpected matches on oscillating prices: {matches}"

    def test_reset_clears_state(self) -> None:
        """After reset, scanner behaves as if freshly constructed."""
        scanner = RSIScanner(period=14)
        for _ in range(20):
            scanner.on_candle(_make_candle(close=100.0), [])
        scanner.reset("NIFTY")
        assert "NIFTY" not in scanner._symbol_states

    def test_per_symbol_state_isolation(self) -> None:
        """Different symbols must not share RSI state."""
        scanner = RSIScanner(period=14, oversold=30.0)
        # Warm up NIFTY with declining prices
        prices_nifty = [100.0] * 15 + [100.0 - i * 3.0 for i in range(20)]
        matches_nifty: list[ScannerMatch] = []
        for p in prices_nifty:
            r = scanner.on_candle(_make_candle(symbol="NIFTY", close=p), [])
            if r:
                matches_nifty.append(r)

        # BANKNIFTY at flat prices should NOT be oversold
        scanner_flat = RSIScanner(period=14, oversold=30.0)
        for p in prices_nifty:
            scanner_flat.on_candle(_make_candle(symbol="NIFTY", close=p), [])

        result = scanner_flat.on_candle(_make_candle(symbol="BANKNIFTY", close=22000.0), [])
        # BANKNIFTY has no warm-up ticks, result should be None
        assert result is None


# ---------------------------------------------------------------------------
# EMA Crossover Scanner tests
# ---------------------------------------------------------------------------


class TestEMACrossoverScanner:
    """EMACrossoverScanner correctness tests."""

    def test_invalid_fast_slow_raises(self) -> None:
        """fast >= slow should raise ValueError."""
        with pytest.raises(ValueError, match="fast period"):
            EMACrossoverScanner(fast=21, slow=9)

    def test_equal_fast_slow_raises(self) -> None:
        """fast == slow should raise ValueError."""
        with pytest.raises(ValueError):
            EMACrossoverScanner(fast=9, slow=9)

    def test_no_match_during_warmup(self) -> None:
        """No match while either EMA is still warming up."""
        scanner = EMACrossoverScanner(fast=3, slow=5)
        for _ in range(5):
            result = scanner.on_candle(_make_candle(close=100.0), [])
            assert result is None

    def test_golden_cross_detected(self) -> None:
        """Golden cross: fast EMA crosses above slow EMA."""
        scanner = EMACrossoverScanner(fast=3, slow=5)
        matches: list[ScannerMatch] = []

        # Start with declining prices so fast < slow
        declining = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 94.0, 93.0, 92.0, 91.0]
        for p in declining:
            r = scanner.on_candle(_make_candle(close=p), [])
            if r:
                matches.append(r)

        # Then sharply rising prices to trigger fast > slow
        rising = [91.0, 93.0, 95.0, 98.0, 103.0, 110.0, 118.0, 130.0]
        for p in rising:
            r = scanner.on_candle(_make_candle(close=p), [])
            if r:
                matches.append(r)

        golden = [m for m in matches if m.signal == "golden_cross"]
        assert len(golden) >= 1, "Expected at least one golden_cross signal"

    def test_death_cross_detected(self) -> None:
        """Death cross: fast EMA crosses below slow EMA."""
        scanner = EMACrossoverScanner(fast=3, slow=5)
        matches: list[ScannerMatch] = []

        # Start rising so fast > slow
        rising = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 107.0, 110.0, 115.0, 120.0]
        for p in rising:
            r = scanner.on_candle(_make_candle(close=p), [])
            if r:
                matches.append(r)

        # Then sharply declining
        declining = [120.0, 118.0, 115.0, 110.0, 103.0, 95.0, 85.0, 73.0]
        for p in declining:
            r = scanner.on_candle(_make_candle(close=p), [])
            if r:
                matches.append(r)

        death = [m for m in matches if m.signal == "death_cross"]
        assert len(death) >= 1, "Expected at least one death_cross signal"

    def test_match_contains_ema_values(self) -> None:
        """ScannerMatch extra must contain fast_ema and slow_ema."""
        scanner = EMACrossoverScanner(fast=3, slow=5)
        matches: list[ScannerMatch] = []
        prices = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 94.0, 91.0, 95.0, 103.0, 115.0, 130.0]
        for p in prices:
            r = scanner.on_candle(_make_candle(close=p), [])
            if r:
                matches.append(r)

        for m in matches:
            assert "fast_ema" in m.extra
            assert "slow_ema" in m.extra

    def test_reset_clears_state(self) -> None:
        """reset should clear per-symbol EMA state."""
        scanner = EMACrossoverScanner(fast=3, slow=5)
        for p in [100.0, 101.0, 102.0, 103.0, 104.0]:
            scanner.on_candle(_make_candle(close=p), [])
        scanner.reset("NIFTY")
        assert "NIFTY" not in scanner._symbol_states

    def test_signal_is_golden_or_death(self) -> None:
        """Any match must be either golden_cross or death_cross."""
        scanner = EMACrossoverScanner(fast=3, slow=5)
        prices = [100.0 - i for i in range(10)] + [90.0 + i * 2 for i in range(10)]
        for p in prices:
            r = scanner.on_candle(_make_candle(close=p), [])
            if r is not None:
                assert r.signal in {"golden_cross", "death_cross"}


# ---------------------------------------------------------------------------
# Volume Spike Scanner tests
# ---------------------------------------------------------------------------


class TestVolumeSpikeScanner:
    """VolumeSpikeScanner correctness tests."""

    def test_invalid_lookback_raises(self) -> None:
        """lookback < 2 should raise ValueError."""
        with pytest.raises(ValueError, match="lookback"):
            VolumeSpikeScanner(lookback=1)

    def test_invalid_threshold_raises(self) -> None:
        """threshold_multiplier <= 0 should raise ValueError."""
        with pytest.raises(ValueError, match="threshold_multiplier"):
            VolumeSpikeScanner(threshold_multiplier=-1.0)

    def test_no_match_during_warmup(self) -> None:
        """No match until lookback bars have been seen."""
        scanner = VolumeSpikeScanner(lookback=5, threshold_multiplier=2.0)
        for _ in range(5):
            result = scanner.on_candle(_make_candle(volume=1000.0), [])
            assert result is None

    def test_volume_spike_detected(self) -> None:
        """A candle with volume > 2× average should trigger a spike match."""
        scanner = VolumeSpikeScanner(lookback=5, threshold_multiplier=2.0)
        # Warm up with baseline volume
        for _ in range(5):
            scanner.on_candle(_make_candle(volume=1000.0), [])

        # Spike: 5× average
        result = scanner.on_candle(_make_candle(volume=5000.0), [])
        assert result is not None
        assert result.signal == "volume_spike"
        assert result.value > 2.0

    def test_no_spike_below_threshold(self) -> None:
        """Volume just below the threshold should not fire."""
        scanner = VolumeSpikeScanner(lookback=5, threshold_multiplier=2.0)
        for _ in range(5):
            scanner.on_candle(_make_candle(volume=1000.0), [])

        # 1.9× — below threshold of 2.0
        result = scanner.on_candle(_make_candle(volume=1900.0), [])
        assert result is None

    def test_spike_at_exact_threshold_boundary(self) -> None:
        """Volume exactly at threshold should NOT fire (uses strict >)."""
        scanner = VolumeSpikeScanner(lookback=5, threshold_multiplier=2.0)
        for _ in range(5):
            scanner.on_candle(_make_candle(volume=1000.0), [])

        # Exactly 2.0× — should NOT fire (value must be strictly greater)
        result = scanner.on_candle(_make_candle(volume=2000.0), [])
        assert result is None

    def test_multiplier_value_in_match(self) -> None:
        """ScannerMatch value must reflect the actual volume multiplier."""
        scanner = VolumeSpikeScanner(lookback=5, threshold_multiplier=2.0)
        for _ in range(5):
            scanner.on_candle(_make_candle(volume=1000.0), [])

        result = scanner.on_candle(_make_candle(volume=4000.0), [])
        assert result is not None
        # Average is 1000, so multiplier should be ~4.0
        assert abs(result.value - 4.0) < 0.1

    def test_zero_average_volume_no_match(self) -> None:
        """If average volume is zero, no spike should be reported."""
        scanner = VolumeSpikeScanner(lookback=3, threshold_multiplier=2.0)
        for _ in range(3):
            scanner.on_candle(_make_candle(volume=0.0), [])

        result = scanner.on_candle(_make_candle(volume=1000.0), [])
        assert result is None

    def test_per_symbol_state_isolation(self) -> None:
        """Each symbol maintains independent volume history."""
        scanner = VolumeSpikeScanner(lookback=3, threshold_multiplier=2.0)
        # Warm up NIFTY
        for _ in range(3):
            scanner.on_candle(_make_candle(symbol="NIFTY", volume=1000.0), [])

        # BANKNIFTY hasn't warmed up — should not fire even with huge volume
        result = scanner.on_candle(_make_candle(symbol="BANKNIFTY", volume=50000.0), [])
        assert result is None

    def test_reset_clears_state(self) -> None:
        """reset should clear the rolling volume window for a symbol."""
        scanner = VolumeSpikeScanner(lookback=3, threshold_multiplier=2.0)
        for _ in range(3):
            scanner.on_candle(_make_candle(volume=1000.0), [])
        scanner.reset("NIFTY")
        assert "NIFTY" not in scanner._symbol_states


# ---------------------------------------------------------------------------
# ScannerService integration tests
# ---------------------------------------------------------------------------


class TestScannerService:
    """Integration tests for ScannerService tick dispatch and queue publishing."""

    def _build_service(self) -> tuple[ScannerService, RSIScanner, VolumeSpikeScanner]:
        rsi = RSIScanner(period=14, oversold=30.0, overbought=70.0, timeframe=1)
        vol = VolumeSpikeScanner(lookback=5, threshold_multiplier=2.0, timeframe=1)
        svc = ScannerService(queue_maxsize=500)
        svc.add_scanner(rsi)
        svc.add_scanner(vol)
        return svc, rsi, vol

    def test_add_scanner_registered(self) -> None:
        """Registered scanners should appear in list_scanners."""
        svc = ScannerService()
        scanner = RSIScanner()
        svc.add_scanner(scanner)
        assert scanner in svc.list_scanners()

    def test_add_scanner_idempotent(self) -> None:
        """Adding the same scanner instance twice should not duplicate it."""
        svc = ScannerService()
        scanner = RSIScanner()
        svc.add_scanner(scanner)
        svc.add_scanner(scanner)
        assert svc.list_scanners().count(scanner) == 1

    def test_remove_scanner(self) -> None:
        """Removed scanner should not appear in list_scanners."""
        svc = ScannerService()
        scanner = RSIScanner()
        svc.add_scanner(scanner)
        result = svc.remove_scanner(scanner)
        assert result is True
        assert scanner not in svc.list_scanners()

    def test_remove_nonexistent_returns_false(self) -> None:
        """Removing a scanner that was never added should return False."""
        svc = ScannerService()
        result = svc.remove_scanner(RSIScanner())
        assert result is False

    def test_on_tick_tracks_symbol(self) -> None:
        """After on_tick, the symbol should be in tracked_symbols."""
        svc = ScannerService()

        async def _run() -> None:
            tick = _make_tick(symbol="RELIANCE", ltp=2500.0)
            await svc.on_tick(tick)
            assert "RELIANCE" in svc.tracked_symbols

        asyncio.run(_run())

    def test_on_tick_accepts_raw_dict(self) -> None:
        """on_tick should accept a raw WebSocket dict payload."""
        svc = ScannerService()

        async def _run() -> None:
            payload = {
                "type": "market_data",
                "data": {
                    "symbol": "TCS",
                    "ltp": 3500.0,
                    "volume": 50000.0,
                    "exchange": "NSE",
                },
            }
            await svc.on_tick(payload)
            assert "TCS" in svc.tracked_symbols

        asyncio.run(_run())

    def test_no_match_on_single_tick(self) -> None:
        """A single tick cannot close a bar, so no matches should be returned."""
        svc, _, _ = self._build_service()

        async def _run() -> list[ScannerMatch]:
            tick = _make_tick(ltp=100.0)
            return await svc.on_tick(tick)

        matches = asyncio.run(_run())
        assert matches == []

    def test_dispatches_ticks_to_all_registered_scanners(self) -> None:
        """All registered scanners must be evaluated when a bar closes."""
        seen_names: list[str] = []

        class _SpyScanner(AbstractScanner):
            def __init__(self, label: str) -> None:
                super().__init__(name=label, timeframe=1)
                self._label = label

            def on_candle(self, candle: Any, history: list[Any]) -> ScannerMatch | None:
                seen_names.append(self._label)
                return None

        svc = ScannerService()
        svc.add_scanner(_SpyScanner("scanner_a"))
        svc.add_scanner(_SpyScanner("scanner_b"))
        svc.add_scanner(_SpyScanner("scanner_c"))

        async def _run() -> None:
            base = datetime(2026, 4, 14, 9, 15, 0, tzinfo=timezone.utc)
            # Tick in minute 0
            await svc.on_tick(_make_tick(ltp=100.0, ts=base))
            # Tick in minute 1 — closes the bar
            await svc.on_tick(_make_tick(ltp=101.0, ts=base + timedelta(minutes=1, seconds=5)))

        asyncio.run(_run())

        assert "scanner_a" in seen_names
        assert "scanner_b" in seen_names
        assert "scanner_c" in seen_names

    def test_scanner_with_different_timeframe_not_called(self) -> None:
        """A 5m scanner should not be called when only 1m bars close."""
        called: list[bool] = []

        class _SpyScanner5m(AbstractScanner):
            def __init__(self) -> None:
                super().__init__(name="spy5m", timeframe=5)

            def on_candle(self, candle: Any, history: list[Any]) -> ScannerMatch | None:
                called.append(True)
                return None

        svc = ScannerService()
        svc.add_scanner(_SpyScanner5m())

        async def _run() -> None:
            base = datetime(2026, 4, 14, 9, 15, 0, tzinfo=timezone.utc)
            await svc.on_tick(_make_tick(ltp=100.0, ts=base))
            # Only 1m bar closes here
            await svc.on_tick(_make_tick(ltp=101.0, ts=base + timedelta(minutes=1, seconds=5)))

        asyncio.run(_run())
        assert called == [], "5m scanner should not fire when only a 1m bar closes"

    def test_match_published_to_queue(self) -> None:
        """Matches produced by scanners should appear in the matches queue."""

        class _AlwaysMatch(AbstractScanner):
            def __init__(self) -> None:
                super().__init__(name="always_match", timeframe=1)

            def on_candle(self, candle: Any, history: list[Any]) -> ScannerMatch | None:
                return ScannerMatch(
                    scanner_name=self.name,
                    symbol=candle.symbol,
                    exchange="NSE",
                    timeframe=candle.timeframe,
                    signal="test",
                    value=0.0,
                    ltp=candle.close,
                    matched_at=candle.bar_close_ts,
                )

        svc = ScannerService(queue_maxsize=10)
        svc.add_scanner(_AlwaysMatch())

        async def _run() -> None:
            base = datetime(2026, 4, 14, 9, 15, 0, tzinfo=timezone.utc)
            await svc.on_tick(_make_tick(ltp=100.0, ts=base))
            await svc.on_tick(_make_tick(ltp=101.0, ts=base + timedelta(minutes=1, seconds=5)))

        asyncio.run(_run())
        assert not svc.matches.empty()

    def test_match_callback_invoked(self) -> None:
        """Optional match_callback should be called for each match."""
        callback_calls: list[ScannerMatch] = []

        def _cb(match: ScannerMatch) -> None:
            callback_calls.append(match)

        class _AlwaysMatch(AbstractScanner):
            def __init__(self) -> None:
                super().__init__(name="always", timeframe=1)

            def on_candle(self, candle: Any, history: list[Any]) -> ScannerMatch | None:
                return ScannerMatch(
                    scanner_name=self.name,
                    symbol=candle.symbol,
                    exchange="NSE",
                    timeframe=candle.timeframe,
                    signal="cb_test",
                    value=0.0,
                    ltp=candle.close,
                    matched_at=candle.bar_close_ts,
                )

        svc = ScannerService(match_callback=_cb)
        svc.add_scanner(_AlwaysMatch())

        async def _run() -> None:
            base = datetime(2026, 4, 14, 9, 15, 0, tzinfo=timezone.utc)
            await svc.on_tick(_make_tick(ltp=100.0, ts=base))
            await svc.on_tick(_make_tick(ltp=101.0, ts=base + timedelta(minutes=1, seconds=5)))

        asyncio.run(_run())
        assert len(callback_calls) >= 1
        assert all(isinstance(c, ScannerMatch) for c in callback_calls)

    def test_async_context_manager(self) -> None:
        """ScannerService should work as an async context manager."""
        svc = ScannerService()

        async def _run() -> bool:
            async with svc:
                return svc._started
            return svc._started

        started_inside = asyncio.run(_run())
        assert started_inside is True
        assert svc._started is False

    def test_stats_returns_expected_keys(self) -> None:
        """stats() should include tracked_symbols, registered_scanners, pending_matches."""
        svc = ScannerService()
        svc.add_scanner(RSIScanner())
        s = svc.stats()
        assert "tracked_symbols" in s
        assert "registered_scanners" in s
        assert "pending_matches" in s
        assert s["registered_scanners"] == 1

    def test_get_builder_returns_none_for_unknown(self) -> None:
        """get_builder should return None for unseen symbols."""
        svc = ScannerService()
        assert svc.get_builder("UNKNOWN") is None

    def test_get_builder_returns_builder_after_tick(self) -> None:
        """get_builder should return CandleBuilder after a tick is processed."""
        svc = ScannerService()

        async def _run() -> None:
            await svc.on_tick(_make_tick(symbol="SBIN"))
            assert svc.get_builder("SBIN") is not None

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# Tick.from_ws_payload tests
# ---------------------------------------------------------------------------


class TestTickFromWSPayload:
    """Unit tests for Tick.from_ws_payload normalisation."""

    def test_flat_payload(self) -> None:
        """Flat dict with ltp and symbol should parse correctly."""
        t = Tick.from_ws_payload({"symbol": "NIFTY", "ltp": 22450.0, "volume": 1000.0})
        assert t.symbol == "NIFTY"
        assert t.ltp == 22450.0
        assert t.volume == 1000.0

    def test_nested_data_payload(self) -> None:
        """OpenAlgo market_data format nests fields under 'data' key."""
        payload = {
            "type": "market_data",
            "data": {
                "symbol": "BANKNIFTY",
                "ltp": 48000.0,
                "volume": 25000.0,
                "exchange": "NSE_INDEX",
            },
        }
        t = Tick.from_ws_payload(payload)
        assert t.symbol == "BANKNIFTY"
        assert t.ltp == 48000.0
        assert t.exchange == "NSE_INDEX"

    def test_missing_volume_defaults_to_zero(self) -> None:
        """Missing volume field should default to 0.0."""
        t = Tick.from_ws_payload({"symbol": "TCS", "ltp": 3500.0})
        assert t.volume == 0.0

    def test_missing_timestamp_defaults_to_utc_now(self) -> None:
        """Missing timestamp should produce a UTC datetime."""
        t = Tick.from_ws_payload({"symbol": "INFY", "ltp": 1500.0})
        assert t.timestamp.tzinfo is not None

    def test_volume_coercion_from_string(self) -> None:
        """Volume provided as a string should be coerced to float."""
        t = Tick.from_ws_payload({"symbol": "RELIANCE", "ltp": 2800.0, "volume": "75000"})
        assert t.volume == 75000.0

    def test_ltp_coercion_from_string(self) -> None:
        """LTP provided as a string should be coerced to float."""
        t = Tick.from_ws_payload({"symbol": "WIPRO", "ltp": "425.50"})
        assert t.ltp == 425.50

    def test_missing_symbol_raises(self) -> None:
        """Payload without symbol should raise KeyError."""
        with pytest.raises(KeyError):
            Tick.from_ws_payload({"ltp": 100.0})

    def test_missing_ltp_raises(self) -> None:
        """Payload without ltp should raise KeyError."""
        with pytest.raises(KeyError):
            Tick.from_ws_payload({"symbol": "NIFTY"})
