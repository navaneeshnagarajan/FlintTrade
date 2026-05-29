"""Backtest blueprint — /api/v1/backtest/run and /api/v1/strategies/* endpoints.

Runs backtests via the flinttrade_backtest package and exposes strategy
lifecycle management.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import sys
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, jsonify, request

# Resolve repo root relative to this file (packages/core/core/src/backtest_routes.py)
_REPO_ROOT = str(Path(__file__).resolve().parents[4])

logger = logging.getLogger("flinttrade")

backtest_bp = Blueprint("backtest", __name__, url_prefix="/api/v1")


def _load_backtest_engine() -> tuple[Any, Any, Any, Any]:
    """Import backtest modules via sys.path injection.

    We temporarily inject the service package's src directory onto sys.path,
    import the required modules, then remove the injection.

    Returns:
        Tuple of (BacktestConfig, BacktestSimulator, BUILTIN_STRATEGIES,
        DataConnector, PerformanceMetrics) — actually 5 objects; caller unpacks
        the returned tuple.
    """
    _be_src = str(Path(_REPO_ROOT) / "packages" / "services" / "backtest" / "src")
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
    # Inject the backtest service src dir onto sys.path temporarily so direct
    # imports resolve, then remove it to avoid polluting the path.
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


@backtest_bp.route("/backtest/portfolio", methods=["POST"])
def backtest_portfolio() -> tuple[Any, int]:
    """Run a portfolio-level backtest with multi-asset allocation.

    Uses :class:`~portfolio_backtest.PortfolioBacktester` backed by VectorBT
    when available, otherwise the pure-Python simulator.

    Request JSON:
        symbols (list[str]): Asset symbols to include in the portfolio.
        start_date (str): Start date in ``YYYY-MM-DD`` format.
        end_date (str): End date in ``YYYY-MM-DD`` format.
        allocation_strategy (str, optional): One of ``"equal_weight"``
            (default), ``"inverse_volatility"``, ``"momentum"``,
            ``"market_cap"``.
        rebalance_freq (str, optional): One of ``"daily"``, ``"weekly"``,
            ``"monthly"``, ``"quarterly"`` (default), ``"yearly"``.
        initial_capital (float, optional): Starting capital (default 1 000 000).
        benchmark (str, optional): Benchmark label (default ``"NIFTY 50"``).
        include_benchmark (bool, optional): Whether to include benchmark
            comparison in the response (default ``true``).
        momentum_lookback (int, optional): Lookback for momentum strategy
            (default 126 trading days).
        vol_lookback (int, optional): Lookback for inverse-volatility strategy
            (default 63 trading days).
        top_n (int, optional): Top-N symbols for momentum strategy.

    Returns:
        JSON with ``status`` and ``data`` containing ``result`` and
        optionally ``comparison`` on success, or ``status`` and ``message``
        on error.
    """
    _be_src = str(Path(_REPO_ROOT) / "packages" / "services" / "backtest" / "src")
    _be_src_added = _be_src not in sys.path
    if _be_src_added:
        sys.path.insert(0, _be_src)
    try:
        import importlib

        _pb_mod = importlib.import_module("portfolio_backtest")
        PortfolioBacktester = _pb_mod.PortfolioBacktester
    except Exception:
        logger.exception("portfolio_backtest module load error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500
    finally:
        if _be_src_added and _be_src in sys.path:
            sys.path.remove(_be_src)

    body = request.get_json(silent=True) or {}

    symbols: list[str] = body.get("symbols", [])
    if not symbols or not isinstance(symbols, list):
        return jsonify({"status": "error", "message": "symbols must be a non-empty list"}), 400
    symbols = [str(s).strip() for s in symbols if str(s).strip()]
    if not symbols:
        return jsonify({"status": "error", "message": "symbols must contain non-empty strings"}), 400

    start_date: str = body.get("start_date", "").strip()
    end_date: str = body.get("end_date", "").strip()
    if not start_date or not end_date:
        return jsonify({"status": "error", "message": "start_date and end_date are required"}), 400

    allocation_strategy: str = body.get("allocation_strategy", "equal_weight").strip()
    rebalance_freq: str = body.get("rebalance_freq", "quarterly").strip()
    benchmark: str = body.get("benchmark", "NIFTY 50").strip()
    include_benchmark: bool = bool(body.get("include_benchmark", True))

    try:
        initial_capital = float(body.get("initial_capital", 1_000_000))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "initial_capital must be a number"}), 400

    try:
        momentum_lookback = int(body.get("momentum_lookback", 126))
        vol_lookback = int(body.get("vol_lookback", 63))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "lookback values must be integers"}), 400

    top_n: int | None = None
    if "top_n" in body:
        try:
            top_n = int(body["top_n"])
        except (ValueError, TypeError):
            return jsonify({"status": "error", "message": "top_n must be an integer"}), 400

    try:
        backtester = PortfolioBacktester(
            symbols=symbols,
            benchmark=benchmark,
            rebalance_freq=rebalance_freq,
            initial_capital=initial_capital,
        )
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    try:
        result = backtester.run(
            start_date=start_date,
            end_date=end_date,
            allocation_strategy=allocation_strategy,
            momentum_lookback=momentum_lookback,
            vol_lookback=vol_lookback,
            top_n=top_n,
        )
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except Exception:
        logger.exception("Portfolio backtest simulation error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500

    result_dict: dict[str, Any] = {
        "total_return": result.total_return,
        "annual_return": result.annual_return,
        "sharpe_ratio": result.sharpe_ratio,
        "sortino_ratio": result.sortino_ratio,
        "max_drawdown": result.max_drawdown,
        "calmar_ratio": result.calmar_ratio,
        "volatility": result.volatility,
        "var_95": result.var_95,
        "final_equity": result.final_equity,
        "equity_curve": result.equity_curve,
        "drawdown_curve": result.drawdown_curve,
        "rebalance_log": [
            {
                "date": e.date,
                "old_weights": e.old_weights,
                "new_weights": e.new_weights,
                "trades": e.trades,
            }
            for e in result.rebalance_log
        ],
    }

    response_data: dict[str, Any] = {"result": result_dict}

    if include_benchmark:
        try:
            comparison = backtester.compare_benchmark(result, start_date=start_date, end_date=end_date)
            response_data["comparison"] = {
                "alpha": comparison.alpha,
                "beta": comparison.beta,
                "information_ratio": comparison.information_ratio,
                "buy_hold": {
                    "total_return": comparison.buy_hold.total_return,
                    "annual_return": comparison.buy_hold.annual_return,
                    "sharpe_ratio": comparison.buy_hold.sharpe_ratio,
                    "max_drawdown": comparison.buy_hold.max_drawdown,
                    "equity_curve": comparison.buy_hold.equity_curve,
                    "drawdown_curve": comparison.buy_hold.drawdown_curve,
                },
            }
        except Exception as exc:
            logger.warning("Benchmark comparison failed (non-fatal): %s", exc)

    return jsonify({"status": "success", "data": response_data}), 200


@backtest_bp.route("/backtest/strategies/uploaded", methods=["GET"])
def list_uploaded_strategies() -> tuple[Any, int]:
    """Return user-uploaded strategy files managed by the strategy runner.

    Delegates to ``strategy_bp``'s runner so the frontend can call
    ``GET /api/v1/strategies/uploaded`` without needing to know that the
    strategy runner lives under ``/v1/strategies/``.

    Returns:
        JSON with ``status`` and ``data.strategies`` — a list of uploaded
        strategy objects from :class:`~flinttrade_engine.strategy_runner.UserStrategyRunner`.
    """
    runner = current_app.config.get("STRATEGY_RUNNER")
    if runner is None:
        # Runner not configured — return empty list so the frontend degrades gracefully.
        return jsonify({"status": "success", "data": {"strategies": []}}), 200

    try:
        strategies = runner.list_strategies()
        return jsonify({"status": "success", "data": {"strategies": strategies}}), 200
    except Exception:
        logger.exception("list_uploaded_strategies error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@backtest_bp.route("/backtest/strategies", methods=["GET"])
def list_strategies() -> tuple[Any, int]:
    """Return available backtest strategy names and descriptions.

    Mounted at ``/backtest/strategies`` (not ``/strategies``) because the
    engine's ``strategy_bp`` owns ``/api/v1/strategies`` for live strategy
    lifecycle. Pre-2026-05-19 both blueprints registered ``/strategies``
    and Flask first-match-wins silently shadowed this one; Codex caught
    it in the duplicate-route audit.

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


@backtest_bp.route("/backtest/strategies/running", methods=["GET"])
def strategies_running() -> tuple[Any, int]:
    """Return status of all currently registered and running strategies.

    Returns:
        JSON with ``status`` and ``data.strategies`` — a list of objects
        with ``name``, ``state``, ``is_running``, ``exchange``, and
        ``tick_count`` fields.
    """
    from flinttrade_engine.scheduler import StrategyScheduler  # noqa: PLC0415

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


@backtest_bp.route("/backtest/strategies/<name>/start", methods=["POST"])
def strategy_start(name: str) -> tuple[Any, int]:
    """Start a registered strategy by name.

    Args:
        name: Strategy name as registered in the scheduler.

    Returns:
        JSON with ``status`` and confirmation message.
    """
    from flinttrade_engine.scheduler import StrategyScheduler  # noqa: PLC0415

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


@backtest_bp.route("/backtest/strategies/<name>/stop", methods=["POST"])
def strategy_stop(name: str) -> tuple[Any, int]:
    """Stop a running strategy by name.

    Args:
        name: Strategy name as registered in the scheduler.

    Returns:
        JSON with ``status`` and confirmation message.
    """
    from flinttrade_engine.scheduler import StrategyScheduler  # noqa: PLC0415

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
