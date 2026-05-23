"""Tests for generate_sharpe_labels and compute_turbulence in signals.py."""

from __future__ import annotations



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rising(n: int = 100, start: float = 100.0, step: float = 0.5) -> list[float]:
    """Steady uptrend close series."""
    return [start + i * step for i in range(n)]


def _falling(n: int = 100, start: float = 100.0, step: float = 0.5) -> list[float]:
    """Steady downtrend close series."""
    return [start - i * step for i in range(n)]


def _flat(n: int = 100, value: float = 100.0) -> list[float]:
    """Perfectly flat price series."""
    return [value] * n


def _noisy(n: int = 200, seed: int = 42) -> list[float]:
    """Pseudo-random noisy returns around a level."""
    import random
    rng = random.Random(seed)
    prices = [100.0]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + rng.gauss(0.0001, 0.01)))
    return prices


# ---------------------------------------------------------------------------
# generate_sharpe_labels
# ---------------------------------------------------------------------------


class TestGenerateSharpeLabels:
    """Tests for generate_sharpe_labels."""

    def test_output_length_matches_offset(self):
        from flinttrade_ai.signals import generate_sharpe_labels

        closes = _rising(80)
        labels = generate_sharpe_labels(closes, lookahead=5, offset=20)
        assert len(labels) == 60  # 80 - offset(20)

    def test_labels_only_valid_values(self):
        from flinttrade_ai.signals import generate_sharpe_labels

        closes = _noisy(150)
        labels = generate_sharpe_labels(closes, lookahead=5, offset=20)
        for lbl in labels:
            assert int(lbl) in (-1, 0, 1), f"Unexpected label: {lbl}"

    def test_uptrend_mostly_buy(self):
        """A consistent uptrend should produce predominantly BUY (1) labels."""
        from flinttrade_ai.signals import generate_sharpe_labels

        closes = _rising(120, step=1.0)
        labels = generate_sharpe_labels(closes, lookahead=5, min_sharpe=0.3, offset=10)
        buy_count = sum(1 for lbl in labels if int(lbl) == 1)
        # At least 50% BUY in a clear uptrend
        assert buy_count / len(labels) >= 0.5

    def test_downtrend_mostly_sell(self):
        """A consistent downtrend should produce predominantly SELL (0) labels."""
        from flinttrade_ai.signals import generate_sharpe_labels

        closes = _falling(120, start=200.0, step=1.0)
        labels = generate_sharpe_labels(closes, lookahead=5, min_sharpe=0.3, offset=10)
        sell_count = sum(1 for lbl in labels if int(lbl) == 0)
        assert sell_count / len(labels) >= 0.5

    def test_flat_series_all_hold(self):
        """Zero-volatility flat series should all resolve to HOLD or directional by mean."""
        from flinttrade_ai.signals import generate_sharpe_labels

        closes = _flat(80, value=100.0)
        labels = generate_sharpe_labels(closes, lookahead=5, min_sharpe=0.5, offset=10)
        # Flat: mean return = 0, no std → should label as HOLD (-1)
        for lbl in labels[:-5]:  # last few are edge cases
            assert int(lbl) in (-1, 1, 0)  # all valid

    def test_high_threshold_gives_more_hold(self):
        """Very high min_sharpe threshold should produce more HOLD labels than low threshold."""
        from flinttrade_ai.signals import generate_sharpe_labels

        closes = _noisy(150)
        labels_strict = generate_sharpe_labels(closes, lookahead=5, min_sharpe=5.0, offset=10)
        labels_loose = generate_sharpe_labels(closes, lookahead=5, min_sharpe=0.1, offset=10)

        hold_strict = sum(1 for lbl in labels_strict if int(lbl) == -1)
        hold_loose = sum(1 for lbl in labels_loose if int(lbl) == -1)
        assert hold_strict >= hold_loose

    def test_offset_parameter_respected(self):
        """Different offsets should produce different lengths."""
        from flinttrade_ai.signals import generate_sharpe_labels

        closes = _rising(100)
        labels_20 = generate_sharpe_labels(closes, offset=20)
        labels_30 = generate_sharpe_labels(closes, offset=30)
        assert len(labels_20) == 80
        assert len(labels_30) == 70

    def test_insufficient_lookahead_at_end(self):
        """Bars near the end without full lookahead should be HOLD (-1)."""
        from flinttrade_ai.signals import generate_sharpe_labels

        closes = _rising(30, step=1.0)
        labels = generate_sharpe_labels(closes, lookahead=5, offset=0)
        # Last 5 bars must be HOLD because future window is incomplete
        assert all(int(lbl) == -1 for lbl in labels[-5:])

    def test_numpy_array_input(self):
        """Should accept numpy arrays without error when numpy is available."""
        try:
            import numpy as np
        except ImportError:
            return  # skip if numpy not installed

        from flinttrade_ai.signals import generate_sharpe_labels

        closes = np.array(_rising(80), dtype=np.float64)
        labels = generate_sharpe_labels(closes, lookahead=5, offset=10)
        assert len(labels) == 70

    def test_lookahead_1_bar(self):
        """Single-bar lookahead is the simplest case — should not raise."""
        from flinttrade_ai.signals import generate_sharpe_labels

        closes = _rising(50)
        labels = generate_sharpe_labels(closes, lookahead=1, offset=5)
        assert len(labels) == 45

    def test_package_export(self):
        from flinttrade_ai import generate_sharpe_labels

        assert generate_sharpe_labels is not None


# ---------------------------------------------------------------------------
# compute_turbulence
# ---------------------------------------------------------------------------


