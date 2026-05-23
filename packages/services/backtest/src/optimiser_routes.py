"""Flask Blueprint for portfolio optimisation endpoints.

External URLs (frontend calls these via /ft-api/v1/portfolio/*; the WSGI prefix
stripper in app.py rewrites to /v1/portfolio/* before Flask dispatch):

- ``POST /ft-api/v1/portfolio/optimise`` — return optimal weights for a given
  set of historical returns and an :class:`OptimiserConfig`.
- ``POST /ft-api/v1/portfolio/frontier`` — return efficient frontier points.

Blueprint registered at ``/v1/portfolio`` (post-strip form).

Request format (both endpoints)::

    {
        "returns": {
            "RELIANCE": [0.01, -0.005, 0.008, ...],
            "TCS":      [0.007, 0.002, -0.003, ...],
            ...
        },
        "config": {
            "method": "markowitz",
            "risk_free_rate": 0.065,
            "max_weight": 0.4,
            "min_weight": 0.0,
            "rebalance_frequency": "monthly"
        }
    }

``returns`` values must be equal-length lists of daily returns (floats).
``config`` is optional — defaults are used if omitted.

The ``/frontier`` endpoint additionally accepts ``n_points`` (int, default 50).

Response format::

    {
        "status": "success",
        "data": { ... PortfolioResult fields ... }
    }

or for ``/frontier``::

    {
        "status": "success",
        "data": [ { ...PortfolioResult... }, ... ]
    }
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from flask import Blueprint, Response, jsonify, request
from pydantic import ValidationError

try:
    from .portfolio_optimiser import OptimiserConfig, PortfolioOptimiser
except ImportError:
    from portfolio_optimiser import OptimiserConfig, PortfolioOptimiser  # type: ignore[no-redef]

logger = logging.getLogger("flinttrade.backtest.optimiser_routes")

optimiser_bp = Blueprint(
    "portfolio_optimiser",
    __name__,
    url_prefix="/v1/portfolio",
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _parse_returns(raw: Any) -> pd.DataFrame | None:
    """Build a returns DataFrame from a ``{ticker: [float, ...]}`` mapping.

    Args:
        raw: Decoded JSON value expected to be a dict of lists.

    Returns:
        DataFrame or ``None`` if validation fails.
    """
    if not isinstance(raw, dict) or not raw:
        return None
    try:
        df = pd.DataFrame(raw)
    except Exception:
        return None
    if df.empty or df.shape[1] < 2:
        return None
    return df.astype(float)


def _parse_config(raw: Any) -> OptimiserConfig | None:
    """Parse an optional config dict into :class:`OptimiserConfig`.

    Args:
        raw: Decoded JSON value or ``None``.

    Returns:
        :class:`OptimiserConfig` (defaults used when ``raw`` is ``None``).
    """
    if raw is None:
        return OptimiserConfig()
    if not isinstance(raw, dict):
        return None
    try:
        return OptimiserConfig(**raw)
    except (ValidationError, TypeError):
        return None


def _result_to_dict(result: object) -> dict[str, Any]:
    """Serialise a :class:`PortfolioResult` to a plain dict.

    Args:
        result: :class:`PortfolioResult` instance.

    Returns:
        JSON-serialisable dictionary.
    """
    return result.model_dump()  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@optimiser_bp.route("/optimise", methods=["POST"])
def optimise_portfolio() -> tuple[Response, int]:
    """Optimise portfolio weights and return a single optimal result.

    Request JSON:
        returns (dict[str, list[float]], required): Daily returns per asset.
        config  (dict, optional): :class:`OptimiserConfig` fields.

    Returns:
        JSON with ``status`` and ``data`` fields.  ``data`` contains
        :class:`PortfolioResult` fields: ``weights``, ``expected_return``,
        ``expected_volatility``, ``sharpe_ratio``, ``diversification_ratio``.
    """
    body: dict[str, Any] = request.get_json(silent=True) or {}

    returns_raw = body.get("returns")
    if returns_raw is None:
        return jsonify({"status": "error", "message": "returns field is required"}), 400

    returns = _parse_returns(returns_raw)
    if returns is None:
        return jsonify({
            "status": "error",
            "message": (
                "returns must be a dict mapping ticker → list[float] "
                "with at least 2 assets"
            ),
        }), 400

    config = _parse_config(body.get("config"))
    if config is None:
        return jsonify({
            "status": "error",
            "message": "config is invalid — check OptimiserConfig field names and types",
        }), 400

    try:
        optimiser = PortfolioOptimiser(config)
        result = optimiser.optimise(returns)
    except ValueError as exc:
        logger.warning("Optimisation failed: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 422
    except Exception as exc:
        logger.exception("Unexpected error during portfolio optimisation")
        return jsonify({"status": "error", "message": f"Internal error: {exc}"}), 500

    logger.info(
        "Portfolio optimised: method=%s assets=%d sharpe=%.3f",
        config.method, len(result.weights), result.sharpe_ratio,
    )
    return jsonify({"status": "success", "data": _result_to_dict(result)}), 200


@optimiser_bp.route("/frontier", methods=["POST"])
def efficient_frontier() -> tuple[Response, int]:
    """Compute and return efficient frontier points.

    Request JSON:
        returns  (dict[str, list[float]], required): Daily returns per asset.
        config   (dict, optional): :class:`OptimiserConfig` fields.
        n_points (int, optional): Number of frontier points (default 50).

    Returns:
        JSON with ``status`` and ``data`` fields.  ``data`` is a list of
        :class:`PortfolioResult` dicts ordered from low to high expected return.
    """
    body: dict[str, Any] = request.get_json(silent=True) or {}

    returns_raw = body.get("returns")
    if returns_raw is None:
        return jsonify({"status": "error", "message": "returns field is required"}), 400

    returns = _parse_returns(returns_raw)
    if returns is None:
        return jsonify({
            "status": "error",
            "message": (
                "returns must be a dict mapping ticker → list[float] "
                "with at least 2 assets"
            ),
        }), 400

    config = _parse_config(body.get("config"))
    if config is None:
        return jsonify({
            "status": "error",
            "message": "config is invalid — check OptimiserConfig field names and types",
        }), 400

    n_points_raw = body.get("n_points", 50)
    try:
        n_points = int(n_points_raw)
        if n_points < 2 or n_points > 500:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({
            "status": "error",
            "message": "n_points must be an integer between 2 and 500",
        }), 400

    try:
        optimiser = PortfolioOptimiser(config)
        frontier = optimiser.efficient_frontier(returns, n_points=n_points)
    except ValueError as exc:
        logger.warning("Frontier generation failed: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 422
    except Exception as exc:
        logger.exception("Unexpected error during efficient frontier computation")
        return jsonify({"status": "error", "message": f"Internal error: {exc}"}), 500

    logger.info(
        "Efficient frontier: %d points computed for %d assets",
        len(frontier), len(returns.columns),
    )
    return jsonify({
        "status": "success",
        "data": [_result_to_dict(pt) for pt in frontier],
    }), 200
