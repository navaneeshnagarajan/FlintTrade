"""Feature engineering and reward functions for RL trading environments.

Adapts patterns from FinRL's data processing and feature engineering.
Provides technical indicator computation, normalisation, and multiple
reward function implementations for reinforcement learning agents.

All dependencies (pandas, numpy) are standard — no RL library imports.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Feature list constants (inspired by FinRL's INDICATORS config)
# ---------------------------------------------------------------------------

DEFAULT_FEATURES: list[str] = [
    "returns",
    "log_returns",
    "volatility_20",
    "rsi_14",
    "sma_20",
    "sma_50",
    "ema_12",
    "ema_26",
    "macd",
    "macd_signal",
    "bollinger_upper",
    "bollinger_lower",
    "volume_ratio",
    "atr_14",
]

# Features suitable for a minimal/fast setup
MINIMAL_FEATURES: list[str] = [
    "returns",
    "volatility_20",
    "rsi_14",
    "sma_20",
    "volume_ratio",
]


# ---------------------------------------------------------------------------
# Reward function types
# ---------------------------------------------------------------------------


class RewardType(StrEnum):
    """Available reward function types."""

    PNL = "pnl"
    SHARPE = "sharpe"
    SORTINO = "sortino"
    RISK_ADJUSTED = "risk_adjusted"
    LOG_RETURN = "log_return"


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------


def compute_features(
    df: pd.DataFrame,
    features: list[str] | None = None,
    inplace: bool = False,
) -> pd.DataFrame:
    """Compute technical features and add them as columns.

    Args:
        df: DataFrame with at least 'close' and 'volume' columns.
            Optionally 'high' and 'low' for ATR.
        features: list of feature names to compute. Defaults to DEFAULT_FEATURES.
        inplace: if True, modify df in place; otherwise return a copy.

    Returns:
        DataFrame with feature columns added.
    """
    if not inplace:
        df = df.copy()

    if features is None:
        features = DEFAULT_FEATURES

    close = df["close"].astype(float)
    volume = df["volume"].astype(float) if "volume" in df.columns else pd.Series(
        np.ones(len(df)), index=df.index,
    )
    high = df["high"].astype(float) if "high" in df.columns else close
    low = df["low"].astype(float) if "low" in df.columns else close

    for feat in features:
        if feat == "returns":
            df["returns"] = close.pct_change().fillna(0.0)

        elif feat == "log_returns":
            df["log_returns"] = np.log(close / close.shift(1)).fillna(0.0)

        elif feat.startswith("volatility_"):
            window = int(feat.split("_")[1])
            df[feat] = close.pct_change().rolling(window).std().fillna(0.0)

        elif feat.startswith("rsi_"):
            period = int(feat.split("_")[1])
            df[feat] = _compute_rsi(close, period)

        elif feat.startswith("sma_"):
            window = int(feat.split("_")[1])
            df[feat] = close.rolling(window).mean().fillna(close.iloc[0])

        elif feat.startswith("ema_"):
            span = int(feat.split("_")[1])
            df[feat] = close.ewm(span=span, adjust=False).mean()

        elif feat == "macd":
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            df["macd"] = ema12 - ema26

        elif feat == "macd_signal":
            if "macd" not in df.columns:
                ema12 = close.ewm(span=12, adjust=False).mean()
                ema26 = close.ewm(span=26, adjust=False).mean()
                df["macd"] = ema12 - ema26
            df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()

        elif feat == "bollinger_upper":
            sma20 = close.rolling(20).mean().fillna(close.iloc[0])
            std20 = close.rolling(20).std().fillna(0.0)
            df["bollinger_upper"] = sma20 + 2 * std20

        elif feat == "bollinger_lower":
            sma20 = close.rolling(20).mean().fillna(close.iloc[0])
            std20 = close.rolling(20).std().fillna(0.0)
            df["bollinger_lower"] = sma20 - 2 * std20

        elif feat == "volume_ratio":
            avg_vol = volume.rolling(20).mean().fillna(volume.iloc[0] if len(volume) > 0 else 1.0)
            df["volume_ratio"] = (volume / avg_vol.replace(0, 1)).fillna(1.0)

        elif feat.startswith("atr_"):
            period = int(feat.split("_")[1])
            df[feat] = _compute_atr(high, low, close, period)

    return df


def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.inf)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(50.0)


def _compute_atr(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14,
) -> pd.Series:
    """Average True Range."""
    prev_close = close.shift(1).fillna(close.iloc[0])
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean().fillna(0.0)


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def normalise_features(
    df: pd.DataFrame,
    features: list[str],
    method: str = "zscore",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Normalise feature columns.

    Args:
        df: DataFrame containing feature columns.
        features: list of column names to normalise.
        method: 'zscore' (default), 'minmax', or 'robust'.

    Returns:
        (normalised_df, stats_dict) — stats can be used to normalise new data.
    """
    df = df.copy()
    stats: dict[str, Any] = {"method": method}

    for feat in features:
        if feat not in df.columns:
            continue

        col = df[feat].astype(float)

        if method == "zscore":
            mean = col.mean()
            std = col.std()
            if std == 0:
                std = 1.0
            df[feat] = (col - mean) / std
            stats[feat] = {"mean": mean, "std": std}

        elif method == "minmax":
            col_min = col.min()
            col_max = col.max()
            span = col_max - col_min
            if span == 0:
                span = 1.0
            df[feat] = (col - col_min) / span
            stats[feat] = {"min": col_min, "max": col_max}

        elif method == "robust":
            median = col.median()
            q1 = col.quantile(0.25)
            q3 = col.quantile(0.75)
            iqr = q3 - q1
            if iqr == 0:
                iqr = 1.0
            df[feat] = (col - median) / iqr
            stats[feat] = {"median": median, "q1": q1, "q3": q3, "iqr": iqr}

    return df, stats


