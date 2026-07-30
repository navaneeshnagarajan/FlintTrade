"""Gymnasium-compatible trading environment for RL agents.

Adapts patterns from FinRL's StockTradingEnv. Designed to work standalone
for testing (no gymnasium/stable-baselines3 required at import time).

Key design choices from FinRL:
- Observation = [cash, prices, holdings, technical_indicators]
- Action space = continuous [-1, 1] per stock (sell to buy)
- Supports turbulence-based risk management
- Tracks asset memory, rewards, actions for analysis
- Reward scaling for stable training

FlintTrade additions:
- Indian market defaults (INR, IST, SEBI lot sizes)
- Multiple reward functions (Sharpe, Sortino, risk-adjusted)
- Configurable via dataclass, not 20+ constructor args
- Works without gymnasium installed (duck-typed spaces)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

try:
    from .rl_features import (
        DEFAULT_FEATURES,
        RewardState,
        compute_features,
        compute_reward,
    )
except ImportError:
    from flinttrade_backtest.rl_features import (
        DEFAULT_FEATURES,
        RewardState,
        compute_features,
        compute_reward,
    )

logger = logging.getLogger("flinttrade.backtest.rl_environment")


# ---------------------------------------------------------------------------
# Duck-typed spaces (used when gymnasium is not installed)
# ---------------------------------------------------------------------------


class _BoxSpace:
    """Minimal Box space compatible with gymnasium.spaces.Box interface."""

    def __init__(
        self,
        low: float | np.ndarray,
        high: float | np.ndarray,
        shape: tuple[int, ...],
        dtype: type = np.float32,
    ) -> None:
        self.low = np.full(shape, low, dtype=dtype) if isinstance(low, (int, float)) else np.asarray(low, dtype=dtype)
        self.high = np.full(shape, high, dtype=dtype) if isinstance(high, (int, float)) else np.asarray(high, dtype=dtype)
        self.shape = shape
        self.dtype = dtype

    def sample(self) -> np.ndarray:
        """Random sample from the space."""
        return np.random.uniform(self.low, self.high).astype(self.dtype)

    def contains(self, x: np.ndarray) -> bool:
        """Check if x is within bounds."""
        return bool(
            np.all(x >= self.low) and np.all(x <= self.high)
            and x.shape == self.shape
        )


# Try to use real gymnasium spaces if available
try:
    import gymnasium as gym  # noqa: F401
    from gymnasium import spaces as gym_spaces
    _GYM_AVAILABLE = True
except ImportError:
    _GYM_AVAILABLE = False


# ---------------------------------------------------------------------------
# Environment configuration
# ---------------------------------------------------------------------------


@dataclass
class EnvironmentConfig:
    """Configuration for the trading environment."""

    initial_capital: float = 100_000.0
    transaction_cost_pct: float = 0.001  # 0.1% per trade
    max_shares_per_stock: int = 100
    reward_type: str = "pnl"
    reward_scaling: float = 1e-4
    turbulence_threshold: float | None = None
    risk_free_rate: float = 0.07  # Indian risk-free rate (annual)
    lot_size: int = 1  # SEBI lot size (for F&O, typically 25/50/75)
    print_verbosity: int = 10


# ---------------------------------------------------------------------------
# Trading Environment
# ---------------------------------------------------------------------------


class TradingEnvironment:
    """Gymnasium-compatible trading environment for RL agents.

    Inspired by FinRL's StockTradingEnv. Supports multi-stock trading
    with continuous action space, technical indicators as features,
    and configurable reward functions.

    The environment does NOT require gymnasium to be installed. It implements
    the same interface (reset, step, observation_space, action_space) so it
    works with stable-baselines3 when available, or standalone for testing.

    Observation vector layout (following FinRL convention):
        [cash_balance, stock_1_price, ..., stock_N_price,
         stock_1_holdings, ..., stock_N_holdings,
         feature_1_stock_1, ..., feature_M_stock_N]

    Action vector:
        [action_stock_1, ..., action_stock_N]
        where action in [-1, 1]: negative = sell, positive = buy,
        scaled by max_shares_per_stock.

    Usage::

        df = pd.DataFrame({'close': [...], 'volume': [...]})
        env = TradingEnvironment(df, features=['returns', 'rsi_14'])
        obs, info = env.reset()
        action = env.action_space.sample()
        obs, reward, terminated, truncated, info = env.step(action)
    """

    metadata: dict[str, Any] = {"render_modes": ["human"]}

    def __init__(
        self,
        df: pd.DataFrame,
        features: list[str] | None = None,
        initial_capital: float = 100_000.0,
        transaction_cost: float = 0.001,
        config: EnvironmentConfig | None = None,
    ) -> None:
        """Initialise the trading environment.

        Args:
            df: DataFrame indexed by time step. Must have 'close' column.
                For multi-stock, must have 'tic' (ticker) column and be
                indexed so that df.loc[day] returns all stocks for that day.
                For single stock, each row is one time step.
            features: list of feature names to include in observation.
                Features are computed automatically if not present in df.
            initial_capital: starting cash balance.
            transaction_cost: cost as fraction of trade value (0.001 = 0.1%).
            config: full EnvironmentConfig (overrides individual params).
        """
        if config is not None:
            self._config = config
        else:
            self._config = EnvironmentConfig(
                initial_capital=initial_capital,
                transaction_cost_pct=transaction_cost,
            )

        self._features = features if features is not None else DEFAULT_FEATURES

        # Detect multi-stock vs single-stock
        if "tic" in df.columns:
            self._multi_stock = True
            self._tickers = sorted(df["tic"].unique().tolist())
            self._stock_dim = len(self._tickers)
            # Re-index by integer day for FinRL-style indexing
            dates = sorted(df["date"].unique()) if "date" in df.columns else sorted(df.index.unique())
            self._dates = dates
            self._df = df.copy()
        else:
            self._multi_stock = False
            self._tickers = ["STOCK"]
            self._stock_dim = 1
            self._dates = list(range(len(df)))
            self._df = df.copy().reset_index(drop=True)

        # Compute features if needed
        if self._multi_stock:
            for tic in self._tickers:
                mask = self._df["tic"] == tic
                tic_df = self._df.loc[mask].copy()
                tic_df = compute_features(tic_df, self._features)
                self._df.loc[mask, self._features] = tic_df[self._features].values
        else:
            self._df = compute_features(self._df, self._features)

        self._max_step = len(self._dates) - 1

        # Observation and action dimensions
        # obs = [cash] + [prices] + [holdings] + [features per stock]
        self._obs_dim = 1 + self._stock_dim + self._stock_dim + len(self._features) * self._stock_dim

        # Build spaces
        self._observation_space = self._make_box(-np.inf, np.inf, (self._obs_dim,))
        self._action_space = self._make_box(-1.0, 1.0, (self._stock_dim,))

        # State variables (initialised in reset)
        self._day: int = 0
        self._cash: float = self._config.initial_capital
        self._holdings: np.ndarray = np.zeros(self._stock_dim, dtype=np.float32)
        self._terminal: bool = False
        self._episode: int = 0

        # Memory for analysis (FinRL pattern)
        self._asset_memory: list[float] = []
        self._rewards_memory: list[float] = []
        self._actions_memory: list[np.ndarray] = []
        self._date_memory: list[Any] = []

        # Reward tracking
        self._reward_state: RewardState = RewardState(
            portfolio_values=[],
            risk_free_daily=self._config.risk_free_rate / 252,
        )

        # Cumulative stats
        self._total_cost: float = 0.0
        self._total_trades: int = 0

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def observation_space(self) -> Any:
        """Observation space (Box)."""
        return self._observation_space

    @property
    def action_space(self) -> Any:
        """Action space (Box)."""
        return self._action_space

    @property
    def stock_dim(self) -> int:
        """Number of tradeable stocks."""
        return self._stock_dim

    @property
    def obs_dim(self) -> int:
        """Observation vector dimension."""
        return self._obs_dim

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Reset environment to initial state.

        Returns:
            (observation, info) tuple.
        """
        if seed is not None:
            np.random.seed(seed)

        self._day = 0
        self._cash = self._config.initial_capital
        self._holdings = np.zeros(self._stock_dim, dtype=np.float32)
        self._terminal = False
        self._episode += 1

        prices = self._get_prices()
        initial_asset = self._cash + np.sum(self._holdings * prices)

        self._asset_memory = [initial_asset]
        self._rewards_memory = []
        self._actions_memory = []
        self._date_memory = [self._get_current_date()]
        self._reward_state = RewardState(
            portfolio_values=[initial_asset],
            risk_free_daily=self._config.risk_free_rate / 252,
        )
        self._total_cost = 0.0
        self._total_trades = 0

        obs = self._get_observation()
        info = {"episode": self._episode, "initial_capital": self._config.initial_capital}

        return obs, info

    def step(
        self, action: np.ndarray,
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        """Execute one time step.

        Args:
            action: array of shape (stock_dim,) with values in [-1, 1].
                Negative = sell, positive = buy.
                Magnitude scaled by max_shares_per_stock.

        Returns:
            (observation, reward, terminated, truncated, info)
        """
        self._terminal = self._day >= self._max_step

        if self._terminal:
            return self._handle_terminal()

        # Scale actions to share quantities (FinRL pattern)
        actions = np.array(action, dtype=np.float32).flatten()
        actions = np.clip(actions, -1.0, 1.0)
        scaled_actions = (actions * self._config.max_shares_per_stock).astype(int)

        # Get current prices
        prices = self._get_prices()
        begin_total_asset = self._cash + np.sum(self._holdings * prices)

        # Check turbulence — liquidate if threshold exceeded
        if self._config.turbulence_threshold is not None:
            turbulence = self._get_turbulence()
            if turbulence >= self._config.turbulence_threshold:
                scaled_actions = np.full(self._stock_dim, -self._config.max_shares_per_stock)

        # Execute trades: sell first, then buy (FinRL pattern)
        sell_indices = np.where(scaled_actions < 0)[0]
        buy_indices = np.where(scaled_actions > 0)[0]

        # Sort by action magnitude (sell most negative first, buy most positive first)
        sell_indices = sell_indices[np.argsort(scaled_actions[sell_indices])]
        buy_indices = buy_indices[np.argsort(-scaled_actions[buy_indices])]

        for idx in sell_indices:
            self._execute_sell(idx, abs(scaled_actions[idx]), prices[idx])

        for idx in buy_indices:
            self._execute_buy(idx, scaled_actions[idx], prices[idx])

        self._actions_memory.append(scaled_actions.copy())

        # Advance to next day
        self._day += 1
        new_prices = self._get_prices()
        end_total_asset = self._cash + np.sum(self._holdings * new_prices)

        # Record asset memory
        self._asset_memory.append(end_total_asset)
        self._date_memory.append(self._get_current_date())
        self._reward_state.portfolio_values.append(end_total_asset)

        # Compute reward
        reward = compute_reward(
            reward_type=self._config.reward_type,
            current_value=end_total_asset,
            previous_value=begin_total_asset,
            state=self._reward_state,
            scaling=self._config.reward_scaling,
        )
        self._rewards_memory.append(reward)

        obs = self._get_observation()
        terminated = self._day >= self._max_step
        truncated = False

        info = {
            "total_asset": end_total_asset,
            "cash": self._cash,
            "holdings": self._holdings.copy(),
            "total_cost": self._total_cost,
            "total_trades": self._total_trades,
            "day": self._day,
        }

        return obs, reward, terminated, truncated, info

    def render(self, mode: str = "human") -> dict[str, Any]:
        """Return current state as a dict."""
        prices = self._get_prices()
        return {
            "day": self._day,
            "cash": self._cash,
            "holdings": self._holdings.tolist(),
            "prices": prices.tolist(),
            "total_asset": self._cash + np.sum(self._holdings * prices),
        }

    # ------------------------------------------------------------------
    # Trade execution
    # ------------------------------------------------------------------

    def _execute_sell(self, index: int, quantity: int, price: float) -> None:
        """Sell shares of stock at given index."""
        if price <= 0 or self._holdings[index] <= 0:
            return

        actual_qty = min(quantity, int(self._holdings[index]))
        if actual_qty <= 0:
            return

        sell_amount = price * actual_qty * (1 - self._config.transaction_cost_pct)
        self._cash += sell_amount
        self._holdings[index] -= actual_qty
        self._total_cost += price * actual_qty * self._config.transaction_cost_pct
        self._total_trades += 1

    def _execute_buy(self, index: int, quantity: int, price: float) -> None:
        """Buy shares of stock at given index."""
        if price <= 0:
            return

        cost_per_share = price * (1 + self._config.transaction_cost_pct)
        affordable = int(self._cash // cost_per_share) if cost_per_share > 0 else 0
        actual_qty = min(affordable, quantity)
        if actual_qty <= 0:
            return

        buy_amount = price * actual_qty * (1 + self._config.transaction_cost_pct)
        self._cash -= buy_amount
        self._holdings[index] += actual_qty
        self._total_cost += price * actual_qty * self._config.transaction_cost_pct
        self._total_trades += 1

    # ------------------------------------------------------------------
    # Observation construction
    # ------------------------------------------------------------------

    def _get_observation(self) -> np.ndarray:
        """Build observation vector.

        Layout: [cash, price_1..N, holdings_1..N, feat_1_stock_1..feat_M_stock_N]
        """
        prices = self._get_prices()
        features = self._get_features()

        obs = np.concatenate([
            [self._cash],
            prices,
            self._holdings,
            features.flatten(),
        ]).astype(np.float32)

        return obs

    def _get_prices(self) -> np.ndarray:
        """Get current close prices for all stocks."""
        if self._multi_stock:
            day_date = self._dates[min(self._day, len(self._dates) - 1)]
            if "date" in self._df.columns:
                day_data = self._df[self._df["date"] == day_date]
            else:
                day_data = self._df.loc[day_date]
            prices = []
            for tic in self._tickers:
                tic_data = day_data[day_data["tic"] == tic]
                if len(tic_data) > 0:
                    prices.append(float(tic_data["close"].iloc[0]))
                else:
                    prices.append(0.0)
            return np.array(prices, dtype=np.float32)
        else:
            idx = min(self._day, len(self._df) - 1)
            return np.array([float(self._df["close"].iloc[idx])], dtype=np.float32)

    def _get_features(self) -> np.ndarray:
        """Get feature values for current day, all stocks."""
        if self._multi_stock:
            day_date = self._dates[min(self._day, len(self._dates) - 1)]
            if "date" in self._df.columns:
                day_data = self._df[self._df["date"] == day_date]
            else:
                day_data = self._df.loc[day_date]
            result = []
            for tic in self._tickers:
                tic_data = day_data[day_data["tic"] == tic]
                for feat in self._features:
                    if feat in tic_data.columns and len(tic_data) > 0:
                        result.append(float(tic_data[feat].iloc[0]))
                    else:
                        result.append(0.0)
            return np.array(result, dtype=np.float32)
        else:
            idx = min(self._day, len(self._df) - 1)
            result = []
            for feat in self._features:
                if feat in self._df.columns:
                    result.append(float(self._df[feat].iloc[idx]))
                else:
                    result.append(0.0)
            return np.array(result, dtype=np.float32)

    def _get_turbulence(self) -> float:
        """Get turbulence value for current day (0.0 if not available)."""
        if "turbulence" not in self._df.columns:
            return 0.0
        if self._multi_stock:
            day_date = self._dates[min(self._day, len(self._dates) - 1)]
            if "date" in self._df.columns:
                day_data = self._df[self._df["date"] == day_date]
            else:
                day_data = self._df.loc[day_date]
            if len(day_data) > 0:
                return float(day_data["turbulence"].iloc[0])
        else:
            idx = min(self._day, len(self._df) - 1)
            return float(self._df["turbulence"].iloc[idx])
        return 0.0

    def _get_current_date(self) -> Any:
        """Get current date/index."""
        idx = min(self._day, len(self._dates) - 1)
        return self._dates[idx]

    # ------------------------------------------------------------------
    # Terminal handling
    # ------------------------------------------------------------------

    def _handle_terminal(self) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        """Handle episode termination — compute final stats."""
        prices = self._get_prices()
        end_total_asset = self._cash + np.sum(self._holdings * prices)

        # Compute episode statistics
        df_total_value = pd.DataFrame({
            "date": self._date_memory,
            "account_value": self._asset_memory,
        })
        df_total_value["daily_return"] = df_total_value["account_value"].pct_change(1)

        total_return = (end_total_asset - self._config.initial_capital) / self._config.initial_capital
        sharpe = 0.0
        if len(df_total_value) > 1 and df_total_value["daily_return"].std() != 0:
            sharpe = (
                (252 ** 0.5)
                * df_total_value["daily_return"].mean()
                / df_total_value["daily_return"].std()
            )

        if self._episode % self._config.print_verbosity == 0:
            logger.info(
                "Episode %d | Return: %.2f%% | Sharpe: %.3f | Trades: %d | Cost: %.2f",
                self._episode, total_return * 100, sharpe,
                self._total_trades, self._total_cost,
            )

        obs = self._get_observation()
        reward = compute_reward(
            reward_type=self._config.reward_type,
            current_value=end_total_asset,
            previous_value=self._asset_memory[-1] if self._asset_memory else self._config.initial_capital,
            state=self._reward_state,
            scaling=self._config.reward_scaling,
        )

        info = {
            "total_asset": end_total_asset,
            "total_return": total_return,
            "sharpe": sharpe,
            "total_cost": self._total_cost,
            "total_trades": self._total_trades,
            "episode": self._episode,
        }

        return obs, reward, True, False, info

    # ------------------------------------------------------------------
    # Analysis helpers (FinRL pattern)
    # ------------------------------------------------------------------

    def save_asset_memory(self) -> pd.DataFrame:
        """Return portfolio value history as DataFrame."""
        return pd.DataFrame({
            "date": self._date_memory,
            "account_value": self._asset_memory,
        })

    def save_action_memory(self) -> pd.DataFrame:
        """Return action history as DataFrame."""
        if not self._actions_memory:
            return pd.DataFrame()
        dates = self._date_memory[:-1] if len(self._date_memory) > len(self._actions_memory) else self._date_memory
        df = pd.DataFrame(self._actions_memory, columns=self._tickers)
        df.insert(0, "date", dates[:len(df)])
        return df

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_box(
        low: float, high: float, shape: tuple[int, ...],
    ) -> Any:
        """Create a Box space — use gymnasium if available, else duck-typed."""
        if _GYM_AVAILABLE:
            return gym_spaces.Box(low=low, high=high, shape=shape, dtype=np.float32)
        return _BoxSpace(low=low, high=high, shape=shape, dtype=np.float32)

    def get_sb_env(self) -> tuple[Any, np.ndarray]:
        """Wrap in a DummyVecEnv for stable-baselines3 (if available).

        Returns:
            (vec_env, initial_obs) tuple.

        Raises:
            ImportError if stable-baselines3 is not installed.
        """
        try:
            from stable_baselines3.common.vec_env import DummyVecEnv
        except ImportError as exc:
            raise ImportError(
                "stable-baselines3 is required for get_sb_env(). "
                "Install with: pip install stable-baselines3"
            ) from exc

        env = DummyVecEnv([lambda: self])
        obs = env.reset()
        return env, obs
