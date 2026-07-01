"""Tests for social trading — Leaderboard + StrategyMarketplace.

Covers: CRUD operations, sorting, validation, edge cases, seed data.
"""

from __future__ import annotations

import pytest

from flinttrade_engine.social_trading import (
    Leaderboard,
    SharedStrategy,
    StrategyMarketplace,
    TraderProfile,
    seed_leaderboard,
    seed_marketplace,
    sync_from_registry,
    _classify_strategy,
    _humanise_name,
)


# ======================================================================
# Leaderboard
# ======================================================================


class TestLeaderboard:
    """Tests for the Leaderboard class."""

    def _make_profile(self, **overrides: object) -> TraderProfile:
        defaults: dict[str, object] = {
            "user_id": "user_1",
            "display_name": "Test Trader",
            "strategy_count": 2,
            "win_rate": 65.0,
            "total_return_pct": 50.0,
            "sharpe_ratio": 1.5,
            "follower_count": 100,
            "trades_count": 500,
            "risk_score": 3,
        }
        defaults.update(overrides)
        return TraderProfile(**defaults)  # type: ignore[arg-type]

    def test_update_and_get_profile(self) -> None:
        lb = Leaderboard()
        profile = self._make_profile()
        lb.update_profile(profile)
        assert lb.count == 1
        assert lb.get_profile("user_1") is profile

    def test_get_profile_not_found(self) -> None:
        lb = Leaderboard()
        assert lb.get_profile("nonexistent") is None

    def test_update_profile_replaces_existing(self) -> None:
        lb = Leaderboard()
        lb.update_profile(self._make_profile(win_rate=50.0))
        lb.update_profile(self._make_profile(win_rate=75.0))
        assert lb.count == 1
        assert lb.get_profile("user_1") is not None
        assert lb.get_profile("user_1").win_rate == 75.0  # type: ignore[union-attr]

    def test_update_profile_empty_user_id_raises(self) -> None:
        lb = Leaderboard()
        with pytest.raises(ValueError, match="user_id"):
            lb.update_profile(self._make_profile(user_id=""))

    def test_update_profile_empty_display_name_raises(self) -> None:
        lb = Leaderboard()
        with pytest.raises(ValueError, match="display_name"):
            lb.update_profile(self._make_profile(display_name=""))

    def test_update_profile_invalid_risk_score_raises(self) -> None:
        lb = Leaderboard()
        with pytest.raises(ValueError, match="risk_score"):
            lb.update_profile(self._make_profile(risk_score=0))
        with pytest.raises(ValueError, match="risk_score"):
            lb.update_profile(self._make_profile(risk_score=6))

    def test_get_top_traders_sorted_by_return(self) -> None:
        lb = Leaderboard()
        lb.update_profile(self._make_profile(user_id="a", total_return_pct=30.0))
        lb.update_profile(self._make_profile(user_id="b", total_return_pct=90.0))
        lb.update_profile(self._make_profile(user_id="c", total_return_pct=60.0))

        top = lb.get_top_traders(metric="total_return_pct", limit=2)
        assert len(top) == 2
        assert top[0].user_id == "b"
        assert top[1].user_id == "c"

    def test_get_top_traders_sorted_by_win_rate(self) -> None:
        lb = Leaderboard()
        lb.update_profile(self._make_profile(user_id="a", win_rate=55.0))
        lb.update_profile(self._make_profile(user_id="b", win_rate=80.0))

        top = lb.get_top_traders(metric="win_rate")
        assert top[0].user_id == "b"

    def test_get_top_traders_sorted_by_sharpe(self) -> None:
        lb = Leaderboard()
        lb.update_profile(self._make_profile(user_id="a", sharpe_ratio=1.0))
        lb.update_profile(self._make_profile(user_id="b", sharpe_ratio=3.0))

        top = lb.get_top_traders(metric="sharpe_ratio")
        assert top[0].user_id == "b"

    def test_get_top_traders_invalid_metric_raises(self) -> None:
        lb = Leaderboard()
        with pytest.raises(ValueError, match="Invalid metric"):
            lb.get_top_traders(metric="invalid_field")

    def test_get_top_traders_empty_leaderboard(self) -> None:
        lb = Leaderboard()
        assert lb.get_top_traders() == []

    def test_get_top_traders_limit(self) -> None:
        lb = Leaderboard()
        for i in range(10):
            lb.update_profile(
                self._make_profile(user_id=f"user_{i}", total_return_pct=float(i * 10))
            )
        top = lb.get_top_traders(limit=3)
        assert len(top) == 3

    def test_remove_profile(self) -> None:
        lb = Leaderboard()
        lb.update_profile(self._make_profile())
        assert lb.remove_profile("user_1") is True
        assert lb.count == 0
        assert lb.get_profile("user_1") is None

    def test_remove_nonexistent_profile(self) -> None:
        lb = Leaderboard()
        assert lb.remove_profile("ghost") is False


