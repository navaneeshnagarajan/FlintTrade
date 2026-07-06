"""Tests for the index-contribution analytics module (W7).

Pure, offline computation over synthetic quotes.
"""

from __future__ import annotations

from flinttrade_screener.index_contribution import (
    IndexContributionResult,
    compute_index_contribution,
    index_weights,
    make_sample_index_contribution,
)


class TestIndexWeights:
    def test_nifty_weights_normalise_to_100(self):
        weights = index_weights("NIFTY")
        assert weights is not None
        assert abs(sum(weights.values()) - 100.0) < 0.01

    def test_banknifty_weights_normalise_to_100(self):
        weights = index_weights("BANKNIFTY")
        assert weights is not None
        assert abs(sum(weights.values()) - 100.0) < 0.01

    def test_unknown_index_returns_none(self):
        assert index_weights("NONSENSE") is None


class TestComputeIndexContribution:
    def test_positive_and_negative_contributions(self):
        quotes = {
            "HDFCBANK": {"ltp": 1010.0, "prev_close": 1000.0},  # +1%
            "RELIANCE": {"ltp": 990.0, "prev_close": 1000.0},   # -1%
        }
        result = compute_index_contribution("NIFTY", quotes, index_level=24000.0)
        assert isinstance(result, IndexContributionResult)
        hdfc = next(c for c in result.constituents if c.symbol == "HDFCBANK")
        rel = next(c for c in result.constituents if c.symbol == "RELIANCE")
        assert hdfc.change_pct == 1.0
        assert rel.change_pct == -1.0
        assert hdfc.contribution_pct > 0
        assert rel.contribution_pct < 0

    def test_ranked_by_absolute_contribution(self):
        result = make_sample_index_contribution("NIFTY")
        contribs = [abs(c.contribution_pct) for c in result.constituents]
        assert contribs == sorted(contribs, reverse=True)

    def test_advancers_decliners_counted(self):
        quotes = {
            "HDFCBANK": {"ltp": 1010.0, "prev_close": 1000.0},
            "RELIANCE": {"ltp": 990.0, "prev_close": 1000.0},
            "INFY": {"ltp": 1000.0, "prev_close": 1000.0},
        }
        result = compute_index_contribution("NIFTY", quotes)
        assert result.advancers == 1
        assert result.decliners == 1

    def test_points_scaled_when_level_supplied(self):
        result = make_sample_index_contribution("NIFTY")
        assert result.index_level == 24000.0
        # With a level, at least one constituent carries a non-zero point value.
        assert any(c.contribution_points != 0.0 for c in result.constituents)

    def test_unknown_index_empty_result(self):
        result = compute_index_contribution("NONSENSE", {})
        assert result.constituents == []

    def test_to_dict_json_serialisable(self):
        import json

        payload = make_sample_index_contribution("BANKNIFTY").to_dict()
        loaded = json.loads(json.dumps(payload))
        assert loaded["index_name"] == "BANKNIFTY"
        assert len(loaded["constituents"]) > 0
