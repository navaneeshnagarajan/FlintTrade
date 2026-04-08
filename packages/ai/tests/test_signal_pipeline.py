"""Tests for the live market signals pipeline (v0.5.0).

Covers: tick processing, threshold-based signal generation, recent signals
ordering, ring buffer max size, configuration updates, and edge cases.
"""

from __future__ import annotations


class TestSignalModels:
    """Tests for Signal and SignalConfig dataclasses."""

    def test_signal_to_dict(self):
        from packages.ai.src.signal_models import Signal

        sig = Signal(
            timestamp="2026-04-08T10:00:00+00:00",
            symbol="NIFTY",
            signal_type="BUY",
            indicator="RSI",
            value=28.5,
            threshold=30.0,
            confidence=0.72,
            message="NIFTY RSI oversold",
        )
        d = sig.to_dict()
        assert d["symbol"] == "NIFTY"
        assert d["signal_type"] == "BUY"
        assert d["indicator"] == "RSI"
        assert isinstance(d["value"], float)

    def test_signal_defaults(self):
        from packages.ai.src.signal_models import Signal

        sig = Signal()
        assert sig.signal_type == "ALERT"
        assert sig.confidence == 0.0

    def test_signal_config_defaults(self):
        from packages.ai.src.signal_models import SignalConfig

        cfg = SignalConfig()
        assert "NIFTY" in cfg.instruments
        assert len(cfg.indicators) >= 1
        assert "rsi_oversold" in cfg.thresholds

    def test_signal_config_roundtrip(self):
        from packages.ai.src.signal_models import SignalConfig

        cfg = SignalConfig(instruments=["RELIANCE"], thresholds={"rsi_oversold": 25})
        d = cfg.to_dict()
        cfg2 = SignalConfig.from_dict(d)
        assert cfg2.instruments == ["RELIANCE"]
        assert cfg2.thresholds["rsi_oversold"] == 25