# ======================================================================
# StrategyMarketplace
# ======================================================================


class TestStrategyMarketplace:
    """Tests for the StrategyMarketplace class."""

    def _make_strategy(self, **overrides: object) -> SharedStrategy:
        defaults: dict[str, object] = {
            "strategy_id": "strat_1",
            "creator_id": "creator_1",
            "name": "Test Strategy",
            "description": "A test strategy",
            "category": "intraday",
            "instruments": ["NIFTY"],
            "backtest_sharpe": 1.5,
            "backtest_return_pct": 50.0,
            "follower_count": 100,
        }
        defaults.update(overrides)
        return SharedStrategy(**defaults)  # type: ignore[arg-type]

    def test_publish_and_get_strategy(self) -> None:
        mp = StrategyMarketplace()
        strat = self._make_strategy()
        mp.publish(strat)
        assert mp.count == 1
        assert mp.get_strategy("strat_1") is strat

    def test_publish_sets_created_at_if_missing(self) -> None:
        mp = StrategyMarketplace()
        strat = self._make_strategy(created_at="")
        mp.publish(strat)
        assert strat.created_at != ""

    def test_publish_empty_strategy_id_raises(self) -> None:
        mp = StrategyMarketplace()
        with pytest.raises(ValueError, match="strategy_id"):
            mp.publish(self._make_strategy(strategy_id=""))

    def test_publish_empty_creator_id_raises(self) -> None:
        mp = StrategyMarketplace()
        with pytest.raises(ValueError, match="creator_id"):
            mp.publish(self._make_strategy(creator_id=""))

    def test_publish_empty_name_raises(self) -> None:
        mp = StrategyMarketplace()
        with pytest.raises(ValueError, match="name"):
            mp.publish(self._make_strategy(name=""))

    def test_publish_invalid_category_raises(self) -> None:
        mp = StrategyMarketplace()
        with pytest.raises(ValueError, match="Invalid category"):
            mp.publish(self._make_strategy(category="forex"))

    def test_browse_returns_public_only(self) -> None:
        mp = StrategyMarketplace()
        mp.publish(self._make_strategy(strategy_id="pub", is_public=True))
        mp.publish(self._make_strategy(strategy_id="priv", is_public=False))
        results = mp.browse()
        assert len(results) == 1
        assert results[0].strategy_id == "pub"

    def test_browse_filter_by_category(self) -> None:
        mp = StrategyMarketplace()
        mp.publish(self._make_strategy(strategy_id="s1", category="intraday"))
        mp.publish(self._make_strategy(strategy_id="s2", category="swing"))
        mp.publish(self._make_strategy(strategy_id="s3", category="intraday"))

        results = mp.browse(category="intraday")
        assert len(results) == 2
        assert all(s.category == "intraday" for s in results)

    def test_browse_sort_by_return(self) -> None:
        mp = StrategyMarketplace()
        mp.publish(self._make_strategy(strategy_id="s1", backtest_return_pct=20.0))
        mp.publish(self._make_strategy(strategy_id="s2", backtest_return_pct=80.0))

        results = mp.browse(sort_by="backtest_return_pct")
        assert results[0].strategy_id == "s2"

    def test_browse_invalid_sort_raises(self) -> None:
        mp = StrategyMarketplace()
        with pytest.raises(ValueError, match="Invalid sort_by"):
            mp.browse(sort_by="banana")

    def test_browse_invalid_category_raises(self) -> None:
        mp = StrategyMarketplace()
        with pytest.raises(ValueError, match="Invalid category"):
            mp.browse(category="forex")

    def test_browse_limit(self) -> None:
        mp = StrategyMarketplace()
        for i in range(10):
            mp.publish(self._make_strategy(strategy_id=f"s_{i}"))
        results = mp.browse(limit=3)
        assert len(results) == 3

    def test_copy_strategy(self) -> None:
        mp = StrategyMarketplace()
        mp.publish(self._make_strategy(follower_count=10))
        result = mp.copy("strat_1", "user_1")
        assert result["status"] == "success"
        assert mp.get_strategy("strat_1") is not None
        assert mp.get_strategy("strat_1").follower_count == 11  # type: ignore[union-attr]

    def test_copy_strategy_not_found_raises(self) -> None:
        mp = StrategyMarketplace()
        with pytest.raises(ValueError, match="not found"):
            mp.copy("ghost", "user_1")

    def test_copy_own_strategy_raises(self) -> None:
        mp = StrategyMarketplace()
        mp.publish(self._make_strategy())
        with pytest.raises(ValueError, match="Cannot copy your own"):
            mp.copy("strat_1", "creator_1")

    def test_copy_empty_user_id_raises(self) -> None:
        mp = StrategyMarketplace()
        mp.publish(self._make_strategy())
        with pytest.raises(ValueError, match="user_id"):
            mp.copy("strat_1", "")

    def test_copy_duplicate_returns_already_copied(self) -> None:
        mp = StrategyMarketplace()
        mp.publish(self._make_strategy(follower_count=10))
        mp.copy("strat_1", "user_1")
        result = mp.copy("strat_1", "user_1")
        assert result["status"] == "already_copied"
        # follower_count should not increment on duplicate copy
        assert mp.get_strategy("strat_1").follower_count == 11  # type: ignore[union-attr]

    def test_get_copies(self) -> None:
        mp = StrategyMarketplace()
        mp.publish(self._make_strategy())
        mp.copy("strat_1", "user_a")
        mp.copy("strat_1", "user_b")
        copies = mp.get_copies("strat_1")
        assert set(copies) == {"user_a", "user_b"}

    def test_get_copies_empty(self) -> None:
        mp = StrategyMarketplace()
        assert mp.get_copies("nonexistent") == []

    def test_remove_strategy(self) -> None:
        mp = StrategyMarketplace()
        mp.publish(self._make_strategy())
        assert mp.remove_strategy("strat_1") is True
        assert mp.count == 0

    def test_remove_nonexistent_strategy(self) -> None:
        mp = StrategyMarketplace()
        assert mp.remove_strategy("ghost") is False

    def test_get_strategy_not_found(self) -> None:
        mp = StrategyMarketplace()
        assert mp.get_strategy("nonexistent") is None


