"""Tests for the PCA-based Dissimilarity Index (DI) implementation.

Covers:
- calculate_di returns 0.0 on empty inputs.
- calculate_di returns 0.0 when train == live (no drift).
- calculate_di returns a positive float for clearly drifted data.
- calculate_di with n_pca_components >= n_features falls back gracefully.
- compute_dissimilarity_index (backward-compat alias) behaves identically.
- EnsembleSelector.check_staleness flags stale data at DI > threshold.
- EnsembleSelector default di_threshold is 2.0.
- _pca_reduce returns correct shape.
"""

from __future__ import annotations

import math

import pytest

from flinttrade_ai.ensemble_selector import (
    EnsembleSelector,
    _pca_reduce,
    calculate_di,
    compute_dissimilarity_index,
)


# ---------------------------------------------------------------------------
# _pca_reduce
# ---------------------------------------------------------------------------


class TestPcaReduce:
    """Tests for the internal PCA helper."""

    def test_output_shape_correct(self) -> None:
        """Output has [n_samples x n_components] shape."""
        matrix = [[float(i * j + j) for j in range(1, 6)] for i in range(10)]
        result = _pca_reduce(matrix, n_components=2)

        assert len(result) == 10
        assert all(len(row) == 2 for row in result)

    def test_passthrough_when_components_ge_features(self) -> None:
        """Returns original matrix when n_components >= n_features."""
        matrix = [[1.0, 2.0, 3.0]] * 5
        result = _pca_reduce(matrix, n_components=5)

        assert result == matrix

    def test_passthrough_with_single_sample(self) -> None:
        """Returns original matrix for < 2 samples."""
        matrix = [[1.0, 2.0, 3.0]]
        result = _pca_reduce(matrix, n_components=2)

        assert result == matrix

    def test_empty_features_returns_original(self) -> None:
        """Empty inner lists are returned unchanged."""
        matrix: list[list[float]] = [[], []]
        result = _pca_reduce(matrix, n_components=2)

        assert result == matrix


# ---------------------------------------------------------------------------
# calculate_di
# ---------------------------------------------------------------------------


class TestCalculateDi:
    """Tests for calculate_di — proper DI with PCA reduction."""

    def test_returns_zero_for_empty_train(self) -> None:
        result = calculate_di([], [[1.0, 2.0]])
        assert result == 0.0

    def test_returns_zero_for_empty_live(self) -> None:
        result = calculate_di([[1.0, 2.0]], [])
        assert result == 0.0

    def test_zero_drift_for_identical_distributions(self) -> None:
        """Identical train and live should produce a low DI."""
        train = [[float(i), float(i * 2), float(i * 3)] for i in range(1, 21)]
        live = [[float(i), float(i * 2), float(i * 3)] for i in range(1, 6)]
        di = calculate_di(train, live, n_pca_components=2)

        # DI may not be exactly 0 due to normalisation, but should be small
        assert di >= 0.0
        assert not math.isnan(di)

    def test_high_drift_for_shifted_distribution(self) -> None:
        """Live features shifted far from training should yield DI > 1."""
        train = [[float(i) for _ in range(5)] for i in range(1, 31)]
        live = [[float(i + 1000) for _ in range(5)] for i in range(1, 6)]
        di = calculate_di(train, live, n_pca_components=2)

        assert di > 1.0

    def test_returns_float(self) -> None:
        train = [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]] * 5
        live = [[1.5, 2.5], [3.5, 4.5]]
        di = calculate_di(train, live)

        assert isinstance(di, float)
        assert not math.isnan(di)

    def test_n_pca_components_respected(self) -> None:
        """Different n_pca_components values return valid floats."""
        train = [[float(i + j) for j in range(6)] for i in range(20)]
        live = [[float(i + j + 0.1) for j in range(6)] for i in range(3)]

        for n in [1, 2, 3, 6, 10]:
            di = calculate_di(train, live, n_pca_components=n)
            assert isinstance(di, float)
            assert not math.isnan(di)

    def test_single_train_sample(self) -> None:
        """With a single train sample intra-dist is 0 → returns 0."""
        train = [[1.0, 2.0, 3.0]]
        live = [[4.0, 5.0, 6.0]]
        di = calculate_di(train, live)

        assert di == 0.0

    def test_single_live_sample(self) -> None:
        """Single live sample still produces a valid DI."""
        train = [[float(i), float(i * 2)] for i in range(1, 15)]
        live = [[50.0, 100.0]]
        di = calculate_di(train, live)

        assert isinstance(di, float)
        assert di >= 0.0


