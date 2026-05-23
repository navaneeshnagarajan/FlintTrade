"""Portfolio optimisation module.

Supports multiple optimisation strategies for constructing an optimal
portfolio from a DataFrame of historical asset returns:

- **Markowitz** — classic mean-variance (max Sharpe ratio)
- **Min-variance** — minimum volatility regardless of return
- **Risk parity** — equal risk contribution across assets
- **Equal weight** — naive 1/N baseline
- **Max Sharpe** — alias for Markowitz with explicit Sharpe maximisation
- **Black-Litterman** — incorporate analyst views into the prior

All methods return a :class:`PortfolioResult` Pydantic model.  The efficient
frontier helper produces a list of results spanning the achievable
return / risk space.

Dependencies: numpy, scipy (SLSQP), pandas, pydantic.

Example::

    import pandas as pd
    from .portfolio_optimiser import (
        OptimiserConfig, PortfolioOptimiser,
    )

    returns = pd.DataFrame(...)        # (n_days, n_assets) daily returns
    cfg = OptimiserConfig(method="markowitz")
    result = PortfolioOptimiser(cfg).optimise(returns)
    print(result.weights)
"""

from __future__ import annotations

import logging
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, model_validator
from scipy.optimize import minimize

logger = logging.getLogger("flinttrade.backtest.portfolio_optimiser")

# India 10-year government bond yield used as proxy for risk-free rate.
_INDIA_RFR_DAILY = 0.065 / 252  # annualised 6.5% → daily

OptimisationMethod = Literal[
    "markowitz", "risk_parity", "equal_weight", "min_variance", "max_sharpe"
]
RebalanceFrequency = Literal["daily", "weekly", "monthly", "quarterly"]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class OptimiserConfig(BaseModel):
    """Configuration for :class:`PortfolioOptimiser`.

    Attributes:
        method: Optimisation algorithm to use.
        risk_free_rate: Annualised risk-free rate (India 10Y ~6.5%).
        target_return: Annualised target return for efficient-frontier
            generation.  When ``None`` the full frontier is auto-ranged.
        max_weight: Maximum allocation per asset (0–1).
        min_weight: Minimum allocation per asset (0–1).
        rebalance_frequency: How often the portfolio is rebalanced in
            production (informational — optimiser is stateless).
    """

    method: OptimisationMethod = "markowitz"
    risk_free_rate: float = Field(default=0.065, ge=0.0, le=1.0)
    target_return: float | None = None
    max_weight: float = Field(default=0.4, ge=0.0, le=1.0)
    min_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    rebalance_frequency: RebalanceFrequency = "monthly"

    @model_validator(mode="after")
    def _validate_weight_bounds(self) -> "OptimiserConfig":
        if self.min_weight > self.max_weight:
            raise ValueError(
                f"min_weight ({self.min_weight}) must be <= max_weight ({self.max_weight})"
            )
        return self


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