def apply_normalisation(
    df: pd.DataFrame,
    features: list[str],
    stats: dict[str, Any],
) -> pd.DataFrame:
    """Apply previously computed normalisation statistics to new data."""
    df = df.copy()
    method = stats.get("method", "zscore")

    for feat in features:
        if feat not in df.columns or feat not in stats:
            continue

        col = df[feat].astype(float)
        s = stats[feat]

        if method == "zscore":
            df[feat] = (col - s["mean"]) / s["std"]
        elif method == "minmax":
            span = s["max"] - s["min"]
            if span == 0:
                span = 1.0
            df[feat] = (col - s["min"]) / span
        elif method == "robust":
            df[feat] = (col - s["median"]) / s["iqr"]

    return df


# ---------------------------------------------------------------------------
# Reward functions
# ---------------------------------------------------------------------------


@dataclass
class RewardState:
    """Tracks state needed for reward computation across steps."""

    portfolio_values: list[float]
    risk_free_daily: float = 0.07 / 252  # India risk-free rate, daily


def compute_reward(
    reward_type: RewardType | str,
    current_value: float,
    previous_value: float,
    state: RewardState | None = None,
    scaling: float = 1.0,
) -> float:
    """Compute reward for a single environment step.

    Args:
        reward_type: which reward function to use.
        current_value: portfolio value after action.
        previous_value: portfolio value before action.
        state: RewardState for stateful rewards (Sharpe, Sortino).
        scaling: reward scaling factor (FinRL uses 2**-11 typically).

    Returns:
        Scalar reward value.
    """
    reward_type = RewardType(reward_type) if isinstance(reward_type, str) else reward_type

    if reward_type == RewardType.PNL:
        return (current_value - previous_value) * scaling

    elif reward_type == RewardType.LOG_RETURN:
        if previous_value <= 0:
            return 0.0
        return math.log(current_value / previous_value) * scaling

    elif reward_type == RewardType.SHARPE:
        if state is None or len(state.portfolio_values) < 2:
            return (current_value - previous_value) * scaling
        returns = _compute_returns_from_values(state.portfolio_values)
        if len(returns) < 2:
            return 0.0
        excess = np.array(returns) - state.risk_free_daily
        std = np.std(excess)
        if std == 0:
            return 0.0
        sharpe = np.mean(excess) / std
        return float(sharpe) * scaling

    elif reward_type == RewardType.SORTINO:
        if state is None or len(state.portfolio_values) < 2:
            return (current_value - previous_value) * scaling
        returns = _compute_returns_from_values(state.portfolio_values)
        if len(returns) < 2:
            return 0.0
        excess = np.array(returns) - state.risk_free_daily
        downside = excess[excess < 0]
        down_std = np.std(downside) if len(downside) > 0 else 0.0
        if down_std == 0:
            return 0.0
        sortino = np.mean(excess) / down_std
        return float(sortino) * scaling

    elif reward_type == RewardType.RISK_ADJUSTED:
        # Blend: PnL reward penalised by drawdown
        pnl_reward = (current_value - previous_value) * scaling
        if state is not None and len(state.portfolio_values) > 0:
            peak = max(state.portfolio_values)
            dd = (peak - current_value) / peak if peak > 0 else 0.0
            pnl_reward -= dd * abs(pnl_reward) * 0.5
        return pnl_reward

    return 0.0


def _compute_returns_from_values(values: list[float]) -> list[float]:
    """Compute simple returns from a list of portfolio values."""
    returns = []
    for i in range(1, len(values)):
        if values[i - 1] > 0:
            returns.append((values[i] - values[i - 1]) / values[i - 1])
        else:
            returns.append(0.0)
    return returns