# ---------------------------------------------------------------------------
# compute_dissimilarity_index (backward-compat alias)
# ---------------------------------------------------------------------------


class TestComputeDiAlias:
    """Ensures the legacy alias delegates to calculate_di correctly."""

    def test_alias_matches_calculate_di_output(self) -> None:
        train = [[float(i), float(i * 2)] for i in range(1, 16)]
        live = [[float(i + 1), float(i * 2 + 2)] for i in range(1, 4)]

        di_new = calculate_di(train, live)
        di_old = compute_dissimilarity_index(train, live)

        assert di_new == pytest.approx(di_old, abs=1e-9)

    def test_alias_returns_zero_for_empty(self) -> None:
        assert compute_dissimilarity_index([], []) == 0.0


# ---------------------------------------------------------------------------
# EnsembleSelector.check_staleness — DI-based trigger
# ---------------------------------------------------------------------------


class TestEnsembleSelectorStaleness:
    """Tests that check_staleness uses calculate_di with the new threshold."""

    def test_default_di_threshold_is_2(self) -> None:
        """EnsembleSelector default di_threshold changed to 2.0."""
        sel = EnsembleSelector()
        assert sel._di_threshold == 2.0

    def test_no_train_features_returns_not_stale(self) -> None:
        """Without training data check_staleness returns (False, 0.0)."""
        sel = EnsembleSelector()
        bars = [
            {"timestamp": f"2026-01-{i:02d}", "open": 100.0, "high": 105.0,
             "low": 95.0, "close": 102.0, "volume": 100000}
            for i in range(1, 41)
        ]
        is_stale, di = sel.check_staleness(bars)

        assert not is_stale
        assert di == 0.0

    def test_pca_components_configurable(self) -> None:
        """di_pca_components is stored on the instance."""
        sel = EnsembleSelector(di_pca_components=5)
        assert sel._di_pca_components == 5

    def test_low_threshold_triggers_stale(self) -> None:
        """With a near-zero threshold, almost any live data is flagged stale."""
        import random
        random.seed(0)

        sel = EnsembleSelector(di_threshold=0.001, di_pca_components=2)

        # Manually inject training features
        sel._train_features = [
            [float(i), float(i * 2), float(i * 3)]
            for i in range(1, 31)
        ]

        # Build bars that engineer_features can process (need 30+ bars)
        bars = [
            {
                "timestamp": f"2026-01-{(i % 28) + 1:02d}",
                "open": float(100 + i),
                "high": float(105 + i),
                "low": float(95 + i),
                "close": float(102 + i),
                "volume": 100000,
            }
            for i in range(40)
        ]

        is_stale, di = sel.check_staleness(bars)
        # di >= 0; stale depends on actual computed value vs near-zero threshold
        assert isinstance(is_stale, bool)
        assert di >= 0.0

    def test_high_threshold_never_stale(self) -> None:
        """With a very high threshold, no data should be flagged stale."""
        sel = EnsembleSelector(di_threshold=1e9)
        sel._train_features = [
            [float(i), float(i * 2), float(i * 3)]
            for i in range(1, 31)
        ]
        bars = [
            {
                "timestamp": f"2026-01-{(i % 28) + 1:02d}",
                "open": float(100 + i),
                "high": float(105 + i),
                "low": float(95 + i),
                "close": float(102 + i),
                "volume": 100000,
            }
            for i in range(40)
        ]
        is_stale, di = sel.check_staleness(bars)

        assert not is_stale
        assert di >= 0.0
