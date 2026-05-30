"""Tests for RL environment, features, and trainer (no RL libraries required).

All tests use synthetic data and test the environment standalone,
without gymnasium or stable-baselines3 installed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


from flinttrade_backtest.rl_environment import EnvironmentConfig, TradingEnvironment
from flinttrade_backtest.rl_features import (
    DEFAULT_FEATURES,
    MINIMAL_FEATURES,
    RewardState,
    RewardType,
    apply_normalisation,
    compute_features,
    compute_reward,
    normalise_features,
)
from flinttrade_backtest.rl_trainer import DEFAULT_PARAMS, RLAlgorithm, RLTrainer, TrainingResult


# ======================================================================
# Helpers
# ======================================================================


def _make_price_df(n: int = 100, start_price: float = 100.0) -> pd.DataFrame:
    """Generate synthetic single-stock OHLCV data."""
    np.random.seed(42)
    prices = start_price + np.cumsum(np.random.randn(n) * 0.5)
    prices = np.maximum(prices, 1.0)  # keep positive

    return pd.DataFrame({
        "open": prices + np.random.randn(n) * 0.1,
        "high": prices + abs(np.random.randn(n) * 0.5),
        "low": prices - abs(np.random.randn(n) * 0.5),
        "close": prices,
        "volume": np.random.randint(1000, 10000, size=n).astype(float),
    })


def _make_multi_stock_df(n_days: int = 50, n_stocks: int = 3) -> pd.DataFrame:
    """Generate synthetic multi-stock data with 'tic' and 'date' columns."""
    np.random.seed(42)
    tickers = [f"STOCK_{i}" for i in range(n_stocks)]
    rows = []
    for day in range(n_days):
        for tic in tickers:
            price = 100 + np.random.randn() * 5
            rows.append({
                "date": f"2025-01-{day + 1:02d}",
                "tic": tic,
                "open": price + 0.1,
                "high": price + 1.0,
                "low": price - 1.0,
                "close": max(price, 1.0),
                "volume": float(np.random.randint(1000, 10000)),
            })
    return pd.DataFrame(rows)


# ======================================================================
# Test: rl_features.py — Feature engineering
# ======================================================================


class TestFeatureEngineering:
    """Tests for compute_features and normalisation."""

    def test_compute_default_features(self) -> None:
        """All default features are computed and added as columns."""
        df = _make_price_df(100)
        result = compute_features(df, DEFAULT_FEATURES)

        for feat in DEFAULT_FEATURES:
            assert feat in result.columns, f"Missing feature: {feat}"
            assert not result[feat].isna().all(), f"Feature all NaN: {feat}"

    def test_compute_minimal_features(self) -> None:
        """Minimal feature set computes correctly."""
        df = _make_price_df(50)
        result = compute_features(df, MINIMAL_FEATURES)
        for feat in MINIMAL_FEATURES:
            assert feat in result.columns

    def test_feature_shapes(self) -> None:
        """Feature columns have same length as input."""
        df = _make_price_df(60)
        result = compute_features(df, ["returns", "rsi_14", "sma_20"])
        assert len(result) == 60
        assert result["returns"].shape == (60,)

    def test_rsi_range(self) -> None:
        """RSI values should be between 0 and 100."""
        df = _make_price_df(100)
        result = compute_features(df, ["rsi_14"])
        assert result["rsi_14"].min() >= 0.0
        assert result["rsi_14"].max() <= 100.0

    def test_normalise_zscore(self) -> None:
        """Z-score normalisation produces mean~0, std~1."""
        df = _make_price_df(100)
        df = compute_features(df, ["returns", "rsi_14"])
        normed, stats = normalise_features(df, ["returns", "rsi_14"], method="zscore")

        assert "returns" in stats
        assert abs(normed["returns"].mean()) < 0.01
        assert abs(normed["returns"].std() - 1.0) < 0.01

    def test_normalise_minmax(self) -> None:
        """Min-max normalisation produces values in [0, 1]."""
        df = _make_price_df(100)
        df = compute_features(df, ["returns"])
        normed, stats = normalise_features(df, ["returns"], method="minmax")
        assert normed["returns"].min() >= -0.01
        assert normed["returns"].max() <= 1.01

    def test_apply_normalisation(self) -> None:
        """apply_normalisation uses stored stats correctly."""
        df1 = _make_price_df(100)
        df1 = compute_features(df1, ["returns"])
        _, stats = normalise_features(df1, ["returns"], method="zscore")

        df2 = _make_price_df(50)
        df2 = compute_features(df2, ["returns"])
        normed = apply_normalisation(df2, ["returns"], stats)
        assert "returns" in normed.columns


# ======================================================================
# Test: rl_features.py — Reward functions
# ======================================================================


class TestRewardFunctions:
    """Tests for reward computation."""

    def test_pnl_reward(self) -> None:
        """PnL reward = (current - previous) * scaling."""
        r = compute_reward(RewardType.PNL, 101000, 100000, scaling=1e-4)
        assert abs(r - 0.1) < 1e-6

    def test_pnl_reward_negative(self) -> None:
        """Negative PnL gives negative reward."""
        r = compute_reward(RewardType.PNL, 99000, 100000, scaling=1e-4)
        assert r < 0

    def test_log_return_reward(self) -> None:
        """Log return reward computation."""
        r = compute_reward(RewardType.LOG_RETURN, 110000, 100000, scaling=1.0)
        expected = np.log(110000 / 100000)
        assert abs(r - expected) < 1e-6

    def test_log_return_zero_previous(self) -> None:
        """Log return with zero previous value returns 0."""
        r = compute_reward(RewardType.LOG_RETURN, 100, 0, scaling=1.0)
        assert r == 0.0

    def test_sharpe_reward_with_state(self) -> None:
        """Sharpe reward uses portfolio history."""
        state = RewardState(
            portfolio_values=[100000, 101000, 100500, 101500, 102000],
        )
        r = compute_reward(RewardType.SHARPE, 102500, 102000, state=state, scaling=1.0)
        # Should be a finite number
        assert np.isfinite(r)

    def test_risk_adjusted_reward(self) -> None:
        """Risk-adjusted reward penalises drawdowns."""
        state = RewardState(portfolio_values=[100000, 105000])
        # At drawdown (current < peak)
        r_dd = compute_reward(RewardType.RISK_ADJUSTED, 103000, 105000, state=state, scaling=1e-4)
        # Without drawdown
        r_up = compute_reward(RewardType.RISK_ADJUSTED, 106000, 105000, state=state, scaling=1e-4)
        assert r_up > r_dd


# ======================================================================
# Test: rl_environment.py — TradingEnvironment
# ======================================================================


class TestTradingEnvironment:
    """Tests for the Gymnasium-compatible trading environment."""

    def test_single_stock_reset(self) -> None:
        """Reset returns observation of correct shape."""
        df = _make_price_df(50)
        env = TradingEnvironment(df, features=["returns", "rsi_14"])

        obs, info = env.reset()
        # obs = [cash, price, holdings, returns, rsi_14]
        expected_dim = 1 + 1 + 1 + 2  # cash + 1 price + 1 holding + 2 features
        assert obs.shape == (expected_dim,)
        assert obs.dtype == np.float32

    def test_observation_space_shape(self) -> None:
        """observation_space.shape matches actual observation."""
        df = _make_price_df(50)
        features = ["returns", "rsi_14", "sma_20"]
        env = TradingEnvironment(df, features=features)

        obs, _ = env.reset()
        assert obs.shape == env.observation_space.shape

    def test_action_space_shape(self) -> None:
        """action_space.shape matches stock_dim."""
        df = _make_price_df(50)
        env = TradingEnvironment(df, features=["returns"])

        assert env.action_space.shape == (1,)

    def test_step_returns_correct_tuple(self) -> None:
        """step() returns (obs, reward, terminated, truncated, info)."""
        df = _make_price_df(50)
        env = TradingEnvironment(df, features=["returns"])
        env.reset()

        action = np.array([0.5], dtype=np.float32)
        result = env.step(action)

        assert len(result) == 5
        obs, reward, terminated, truncated, info = result
        assert isinstance(obs, np.ndarray)
        assert isinstance(reward, float)
        assert isinstance(terminated, bool)
        assert isinstance(truncated, bool)
        assert isinstance(info, dict)

    def test_step_observation_shape_consistent(self) -> None:
        """Observation shape stays the same across steps."""
        df = _make_price_df(30)
        env = TradingEnvironment(df, features=["returns", "rsi_14"])
        obs0, _ = env.reset()

        for _ in range(10):
            action = env.action_space.sample()
            obs, _, done, _, _ = env.step(action)
            assert obs.shape == obs0.shape
            if done:
                break

    def test_episode_terminates(self) -> None:
        """Environment terminates after all bars are consumed."""
        df = _make_price_df(20)
        env = TradingEnvironment(df, features=["returns"])
        env.reset()

        done = False
        steps = 0
        while not done:
            action = np.array([0.0])
            _, _, done, _, _ = env.step(action)
            steps += 1

        assert done
        assert steps == 19  # max_step = len - 1, so 19 steps

    def test_buy_decreases_cash(self) -> None:
        """Buying stock reduces cash balance."""
        df = _make_price_df(30)
        env = TradingEnvironment(df, features=["returns"], initial_capital=100000)
        obs, _ = env.reset()
        initial_cash = obs[0]

        # Buy action
        action = np.array([1.0])
        obs, _, _, _, info = env.step(action)
        assert info["cash"] < initial_cash

    def test_sell_without_holdings_no_effect(self) -> None:
        """Selling with no holdings does nothing."""
        df = _make_price_df(30)
        env = TradingEnvironment(df, features=["returns"], initial_capital=100000)
        env.reset()

        action = np.array([-1.0])  # sell
        _, _, _, _, info = env.step(action)
        assert info["total_trades"] == 0

    def test_save_asset_memory(self) -> None:
        """save_asset_memory returns DataFrame with correct structure."""
        df = _make_price_df(20)
        env = TradingEnvironment(df, features=["returns"])
        env.reset()

        for _ in range(10):
            action = env.action_space.sample()
            _, _, done, _, _ = env.step(action)
            if done:
                break

        mem = env.save_asset_memory()
        assert isinstance(mem, pd.DataFrame)
        assert "date" in mem.columns
        assert "account_value" in mem.columns
        assert len(mem) > 1

    def test_multi_stock_environment(self) -> None:
        """Multi-stock environment has correct dimensions."""
        df = _make_multi_stock_df(n_days=30, n_stocks=3)
        env = TradingEnvironment(df, features=["returns"])

        assert env.stock_dim == 3
        assert env.action_space.shape == (3,)

        obs, _ = env.reset()
        # obs = [cash, 3 prices, 3 holdings, 3 features]
        assert obs.shape == (1 + 3 + 3 + 3,)

    def test_custom_config(self) -> None:
        """EnvironmentConfig overrides individual parameters."""
        df = _make_price_df(30)
        config = EnvironmentConfig(
            initial_capital=500_000,
            transaction_cost_pct=0.002,
            max_shares_per_stock=50,
            reward_type="log_return",
        )
        env = TradingEnvironment(df, features=["returns"], config=config)
        obs, _ = env.reset()

        # Cash should be 500k
        assert abs(obs[0] - 500_000) < 1.0

    def test_render(self) -> None:
        """render() returns dict with expected keys."""
        df = _make_price_df(20)
        env = TradingEnvironment(df, features=["returns"])
        env.reset()

        state = env.render()
        assert "day" in state
        assert "cash" in state
        assert "holdings" in state
        assert "total_asset" in state

    def test_action_clipping(self) -> None:
        """Actions outside [-1, 1] are clipped."""
        df = _make_price_df(30)
        env = TradingEnvironment(df, features=["returns"])
        env.reset()

        # Extreme action — should not crash
        action = np.array([5.0])
        obs, reward, _, _, info = env.step(action)
        assert np.isfinite(reward)


# ======================================================================
# Test: rl_trainer.py — Trainer (no SB3 required)
# ======================================================================


class TestRLTrainer:
    """Tests for RLTrainer that don't require stable-baselines3."""

    def test_algorithm_enum(self) -> None:
        """RLAlgorithm enum has all expected values."""
        assert RLAlgorithm.PPO.value == "PPO"
        assert RLAlgorithm.A2C.value == "A2C"
        assert RLAlgorithm.DDPG.value == "DDPG"
        assert RLAlgorithm.SAC.value == "SAC"
        assert RLAlgorithm.TD3.value == "TD3"

    def test_default_params_exist(self) -> None:
        """Default params defined for all algorithms."""
        for algo in RLAlgorithm:
            assert algo.value in DEFAULT_PARAMS

    def test_trainer_init(self) -> None:
        """Trainer initialises without SB3 import."""
        df = _make_price_df(30)
        env = TradingEnvironment(df, features=["returns"])
        trainer = RLTrainer(env, algorithm="PPO")

        assert trainer.algorithm == "PPO"
        assert not trainer.is_trained

    def test_trainer_predict_before_train_raises(self) -> None:
        """predict() raises RuntimeError if not trained."""
        df = _make_price_df(30)
        env = TradingEnvironment(df, features=["returns"])
        trainer = RLTrainer(env, algorithm="A2C")

        with pytest.raises(RuntimeError, match="No model available"):
            trainer.predict(np.zeros(env.obs_dim))

    def test_training_result_dataclass(self) -> None:
        """TrainingResult dataclass has expected fields."""
        result = TrainingResult(
            algorithm="PPO",
            total_timesteps=1000,
            training_time_seconds=5.0,
        )
        assert result.algorithm == "PPO"
        assert result.total_timesteps == 1000
        assert result.training_time_seconds == 5.0
        assert result.episode_rewards == []


