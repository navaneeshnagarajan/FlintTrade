"""Sandbox Flask Blueprint — virtual paper trading endpoints.

All endpoints are under the ``/v1/sandbox/`` prefix.  The
:class:`~packages.engine.src.sandbox.SandboxEngine` is stored on
``app.config["SANDBOX_ENGINE"]`` and injected when the Flask app is created.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request

logger = logging.getLogger("flinttrade.engine.sandbox_routes")

sandbox_bp = Blueprint("sandbox", __name__, url_prefix="/v1/sandbox")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_engine():
    """Retrieve the SandboxEngine from the Flask app config.

    Returns:
        The SandboxEngine instance, or None if not configured.
    """
    return current_app.config.get("SANDBOX_ENGINE")


def _engine_required() -> tuple[Any, Response | None]:
    """Return (engine, None) or (None, error_response)."""
    engine = _get_engine()
    if engine is None:
        return None, (
            jsonify({"status": "error", "message": "Sandbox engine not configured"}),
            503,
        )
    return engine, None


# ---------------------------------------------------------------------------
# Config endpoints
# ---------------------------------------------------------------------------


@sandbox_bp.route("/config", methods=["GET"])
def get_config() -> Response:
    """Return the current sandbox configuration.

    Returns:
        JSON with sandbox config fields.
    """
    engine, err = _engine_required()
    if err:
        return err

    cfg = engine.config
    return jsonify(
        {
            "status": "success",
            "config": {
                "starting_capital": cfg.starting_capital,
                "equity_leverage": cfg.equity_leverage,
                "futures_leverage": cfg.futures_leverage,
                "option_buy_leverage": cfg.option_buy_leverage,
                "option_sell_leverage": cfg.option_sell_leverage,
                "squareoff_time": cfg.squareoff_time,
                "mcx_squareoff_time": cfg.mcx_squareoff_time,
            },
        }
    )


@sandbox_bp.route("/config", methods=["POST"])
def update_config() -> Response:
    """Update sandbox configuration fields.

    Accepts a JSON body with any subset of SandboxConfig fields.
    Changes take effect immediately (in-memory; persisted to the next reset).

    Returns:
        JSON with updated config.
    """
    engine, err = _engine_required()
    if err:
        return err

    body: dict[str, Any] = request.get_json(silent=True) or {}
    cfg = engine.config

    for field_name in (
        "starting_capital",
        "equity_leverage",
        "futures_leverage",
        "option_buy_leverage",
        "option_sell_leverage",
        "squareoff_time",
        "mcx_squareoff_time",
    ):
        if field_name in body:
            setattr(cfg, field_name, body[field_name])

    return jsonify(
        {
            "status": "success",
            "message": "Sandbox config updated",
            "config": {
                "starting_capital": cfg.starting_capital,
                "equity_leverage": cfg.equity_leverage,
                "futures_leverage": cfg.futures_leverage,
                "option_buy_leverage": cfg.option_buy_leverage,
                "option_sell_leverage": cfg.option_sell_leverage,
                "squareoff_time": cfg.squareoff_time,
                "mcx_squareoff_time": cfg.mcx_squareoff_time,
            },
        }
    )


# ---------------------------------------------------------------------------
# Funds
# ---------------------------------------------------------------------------


@sandbox_bp.route("/funds", methods=["GET"])
def get_funds() -> Response:
    """Return virtual fund balance for the sandbox account.

    Returns:
        JSON with starting_capital, used_margin, realized_pnl, available_balance.
    """
    engine, err = _engine_required()
    if err:
        return err

    return jsonify({"status": "success", "funds": engine.get_funds()})


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------


@sandbox_bp.route("/positions", methods=["GET"])
def get_positions() -> Response:
    """Return open virtual positions.

    Returns:
        JSON with list of position objects.
    """
    engine, err = _engine_required()
    if err:
        return err

    return jsonify({"status": "success", "positions": engine.get_positions()})


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


@sandbox_bp.route("/orders", methods=["GET"])
def get_orders() -> Response:
    """Return all virtual orders (all statuses).

    Returns:
        JSON with list of order objects.
    """
    engine, err = _engine_required()
    if err:
        return err

    return jsonify({"status": "success", "orders": engine.get_orders()})


# ---------------------------------------------------------------------------
# Trades
# ---------------------------------------------------------------------------


@sandbox_bp.route("/trades", methods=["GET"])
def get_trades() -> Response:
    """Return all executed virtual trades.

    Returns:
        JSON with list of trade objects.
    """
    engine, err = _engine_required()
    if err:
        return err

    return jsonify({"status": "success", "trades": engine.get_trades()})


# ---------------------------------------------------------------------------
# P&L history
# ---------------------------------------------------------------------------


@sandbox_bp.route("/pnl", methods=["GET"])
def get_pnl() -> Response:
    """Return daily P&L history.

    Returns:
        JSON with list of daily P&L records.
    """
    engine, err = _engine_required()
    if err:
        return err

    return jsonify({"status": "success", "pnl_history": engine.get_pnl_history()})


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


@sandbox_bp.route("/reset", methods=["POST"])
def reset_sandbox() -> Response:
    """Reset the sandbox to its initial state.

    Deletes all virtual orders, trades, positions, and P&L history.
    Resets the fund balance to starting_capital.

    Returns:
        JSON confirmation message.
    """
    engine, err = _engine_required()
    if err:
        return err

    engine.reset()
    return jsonify(
        {
            "status": "success",
            "message": "Sandbox reset to initial state",
            "starting_capital": engine.config.starting_capital,
        }
    )