# ======================================================================
# Seed Data
# ======================================================================


class TestSeedData:
    """Tests for seed_leaderboard() and seed_marketplace()."""

    def test_seed_leaderboard_has_15_profiles(self) -> None:
        lb = seed_leaderboard()
        assert lb.count == 15

    def test_seed_leaderboard_profiles_are_valid(self) -> None:
        lb = seed_leaderboard()
        top = lb.get_top_traders(metric="total_return_pct", limit=100)
        for p in top:
            assert p.user_id
            assert p.display_name
            assert 1 <= p.risk_score <= 5
            assert p.win_rate > 0
            assert p.total_return_pct > 0

    def test_seed_leaderboard_unique_user_ids(self) -> None:
        lb = seed_leaderboard()
        top = lb.get_top_traders(limit=100)
        ids = [p.user_id for p in top]
        assert len(ids) == len(set(ids))

    def test_seed_marketplace_has_10_strategies(self) -> None:
        mp = seed_marketplace()
        assert mp.count == 10

    def test_seed_marketplace_strategies_are_valid(self) -> None:
        mp = seed_marketplace()
        strategies = mp.browse(limit=100)
        for s in strategies:
            assert s.strategy_id
            assert s.creator_id
            assert s.name
            assert s.category in {"intraday", "swing", "options", "investment"}
            assert s.created_at

    def test_seed_marketplace_unique_strategy_ids(self) -> None:
        mp = seed_marketplace()
        strategies = mp.browse(limit=100)
        ids = [s.strategy_id for s in strategies]
        assert len(ids) == len(set(ids))

    def test_seed_marketplace_all_categories_represented(self) -> None:
        mp = seed_marketplace()
        strategies = mp.browse(limit=100)
        categories = {s.category for s in strategies}
        assert categories == {"intraday", "swing", "options", "investment"}


