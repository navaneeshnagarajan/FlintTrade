"""Portfolio optimiser — pure NumPy, zero scipy/cvxpy dependency.

Four optimisation methods for constructing an optimal portfolio from a
DataFrame (or dict) of historical asset returns:

1. ``mean_variance``  — Markowitz mean-variance with analytical solution
2. ``risk_parity``    — equal risk contribution via iterative Newton (Spinu 2013)
3. ``max_diversification`` — maximise diversification ratio (Choueifaty & Coignard)
4. ``equal_volatility``    — weight inversely proportional to per-asset volatility

All four return a :class:`PortfolioResult` Pydantic model.  The unified entry
point :func:`optimize` dispatches to the chosen method.

Design constraints:
- **Pure NumPy** — no scipy, cvxpy, or any other numerical optimisation library.
- Iterative methods converge in ≤ 1 000 iterations with tolerance 1e-10.
- All public functions accept a ``pd.DataFrame`` *or* a ``dict[str, list[float]]``
  (auto-converted internally).

India-specific default: risk-free rate is set to 6.5% p.a. (India 10-year
government bond yield proxy).

Example::

    import pandas as pd
    from .portfolio_optimizer import optimize

    returns = pd.DataFrame(...)          # (n_days, n_assets) daily returns
    result = optimize(returns, method="risk_parity")
    print(result.weights)                # {"NIFTY": 0.42, "BANKNIFTY": 0.58, …}
"""

from __future__ import annotations

import logging
from typing import Union

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

logger = logging.getLogger("flinttrade.backtest.portfolio_optimizer")

# India 10-year G-sec yield (~6.5%) converted to an annualised float.
_INDIA_RFR: float = 0.065

# Type alias for the raw input that every public function accepts.
ReturnsInput = Union[pd.DataFrame, "dict[str, list[float]]"]

# Convenience alias exported for callers.
Weights = dict[str, float]


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


class PortfolioResult(BaseModel):
    """Optimised portfolio statistics.

    Attributes:
        weights: Asset ticker → portfolio weight.  Values sum to 1.0.
        expected_return: Annualised expected return (fraction, e.g. 0.15 = 15%).
        expected_volatility: Annualised expected volatility (fraction).
        sharpe_ratio: Annualised Sharpe ratio using India 10-year G-sec as RFR.
        diversification_ratio: Weighted-average individual volatility divided by
            portfolio volatility.  Higher means more diversification.
    """

    weights: Weights
    expected_return: float
    expected_volatility: float
    sharpe_ratio: float
    diversification_ratio: float = Field(ge=0.0)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_dataframe(returns: ReturnsInput) -> pd.DataFrame:
    """Coerce the caller-supplied input to a :class:`pd.DataFrame`.

    Args:
        returns: Either a ``pd.DataFrame`` (n_days × n_assets) or a dict
            mapping asset name → list of daily returns.

    Returns:
        Normalised ``pd.DataFrame``.

    Raises:
        TypeError: If ``returns`` is neither a DataFrame nor a dict.
    """
    if isinstance(returns, pd.DataFrame):
        return returns
    if isinstance(returns, dict):
        return pd.DataFrame(returns)
    raise TypeError(
        f"returns must be a pd.DataFrame or dict, got {type(returns).__name__}"
    )


def _validate(df: pd.DataFrame) -> None:
    """Validate a returns DataFrame before optimisation.

    Args:
        df: Daily returns, shape (n_days, n_assets).

    Raises:
        ValueError: If the DataFrame is empty, has fewer than 2 assets, or
            contains only NaN values.
    """
    if df.empty:
        raise ValueError("returns is empty")
    if df.shape[1] < 2:
        raise ValueError(
            f"Portfolio optimisation requires at least 2 assets; got {df.shape[1]}"
        )
    if df.isnull().all().all():
        raise ValueError("returns contains only NaN values")