# ======================================================================
# Test: Integration — environment + features together
# ======================================================================


class TestIntegration:
    """Integration tests combining features and environment."""

    def test_full_episode_run(self) -> None:
        """Run a complete episode and verify final stats."""
        df = _make_price_df(50)
        env = TradingEnvironment(
            df,
            features=["returns", "rsi_14", "volume_ratio"],
            initial_capital=100_000,
        )

        obs, _ = env.reset()
        total_reward = 0.0
        done = False

        while not done:
            # Simple strategy: buy if RSI < 30, sell if RSI > 70
            # RSI is at index: 1 (price) + 1 (holding) + 1 (returns) + 0-based = index 3 in obs
            # Actually, obs layout: [cash, price, holdings, returns, rsi_14, volume_ratio]
            rsi_idx = 1 + 1 + 1 + 1  # 4th feature position
            if rsi_idx < len(obs):
                rsi = obs[rsi_idx]
            else:
                rsi = 50.0

            if rsi < 30:
                action = np.array([0.5])
            elif rsi > 70:
                action = np.array([-0.5])
            else:
                action = np.array([0.0])

            obs, reward, done, _, info = env.step(action)
            total_reward += reward

        assert "total_asset" in info
        assert info["total_asset"] > 0
        assert isinstance(total_reward, float)

    def test_different_reward_types(self) -> None:
        """Environment works with all reward types."""
        df = _make_price_df(30)

        for rt in RewardType:
            config = EnvironmentConfig(reward_type=rt.value)
            env = TradingEnvironment(df, features=["returns"], config=config)
            obs, _ = env.reset()

            for _ in range(5):
                action = env.action_space.sample()
                obs, reward, done, _, _ = env.step(action)
                assert np.isfinite(reward), f"Non-finite reward with {rt.value}"
                if done:
                    break