# ======================================================================
# sync_from_registry
# ======================================================================


class TestSyncFromRegistry:
    """Tests for sync_from_registry and helper functions."""

    def test_classify_legacy_strategy(self) -> None:
        assert _classify_strategy("EMACrossover") == "trend"
        assert _classify_strategy("ORB") == "intraday"
        assert _classify_strategy("IronCondor") == "options"
        assert _classify_strategy("BollingerMR") == "mean_reversion"

    def test_classify_prefix_strategy(self) -> None:
        assert _classify_strategy("IntradayGapFill") == "intraday"
        assert _classify_strategy("MTFRSITrend") == "swing"
        assert _classify_strategy("ScalpTapeReading") == "scalping"
        assert _classify_strategy("CryptoGrid") == "crypto"
        assert _classify_strategy("CommoditySeasonal") == "commodity"
        assert _classify_strategy("EventEarnings") == "event"
        assert _classify_strategy("MLFeatureSignal") == "ml"
        assert _classify_strategy("PortfolioEqualWeight") == "portfolio"
        assert _classify_strategy("PairsCointegration") == "pairs"
        assert _classify_strategy("StatRegimeHMM") == "statistical"

    def test_classify_unknown_defaults_to_swing(self) -> None:
        assert _classify_strategy("SomeUnknownStrategy") == "swing"

    def test_humanise_name(self) -> None:
        assert _humanise_name("MTFRSITrend") == "MTFRSI Trend"
        assert _humanise_name("IntradayGapFill") == "Intraday Gap Fill"
        assert _humanise_name("EMACrossover") == "EMA Crossover"
        assert _humanise_name("RSIMomentum") == "RSI Momentum"
        assert _humanise_name("VWAPReversion") == "VWAP Reversion"

    def test_sync_from_registry_creates_marketplace(self) -> None:
        mp = sync_from_registry()
        # Must have at least the 10 seeded + some registry strategies
        assert mp.count > 10

    def test_sync_from_registry_with_existing_marketplace(self) -> None:
        mp = seed_marketplace()
        original_count = mp.count
        mp = sync_from_registry(mp)
        assert mp.count > original_count

    def test_sync_from_registry_idempotent(self) -> None:
        mp = sync_from_registry()
        count_after_first = mp.count
        mp = sync_from_registry(mp)
        assert mp.count == count_after_first

    def test_sync_from_registry_strategy_ids_prefixed(self) -> None:
        mp = sync_from_registry()
        all_strats = mp.browse(limit=10_000)
        registry_strats = [s for s in all_strats if s.strategy_id.startswith("registry_")]
        assert len(registry_strats) > 0
        for s in registry_strats:
            assert s.creator_id == "flinttrade_registry"
            assert s.is_public is True
            assert s.name  # non-empty
            assert s.category  # non-empty

    def test_sync_from_registry_all_categories_valid(self) -> None:
        from flinttrade_engine.social_trading import VALID_CATEGORIES

        mp = sync_from_registry()
        all_strats = mp.browse(limit=10_000)
        for s in all_strats:
            assert s.category in VALID_CATEGORIES, f"{s.strategy_id} has invalid category {s.category}"