def _annual_stats(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Compute annualised mean returns and covariance matrix.

    Args:
        df: Daily returns, shape (n_days, n_assets).

    Returns:
        Tuple ``(mu, cov)`` where both arrays are annualised (× 252).
    """
    mu: np.ndarray = df.mean().to_numpy() * 252
    cov: np.ndarray = df.cov().to_numpy() * 252
    return mu, cov


def _portfolio_stats(
    weights: np.ndarray,
    mu: np.ndarray,
    cov: np.ndarray,
    rfr: float = _INDIA_RFR,
) -> tuple[float, float, float]:
    """Compute portfolio expected return, volatility, and Sharpe ratio.

    Args:
        weights: Asset weight vector (length = n_assets).
        mu: Annualised mean return vector.
        cov: Annualised covariance matrix.
        rfr: Annualised risk-free rate.

    Returns:
        Tuple ``(expected_return, expected_volatility, sharpe_ratio)``.
    """
    ret: float = float(weights @ mu)
    var: float = float(weights @ cov @ weights)
    vol: float = float(np.sqrt(max(var, 1e-12)))
    sharpe: float = (ret - rfr) / vol
    return ret, vol, sharpe


def _diversification_ratio(weights: np.ndarray, cov: np.ndarray) -> float:
    """Compute diversification ratio.

    Defined as weighted-average individual volatility / portfolio volatility.

    Args:
        weights: Asset weight vector.
        cov: Annualised covariance matrix.

    Returns:
        Diversification ratio (≥ 1.0 for long-only portfolios).
    """
    individual_vols: np.ndarray = np.sqrt(np.diag(cov))
    weighted_avg: float = float(weights @ individual_vols)
    port_vol: float = float(np.sqrt(max(weights @ cov @ weights, 1e-12)))
    return weighted_avg / port_vol


def _build_result(
    assets: list[str],
    weights: np.ndarray,
    mu: np.ndarray,
    cov: np.ndarray,
    rfr: float = _INDIA_RFR,
) -> PortfolioResult:
    """Assemble a :class:`PortfolioResult` from raw arrays.

    Args:
        assets: Asset ticker names (aligned with weight / mu / cov columns).
        weights: Optimised weight vector.
        mu: Annualised mean return vector.
        cov: Annualised covariance matrix.
        rfr: Annualised risk-free rate.

    Returns:
        Populated :class:`PortfolioResult`.
    """
    ret, vol, sharpe = _portfolio_stats(weights, mu, cov, rfr)
    dr = _diversification_ratio(weights, cov)
    weight_dict: Weights = {a: round(float(w), 8) for a, w in zip(assets, weights)}
    return PortfolioResult(
        weights=weight_dict,
        expected_return=round(ret, 8),
        expected_volatility=round(vol, 8),
        sharpe_ratio=round(sharpe, 8),
        diversification_ratio=round(dr, 8),
    )


def _normalise(w: np.ndarray) -> np.ndarray:
    """Normalise a non-negative weight vector to sum to 1.

    Falls back to equal weights when the sum is near-zero.

    Args:
        w: Raw weight vector (values must be ≥ 0).

    Returns:
        Normalised weight vector.
    """
    w = np.maximum(w, 0.0)
    total = w.sum()
    if total < 1e-12:
        return np.ones(len(w)) / len(w)
    return w / total


# ---------------------------------------------------------------------------
# 1. Mean-variance (Markowitz) — analytical solution via two-fund theorem
# ---------------------------------------------------------------------------


def mean_variance(
    returns: ReturnsInput,
    target_return: float | None = None,
    rfr: float = _INDIA_RFR,
) -> Weights:
    """Markowitz mean-variance optimisation — pure NumPy analytical solution.

    When ``target_return`` is ``None``, computes the maximum-Sharpe-ratio
    (tangency) portfolio analytically using the two-fund separation theorem:

        z = Σ⁻¹ (μ - rfr · 1)
        w = z / sum(z)

    Negative weights (short positions) are projected to zero and the result
    is renormalised (long-only constrained approximation).

    When ``target_return`` is given, solves the efficient-frontier quadratic
    programme analytically via the three-parameter characterisation
    (Merton 1972) and returns the minimum-variance portfolio at that return.

    Args:
        returns: Daily return DataFrame or dict of return arrays.
        target_return: Desired annualised target return.  ``None`` → max Sharpe.
        rfr: Annualised risk-free rate (default: India 6.5%).

    Returns:
        ``Weights`` dict mapping asset name → allocation (sums to 1.0).

    Raises:
        ValueError: If ``returns`` is invalid.
        np.linalg.LinAlgError: If the covariance matrix is singular.
    """
    df = _to_dataframe(returns)
    _validate(df)
    mu, cov = _annual_stats(df)
    assets = list(df.columns)
    n = len(assets)

    try:
        cov_inv = np.linalg.inv(cov)
    except np.linalg.LinAlgError:
        # Singular covariance — fall back to equal weights
        logger.warning("mean_variance: singular covariance matrix; using equal weights")
        return {a: round(1.0 / n, 8) for a in assets}

    if target_return is None:
        # Tangency portfolio: z = Σ⁻¹ (μ - rfr · 1)
        excess = mu - rfr
        z = cov_inv @ excess
        w = _normalise(z)
    else:
        # Merton (1972) analytical minimum-variance at target return.
        # Uses the three scalars A, B, C of the efficient-frontier parabola.
        ones = np.ones(n)
        A = float(ones @ cov_inv @ mu)
        B = float(mu @ cov_inv @ mu)
        C = float(ones @ cov_inv @ ones)
        D = B * C - A * A

        if abs(D) < 1e-12:
            # Degenerate — fall back to equal weights
            logger.warning("mean_variance: degenerate frontier (D≈0); using equal weights")
            return {a: round(1.0 / n, 8) for a in assets}

        lam = (C * target_return - A) / D
        gam = (B - A * target_return) / D

        w = lam * (cov_inv @ mu) + gam * (cov_inv @ ones)
        w = _normalise(w)

    return {a: round(float(wi), 8) for a, wi in zip(assets, w)}


# ---------------------------------------------------------------------------
# 2. Risk parity — equal risk contribution (iterative Newton, Spinu 2013)
# ---------------------------------------------------------------------------


def risk_parity(
    returns: ReturnsInput,
    max_iter: int = 1000,
    tol: float = 1e-10,
) -> Weights:
    """Equal risk contribution (ERC / risk parity) portfolio.

    Uses the Spinu (2013) inverse-volatility seed followed by multiplicative
    Newton updates until convergence.  Pure NumPy — no solver libraries.

    The target for each asset i is:

        RC_i = w_i × (Σw)_i / (wᵀΣw) = 1/n

    Args:
        returns: Daily return DataFrame or dict of return arrays.
        max_iter: Maximum Newton iterations (default 1 000).
        tol: Convergence tolerance on the risk-contribution deviation
            (default 1e-10).

    Returns:
        ``Weights`` dict mapping asset name → allocation (sums to 1.0).

    Raises:
        ValueError: If ``returns`` is invalid.
    """
    df = _to_dataframe(returns)
    _validate(df)
    mu, cov = _annual_stats(df)
    assets = list(df.columns)
    n = len(assets)

    vols = np.sqrt(np.diag(cov))
    if np.any(vols < 1e-12):
        # Degenerate zero-vol asset — fall back to equal weight
        logger.warning("risk_parity: zero-volatility asset detected; using equal weights")
        return {a: round(1.0 / n, 8) for a in assets}

    # Seed: inverse-volatility weights (strictly positive, sums to 1)
    inv_vol = 1.0 / vols
    w = inv_vol / inv_vol.sum()

    # We optimise x = log(w) to keep weights strictly positive at all times.
    # ERC objective: minimise f(x) = Σ_i Σ_j (RC_i - RC_j)^2
    # where RC_i = w_i * (Σw)_i / (wᵀΣw).
    # Gradient of f w.r.t. x_k = ∂f/∂w_k * w_k  (chain rule through log).
    # We use gradient descent on the log-weight parametrisation with a
    # backtracking line-search — guaranteed to keep weights positive.

    def _rc_deviation_sq(x: np.ndarray) -> float:
        """Squared pairwise RC deviations (objective, lower is better)."""
        ww = np.exp(x)
        pv = float(ww @ cov @ ww)
        if pv < 1e-12:
            return 1e12
        mrc = cov @ ww
        rc = ww * mrc / pv          # risk contributions (normalised by port var)
        target_rc = 1.0 / n
        return float(np.sum((rc - target_rc) ** 2))

    def _grad_rc_dev(x: np.ndarray) -> np.ndarray:
        """Numerical gradient of the objective w.r.t. log-weights."""
        eps = 1e-5
        grad = np.zeros(n)
        f0 = _rc_deviation_sq(x)
        for k in range(n):
            xp = x.copy()
            xp[k] += eps
            grad[k] = (_rc_deviation_sq(xp) - f0) / eps
        return grad

    x = np.log(w)  # work in log-space
    step = 1.0

    for iteration in range(max_iter):
        grad = _grad_rc_dev(x)
        grad_norm = float(np.linalg.norm(grad))
        if grad_norm < tol:
            logger.debug("risk_parity: converged after %d iterations", iteration + 1)
            break

        # Armijo back-tracking line search
        f0 = _rc_deviation_sq(x)
        a = step
        for _ in range(60):
            x_new = x - a * grad
            if _rc_deviation_sq(x_new) <= f0 - 1e-4 * a * grad_norm ** 2:
                break
            a *= 0.5
        else:
            logger.debug("risk_parity: line search exhausted at iter %d", iteration)
            break

        x = x - a * grad

    # Convert back from log-space, normalise
    w = np.exp(x)
    w = np.maximum(w, 0.0)
    w = w / w.sum()

    return {a: round(float(wi), 8) for a, wi in zip(assets, w)}


# ---------------------------------------------------------------------------
# 3. Max diversification — pure NumPy gradient ascent
# ---------------------------------------------------------------------------


def max_diversification(
    returns: ReturnsInput,
    max_iter: int = 1000,
    tol: float = 1e-10,
    step_size: float = 0.01,
) -> Weights:
    """Maximum diversification portfolio (Choueifaty & Coignard 2008).

    Maximises the diversification ratio:

        DR(w) = (wᵀσ) / sqrt(wᵀΣw)

    where σ is the vector of individual asset volatilities.

    Uses projected gradient ascent on the unit simplex with adaptive
    Armijo line-search.  Pure NumPy.

    Args:
        returns: Daily return DataFrame or dict of return arrays.
        max_iter: Maximum gradient iterations (default 1 000).
        tol: Gradient norm convergence threshold (default 1e-10).
        step_size: Initial step size for gradient ascent (default 0.01).

    Returns:
        ``Weights`` dict mapping asset name → allocation (sums to 1.0).

    Raises:
        ValueError: If ``returns`` is invalid.
    """
    df = _to_dataframe(returns)
    _validate(df)
    mu, cov = _annual_stats(df)
    assets = list(df.columns)
    n = len(assets)

    vols = np.sqrt(np.diag(cov))
    if np.any(vols < 1e-12):
        logger.warning("max_diversification: zero-vol asset; using equal weights")
        return {a: round(1.0 / n, 8) for a in assets}

    def _dr(w: np.ndarray) -> float:
        pv = float(w @ cov @ w)
        return float(w @ vols) / np.sqrt(max(pv, 1e-12))

    def _grad_dr(w: np.ndarray) -> np.ndarray:
        """Analytical gradient of DR w.r.t. weights."""
        pv = float(w @ cov @ w)
        pv = max(pv, 1e-12)
        pv_sqrt = np.sqrt(pv)
        num = float(w @ vols)
        # ∂DR/∂w = vols/pv_sqrt - num * (Σw) / pv^(3/2)
        return vols / pv_sqrt - num * (cov @ w) / (pv * pv_sqrt)

    def _project_simplex(v: np.ndarray) -> np.ndarray:
        """Project onto the probability simplex (long-only, sum-to-1).

        Uses the sort-based O(n log n) algorithm of Duchi et al. (2008).
        """
        u = np.sort(v)[::-1]
        cssv = np.cumsum(u)
        rho = int(np.where(u > (cssv - 1.0) / (np.arange(n) + 1))[0][-1])
        theta = (cssv[rho] - 1.0) / (rho + 1)
        return np.maximum(v - theta, 0.0)

    # Initialise at inverse-volatility weights (close to optimum empirically)
    w = _normalise(1.0 / vols)

    alpha = step_size
    prev_dr = _dr(w)

    for iteration in range(max_iter):
        grad = _grad_dr(w)
        grad_norm = float(np.linalg.norm(grad))
        if grad_norm < tol:
            logger.debug("max_diversification: converged after %d iterations", iteration + 1)
            break

        # Armijo back-tracking line search
        a = alpha
        for _ in range(50):
            w_new = _project_simplex(w + a * grad)
            if _dr(w_new) >= prev_dr + 1e-4 * a * grad_norm**2:
                break
            a *= 0.5
        else:
            # No improvement found — break gracefully
            logger.debug("max_diversification: line search exhausted at iteration %d", iteration)
            break

        w = w_new
        new_dr = _dr(w)
        if abs(new_dr - prev_dr) < tol:
            logger.debug("max_diversification: DR plateau at iteration %d", iteration + 1)
            break
        prev_dr = new_dr

    w = _normalise(w)
    return {a: round(float(wi), 8) for a, wi in zip(assets, w)}


# ---------------------------------------------------------------------------
# 4. Equal volatility (inverse-vol)
# ---------------------------------------------------------------------------


def equal_volatility(returns: ReturnsInput) -> Weights:
    """Equal-volatility (inverse-volatility) portfolio.

    Weights each asset inversely proportional to its historical rolling
    volatility so that every asset contributes similar volatility to the
    portfolio.  Closed-form — no iteration required.

    Args:
        returns: Daily return DataFrame or dict of return arrays.

    Returns:
        ``Weights`` dict mapping asset name → allocation (sums to 1.0).

    Raises:
        ValueError: If ``returns`` is invalid or any asset has zero variance.
    """
    df = _to_dataframe(returns)
    _validate(df)
    assets = list(df.columns)

    vols: np.ndarray = df.std(ddof=1).to_numpy() * np.sqrt(252)

    zero_mask = vols < 1e-12
    if zero_mask.any():
        bad = [assets[i] for i in np.where(zero_mask)[0]]
        logger.warning(
            "equal_volatility: near-zero volatility for %s — assigning minimum weight",
            bad,
        )
        vols = np.where(zero_mask, 1e-12, vols)

    inv_vol = 1.0 / vols
    w = _normalise(inv_vol)
    return {a: round(float(wi), 8) for a, wi in zip(assets, w)}


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------


def optimize(
    returns: ReturnsInput,
    method: str = "risk_parity",
    target_return: float | None = None,
    rfr: float = _INDIA_RFR,
) -> PortfolioResult:
    """Unified portfolio optimisation entry point.

    Dispatches to one of the four optimisation methods and returns a
    :class:`PortfolioResult` with weights, statistics, and diagnostics.

    Args:
        returns: Daily return DataFrame (n_days × n_assets) or dict of
            ``{asset_name: [daily_return, …]}``.
        method: Optimisation method — one of:
            ``"mean_variance"``, ``"risk_parity"``,
            ``"max_diversification"``, ``"equal_volatility"``.
        target_return: Annualised target return for ``mean_variance`` only.
            Ignored by other methods.
        rfr: Annualised risk-free rate (default: India 6.5%).

    Returns:
        :class:`PortfolioResult` with optimal weights and portfolio statistics.

    Raises:
        ValueError: If ``method`` is not recognised or ``returns`` is invalid.

    Example::

        result = optimize(returns_df, method="risk_parity")
        print(result.weights)       # {"NIFTY": 0.42, …}
        print(result.sharpe_ratio)  # 1.34
    """
    df = _to_dataframe(returns)
    _validate(df)
    mu, cov = _annual_stats(df)
    assets = list(df.columns)

    _dispatch: dict[str, Weights] = {}

    match method:
        case "mean_variance":
            raw_weights = mean_variance(df, target_return=target_return, rfr=rfr)
        case "risk_parity":
            raw_weights = risk_parity(df)
        case "max_diversification":
            raw_weights = max_diversification(df)
        case "equal_volatility":
            raw_weights = equal_volatility(df)
        case _:
            raise ValueError(
                f"Unknown method '{method}'. "
                "Choose from: mean_variance, risk_parity, max_diversification, equal_volatility."
            )

    # Reconstruct weight array (preserves asset order)
    w = np.array([raw_weights[a] for a in assets])
    return _build_result(assets, w, mu, cov, rfr)
