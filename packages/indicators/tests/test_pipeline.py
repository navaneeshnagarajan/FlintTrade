"""Tests for IndicatorPipeline.

5+ tests covering single-stage, multi-stage, None propagation, reset, and
the empty-stages guard.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# TestIndicatorPipeline
# ---------------------------------------------------------------------------


class TestIndicatorPipeline:
    def test_single_stage_behaves_like_stage_directly(self):
        """A single-stage pipeline should produce the same output as the stage alone."""
        from packages.indicators.src.streaming import StreamingEMA
        from packages.indicators.src.pipeline import IndicatorPipeline

        prices = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
        period = 3

        direct = StreamingEMA(period)
        pipeline = IndicatorPipeline(StreamingEMA(period))

        for p in prices:
            d = direct.update(p)
            pl = pipeline.update(p)
            if d is None:
                assert pl is None
            else:
                assert pl == pytest.approx(d)

    def test_two_stage_pipeline_chains_correctly(self):
        """EMA(5) → EMA(3) pipeline: output matches manually chained stages."""
        from packages.indicators.src.streaming import StreamingEMA
        from packages.indicators.src.pipeline import IndicatorPipeline

        import numpy as np
        prices = list(100.0 + np.cumsum(np.random.default_rng(1).normal(0, 1, 60)))

        stage1a = StreamingEMA(5)
        stage2a = StreamingEMA(3)

        pipeline = IndicatorPipeline(StreamingEMA(5), StreamingEMA(3))

        for p in prices:
            mid = stage1a.update(p)
            if mid is not None:
                expected = stage2a.update(mid)
            else:
                expected = None
            actual = pipeline.update(p)
            if expected is None:
                assert actual is None
            else:
                assert actual == pytest.approx(expected)

    def test_none_propagates_through_pipeline(self):
        """If the first stage is warming up, the pipeline returns None."""
        from packages.indicators.src.streaming import StreamingEMA
        from packages.indicators.src.pipeline import IndicatorPipeline

        pipeline = IndicatorPipeline(StreamingEMA(10), StreamingEMA(3))
        for i in range(9):
            assert pipeline.update(float(i)) is None

    def test_empty_stages_raises(self):
        from packages.indicators.src.pipeline import IndicatorPipeline

        with pytest.raises(ValueError):
            IndicatorPipeline()

    def test_reset_clears_all_stages(self):
        from packages.indicators.src.streaming import StreamingEMA
        from packages.indicators.src.pipeline import IndicatorPipeline

        pipeline = IndicatorPipeline(StreamingEMA(3), StreamingEMA(3))
        for p in [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]:
            pipeline.update(p)
        pipeline.reset()
        # After reset the pipeline should be back to warm-up state
        assert pipeline.update(1.0) is None

    def test_stages_property_exposes_all_stages(self):
        from packages.indicators.src.streaming import StreamingEMA, StreamingSMA
        from packages.indicators.src.pipeline import IndicatorPipeline

        e = StreamingEMA(5)
        s = StreamingSMA(3)
        pipeline = IndicatorPipeline(e, s)
        assert len(pipeline.stages) == 2
        assert pipeline.stages[0] is e
        assert pipeline.stages[1] is s