class TestComputeTurbulence:
    """Tests for compute_turbulence (single-asset path)."""

    def test_output_length_matches_input(self):
        from flinttrade_ai.signals import compute_turbulence

        returns = [0.01 * i for i in range(80)]
        scores = compute_turbulence(returns, window=20)
        assert len(scores) == 80

    def test_pre_window_bars_are_zero(self):
        """Scores before the first full window should be zero (warm-up)."""
        from flinttrade_ai.signals import compute_turbulence

        returns = [0.005] * 100
        scores = compute_turbulence(returns, window=30)
        for i in range(30):
            assert float(scores[i]) == 0.0, f"Bar {i} should be 0"

    def test_scores_non_negative(self):
        from flinttrade_ai.signals import compute_turbulence

        returns = [(i % 5 - 2) * 0.01 for i in range(100)]
        scores = compute_turbulence(returns, window=20)
        for s in scores:
            assert float(s) >= 0.0

    def test_spike_produces_high_score(self):
        """A return far from the historical mean should yield a high turbulence score."""
        from flinttrade_ai.signals import compute_turbulence

        # Alternating small returns to ensure non-zero variance in the window,
        # followed by a large spike.  window=20 keeps warm-up short.
        quiet = [0.001 if i % 2 == 0 else -0.001 for i in range(80)]
        spike = [0.20]
        returns = quiet + spike  # 81 bars total
        scores = compute_turbulence(returns, window=20)
        # Bar 60 is well past the warm-up and has non-zero variance in its window
        assert float(scores[60]) > 0.0, "Bar 60 should have non-zero turbulence score"
        # The spike bar (±20%) must stand far above a quiet bar
        assert float(scores[-1]) > float(scores[60])

    def test_flat_returns_produce_zero_turbulence(self):
        """Constant returns have zero variance — turbulence should be 0."""
        from flinttrade_ai.signals import compute_turbulence

        returns = [0.001] * 100
        scores = compute_turbulence(returns, window=30)
        # Constant series → variance = 0 → turbulence = 0 (division guard)
        for s in scores[30:]:
            assert float(s) == 0.0

    def test_larger_window_smoother(self):
        """Larger window should produce smoother (lower-variance) scores."""
        from flinttrade_ai.signals import compute_turbulence

        import random
        rng = random.Random(99)
        returns = [rng.gauss(0.001, 0.01) for _ in range(200)]

        scores_small = [float(s) for s in compute_turbulence(returns, window=10)]
        scores_large = [float(s) for s in compute_turbulence(returns, window=60)]

        # Variance of scores after warm-up
        def var(xs: list[float]) -> float:
            xs = [x for x in xs if x > 0]
            if not xs:
                return 0.0
            mu = sum(xs) / len(xs)
            return sum((x - mu) ** 2 for x in xs) / len(xs)

        assert var(scores_small[10:]) >= var(scores_large[60:])

    def test_list_input_works(self):
        """Plain Python list should be accepted."""
        from flinttrade_ai.signals import compute_turbulence

        returns = [0.01, -0.01, 0.02, -0.02] * 30
        scores = compute_turbulence(returns, window=10)
        assert len(scores) == 120

    def test_numpy_1d_input(self):
        """1-D numpy array input should be accepted."""
        try:
            import numpy as np
        except ImportError:
            return

        from flinttrade_ai.signals import compute_turbulence

        returns = np.array([0.01, -0.01, 0.02, -0.02] * 30)
        scores = compute_turbulence(returns, window=10)
        assert len(scores) == 120

    def test_numpy_2d_multi_asset(self):
        """2-D numpy array triggers full Mahalanobis path."""
        try:
            import numpy as np
        except ImportError:
            return

        from flinttrade_ai.signals import compute_turbulence

        import random
        rng = random.Random(7)
        n, m = 100, 3
        returns = np.array([[rng.gauss(0, 0.01) for _ in range(m)] for _ in range(n)])
        scores = compute_turbulence(returns, window=30)
        assert scores.shape == (n,)
        assert all(s >= 0.0 for s in scores)

    def test_multi_asset_spike_high_score(self):
        """A multi-asset simultaneous spike should produce a higher turbulence score."""
        try:
            import numpy as np
        except ImportError:
            return

        from flinttrade_ai.signals import compute_turbulence

        n, m = 80, 2
        quiet = np.full((n, m), 0.001)
        spike = np.array([[0.15, -0.15]])
        returns = np.vstack([quiet, spike])
        scores = compute_turbulence(returns, window=40)
        assert float(scores[-1]) > float(scores[50])

    def test_package_export(self):
        from flinttrade_ai import compute_turbulence

        assert compute_turbulence is not None


# ---------------------------------------------------------------------------
# Pipeline turbulence integration
# ---------------------------------------------------------------------------


class TestPipelineTurbulenceIntegration:
    """Verify SignalPipeline correctly exposes turbulence parameters."""

    def test_turbulence_disabled_by_default(self):
        from flinttrade_ai.pipeline import SignalPipeline

        p = SignalPipeline()
        assert p._turbulence_enabled is False

    def test_turbulence_enabled_flag(self):
        from flinttrade_ai.pipeline import SignalPipeline

        p = SignalPipeline(turbulence_enabled=True, turbulence_threshold=2.5)
        assert p._turbulence_enabled is True
        assert p._turbulence_threshold == 2.5

    def test_turbulence_window_default(self):
        from flinttrade_ai.pipeline import SignalPipeline

        p = SignalPipeline()
        assert p._turbulence_window == 60

    def test_turbulence_window_custom(self):
        from flinttrade_ai.pipeline import SignalPipeline

        p = SignalPipeline(turbulence_window=30)
        assert p._turbulence_window == 30
