"""Backtest blueprint — /api/v1/backtest/run and /api/v1/strategies/* endpoints.

Runs backtests via the backtest-engine package (hyphen in directory name
requires sys.path injection) and exposes strategy lifecycle management.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import sys
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, jsonify, request

# Resolve repo root relative to this file (packages/core/src/backtest_routes.py)
_REPO_ROOT = str(Path(__file__).resolve().parents[3])

logger = logging.getLogger("flinttrade")

backtest_bp = Blueprint("backtest", __name__, url_prefix="/api/v1")


def _load_backtest_engine() -> tuple[Any, Any, Any, Any]:
    """Import backtest-engine modules via sys.path injection.

    The ``backtest-engine`` directory name contains a hyphen, which prevents
    standard Python imports.  We temporarily inject the src directory onto
    sys.path, import the required modules, then remove the injection.

    Returns:
        Tuple of (BacktestConfig, BacktestSimulator, BUILTIN_STRATEGIES,
        DataConnector, PerformanceMetrics) — actually 5 objects; caller unpacks
        the returned tuple.
    """
    _be_src = str(Path(_REPO_ROOT) / "packages" / "backtest-engine" / "src")
    _be_src_added = _be_src not in sys.path
    if _be_src_added:
        sys.path.insert(0, _be_src)
    try:
        _sim_mod = importlib.import_module("simulator")
        _strat_mod = importlib.import_module("strategies")
        _dc_mod = importlib.import_module("data_connector")
        _met_mod = importlib.import_module("metrics")
        return (
            _sim_mod.BacktestConfig,
            _sim_mod.BacktestSimulator,
            _strat_mod.BUILTIN_STRATEGIES,
            _dc_mod.DataConnector,
            _met_mod.PerformanceMetrics,
        )
    finally:
        if _be_src_added and _be_src in sys.path:
            sys.path.remove(_be_src)


@backtest_bp.route("/backtest/run", methods=["POST"])
def backtest_run() -> tuple[Any, int]:
    """Run a backtest for a given symbol and strategy.

    Request JSON:
        symbol (str): Trading symbol (e.g. ``"RELIANCE"``).
        exchange (str): Exchange code (e.g. ``"NSE"``).
        interval (str): Bar interval such as ``"5m"``, ``"1d"``.
        start_date (str): Start date in ``YYYY-MM-DD`` format.
        end_date (str): End date in ``YYYY-MM-DD`` format.
        strategy (str): Strategy name — must be a key in BUILTIN_STRATEGIES.
        initial_capital (float, optional): Starting capital (default 1 000 000).
        position_size_pct (float, optional): Position size as % of capital (default 10).

    Returns:
        JSON with ``status`` and ``data`` containing ``trades``,
        ``equity_curve``, and ``metrics`` on success, or ``status``
        and ``message`` on error.
    """
    # backtest-engine has a hyphen in its directory name which prevents
    # regular Python imports.  Inject its src dir onto sys.path temporarily
    # so direct imports resolve, then remove it to avoid polluting the path.
    try:
        BacktestConfig, BacktestSimulator, BUILTIN_STRATEGIES, DataConnector, PerformanceMetrics = (
            _load_backtest_engine()
        )
    except Exception:
        logger.exception("Backtest engine load error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500

    body = request.get_json(silent=True) or {}
    symbol: str = body.get("symbol", "").strip()
    exchange: str = body.get("exchange", "NSE").strip()
    interval: str = body.get("interval", "5m").strip()
    start_date: str = body.get("start_date", "").strip()
    end_date: str = body.get("end_date", "").strip()
    strategy_name: str = body.get("strategy", "").strip()
    try:
        initial_capital = float(body.get("initial_capital", 1_000_000))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "initial_capital must be a number"}), 400
    try:
        position_size_pct = float(body.get("position_size_pct", 10.0))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "position_size_pct must be a number"}), 400

    if not symbol:
        return jsonify({"status": "error", "message": "symbol is required"}), 400
    if not strategy_name:
        return jsonify({"status": "error", "message": "strategy is required"}), 400

    strategy_cls = BUILTIN_STRATEGIES.get(strategy_name)
    if strategy_cls is None:
        available = list(BUILTIN_STRATEGIES.keys())
        return jsonify({
            "status": "error",
            "message": f"Unknown strategy '{strategy_name}'. Available: {available}",
        }), 400

    try:
        dc = DataConnector()
        data_result = dc.load(symbol, exchange, interval, start_date, end_date)
    except Exception:
        logger.exception("Backtest data load error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500

    if not data_result.success:
        return jsonify({
            "status": "error",
            "message": f"No data available: {data_result.error or 'unknown error'}",
        }), 400

    try:
        config = BacktestConfig(
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            position_size_pct=position_size_pct,
        )
        sim = BacktestSimulator(config)
        strategy_instance = strategy_cls(
            name=strategy_name,
            exchange=exchange,
            symbol=symbol,
        )
        result = sim.run(strategy_instance, data_result.bars)
    except Exception:
        logger.exception("Backtest simulation error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500

    try:
        report = PerformanceMetrics.compute(result)
        metrics = {
            "total_return": report.total_return_pct,
            "cagr": report.cagr,
            "sharpe": report.sharpe_ratio,
            "sortino": report.sortino_ratio,
            "max_drawdown": report.drawdown.max_drawdown_pct,
            "win_rate": report.trade_stats.win_rate,
            "profit_factor": report.trade_stats.profit_factor,
            "total_trades": report.trade_stats.total_trades,
        }
    except Exception as exc:
        logger.warning("Metrics computation error: %s", exc)
        metrics = {"total_return": result.total_return_pct}

    trades = [
        {
            "entry_timestamp": t.entry_timestamp,
            "exit_timestamp": t.exit_timestamp,
            "symbol": t.symbol,
            "side": t.side,
            "quantity": t.quantity,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "pnl": t.pnl,
            "net_pnl": t.net_pnl,
            "commission": t.commission,
            "bars_held": t.bars_held,
        }
        for t in result.trades
    ]
    equity_curve = [
        {
            "timestamp": pt.timestamp,
            "equity": pt.equity,
            "cash": pt.cash,
            "drawdown": pt.drawdown,
        }
        for pt in result.equity_curve
    ]

    return jsonify({
        "status": "success",
        "data": {
            "trades": trades,
            "equity_curve": equity_curve,
            "metrics": metrics,
            "total_bars": result.total_bars,
            "final_equity": result.final_equity,
        },
    }), 200


@backtest_bp.route("/strategies", methods=["GET"])
def list_strategies() -> tuple[Any, int]:
    """Return available backtest strategy names and descriptions.

    Returns:
        JSON with ``status`` and ``data.strategies`` — a list of objects
        with ``name`` and ``description`` fields.
    """
    try:
        _, _, BUILTIN_STRATEGIES, _, _ = _load_backtest_engine()
        strategies = [
            {"name": name, "description": cls.__doc__.split("\n")[0].strip() if cls.__doc__ else name}
            for name, cls in BUILTIN_STRATEGIES.items()
        ]
    except Exception as exc:
        logger.warning("Could not load BUILTIN_STRATEGIES: %s", exc)
        # Hardcoded fallback list matching the known 12 strategies
        strategies = [
            {"name": "EMACrossover",       "description": "EMA crossover strategy: buy when fast EMA > slow EMA"},
            {"name": "Supertrend",          "description": "Supertrend indicator strategy"},
            {"name": "MACD_RSI",            "description": "MACD + RSI combined momentum strategy"},
            {"name": "BollingerMR",         "description": "Bollinger Bands mean-reversion strategy"},
            {"name": "VWAPDev",             "description": "VWAP deviation mean-reversion strategy"},
            {"name": "StraddleSell",        "description": "Short straddle options-selling strategy"},
            {"name": "StrangleSell",        "description": "Short strangle options-selling strategy"},
            {"name": "IronCondor",          "description": "Iron condor multi-leg options strategy"},
            {"name": "BullPutSpread",       "description": "Bull put spread credit strategy"},
            {"name": "BearCallSpread",      "description": "Bear call spread credit strategy"},
            {"name": "MomentumBreakout",    "description": "Momentum breakout strategy on volume surge"},
            {"name": "ORB",                 "description": "Opening Range Breakout intraday strategy"},
        ]
    return jsonify({"status": "success", "data": {"strategies": strategies}}), 200


@backtest_bp.route("/strategies/running", methods=["GET"])
def strategies_running() -> tuple[Any, int]:
    """Return status of all currently registered and running strategies.

    Returns:
        JSON with ``status`` and ``data.strategies`` — a list of objects
        with ``name``, ``state``, ``is_running``, ``exchange``, and
        ``tick_count`` fields.
    """
    from packages.engine.src.scheduler import StrategyScheduler  # noqa: PLC0415

    _scheduler: StrategyScheduler | None = current_app.config.get("SCHEDULER")
    if _scheduler is None:
        return jsonify({"status": "success", "data": {"strategies": []}}), 200

    try:
        status_map = _scheduler.status()
        strategies_list = [
            {"name": name, **info}
            for name, info in status_map.items()
        ]
        return jsonify({"status": "success", "data": {"strategies": strategies_list}}), 200
    except Exception:
        logger.exception("strategies_running error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@backtest_bp.route("/strategies/<name>/start", methods=["POST"])
def strategy_start(name: str) -> tuple[Any, int]:
    """Start a registered strategy by name.

    Args:
        name: Strategy name as registered in the scheduler.

    Returns:
        JSON with ``status`` and confirmation message.
    """
    from packages.engine.src.scheduler import StrategyScheduler  # noqa: PLC0415

    _scheduler: StrategyScheduler | None = current_app.config.get("SCHEDULER")
    if _scheduler is None:
        return jsonify({"status": "error", "message": "Scheduler not available"}), 503

    runner = _scheduler.get_runner(name)
    if runner is None:
        return jsonify({"status": "error", "message": f"Strategy '{name}' not registered"}), 404

    try:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(runner.start())
        finally:
            loop.close()
        return jsonify({"status": "success", "data": {"message": f"Strategy '{name}' started"}}), 200
    except Exception:
        logger.exception("strategy_start error for %s", name)
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@backtest_bp.route("/strategies/<name>/stop", methods=["POST"])
def strategy_stop(name: str) -> tuple[Any, int]:
    """Stop a running strategy by name.

    Args:
        name: Strategy name as registered in the scheduler.

    Returns:
        JSON with ``status`` and confirmation message.
    """
    from packages.engine.src.scheduler import StrategyScheduler  # noqa: PLC0415

    _scheduler: StrategyScheduler | None = current_app.config.get("SCHEDULER")
    if _scheduler is None:
        return jsonify({"status": "error", "message": "Scheduler not available"}), 503

    try:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_scheduler.stop_one(name))
        finally:
            loop.close()
        return jsonify({"status": "success", "data": {"message": f"Strategy '{name}' stopped"}}), 200
    except KeyError:
        return jsonify({"status": "error", "message": f"Strategy '{name}' not registered"}), 404
    except Exception:
        logger.exception("strategy_stop error for %s", name)
        return jsonify({"status": "error", "message": "Internal server error"}), 500