class PortfolioResult(BaseModel):
    """Optimised portfolio statistics.

    Attributes:
        weights: Asset ticker → portfolio weight (sum to 1.0).
        expected_return: Annualised expected return (fraction, e.g. 0.15 = 15%).
        expected_volatility: Annualised expected volatility (fraction).
        sharpe_ratio: Annualised Sharpe ratio.
        diversification_ratio: Weighted average asset volatility divided by
            portfolio volatility.  Higher → more diversification.
    """

    weights: dict[str, float]
    expected_return: float
    expected_volatility: float
    sharpe_ratio: float
    diversification_ratio: float


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _annual_stats(
    returns: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute annualised mean returns and covariance matrix.

    Args:
        returns: (n_days × n_assets) daily return DataFrame.

    Returns:
        Tuple of (mean_returns, cov_matrix) both annualised.
    """
    mu: np.ndarray = returns.mean().values * 252
    cov: np.ndarray = returns.cov().values * 252
    return mu, cov


def _portfolio_stats(
    weights: np.ndarray,
    mu: np.ndarray,
    cov: np.ndarray,
    rfr: float,
) -> tuple[float, float, float]:
    """Return (expected_return, volatility, sharpe) for a weight vector.

    Args:
        weights: Asset weight vector (length = n_assets).
        mu: Annualised mean return vector.
        cov: Annualised covariance matrix.
        rfr: Annualised risk-free rate.

    Returns:
        (expected_return, expected_volatility, sharpe_ratio)
    """
    ret: float = float(weights @ mu)
    var: float = float(weights @ cov @ weights)
    vol: float = float(np.sqrt(max(var, 1e-12)))
    sharpe: float = (ret - rfr) / vol
    return ret, vol, sharpe


def _diversification_ratio(
    weights: np.ndarray,
    cov: np.ndarray,
) -> float:
    """Compute diversification ratio.

    Defined as weighted average individual volatility / portfolio volatility.

    Args:
        weights: Asset weight vector.
        cov: Annualised covariance matrix.

    Returns:
        Diversification ratio (≥ 1.0 for long-only portfolios).
    """
    individual_vols: np.ndarray = np.sqrt(np.diag(cov))
    weighted_avg_vol: float = float(weights @ individual_vols)
    portfolio_vol: float = float(np.sqrt(max(weights @ cov @ weights, 1e-12)))
    return weighted_avg_vol / portfolio_vol


def _build_result(
    assets: list[str],
    weights: np.ndarray,
    mu: np.ndarray,
    cov: np.ndarray,
    rfr: float,
) -> PortfolioResult:
    """Build a :class:`PortfolioResult` from raw arrays.

    Args:
        assets: Asset ticker names aligned with weight/return/cov columns.
        weights: Optimised weight vector.
        mu: Annualised mean return vector.
        cov: Annualised covariance matrix.
        rfr: Annualised risk-free rate.

    Returns:
        Populated :class:`PortfolioResult`.
    """
    ret, vol, sharpe = _portfolio_stats(weights, mu, cov, rfr)
    div_ratio = _diversification_ratio(weights, cov)
    weight_dict = {asset: round(float(w), 8) for asset, w in zip(assets, weights)}
    return PortfolioResult(
        weights=weight_dict,
        expected_return=round(ret, 8),
        expected_volatility=round(vol, 8),
        sharpe_ratio=round(sharpe, 8),
        diversification_ratio=round(div_ratio, 8),
    )


def _make_constraints(
    n: int,
    target_return: float | None,
    mu: np.ndarray,
) -> list[dict]:
    """Build SLSQP constraint dictionaries.

    Args:
        n: Number of assets.
        target_return: Fixed return target; ``None`` omits this constraint.
        mu: Annualised mean return vector.

    Returns:
        List of scipy constraint dicts.
    """
    constraints: list[dict] = [
        {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
    ]
    if target_return is not None:
        constraints.append(
            {"type": "eq", "fun": lambda w, r=target_return: float(w @ mu) - r}
        )
    return constraints


# ---------------------------------------------------------------------------
# PortfolioOptimiser
# ---------------------------------------------------------------------------


class PortfolioOptimiser:
    """Multi-method portfolio optimiser.

    Args:
        config: :class:`OptimiserConfig` instance controlling algorithm and
            constraints.

    Example::

        optimiser = PortfolioOptimiser(OptimiserConfig(method="markowitz"))
        result = optimiser.optimise(returns_df)
    """

    def __init__(self, config: OptimiserConfig) -> None:
        self._config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def optimise(self, returns: pd.DataFrame) -> PortfolioResult:
        """Optimise portfolio weights from historical returns.

        Delegates to the method specified in :attr:`config.method`.

        Args:
            returns: DataFrame of shape (n_days, n_assets) where each
                column is an asset ticker and each row is a daily return.

        Returns:
            :class:`PortfolioResult` with optimal weights and statistics.

        Raises:
            ValueError: If ``returns`` is empty or has fewer than 2 assets.
        """
        self._validate_returns(returns)
        method = self._config.method
        if method in ("markowitz", "max_sharpe"):
            return self.markowitz(returns)
        if method == "min_variance":
            return self.min_variance(returns)
        if method == "risk_parity":
            return self.risk_parity(returns)
        # equal_weight
        return self._equal_weight(returns)

    def efficient_frontier(
        self,
        returns: pd.DataFrame,
        n_points: int = 50,
    ) -> list[PortfolioResult]:
        """Generate efficient frontier points.

        Spans from minimum-variance return to maximum-return portfolio,
        computing the minimum-variance portfolio for each target return.

        Args:
            returns: DataFrame of shape (n_days, n_assets) daily returns.
            n_points: Number of frontier points to compute.

        Returns:
            List of :class:`PortfolioResult` ordered from low to high return.
        """
        self._validate_returns(returns)
        mu, cov = _annual_stats(returns)
        n = len(mu)
        bounds = self._bounds(n)

        # Determine return range
        min_ret = float(mu.min())
        max_ret = float(mu.max())
        if min_ret >= max_ret:
            # All assets identical — return single point
            w = np.full(n, 1.0 / n)
            return [_build_result(list(returns.columns), w, mu, cov, self._config.risk_free_rate)]

        target_returns = np.linspace(min_ret, max_ret, n_points)
        rfr = self._config.risk_free_rate
        frontier: list[PortfolioResult] = []

        for target in target_returns:
            constraints = _make_constraints(n, float(target), mu)
            w0 = np.full(n, 1.0 / n)
            result = minimize(
                lambda w: float(w @ cov @ w),
                w0,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={"ftol": 1e-9, "maxiter": 1000},
            )
            if result.success:
                w = np.clip(result.x, 0.0, 1.0)
                w /= w.sum()
                frontier.append(
                    _build_result(list(returns.columns), w, mu, cov, rfr)
                )
            else:
                logger.debug(
                    "Frontier point at target_return=%.4f failed: %s",
                    target, result.message,
                )

        return frontier

    def markowitz(self, returns: pd.DataFrame) -> PortfolioResult:
        """Mean-variance optimisation maximising the Sharpe ratio.

        Uses SLSQP to minimise the negative Sharpe ratio subject to weights
        summing to 1, with per-asset box constraints from the config.

        Args:
            returns: DataFrame of daily returns (n_days × n_assets).

        Returns:
            :class:`PortfolioResult` at the max-Sharpe point.
        """
        self._validate_returns(returns)
        mu, cov = _annual_stats(returns)
        n = len(mu)
        rfr = self._config.risk_free_rate
        bounds = self._bounds(n)
        constraints = _make_constraints(n, None, mu)

        def _neg_sharpe(w: np.ndarray) -> float:
            ret, vol, _ = _portfolio_stats(w, mu, cov, rfr)
            return -(ret - rfr) / max(vol, 1e-12)

        w0 = np.full(n, 1.0 / n)
        result = minimize(
            _neg_sharpe,
            w0,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"ftol": 1e-9, "maxiter": 1000},
        )
        w = self._fallback_if_failed(result, n)
        return _build_result(list(returns.columns), w, mu, cov, rfr)

    def risk_parity(self, returns: pd.DataFrame) -> PortfolioResult:
        """Risk parity — equal risk contribution from every asset.

        Minimises the sum of squared pairwise differences of risk
        contributions so each asset contributes equally to total portfolio
        variance.

        Args:
            returns: DataFrame of daily returns (n_days × n_assets).

        Returns:
            :class:`PortfolioResult` at the risk-parity point.
        """
        self._validate_returns(returns)
        mu, cov = _annual_stats(returns)
        n = len(mu)
        rfr = self._config.risk_free_rate
        bounds = self._bounds(n)

        def _risk_parity_obj(w: np.ndarray) -> float:
            portfolio_var = float(w @ cov @ w)
            # Marginal risk contribution per asset
            mrc = cov @ w
            # Risk contribution
            rc = w * mrc / max(portfolio_var, 1e-12)
            target = 1.0 / n
            return float(np.sum((rc - target) ** 2))

        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
        w0 = np.full(n, 1.0 / n)
        result = minimize(
            _risk_parity_obj,
            w0,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"ftol": 1e-10, "maxiter": 2000},
        )
        w = self._fallback_if_failed(result, n)
        return _build_result(list(returns.columns), w, mu, cov, rfr)

    def min_variance(self, returns: pd.DataFrame) -> PortfolioResult:
        """Minimum variance portfolio — lowest possible portfolio volatility.

        Args:
            returns: DataFrame of daily returns (n_days × n_assets).

        Returns:
            :class:`PortfolioResult` at the global minimum-variance point.
        """
        self._validate_returns(returns)
        mu, cov = _annual_stats(returns)
        n = len(mu)
        rfr = self._config.risk_free_rate
        bounds = self._bounds(n)
        constraints = _make_constraints(n, None, mu)

        def _portfolio_var(w: np.ndarray) -> float:
            return float(w @ cov @ w)

        w0 = np.full(n, 1.0 / n)
        result = minimize(
            _portfolio_var,
            w0,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"ftol": 1e-9, "maxiter": 1000},
        )
        w = self._fallback_if_failed(result, n)
        return _build_result(list(returns.columns), w, mu, cov, rfr)

    def black_litterman(
        self,
        returns: pd.DataFrame,
        views: dict[str, float],
        confidence: dict[str, float],
    ) -> PortfolioResult:
        """Black-Litterman model incorporating analyst views.

        Blends a market-equilibrium prior (from the equal-weight portfolio)
        with absolute views on expected asset returns.

        Args:
            returns: DataFrame of daily returns (n_days × n_assets).
            views: Mapping of asset ticker → expected annualised return
                (e.g. ``{"RELIANCE": 0.18}`` means 18% expected return).
            confidence: Mapping of asset ticker → confidence level in the
                view (0–1, e.g. ``{"RELIANCE": 0.7}``).  Assets not present
                default to 0.5.

        Returns:
            :class:`PortfolioResult` with BL-adjusted weights via max-Sharpe
            on the posterior expected returns.

        Raises:
            ValueError: If any view ticker is not in ``returns.columns``.
        """
        self._validate_returns(returns)
        assets = list(returns.columns)
        mu_eq, cov = _annual_stats(returns)

        # Validate view keys
        unknown = set(views.keys()) - set(assets)
        if unknown:
            raise ValueError(f"View tickers not in returns columns: {unknown}")

        # Scalar uncertainty scaling (τ)
        tau = 0.05

        # Build view matrix P (k × n) and view vector q (k,)
        view_items = [(a, v) for a, v in views.items() if a in assets]
        k = len(view_items)
        if k == 0:
            # No views — fall back to Markowitz
            return self.markowitz(returns)

        asset_index = {a: i for i, a in enumerate(assets)}
        n = len(assets)
        P = np.zeros((k, n))
        q = np.zeros(k)
        omega_diag = np.zeros(k)

        for i, (asset, view_ret) in enumerate(view_items):
            P[i, asset_index[asset]] = 1.0
            q[i] = view_ret
            conf = confidence.get(asset, 0.5)
            # Uncertainty inversely proportional to confidence
            omega_diag[i] = max((1.0 - conf) / max(conf, 1e-6) * tau, 1e-6)

        omega = np.diag(omega_diag)

        # BL posterior mean: μ_BL = [(τΣ)^-1 + P'Ω^-1 P]^-1 [(τΣ)^-1 μ + P'Ω^-1 q]
        tau_cov = tau * cov
        try:
            tau_cov_inv = np.linalg.inv(tau_cov)
            omega_inv = np.linalg.inv(omega)
            m1 = tau_cov_inv + P.T @ omega_inv @ P
            m2 = tau_cov_inv @ mu_eq + P.T @ omega_inv @ q
            mu_bl = np.linalg.solve(m1, m2)
        except np.linalg.LinAlgError:
            logger.warning(
                "Black-Litterman matrix inversion failed; falling back to Markowitz"
            )
            return self.markowitz(returns)

        # Build a synthetic returns frame with BL means then optimise
        # We scale daily returns so the sample mean matches mu_bl / 252
        rfr = self._config.risk_free_rate
        bounds = self._bounds(n)
        constraints = _make_constraints(n, None, mu_bl)

        def _neg_sharpe_bl(w: np.ndarray) -> float:
            ret = float(w @ mu_bl)
            vol = float(np.sqrt(max(w @ cov @ w, 1e-12)))
            return -(ret - rfr) / vol

        w0 = np.full(n, 1.0 / n)
        result = minimize(
            _neg_sharpe_bl,
            w0,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"ftol": 1e-9, "maxiter": 1000},
        )
        w = self._fallback_if_failed(result, n)
        return _build_result(assets, w, mu_bl, cov, rfr)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _equal_weight(self, returns: pd.DataFrame) -> PortfolioResult:
        """Naive 1/N equal-weight portfolio.

        Args:
            returns: DataFrame of daily returns.

        Returns:
            :class:`PortfolioResult` with equal weights.
        """
        mu, cov = _annual_stats(returns)
        n = len(mu)
        w = np.full(n, 1.0 / n)
        return _build_result(
            list(returns.columns), w, mu, cov, self._config.risk_free_rate
        )

    def _bounds(self, n: int) -> list[tuple[float, float]]:
        """Build per-asset box constraints from config.

        Args:
            n: Number of assets.

        Returns:
            List of (min_weight, max_weight) tuples.
        """
        lo = self._config.min_weight
        hi = self._config.max_weight
        return [(lo, hi)] * n

    @staticmethod
    def _fallback_if_failed(result: object, n: int) -> np.ndarray:
        """Return optimised weights or equal-weight fallback.

        Args:
            result: scipy OptimizeResult.
            n: Number of assets.

        Returns:
            Normalised weight array.
        """
        if result.success:  # type: ignore[union-attr]
            w = np.clip(result.x, 0.0, 1.0)  # type: ignore[union-attr]
        else:
            logger.warning(
                "Optimisation did not converge: %s — using equal-weight fallback",
                result.message,  # type: ignore[union-attr]
            )
            w = np.full(n, 1.0 / n)
        total = w.sum()
        if total < 1e-10:
            w = np.full(n, 1.0 / n)
        else:
            w = w / total
        return w

    @staticmethod
    def _validate_returns(returns: pd.DataFrame) -> None:
        """Validate that returns DataFrame is usable.

        Args:
            returns: Input returns DataFrame.

        Raises:
            ValueError: If empty, has fewer than 2 assets, or contains
                only NaN values.
        """
        if returns.empty:
            raise ValueError("returns DataFrame is empty")
        if returns.shape[1] < 2:
            raise ValueError(
                f"Portfolio optimisation requires at least 2 assets; "
                f"got {returns.shape[1]}"
            )
        if returns.isnull().all().all():
            raise ValueError("returns DataFrame contains only NaN values")
