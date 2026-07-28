"""Tests for the live market signals pipeline (v0.5.0).

Covers: tick processing, threshold-based signal generation, recent signals
ordering, ring buffer max size, configuration updates, and edge cases.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest


class _SequenceIndicator:
    """Return predetermined values while exercising the pipeline state machine."""

    def __init__(self, values: list[float], period: int = 2) -> None:
        self._values = iter(values)
        self.period = period
        self.update_count = 0

    def update(self, _value: float) -> float:
        self.update_count += 1
        return next(self._values)


class _SequenceMACD:
    """Return predetermined MACD histogram tuples, mimicking StreamingMACD.update."""

    def __init__(self, histograms: list[float]) -> None:
        self._values = iter(histograms)
        self.update_count = 0

    def update(self, _price: float) -> tuple[float | None, float | None, float | None]:
        self.update_count += 1
        histogram = next(self._values)
        return histogram, 0.0, histogram


class TestSignalModels:
    """Tests for Signal and SignalConfig dataclasses."""

    def test_signal_to_dict(self):
        from flinttrade_ai.signal_models import Signal

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

    def test_signal_to_dict_deep_copies_metadata(self) -> None:
        from flinttrade_ai.signal_models import SignalEvent

        event = SignalEvent(metadata={"context": {"tags": ["retained"]}})

        payload = event.to_dict()
        payload["metadata"]["context"]["tags"].append("mutated")  # type: ignore[index]

        assert event.metadata == {"context": {"tags": ["retained"]}}

    def test_signal_defaults(self):
        from flinttrade_ai.signal_models import Signal

        sig = Signal()
        assert sig.signal_type == "ALERT"
        assert sig.confidence == 0.0

    def test_signal_config_defaults(self):
        from flinttrade_ai.signal_models import SignalConfig

        cfg = SignalConfig()
        assert cfg.instruments == ["NSE_INDEX:NIFTY", "NSE_INDEX:BANKNIFTY"]
        assert len(cfg.indicators) >= 1
        assert "rsi_oversold" in cfg.thresholds

    def test_signal_config_roundtrip(self):
        from flinttrade_ai.signal_models import SignalConfig

        cfg = SignalConfig(instruments=["nse:reliance"], thresholds={"rsi_oversold": 25})
        d = cfg.to_dict()
        cfg2 = SignalConfig.from_dict(d)
        assert cfg2.instruments == ["NSE:RELIANCE"]
        assert cfg2.thresholds["rsi_oversold"] == 25

    def test_signal_config_serialisation_is_a_deep_copy(self) -> None:
        from flinttrade_ai.signal_models import SignalConfig

        config = SignalConfig()
        payload = config.to_dict()

        payload["instruments"].append("NSE:TEST")  # type: ignore[union-attr]
        payload["indicators"][0]["params"]["period"] = 999  # type: ignore[index]
        payload["thresholds"]["rsi_oversold"] = 1.0  # type: ignore[index]

        assert config.instruments == ["NSE_INDEX:NIFTY", "NSE_INDEX:BANKNIFTY"]
        assert config.indicators[0]["params"] == {"period": 14}
        assert config.thresholds["rsi_oversold"] == 30.0

    @pytest.mark.parametrize(
        "instruments",
        [
            ["RELIANCE"],
            ["NSE:"],
            [":RELIANCE"],
            [""],
            ["NSE:REL:IANCE"],
            ["N SE:RELIANCE"],
            ["NSE:REL IANCE"],
            [" NSE:RELIANCE"],
            ["NSE:RELIANCE "],
            [123],
            [None],
        ],
    )
    def test_signal_config_rejects_invalid_instruments(self, instruments: list[object]) -> None:
        from flinttrade_ai.signal_models import SignalConfig

        with pytest.raises(ValueError, match="EXCHANGE:SYMBOL"):
            SignalConfig(instruments=instruments)  # type: ignore[arg-type]

    def test_signal_config_allows_empty_instrument_list(self) -> None:
        from flinttrade_ai.signal_models import SignalConfig

        assert SignalConfig(instruments=[]).instruments == []

    def test_signal_config_deduplicates_normalised_instrument_identities(self) -> None:
        from flinttrade_ai.signal_models import SignalConfig

        assert SignalConfig(instruments=["nse:reliance", "NSE:RELIANCE"]).instruments == ["NSE:RELIANCE"]

    @pytest.mark.parametrize(
        ("indicators", "message"),
        [
            (["RSI"], "mappings"),
            ([{"name": [], "params": {}}], "supported"),
            ([{"name": "Unsupported", "params": {}}], "supported"),
            ([{"name": "RSI", "params": "14"}], "params"),
            ([{"name": "RSI", "params": {"period": math.nan}}], "period"),
            ([{"name": "RSI", "params": {"period": 10_001}}], "at most 10000"),
            ([{"name": "RSI", "params": {"period": 10**400}}], "at most 10000"),
            ([{"name": "EMA_Cross", "params": {"fast": 21, "slow": 9}}], "fast"),
            ([{"name": "MACD", "params": {"fast": 12, "slow": 26, "signal": 0}}], "signal"),
        ],
    )
    def test_signal_config_rejects_invalid_indicators(self, indicators: object, message: str) -> None:
        from flinttrade_ai.signal_models import SignalConfig

        with pytest.raises(ValueError, match=message):
            SignalConfig(indicators=indicators)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        ("thresholds", "message"),
        [
            ({"rsi_oversold": "30"}, "numeric"),
            ({"rsi_oversold": math.nan}, "finite"),
            ({"rsi_overbought": math.inf}, "finite"),
            ({"rsi_oversold": 80, "rsi_overbought": 70}, "oversold"),
            ({"rsi_overbought": 100}, "between"),
            ({"ema_cross_min_pct": -0.01}, "non-negative"),
            ({"macd_crossover_min": -1}, "non-negative"),
            ({"macd_crossover_min": 10**400}, "finite"),
            ({"unknown_threshold": 1}, "unsupported"),
        ],
    )
    def test_signal_config_rejects_invalid_thresholds(self, thresholds: object, message: str) -> None:
        from flinttrade_ai.signal_models import SignalConfig

        with pytest.raises(ValueError, match=message):
            SignalConfig(thresholds=thresholds)  # type: ignore[arg-type]


class TestLiveSignalPipeline:
    """Tests for the LiveSignalPipeline tick processing engine."""

    def _make_pipeline(self, **kwargs):
        from flinttrade_ai.signal_pipeline import LiveSignalPipeline

        defaults = {
            "instruments": ["NSE_INDEX:NIFTY"],
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
            result = pipeline.process_tick("NSE_INDEX", "NIFTY", 100.0)
        assert result is None

    def test_rsi_oversold_generates_buy(self):
        """Steadily falling prices should push RSI below oversold and produce BUY."""
        pipeline = self._make_pipeline()
        # Seed with stable prices so RSI initialises around midpoint
        for i in range(16):
            pipeline.process_tick("NSE_INDEX", "NIFTY", 100.0 + (i % 2) * 0.1)
        # Now feed consistently falling prices to drive RSI below 30
        signal = None
        for i in range(40):
            result = pipeline.process_tick("NSE_INDEX", "NIFTY", 100.0 - (i + 1) * 1.5)
            if result is not None and result.signal_type == "BUY":
                signal = result
                break
        assert signal is not None
        assert signal.signal_type == "BUY"
        assert signal.indicator == "RSI"
        assert signal.symbol == "NIFTY"
        assert signal.exchange == "NSE_INDEX"

    def test_rsi_overbought_generates_sell(self):
        """Steadily rising prices should push RSI above overbought and produce SELL."""
        pipeline = self._make_pipeline()
        # Seed with stable prices
        for i in range(16):
            pipeline.process_tick("NSE_INDEX", "NIFTY", 100.0 + (i % 2) * 0.1)
        # Now feed consistently rising prices to drive RSI above 70
        signal = None
        for i in range(40):
            result = pipeline.process_tick("NSE_INDEX", "NIFTY", 100.0 + (i + 1) * 1.5)
            if result is not None and result.signal_type == "SELL":
                signal = result
                break
        assert signal is not None
        assert signal.signal_type == "SELL"
        assert signal.indicator == "RSI"
        assert signal.exchange == "NSE_INDEX"

    @pytest.mark.parametrize(
        ("rsi_values", "signal_type"),
        [
            ([50.0, 20.0, 10.0, 40.0, 20.0], "BUY"),
            ([50.0, 80.0, 90.0, 60.0, 80.0], "SELL"),
        ],
    )
    def test_rsi_emits_once_per_zone_entry(
        self,
        rsi_values: list[float],
        signal_type: str,
    ) -> None:
        pipeline = self._make_pipeline()
        state = pipeline._get_or_create_state("NSE_INDEX", "NIFTY")
        state.rsi = _SequenceIndicator(rsi_values)  # type: ignore[assignment]

        emissions = [
            (index, signal.signal_type)
            for index in range(len(rsi_values))
            if (signal := pipeline.process_tick("NSE_INDEX", "NIFTY", 100.0)) is not None
        ]

        assert emissions == [(1, signal_type), (4, signal_type)]

    def test_rsi_event_does_not_block_other_indicator_state_updates(self) -> None:
        from flinttrade_ai.signal_pipeline import LiveSignalPipeline

        pipeline = LiveSignalPipeline(
            instruments=["NSE:TEST"],
            indicators=[
                {"name": "RSI", "params": {"period": 2}},
                {"name": "EMA_Cross", "params": {"fast": 2, "slow": 4}},
                {"name": "MACD", "params": {"fast": 2, "slow": 4, "signal": 2}},
            ],
            thresholds={
                "rsi_oversold": 30.0,
                "rsi_overbought": 70.0,
                "ema_cross_min_pct": 0.0,
                "macd_crossover_min": 0.0,
            },
        )
        state = pipeline._get_or_create_state("NSE", "TEST")
        state.rsi = _SequenceIndicator([50.0, 20.0, 20.0])  # type: ignore[assignment]
        state.ema_fast = _SequenceIndicator([99.0, 101.0, 102.0])  # type: ignore[assignment]
        state.ema_slow = _SequenceIndicator([100.0, 100.0, 100.0])  # type: ignore[assignment]
        state.macd = _SequenceMACD([-1.0, 1.0, 2.0])  # type: ignore[assignment]

        assert pipeline.process_tick("NSE", "TEST", 100.0) is None
        signal = pipeline.process_tick("NSE", "TEST", 100.0)

        assert signal is not None
        assert signal.indicator == "RSI"
        assert pipeline.latest_event_id == 1
        assert state.ema_fast.update_count == 2  # type: ignore[union-attr]
        assert state.ema_slow.update_count == 2  # type: ignore[union-attr]
        assert state.macd.update_count == 2  # type: ignore[union-attr]
        assert state.ema_last_nonzero_side == 1
        assert state.macd_last_nonzero_side == 1
        assert pipeline.process_tick("NSE", "TEST", 100.0) is None

    def test_no_signal_when_rsi_in_range(self):
        """Alternating small moves should keep RSI in mid-range and not trigger."""
        pipeline = self._make_pipeline()
        # Alternate around a mean so gains and losses balance → RSI ~50
        for i in range(50):
            price = 100.0 + (0.1 if i % 2 == 0 else -0.1)
            result = pipeline.process_tick("NSE_INDEX", "NIFTY", price)
        # After 50 balanced ticks, RSI should be around 50 — no signal
        assert result is None

    def test_recent_signals_newest_first(self):
        """get_recent_signals returns signals newest-first."""
        pipeline = self._make_pipeline()
        # Trigger multiple signals with different prices
        for i in range(20):
            pipeline.process_tick("NSE_INDEX", "NIFTY", 100.0 + i * 0.5)
        for i in range(30):
            pipeline.process_tick("NSE_INDEX", "NIFTY", 110.0 - i * 2.0)

        signals = pipeline.get_recent_signals(limit=10)
        if len(signals) >= 2:
            # Newest first: first signal should have a later or equal timestamp
            assert signals[0].timestamp >= signals[1].timestamp

    def test_max_signals_capped(self):
        """Ring buffer should not exceed _MAX_SIGNALS (100)."""
        from flinttrade_ai.signal_pipeline import _MAX_SIGNALS

        pipeline = self._make_pipeline()
        # Force many signals by alternating extreme prices
        for cycle in range(200):
            for i in range(20):
                pipeline.process_tick("NSE_INDEX", "NIFTY", 100.0 + i * 0.5)
            for i in range(30):
                pipeline.process_tick("NSE_INDEX", "NIFTY", 110.0 - i * 2.0)

        assert len(pipeline.signals) <= _MAX_SIGNALS

    def test_config_update_resets_indicator_state_without_clearing_signals(self):
        """A valid update resets warm-up state but preserves shared history."""
        from flinttrade_ai.signal_models import SignalEvent

        pipeline = self._make_pipeline()
        for i in range(20):
            pipeline.process_tick("NSE_INDEX", "NIFTY", 100.0 + i)
        pipeline.publish_signal(SignalEvent(symbol="NIFTY"))

        assert len(pipeline._states) > 0
        history = pipeline.get_recent_signals(limit=100)

        pipeline.update_config(instruments=["NSE_INDEX:BANKNIFTY"])
        assert pipeline.config.instruments == ["NSE_INDEX:BANKNIFTY"]
        assert len(pipeline._states) == 0
        assert pipeline.get_recent_signals(limit=100) == history

    def test_config_partial_update(self):
        """update_config with only thresholds should leave instruments unchanged."""
        pipeline = self._make_pipeline()
        pipeline.update_config(thresholds={"rsi_oversold": 25.0, "rsi_overbought": 75.0})
        assert pipeline.config.instruments == ["NSE_INDEX:NIFTY"]
        assert pipeline.config.thresholds["rsi_oversold"] == 25.0

    def test_partial_threshold_update_preserves_customised_siblings(self) -> None:
        pipeline = self._make_pipeline(
            thresholds={
                "rsi_oversold": 25.0,
                "rsi_overbought": 75.0,
                "ema_cross_min_pct": 0.5,
                "macd_crossover_min": 0.25,
            }
        )

        updated = pipeline.update_config(thresholds={"ema_cross_min_pct": 1.0})

        assert updated.thresholds == {
            "rsi_oversold": 25.0,
            "rsi_overbought": 75.0,
            "ema_cross_min_pct": 1.0,
            "macd_crossover_min": 0.25,
        }

    def test_empty_threshold_patch_is_a_non_destructive_noop(self) -> None:
        pipeline = self._make_pipeline()
        pipeline.process_tick("NSE_INDEX", "NIFTY", 100.0)
        state = pipeline._states[("NSE_INDEX", "NIFTY")]
        before = pipeline.get_config().thresholds

        updated = pipeline.update_config(thresholds={})

        assert updated.thresholds == before
        assert pipeline._states[("NSE_INDEX", "NIFTY")] is state

    def test_reordered_equivalent_allowlist_preserves_warmed_state(self) -> None:
        pipeline = self._make_pipeline(instruments=["NSE:RELIANCE", "BSE:RELIANCE"])
        pipeline.process_tick("NSE", "RELIANCE", 100.0)
        state = pipeline._states[("NSE", "RELIANCE")]

        updated = pipeline.update_config(instruments=["BSE:RELIANCE", "NSE:RELIANCE"])

        assert updated.instruments == ["NSE:RELIANCE", "BSE:RELIANCE"]
        assert pipeline._states[("NSE", "RELIANCE")] is state

    def test_get_config(self):
        """get_config returns the current SignalConfig."""
        pipeline = self._make_pipeline()
        cfg = pipeline.get_config()
        assert cfg.instruments == ["NSE_INDEX:NIFTY"]

    def test_config_accessors_return_isolated_validated_snapshots(self) -> None:
        pipeline = self._make_pipeline()

        snapshots = [pipeline.config, pipeline.get_config()]
        updated = pipeline.update_config(thresholds={"rsi_oversold": 25.0, "rsi_overbought": 75.0})
        snapshots.append(updated)

        for snapshot in snapshots:
            snapshot.instruments.append("INVALID")
            snapshot.indicators[0]["params"]["period"] = 0  # type: ignore[index]
            snapshot.thresholds["rsi_oversold"] = -1.0

        live = pipeline.get_config()
        assert live.instruments == ["NSE_INDEX:NIFTY"]
        assert live.indicators[0]["params"] == {"period": 14}
        assert live.thresholds == {"rsi_oversold": 25.0, "rsi_overbought": 75.0}

    def test_ema_crossover_events_retain_exchange(self):
        """EMA bullish and bearish crossover events retain the exchange."""
        from flinttrade_ai.signal_pipeline import LiveSignalPipeline

        pipeline = LiveSignalPipeline(
            instruments=["NSE_INDEX:NIFTY"],
            indicators=[{"name": "EMA_Cross", "params": {"fast": 5, "slow": 10}}],
            thresholds={},
        )
        # Feed falling prices to set slow > fast, then force a bullish cross.
        for i in range(20):
            pipeline.process_tick("NSE_INDEX", "NIFTY", 100.0 - i * 0.5)
        buy_signal = None
        for i in range(30):
            result = pipeline.process_tick("NSE_INDEX", "NIFTY", 90.0 + i * 2.0)
            if result is not None and result.signal_type == "BUY":
                buy_signal = result
                break
        assert buy_signal is not None
        assert buy_signal.indicator == "EMA_Cross"
        assert buy_signal.exchange == "NSE_INDEX"

        # Stabilise above the slow EMA, then force the bearish branch.
        for _ in range(20):
            pipeline.process_tick("NSE_INDEX", "NIFTY", 150.0)
        sell_signal = None
        for i in range(40):
            result = pipeline.process_tick("NSE_INDEX", "NIFTY", 150.0 - i * 2.0)
            if result is not None and result.signal_type == "SELL":
                sell_signal = result
                break
        assert sell_signal is not None
        assert sell_signal.indicator == "EMA_Cross"
        assert sell_signal.exchange == "NSE_INDEX"

    @pytest.mark.parametrize(
        ("movement", "signal_type", "threshold"),
        [
            ([101.0, 102.0, 104.0, 106.0], "BUY", 1.0),
            ([99.0, 98.0, 96.0, 94.0], "SELL", -1.0),
        ],
    )
    def test_ema_minimum_triggers_after_the_zero_crossing(
        self,
        movement: list[float],
        signal_type: str,
        threshold: float,
    ) -> None:
        """A non-zero EMA minimum is a signed percentage crossing."""
        from flinttrade_ai.signal_pipeline import LiveSignalPipeline

        pipeline = LiveSignalPipeline(
            instruments=["NSE:TEST"],
            indicators=[{"name": "EMA_Cross", "params": {"fast": 2, "slow": 4}}],
            thresholds={"ema_cross_min_pct": 1.0},
        )

        results = [pipeline.process_tick("NSE", "TEST", price) for price in [100.0] * 5 + movement]

        assert all(result is None for result in results[:-1])
        signal = results[-1]
        assert signal is not None
        assert signal.signal_type == signal_type
        assert signal.threshold == threshold
        assert signal.value * threshold > 1.0

    def test_ema_minimum_requires_zero_recross_before_rearming(self) -> None:
        from flinttrade_ai.signal_pipeline import LiveSignalPipeline

        spreads = [-0.2, 0.2, 1.2, 0.8, 1.2, 0.7, -0.2, 0.2, 1.2]
        pipeline = LiveSignalPipeline(
            instruments=["NSE:TEST"],
            indicators=[{"name": "EMA_Cross", "params": {"fast": 2, "slow": 4}}],
            thresholds={"ema_cross_min_pct": 1.0},
        )
        state = pipeline._get_or_create_state("NSE", "TEST")
        state.ema_fast = _SequenceIndicator([100.0 + spread for spread in spreads])  # type: ignore[assignment]
        state.ema_slow = _SequenceIndicator([100.0] * len(spreads))  # type: ignore[assignment]

        emissions = [
            (index, signal.signal_type)
            for index, _spread in enumerate(spreads)
            if (signal := pipeline.process_tick("NSE", "TEST", 100.0)) is not None
        ]

        assert emissions == [(2, "BUY"), (8, "BUY")]

    @pytest.mark.parametrize(
        ("spreads", "signal_type"),
        [
            ([-0.2, 0.2, 1.2, 0.0, 0.8, 1.2], "BUY"),
            ([0.2, -0.2, -1.2, 0.0, -0.8, -1.2], "SELL"),
        ],
    )
    def test_ema_exact_zero_bounce_does_not_rearm(
        self,
        spreads: list[float],
        signal_type: str,
    ) -> None:
        from flinttrade_ai.signal_pipeline import LiveSignalPipeline

        pipeline = LiveSignalPipeline(
            instruments=["NSE:TEST"],
            indicators=[{"name": "EMA_Cross", "params": {"fast": 2, "slow": 4}}],
            thresholds={"ema_cross_min_pct": 1.0},
        )
        state = pipeline._get_or_create_state("NSE", "TEST")
        state.ema_fast = _SequenceIndicator([100.0 + spread for spread in spreads])  # type: ignore[assignment]
        state.ema_slow = _SequenceIndicator([100.0] * len(spreads))  # type: ignore[assignment]

        emissions = [
            (index, signal.signal_type)
            for index, _spread in enumerate(spreads)
            if (signal := pipeline.process_tick("NSE", "TEST", 100.0)) is not None
        ]

        assert emissions == [(2, signal_type)]

    def test_macd_crossover_events_retain_exchange(self):
        """MACD bullish and bearish histogram crosses retain the exchange."""
        from flinttrade_ai.signal_pipeline import LiveSignalPipeline

        pipeline = LiveSignalPipeline(
            instruments=["NSE_INDEX:NIFTY"],
            indicators=[{"name": "MACD", "params": {"fast": 5, "slow": 10, "signal": 3}}],
            thresholds={},
        )
        # Feed falling then rising to get a bullish histogram crossover.
        for i in range(20):
            pipeline.process_tick("NSE_INDEX", "NIFTY", 100.0 - i * 0.3)
        buy_signal = None
        for i in range(40):
            result = pipeline.process_tick("NSE_INDEX", "NIFTY", 94.0 + i * 1.5)
            if result is not None and result.signal_type == "BUY":
                buy_signal = result
                break
        assert buy_signal is not None
        assert buy_signal.indicator == "MACD"
        assert buy_signal.exchange == "NSE_INDEX"

        # Stabilise after the bullish cross, then force the bearish branch.
        sell_signal = None
        prices = [155.0] * 20 + [155.0 - i * 1.5 for i in range(50)]
        for price in prices:
            result = pipeline.process_tick("NSE_INDEX", "NIFTY", price)
            if result is not None and result.signal_type == "SELL":
                sell_signal = result
                break
        assert sell_signal is not None
        assert sell_signal.indicator == "MACD"
        assert sell_signal.exchange == "NSE_INDEX"

    @pytest.mark.parametrize(
        ("movement", "signal_type", "threshold"),
        [
            ([110.0, 120.0], "BUY", 1.0),
            ([90.0, 80.0], "SELL", -1.0),
        ],
    )
    def test_macd_minimum_triggers_after_the_zero_crossing(
        self,
        movement: list[float],
        signal_type: str,
        threshold: float,
    ) -> None:
        """A non-zero MACD minimum is a signed histogram crossing."""
        from flinttrade_ai.signal_pipeline import LiveSignalPipeline

        pipeline = LiveSignalPipeline(
            instruments=["NSE:TEST"],
            indicators=[{"name": "MACD", "params": {"fast": 2, "slow": 4, "signal": 2}}],
            thresholds={"macd_crossover_min": 1.0},
        )

        results = [pipeline.process_tick("NSE", "TEST", price) for price in [100.0] * 6 + movement]

        assert all(result is None for result in results[:-1])
        signal = results[-1]
        assert signal is not None
        assert signal.signal_type == signal_type
        assert signal.threshold == threshold
        assert signal.value * threshold > 1.0

    def test_macd_minimum_requires_zero_recross_before_rearming(self) -> None:
        from flinttrade_ai.signal_pipeline import LiveSignalPipeline

        histograms = [-0.2, 0.2, 1.2, 0.8, 1.2, 0.7, -0.2, 0.2, 1.2]
        pipeline = LiveSignalPipeline(
            instruments=["NSE:TEST"],
            indicators=[{"name": "MACD", "params": {"fast": 2, "slow": 4, "signal": 2}}],
            thresholds={"macd_crossover_min": 1.0},
        )
        state = pipeline._get_or_create_state("NSE", "TEST")
        state.macd = _SequenceMACD(histograms)  # type: ignore[assignment]

        emissions = [
            (index, signal.signal_type)
            for index, _histogram in enumerate(histograms)
            if (signal := pipeline.process_tick("NSE", "TEST", 100.0)) is not None
        ]

        assert emissions == [(2, "BUY"), (8, "BUY")]

    @pytest.mark.parametrize(
        ("histograms", "signal_type"),
        [
            ([-0.2, 0.2, 1.2, 0.0, 0.8, 1.2], "BUY"),
            ([0.2, -0.2, -1.2, 0.0, -0.8, -1.2], "SELL"),
        ],
    )
    def test_macd_exact_zero_bounce_does_not_rearm(
        self,
        histograms: list[float],
        signal_type: str,
    ) -> None:
        from flinttrade_ai.signal_pipeline import LiveSignalPipeline

        pipeline = LiveSignalPipeline(
            instruments=["NSE:TEST"],
            indicators=[{"name": "MACD", "params": {"fast": 2, "slow": 4, "signal": 2}}],
            thresholds={"macd_crossover_min": 1.0},
        )
        state = pipeline._get_or_create_state("NSE", "TEST")
        state.macd = _SequenceMACD(histograms)  # type: ignore[assignment]

        emissions = [
            (index, signal.signal_type)
            for index, _histogram in enumerate(histograms)
            if (signal := pipeline.process_tick("NSE", "TEST", 100.0)) is not None
        ]

        assert emissions == [(2, signal_type)]

    @pytest.mark.unit
    def test_macd_state_uses_streaming_macd_with_configured_periods(self) -> None:
        """The MACD path must consume StreamingMACD from flinttrade_indicators."""
        from flinttrade_ai.signal_pipeline import LiveSignalPipeline
        from flinttrade_indicators.streaming import StreamingMACD

        pipeline = LiveSignalPipeline(
            instruments=["NSE:TEST"],
            indicators=[{"name": "MACD", "params": {"fast": 5, "slow": 10, "signal": 3}}],
            thresholds={},
        )

        state = pipeline._get_or_create_state("NSE", "TEST")

        assert isinstance(state.macd, StreamingMACD)
        assert state.macd.fast_period == 5
        assert state.macd.slow_period == 10
        assert state.macd.signal_period == 3

    @pytest.mark.unit
    def test_streaming_macd_matches_chained_ema_reference_exactly(self) -> None:
        """StreamingMACD must reproduce the previous hand-rolled three-EMA chain bit-for-bit.

        The retired implementation fed the fast/slow EMA difference into a third
        StreamingEMA only once both were warm, and emitted histogram = macd - signal
        only once the signal EMA was warm.  StreamingMACD performs the identical
        operations in the identical order, so every value must match exactly.
        """
        from flinttrade_ai.signal_pipeline import LiveSignalPipeline
        from flinttrade_indicators.streaming import StreamingEMA, StreamingMACD

        pipeline = LiveSignalPipeline(
            instruments=["NSE:TEST"],
            indicators=[{"name": "MACD", "params": {"fast": 5, "slow": 10, "signal": 3}}],
            thresholds={},
        )
        reference_fast = StreamingEMA(period=5)
        reference_slow = StreamingEMA(period=10)
        reference_signal = StreamingEMA(period=3)
        prices = [100.0 - i * 0.3 for i in range(20)] + [94.0 + i * 1.5 for i in range(40)]

        for price in prices:
            pipeline.process_tick("NSE", "TEST", price)
            state = pipeline._states[("NSE", "TEST")]
            assert isinstance(state.macd, StreamingMACD)

            fast_val = reference_fast.update(price)
            slow_val = reference_slow.update(price)
            if fast_val is None or slow_val is None:
                assert state.macd.histogram is None
                continue
            macd_line = fast_val - slow_val
            signal_line = reference_signal.update(macd_line)
            if signal_line is None:
                assert state.macd.macd == macd_line
                assert state.macd.histogram is None
                continue

            assert state.macd.macd == macd_line
            assert state.macd.signal == signal_line
            assert state.macd.histogram == macd_line - signal_line

    @pytest.mark.parametrize("indicator", ["EMA_Cross", "MACD"])
    def test_first_nonzero_indicator_sample_seeds_side_without_emitting(self, indicator: str) -> None:
        from flinttrade_ai.signal_pipeline import LiveSignalPipeline

        params = {"fast": 2, "slow": 4} if indicator == "EMA_Cross" else {"fast": 2, "slow": 4, "signal": 2}
        threshold_name = "ema_cross_min_pct" if indicator == "EMA_Cross" else "macd_crossover_min"
        pipeline = LiveSignalPipeline(
            instruments=["NSE:TEST"],
            indicators=[{"name": indicator, "params": params}],
            thresholds={threshold_name: 1.0},
        )
        state = pipeline._get_or_create_state("NSE", "TEST")
        if indicator == "EMA_Cross":
            state.ema_fast = _SequenceIndicator([101.2, 101.4])  # type: ignore[assignment]
            state.ema_slow = _SequenceIndicator([100.0, 100.0])  # type: ignore[assignment]
        else:
            state.macd = _SequenceMACD([1.2, 1.4])  # type: ignore[assignment]

        results = [pipeline.process_tick("NSE", "TEST", 100.0) for _ in range(2)]

        assert results == [None, None]

    @pytest.mark.parametrize(
        ("indicator", "params", "prices", "signal_type"),
        [
            ("EMA_Cross", {"fast": 2, "slow": 4}, [100.0] * 5 + [101.0], "BUY"),
            ("MACD", {"fast": 2, "slow": 4, "signal": 2}, [100.0] * 6 + [110.0], "BUY"),
        ],
    )
    def test_zero_minimum_preserves_zero_crossing_behaviour(
        self,
        indicator: str,
        params: dict[str, int],
        prices: list[float],
        signal_type: str,
    ) -> None:
        from flinttrade_ai.signal_pipeline import LiveSignalPipeline

        threshold_name = "ema_cross_min_pct" if indicator == "EMA_Cross" else "macd_crossover_min"
        pipeline = LiveSignalPipeline(
            instruments=["NSE:TEST"],
            indicators=[{"name": indicator, "params": params}],
            thresholds={threshold_name: 0.0},
        )

        results = [pipeline.process_tick("NSE", "TEST", price) for price in prices]

        assert all(result is None for result in results[:-1])
        assert results[-1] is not None
        assert results[-1].signal_type == signal_type
        assert results[-1].threshold == 0.0

    def test_multi_instrument_isolation(self):
        """Each instrument should have independent indicator state."""
        pipeline = self._make_pipeline(instruments=["NSE_INDEX:NIFTY", "NSE_INDEX:BANKNIFTY"])
        pipeline.process_tick("NSE_INDEX", "NIFTY", 100.0)
        pipeline.process_tick("NSE_INDEX", "BANKNIFTY", 45000.0)
        assert ("NSE_INDEX", "NIFTY") in pipeline._states
        assert ("NSE_INDEX", "BANKNIFTY") in pipeline._states
        assert pipeline._states[("NSE_INDEX", "NIFTY")] is not pipeline._states[("NSE_INDEX", "BANKNIFTY")]

    def test_same_symbol_on_different_exchanges_never_shares_state(self) -> None:
        pipeline = self._make_pipeline(instruments=["NSE:RELIANCE", "BSE:RELIANCE"])

        pipeline.process_tick("nse", "reliance", 1_400.0)
        pipeline.process_tick("bse", "reliance", 1_500.0)

        assert set(pipeline._states) == {("NSE", "RELIANCE"), ("BSE", "RELIANCE")}
        assert pipeline._states[("NSE", "RELIANCE")] is not pipeline._states[("BSE", "RELIANCE")]

    @pytest.mark.parametrize("ltp", [0.0, -1.0, math.nan, math.inf, -math.inf, 10**400])
    def test_invalid_ticks_do_not_create_state(self, ltp: float | int) -> None:
        pipeline = self._make_pipeline()

        assert pipeline.process_tick("NSE_INDEX", "NIFTY", ltp) is None
        assert pipeline._states == {}

    def test_source_timestamp_is_preserved_and_out_of_order_tick_is_rejected(self) -> None:
        pipeline = self._make_pipeline(instruments=["NSE:TEST"])
        state = pipeline._get_or_create_state("NSE", "TEST")
        state.rsi = _SequenceIndicator([50.0, 20.0, 80.0])  # type: ignore[assignment]
        first_timestamp = datetime(2026, 7, 11, 3, 44, tzinfo=timezone.utc)
        signal_timestamp = datetime(2026, 7, 11, 3, 45, tzinfo=timezone.utc)

        assert pipeline.process_tick("NSE", "TEST", 100.0, 0, first_timestamp.timestamp()) is None
        signal = pipeline.process_tick("NSE", "TEST", 99.0, 0, signal_timestamp.timestamp())
        rejected = pipeline.process_tick(
            "NSE",
            "TEST",
            101.0,
            0,
            (signal_timestamp.timestamp() - 30.0),
        )

        assert signal is not None
        assert signal.timestamp == signal_timestamp.isoformat()
        assert rejected is None
        assert state.rsi.update_count == 2  # type: ignore[union-attr]
        assert pipeline.rejected_out_of_order_tick_count == 1

    def test_source_timestamp_ordering_survives_indicator_config_reset(self) -> None:
        pipeline = self._make_pipeline(instruments=["NSE:TEST"])
        accepted_at = datetime(2026, 7, 11, 3, 45, tzinfo=timezone.utc)

        assert pipeline.process_tick("NSE", "TEST", 100.0, 0, accepted_at.timestamp()) is None
        pipeline.update_config(thresholds={"rsi_oversold": 25.0, "rsi_overbought": 75.0})
        assert pipeline._states == {}

        assert pipeline.process_tick("NSE", "TEST", 99.0, 0, accepted_at.timestamp() - 1.0) is None
        assert pipeline._states == {}
        assert pipeline.rejected_out_of_order_tick_count == 1

    def test_ml_numeric_overflow_is_normalised_before_publication(self) -> None:
        pipeline = self._make_pipeline()

        published = pipeline.ingest_ml_cycle(
            {
                "NSE_INDEX:NIFTY": {
                    "signal": "BUY",
                    "method": "ml_model",
                    "ltp": 10**400,
                    "confidence": 10**400,
                    "turbulence_score": 10**400,
                }
            }
        )

        assert len(published) == 1
        assert published[0].event_id == 1
        assert published[0].value == 0.0
        assert published[0].confidence == 0.0
        assert published[0].metadata == {"ltp": 0.0, "turbulence_score": 0.0}

    def test_ml_cycle_emits_only_canonical_configured_identities(self) -> None:
        pipeline = self._make_pipeline(instruments=["nse:reliance"])

        published = pipeline.ingest_ml_cycle(
            {
                "BSE:RELIANCE": {
                    "signal": "SELL",
                    "method": "ml_model",
                    "ltp": 1_390.0,
                },
                "nse:reliance": {
                    "signal": "BUY",
                    "method": "ml_model",
                    "ltp": 1_400.0,
                },
            }
        )

        assert [(event.event_id, event.exchange, event.symbol) for event in published] == [
            (1, "NSE", "RELIANCE")
        ]
        assert pipeline.latest_event_id == 1

    @pytest.mark.parametrize("field_name", ["value", "threshold", "confidence"])
    def test_invalid_event_numbers_do_not_consume_event_ids(self, field_name: str) -> None:
        from flinttrade_ai.signal_models import SignalEvent

        pipeline = self._make_pipeline()
        invalid = SignalEvent(symbol="NIFTY")
        setattr(invalid, field_name, 10**400)

        with pytest.raises(ValueError, match=field_name):
            pipeline.publish_signal(invalid)

        assert pipeline.latest_event_id == 0
        assert pipeline.get_recent_signals() == []
        assert pipeline.publish_signal(SignalEvent(symbol="BANKNIFTY")).event_id == 1

    def test_publication_normalises_numeric_fields_before_assigning_an_id(self) -> None:
        from flinttrade_ai.signal_models import SignalEvent

        pipeline = self._make_pipeline()
        event = SignalEvent(symbol="NIFTY")
        event.value = "1.25"  # type: ignore[assignment]
        event.threshold = "1.0"  # type: ignore[assignment]
        event.confidence = "1.5"  # type: ignore[assignment]

        published = pipeline.publish_signal(event)

        assert published.event_id == 1
        assert published.value == 1.25
        assert published.threshold == 1.0
        assert published.confidence == 1.0

    def test_event_history_and_metadata_are_isolated_at_every_boundary(self) -> None:
        from flinttrade_ai.signal_models import SignalEvent

        pipeline = self._make_pipeline()
        source = SignalEvent(symbol="NIFTY", metadata={"context": {"tags": ["retained"]}})

        first = pipeline.publish_signal(source)
        second = pipeline.publish_signal(source)

        assert source.event_id == 0
        assert (first.event_id, second.event_id) == (1, 2)
        assert first is not source
        assert second is not source
        assert second is not first
        source.metadata["context"]["tags"].append("source")  # type: ignore[index]
        first.metadata["context"]["tags"].append("published")  # type: ignore[index]
        second.symbol = "MUTATED"

        direct = pipeline.signals
        direct[0].metadata["context"]["tags"].append("direct")  # type: ignore[index]
        recent = pipeline.get_recent_signals()
        assert [(event.event_id, event.symbol) for event in recent] == [(2, "NIFTY"), (1, "NIFTY")]
        assert all(event.metadata == {"context": {"tags": ["retained"]}} for event in recent)
        assert recent[0] is not second
        assert recent[1] is not first

        recent[0].metadata["context"]["tags"].append("recent")  # type: ignore[index]
        replay = pipeline.get_signals_after(0)
        assert [event.event_id for event in replay] == [1, 2]
        assert all(event.metadata == {"context": {"tags": ["retained"]}} for event in replay)

        replay[0].metadata["context"]["tags"].append("replay")  # type: ignore[index]
        waited = pipeline.wait_for_signals_after(0, timeout=0.0)
        assert [event.event_id for event in waited] == [1, 2]
        assert all(event.metadata == {"context": {"tags": ["retained"]}} for event in waited)

        waited[0].metadata["context"]["tags"].append("waited")  # type: ignore[index]
        final = pipeline.get_recent_signals()
        assert [(event.event_id, event.symbol) for event in final] == [(2, "NIFTY"), (1, "NIFTY")]
        assert all(event.metadata == {"context": {"tags": ["retained"]}} for event in final)

    def test_unconfigured_identity_is_ignored_before_state_creation(self) -> None:
        pipeline = self._make_pipeline(instruments=["NSE:RELIANCE"])

        assert pipeline.process_tick("BSE", "RELIANCE", 1_500.0) is None
        assert pipeline._states == {}

    def test_empty_constructor_allowlist_disables_all_rule_ticks(self) -> None:
        pipeline = self._make_pipeline(instruments=[])

        assert pipeline.config.instruments == []
        assert pipeline.process_tick("NSE_INDEX", "NIFTY", 24_500.0) is None
        assert pipeline._states == {}

    @pytest.mark.parametrize(("exchange", "symbol"), [("", "RELIANCE"), ("NSE", "")])
    def test_empty_tick_identity_does_not_create_state(self, exchange: str, symbol: str) -> None:
        pipeline = self._make_pipeline()

        assert pipeline.process_tick(exchange, symbol, 100.0) is None
        assert pipeline._states == {}

    def test_update_config_rejects_unqualified_instruments(self) -> None:
        pipeline = self._make_pipeline()

        with pytest.raises(ValueError, match="EXCHANGE:SYMBOL"):
            pipeline.update_config(instruments=["RELIANCE"])

    def test_invalid_config_update_preserves_live_config_and_state(self) -> None:
        from flinttrade_ai.signal_models import SignalEvent

        pipeline = self._make_pipeline()
        pipeline.process_tick("NSE_INDEX", "NIFTY", 100.0)
        event = pipeline.publish_signal(SignalEvent(symbol="NIFTY"))
        original_config = pipeline.get_config().to_dict()
        original_states = pipeline._states

        with pytest.raises(ValueError, match="params"):
            pipeline.update_config(indicators=[{"name": "RSI", "params": "14"}])

        assert pipeline.get_config().to_dict() == original_config
        assert pipeline._states is original_states
        assert pipeline.get_recent_signals() == [event]

    def test_config_update_preserves_bounded_history_and_monotonic_ids(self) -> None:
        from flinttrade_ai.signal_models import SignalEvent
        from flinttrade_ai.signal_pipeline import _MAX_SIGNALS

        pipeline = self._make_pipeline()
        for index in range(_MAX_SIGNALS + 5):
            pipeline.publish_signal(SignalEvent(symbol=f"NIFTY-{index}"))
        retained_before = pipeline.get_recent_signals(limit=_MAX_SIGNALS)

        pipeline.update_config(instruments=["NSE_INDEX:BANKNIFTY"])

        assert pipeline.get_recent_signals(limit=_MAX_SIGNALS) == retained_before
        assert len(pipeline.signals) == _MAX_SIGNALS

        next_event = pipeline.publish_signal(SignalEvent(symbol="BANKNIFTY"))
        assert next_event.event_id == _MAX_SIGNALS + 6
        assert pipeline.get_signals_after(_MAX_SIGNALS + 5) == [next_event]
        assert len(pipeline.signals) == _MAX_SIGNALS

    def test_signal_has_message(self):
        """Generated signals should have a non-empty message."""
        pipeline = self._make_pipeline()
        for i in range(20):
            pipeline.process_tick("NSE_INDEX", "NIFTY", 100.0 + i * 0.5)
        for i in range(30):
            result = pipeline.process_tick("NSE_INDEX", "NIFTY", 110.0 - i * 2.0)
            if result is not None:
                assert len(result.message) > 0
                break

    def test_signal_confidence_range(self):
        """Confidence should be between 0 and 1."""
        pipeline = self._make_pipeline()
        for i in range(20):
            pipeline.process_tick("NSE_INDEX", "NIFTY", 100.0 + i * 0.5)
        for i in range(30):
            result = pipeline.process_tick("NSE_INDEX", "NIFTY", 110.0 - i * 2.0)
            if result is not None:
                assert 0.0 <= result.confidence <= 1.0
                break

    def test_exports_in_init(self):
        """LiveSignalPipeline and friends should be exported from the package."""
        from flinttrade_ai import __all__

        assert "LiveSignalPipeline" in __all__
        assert "LiveSignal" in __all__
        assert "SignalConfig" in __all__

    def test_import_from_package(self):
        from flinttrade_ai import LiveSignalPipeline

        assert LiveSignalPipeline is not None