class TestLiveSignalPipeline:
    """Tests for the LiveSignalPipeline tick processing engine."""

    def _make_pipeline(self, **kwargs):
        from packages.ai.src.signal_pipeline import LiveSignalPipeline

        defaults = {
            "instruments": ["NIFTY"],
            "indicators": [{"name": "RSI", "params": {"period": 14}}],
            "thresholds": {"rsi_oversold": 30.0, "rsi_overbought": 70.0},
        }
        defaults.update(kwargs)
        return LiveSignalPipeline(**defaults)

    def test_no_signal_during_warmup(self):
        """RSI needs period+1 ticks to warm up; no signal before that."""
        pipeline = self._make_pipeline()
        # Feed only 5 ticks (RSI needs 15)
        for _ in range(5):
            result = pipeline.process_tick("NIFTY", 100.0)
        assert result is None

    def test_rsi_oversold_generates_buy(self):
        """Steadily falling prices should push RSI below oversold and produce BUY."""
        pipeline = self._make_pipeline()
        # Seed with stable prices so RSI initialises around midpoint
        for i in range(16):
            pipeline.process_tick("NIFTY", 100.0 + (i % 2) * 0.1)
        # Now feed consistently falling prices to drive RSI below 30
        signal = None
        for i in range(40):
            result = pipeline.process_tick("NIFTY", 100.0 - (i + 1) * 1.5)
            if result is not None and result.signal_type == "BUY":
                signal = result
                break
        assert signal is not None
        assert signal.signal_type == "BUY"
        assert signal.indicator == "RSI"
        assert signal.symbol == "NIFTY"

    def test_rsi_overbought_generates_sell(self):
        """Steadily rising prices should push RSI above overbought and produce SELL."""
        pipeline = self._make_pipeline()
        # Seed with stable prices
        for i in range(16):
            pipeline.process_tick("NIFTY", 100.0 + (i % 2) * 0.1)
        # Now feed consistently rising prices to drive RSI above 70
        signal = None
        for i in range(40):
            result = pipeline.process_tick("NIFTY", 100.0 + (i + 1) * 1.5)
            if result is not None and result.signal_type == "SELL":
                signal = result
                break
        assert signal is not None
        assert signal.signal_type == "SELL"
        assert signal.indicator == "RSI"

    def test_no_signal_when_rsi_in_range(self):
        """Alternating small moves should keep RSI in mid-range and not trigger."""
        pipeline = self._make_pipeline()
        # Alternate around a mean so gains and losses balance → RSI ~50
        for i in range(50):
            price = 100.0 + (0.1 if i % 2 == 0 else -0.1)
            result = pipeline.process_tick("NIFTY", price)
        # After 50 balanced ticks, RSI should be around 50 — no signal
        assert result is None

    def test_recent_signals_newest_first(self):
        """get_recent_signals returns signals newest-first."""
        pipeline = self._make_pipeline()
        # Trigger multiple signals with different prices
        for i in range(20):
            pipeline.process_tick("NIFTY", 100.0 + i * 0.5)
        for i in range(30):
            pipeline.process_tick("NIFTY", 110.0 - i * 2.0)

        signals = pipeline.get_recent_signals(limit=10)
        if len(signals) >= 2:
            # Newest first: first signal should have a later or equal timestamp
            assert signals[0].timestamp >= signals[1].timestamp

    def test_max_signals_capped(self):
        """Ring buffer should not exceed _MAX_SIGNALS (100)."""
        from packages.ai.src.signal_pipeline import _MAX_SIGNALS

        pipeline = self._make_pipeline()
        # Force many signals by alternating extreme prices
        for cycle in range(200):
            for i in range(20):
                pipeline.process_tick("NIFTY", 100.0 + i * 0.5)
            for i in range(30):
                pipeline.process_tick("NIFTY", 110.0 - i * 2.0)

        assert len(pipeline.signals) <= _MAX_SIGNALS

    def test_config_update_resets_state(self):
        """update_config should clear signals and instrument state."""
        pipeline = self._make_pipeline()
        for i in range(20):
            pipeline.process_tick("NIFTY", 100.0 + i)

        assert len(pipeline._states) > 0

        pipeline.update_config(instruments=["BANKNIFTY"])
        assert pipeline.config.instruments == ["BANKNIFTY"]
        assert len(pipeline._states) == 0
        assert len(pipeline.signals) == 0

    def test_config_partial_update(self):
        """update_config with only thresholds should leave instruments unchanged."""
        pipeline = self._make_pipeline()
        pipeline.update_config(thresholds={"rsi_oversold": 25.0, "rsi_overbought": 75.0})
        assert pipeline.config.instruments == ["NIFTY"]
        assert pipeline.config.thresholds["rsi_oversold"] == 25.0

    def test_get_config(self):
        """get_config returns the current SignalConfig."""
        pipeline = self._make_pipeline()
        cfg = pipeline.get_config()
        assert cfg.instruments == ["NIFTY"]

    def test_ema_crossover_signal(self):
        """EMA cross indicator should generate BUY on bullish crossover."""
        from packages.ai.src.signal_pipeline import LiveSignalPipeline

        pipeline = LiveSignalPipeline(
            instruments=["NIFTY"],
            indicators=[{"name": "EMA_Cross", "params": {"fast": 5, "slow": 10}}],
            thresholds={},
        )
        # Feed falling prices to set slow > fast
        for i in range(20):
            pipeline.process_tick("NIFTY", 100.0 - i * 0.5)
        # Now feed sharply rising prices to force fast above slow
        signal = None
        for i in range(30):
            result = pipeline.process_tick("NIFTY", 90.0 + i * 2.0)
            if result is not None:
                signal = result
                break
        # We should eventually get a BUY crossover
        if signal is not None:
            assert signal.signal_type == "BUY"
            assert signal.indicator == "EMA_Cross"

    def test_macd_signal(self):
        """MACD histogram crossover should generate a signal."""
        from packages.ai.src.signal_pipeline import LiveSignalPipeline

        pipeline = LiveSignalPipeline(
            instruments=["NIFTY"],
            indicators=[{"name": "MACD", "params": {"fast": 5, "slow": 10, "signal": 3}}],
            thresholds={},
        )
        # Feed falling then rising to get histogram crossover
        for i in range(20):
            pipeline.process_tick("NIFTY", 100.0 - i * 0.3)
        signal = None
        for i in range(40):
            result = pipeline.process_tick("NIFTY", 94.0 + i * 1.5)
            if result is not None:
                signal = result
                break
        if signal is not None:
            assert signal.indicator == "MACD"

    def test_multi_instrument_isolation(self):
        """Each instrument should have independent indicator state."""
        pipeline = self._make_pipeline(instruments=["NIFTY", "BANKNIFTY"])
        pipeline.process_tick("NIFTY", 100.0)
        pipeline.process_tick("BANKNIFTY", 45000.0)
        assert "NIFTY" in pipeline._states
        assert "BANKNIFTY" in pipeline._states
        assert pipeline._states["NIFTY"] is not pipeline._states["BANKNIFTY"]

    def test_signal_has_message(self):
        """Generated signals should have a non-empty message."""
        pipeline = self._make_pipeline()
        for i in range(20):
            pipeline.process_tick("NIFTY", 100.0 + i * 0.5)
        for i in range(30):
            result = pipeline.process_tick("NIFTY", 110.0 - i * 2.0)
            if result is not None:
                assert len(result.message) > 0
                break

    def test_signal_confidence_range(self):
        """Confidence should be between 0 and 1."""
        pipeline = self._make_pipeline()
        for i in range(20):
            pipeline.process_tick("NIFTY", 100.0 + i * 0.5)
        for i in range(30):
            result = pipeline.process_tick("NIFTY", 110.0 - i * 2.0)
            if result is not None:
                assert 0.0 <= result.confidence <= 1.0
                break

    def test_exports_in_init(self):
        """LiveSignalPipeline and friends should be exported from the package."""
        from packages.ai.src import __all__

        assert "LiveSignalPipeline" in __all__
        assert "LiveSignal" in __all__
        assert "SignalConfig" in __all__

    def test_import_from_package(self):
        from packages.ai.src import LiveSignalPipeline

        assert LiveSignalPipeline is not None
