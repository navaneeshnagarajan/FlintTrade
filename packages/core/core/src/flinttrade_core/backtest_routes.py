"""Backtest blueprint — /api/v1/backtest/run and /api/v1/strategies/* endpoints.

Runs backtests via the flinttrade_backtest package and exposes strategy
lifecycle management.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, current_app, g, jsonify, request

from .backtest_scope import BacktestScopeUnavailable, backtest_run_fence, select_backtest_run
from .model_control_auth import ModelControlDenied

logger = logging.getLogger("flinttrade")

backtest_bp = Blueprint("backtest", __name__, url_prefix="/api/v1")


def _evaluation_store():
    from flinttrade_backtest.result_store import BacktestResultStore

    from .evaluation import EvaluationStore

    store = current_app.config.get("EVALUATION_STORE")
    if store is not None:
        return store
    results = current_app.config.get("BACKTEST_RESULT_STORE")
    if isinstance(results, BacktestResultStore):
        store = EvaluationStore(results.evidence_path)
        current_app.config["EVALUATION_STORE"] = store
    return store


def _begin_evaluation(name, strategy, config, data):
    import hashlib
    import inspect
    from dataclasses import asdict
    from pathlib import Path

    from .evaluation import digest

    selection = getattr(g, "backtest_run_selection", None)
    store = selection.evidence_store if selection is not None else _evaluation_store()
    if selection is not None and current_app.config.get("EVALUATION_STORE") is not store:
        raise BacktestScopeUnavailable
    if store is None:
        return  # Legacy embedding without storage: never a qualification receipt.
    from flinttrade_backtest import engine, metrics, simulator
    files = [Path(inspect.getfile(module)) for module in (engine, simulator, metrics)]
    source = inspect.getsource(strategy)
    data_evidence = {"digest": digest(data.bars), "source": data.source,
                     "provenance_status": getattr(data, "provenance_status", "unqualified_legacy")}
    snapshot = getattr(data, "manifest", None)
    if isinstance(snapshot, dict):
        data_evidence.update(manifest_id=snapshot["snapshot_id"], identity=snapshot["identity"],
                             scope=snapshot["scope"], coverage=snapshot["coverage"],
                             rights=snapshot["rights"], policy_revision=snapshot["policy"]["revision"])
    manifest = {"schema_version": 1, "producer": "backtest", "role": "trading",
                "data": data_evidence,
                "strategy": {"name": name, "source_digest": hashlib.sha256(source.encode()).hexdigest()},
                "config": asdict(config), "model": "none", "skill": "none",
                "training_job": None,
                "evaluator": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    with backtest_run_fence(selection) as control_scope:
        _require_history_scope(snapshot)
        if control_scope is not None:
            manifest["control_scope"] = control_scope
        g.evaluation_experiment = store.create(manifest)
        g.evaluation_trial = store.begin(g.evaluation_experiment)
        g.evaluation_store = store


def _finish_evaluation(status, evidence):
    trial = getattr(g, "evaluation_trial", None)
    if trial and not getattr(g, "evaluation_finished", False):
        import math
        if "metrics" in evidence:
            evidence = dict(evidence)
            evidence["nonfinite_metrics"] = [key for key, value in evidence["metrics"].items() if not math.isfinite(value)]
            evidence["metrics"] = {key: value if math.isfinite(value) else None for key, value in evidence["metrics"].items()}
        g.evaluation_store.finish(trial, status=status, evidence=evidence)
        g.evaluation_finished = True


@backtest_bp.after_request
def _evaluation_headers(response):
    if getattr(g, "evaluation_trial", None):
        response.headers["X-Trial-Id"] = g.evaluation_trial
        response.headers["X-Experiment-Id"] = g.evaluation_experiment
    return response


@backtest_bp.get("/backtest/trials/<identity>")
def read_evaluation_trial(identity):
    return _read_evaluation("trial", identity)


@backtest_bp.get("/backtest/experiments/<identity>")
def read_evaluation_experiment(identity):
    return _read_evaluation("experiment", identity)


def _history_scope() -> tuple[dict[str, Any] | None, tuple[Any, int] | None]:
    """Resolve current server authority, never a scope supplied in task JSON."""
    from .data_contracts import validate_scope

    resolver = current_app.config.get("DATA_SCOPE_RESOLVER")
    if not callable(resolver):
        return None, (jsonify({"status": "unavailable", "message": "Trusted data scope unavailable"}), 503)
    try:
        value = resolver()
        if not isinstance(value, dict):
            raise ValueError("Current data scope unavailable")
        return validate_scope(value), None
    except PermissionError:
        return None, (jsonify({"status": "refused", "message": "Data scope not authorised"}), 403)
    except Exception:
        return None, (jsonify({"status": "unavailable", "message": "Trusted data scope unavailable"}), 503)


def _require_history_scope(snapshot: Any) -> None:
    """Retired data authority cannot publish or receive an in-flight result."""
    if not isinstance(snapshot, dict):
        return
    current_scope, error = _history_scope()
    if error is not None and error[1] == 503:
        raise BacktestScopeUnavailable
    if error is not None or current_scope != snapshot["scope"]:
        raise ModelControlDenied("backtest_history_scope_changed")


def _read_evaluation(kind, identity):
    store = _evaluation_store()
    if store is None:
        return jsonify({"status": "unavailable", "message": "Evaluation store unavailable"}), 503
    try:
        record = getattr(store, kind)(identity)
        experiment = record if kind == "experiment" else store.experiment(record["experiment_id"])
        data = experiment["manifest"]["data"]
        if isinstance(data, dict) and "manifest_id" in data:
            scope, error = _history_scope()
            if error is not None:
                return error
            if scope != data["scope"]:
                return jsonify({"status": "refused", "message": "Data scope not authorised"}), 403
        return jsonify({"status": "success", "data": record}), 200
    except KeyError:
        return jsonify({"status": "error", "message": "Unknown evidence identity"}), 404


@backtest_bp.post("/backtest/evaluation/suites/<identity>/score")
def score_evaluation_suite(identity):
    store = _evaluation_store()
    prospective = current_app.config.get("EVALUATION_PROSPECTIVE_RESOLVER")
    if store is None or prospective is None:
        return jsonify({"status": "unavailable", "message": "Independent prospective evidence resolver required"}), 503
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) != {"trial_id"} or not isinstance(body["trial_id"], str):
        return jsonify({"status": "error", "message": "Only an exact trial_id may be submitted"}), 400
    try:
        result = store.score_final(identity, body["trial_id"], prospective=prospective(body["trial_id"]))
        return jsonify({"status": result["status"], "data": result}), (200 if result["status"] == "completed" else 422)
    except (ValueError, KeyError):
        return jsonify({"status": "refused", "message": "Frozen qualification prerequisites not satisfied"}), 422
    except Exception:
        logger.exception("Independent evaluation unavailable")
        return jsonify({"status": "unknown", "message": "Read trial evidence before retrying"}), 503


@backtest_bp.route("/backtest/training/jobs", methods=["POST"])
def start_training_job():
    return _version_job_command("TRAINING_JOBS", "start")


@backtest_bp.route("/backtest/training/jobs/<identity>", methods=["GET"])
def read_training_job(identity):
    return _version_job_command("TRAINING_JOBS", "get", identity)


@backtest_bp.route("/backtest/training/jobs/<identity>/cancel", methods=["POST"])
def cancel_training_job(identity):
    return _version_job_command("TRAINING_JOBS", "cancel", identity)


@backtest_bp.route("/backtest/training/jobs/<identity>/reconcile", methods=["POST"])
def reconcile_training_job(identity):
    return _version_job_command("TRAINING_JOBS", "reconcile", identity)


@backtest_bp.route("/backtest/adoptions", methods=["POST"])
def adopt_artifact():
    return _version_job_command("ARTIFACT_ACTIVATION", "adopt")


@backtest_bp.route("/backtest/adoptions/<identity>", methods=["GET"])
def read_adoption(identity):
    return _version_job_command("ARTIFACT_ACTIVATION", "get", identity)


@backtest_bp.route("/backtest/adoptions/<identity>/reconcile", methods=["POST"])
def reconcile_adoption(identity):
    return _version_job_command("ARTIFACT_ACTIVATION", "reconcile", identity)


def _version_job_command(key, operation, identity=None):
    owner = current_app.config.get(key)
    if owner is None:
        return jsonify({"status": "unavailable", "message": "Core authority/qualified adapter not configured"}), 503
    body = request.get_json(silent=True) if request.method == "POST" else {}
    if not isinstance(body, dict):
        return jsonify({"status": "error", "message": "JSON object required"}), 400
    try:
        if operation == "start":
            if set(body) != {"request_id", "payload", "lineage"} or not isinstance(body["lineage"], dict):
                raise ValueError("Exact request/payload/lineage required")
            result = owner.start(body["request_id"], body["payload"], lineage=body["lineage"])
        elif operation == "adopt":
            if set(body) - {"request_id", "run_id", "role", "candidate", "expected_generation", "kind"}:
                raise ValueError("Authority cannot be supplied in request")
            result = owner.adopt(body["request_id"], run_id=body["run_id"], role=body["role"],
                candidate=body["candidate"], expected_generation=body["expected_generation"], kind=body.get("kind", "adopt"))
        else:
            if body:
                raise ValueError("No replacement scope permitted")
            result = getattr(owner, operation)(identity)
    except KeyError:
        return jsonify({"status": "error", "message": "Missing or unknown identity"}), 404
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Invalid or unsupported command"}), 400
    except Exception:
        logger.exception("Version/job owner failed")
        return jsonify({"status": "error", "message": "Outcome unavailable; reconcile before retry"}), 503
    return jsonify({"status": "success", "data": result}), (200 if operation == "get" else 202)


def _load_backtest_engine() -> tuple[Any, Any, Any, Any]:
    """Import backtest modules via sys.path injection.

    We temporarily inject the service package's src directory onto sys.path,
    import the required modules, then remove the injection.

    Returns:
        Tuple of (BacktestConfig, BacktestSimulator, BUILTIN_STRATEGIES,
        DataConnector, PerformanceMetrics) — actually 5 objects; caller unpacks
        the returned tuple.
    """
    # Imported from the installed flinttrade_backtest package (no sys.path hack).
    from flinttrade_backtest.data_connector import DataConnector
    from flinttrade_backtest.metrics import PerformanceMetrics
    from flinttrade_backtest.simulator import BacktestConfig, BacktestSimulator
    from flinttrade_backtest.strategies import ALL_STRATEGIES, BUILTIN_STRATEGIES

    # Expose the FULL strategy library, not just the 12 curated BUILTINs: every
    # ALL_STRATEGIES class subclasses the same engine BaseStrategy the simulator
    # runs (verified by the strategies-absorption tests), so they are all
    # runnable through /backtest/run. BUILTIN wins on a name clash (canonical).
    strategies: dict[str, Any] = {**ALL_STRATEGIES, **BUILTIN_STRATEGIES}
    return (
        BacktestConfig,
        BacktestSimulator,
        strategies,
        DataConnector,
        PerformanceMetrics,
    )


def _registry_strategy(name: str) -> Any | None:
    """Return a STRATEGY_REGISTRY strategy class, or None.

    These are kept separate from the BacktestSimulator's strategy map because
    they subclass ``BaseBacktestStrategy`` and run on ``BacktestEngine`` (a
    different engine), not the simulator.
    """
    try:
        from flinttrade_backtest.strategies import STRATEGY_REGISTRY  # noqa: PLC0415
    except Exception:  # noqa: BLE001 - registry import must not break the route
        return None
    return STRATEGY_REGISTRY.get(name)


def _run_registry_backtest(strategy_cls: Any, config: Any, bars: list[dict[str, Any]]) -> Any:
    """Run a STRATEGY_REGISTRY strategy on BacktestEngine; return a simulator
    ``BacktestResult`` so the existing metrics/response code works unchanged.

    These strategies use ``BaseBacktestStrategy`` (OrderIntent + Decimal
    accounting) on ``BacktestEngine``. The engine does the (tested) accounting;
    this only maps its ``EngineResult`` onto the simulator's result shape
    (Decimal -> float) so the tested ``PerformanceMetrics`` computes the metrics —
    no accounting is reimplemented here.
    """
    from decimal import Decimal  # noqa: PLC0415

    from flinttrade_backtest.engine import BacktestEngine, EngineConfig  # noqa: PLC0415
    from flinttrade_backtest.simulator import BacktestResult, EquityPoint, SimTrade  # noqa: PLC0415

    engine = BacktestEngine(
        EngineConfig(
            symbol=config.symbol,
            exchange=config.exchange,
            initial_capital=Decimal(str(config.initial_capital)),
            position_size_pct=Decimal(str(config.position_size_pct)),
        )
    )
    # The strategy must know its symbol — enter_long/short fall back to
    # ``self.symbol`` for the OrderIntent, so a symbol-less strategy emits orders
    # for "" that the engine cannot fill (zero trades). Pass it; tolerate the rare
    # strategy whose constructor doesn't accept a symbol kwarg.
    try:
        strategy = strategy_cls(symbol=config.symbol)
    except TypeError:
        strategy = strategy_cls()
        if hasattr(strategy, "symbol"):
            strategy.symbol = config.symbol
    engine.set_strategy(strategy)
    er = engine.run(bars)

    trades = [
        SimTrade(
            entry_timestamp=str(t.entry_time),
            exit_timestamp=str(t.exit_time),
            symbol=t.symbol,
            side=str(t.side),
            quantity=int(t.quantity),
            entry_price=float(t.entry_price),
            exit_price=float(t.exit_price),
            pnl=float(t.gross_pnl),
            commission=float(t.charges),
            net_pnl=float(t.net_pnl),
        )
        for t in er.trades
    ]
    equity_curve = [
        EquityPoint(
            timestamp=str(p.timestamp),
            equity=float(p.equity),
            cash=float(p.cash),
            positions_value=float(p.positions_value),
            drawdown=float(p.drawdown_pct),
        )
        for p in er.equity_curve
    ]
    return BacktestResult(
        config=config,
        trades=trades,
        equity_curve=equity_curve,
        orders=[],
        final_equity=float(er.final_equity),
        total_bars=er.total_bars,
        error=er.error,
    )


def _validate_manifest_request(body: dict[str, Any]) -> None:
    """Require an exact snapshot token and explicit, non-authoritative selectors."""
    import re

    allowed = {"data_manifest_id", "symbol", "exchange", "interval", "start_date", "end_date",
               "strategy", "initial_capital", "position_size_pct", "run_id"}
    if set(body) - allowed:
        raise ValueError("Unsupported manifest request fields")
    identity = body.get("data_manifest_id")
    if not isinstance(identity, str) or re.fullmatch(r"[0-9a-f]{64}", identity) is None:
        raise ValueError("Canonical history manifest identity required")
    for key in ("symbol", "exchange", "interval", "strategy"):
        value = body.get(key)
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError("Explicit canonical manifest selectors required")
    for key in ("start_date", "end_date"):
        if key in body and not isinstance(body[key], str):
            raise ValueError("Manifest dates must be strings")


def _manifest_date_range(body: dict[str, Any], snapshot: dict[str, Any]) -> tuple[str, str]:
    """Match the whole immutable input; never relabel or silently slice its bars.

    Optional date selectors describe the first/last observed UTC date. The
    manifest's versioned session calendar remains the coverage authority.
    """
    from .data_contracts import timestamp

    identity = snapshot["identity"]
    if body["symbol"] != identity["instrument_id"] or body["exchange"] != identity["venue"]:
        raise ValueError("Manifest instrument or venue does not match request")
    interval = body["interval"]
    unit = {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(interval[-1:])
    seconds = identity["interval_seconds"]
    # Compare to the canonical server-owned magnitude, never regex-match or
    # convert an arbitrarily long client digit string to an integer.
    if unit is None or seconds % unit or interval[:-1] != str(seconds // unit):
        raise ValueError("Manifest interval does not match request")
    dates = (timestamp(snapshot["bars"][0]["timestamp"]).date().isoformat(),
             timestamp(snapshot["bars"][-1]["timestamp"]).date().isoformat())
    for key, observed in zip(("start_date", "end_date"), dates):
        if body.get(key, "") not in ("", observed):
            raise ValueError("Manifest date selection must describe the complete snapshot")
    return dates


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
        data_manifest_id (str, optional): Exact canonical history snapshot. This
            requires explicit matching instrument/venue/interval and server-owned
            data scope. Supplied dates must match its full observed UTC date range;
            omitting dates uses the whole snapshot. No legacy or remote fallback.
        run_id (str, optional): Exact existing run selector. A current full session
            and explicit evaluation-read access are required; the server derives
            immutable control scope. This grants no sealed scoring or activation.

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

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"status": "error", "message": "JSON object required"}), 400
    try:
        g.backtest_run_selection = select_backtest_run(body)
    except ModelControlDenied:
        return jsonify(status="refused", code="backtest_run_scope_refused"), 403
    except (ValueError, KeyError, TypeError):
        return jsonify(status="error", code="backtest_run_scope_invalid"), 400
    except Exception:
        return jsonify(status="unavailable", code="backtest_run_scope_unavailable"), 503
    if "data_manifest_id" in body:
        try:
            _validate_manifest_request(body)
        except ValueError as exc:
            message = "Invalid manifest request"
            for public_message in (
                "Unsupported manifest request fields", "Canonical history manifest identity required",
                "Explicit canonical manifest selectors required", "Manifest dates must be strings",
            ):
                if exc.args == (public_message,):
                    message = public_message
                    break
            return jsonify({"status": "error", "message": message}), 400
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

    # Simulator strategies (BUILTIN + ALL_STRATEGIES) first; otherwise a
    # STRATEGY_REGISTRY strategy that runs on the separate BacktestEngine.
    strategy_cls = BUILTIN_STRATEGIES.get(strategy_name)
    registry_cls = None if strategy_cls is not None else _registry_strategy(strategy_name)
    if strategy_cls is None and registry_cls is None:
        available = sorted(BUILTIN_STRATEGIES.keys())
        return jsonify(
            {
                "status": "error",
                "message": f"Unknown strategy '{strategy_name}'. Available: {available}",
            }
        ), 400

    try:
        connector_factory = current_app.config.get("BACKTEST_DATA_CONNECTOR_FACTORY", DataConnector)
        dc = connector_factory()
        if "data_manifest_id" in body:
            scope, error = _history_scope()
            if error is not None:
                return error
            data_result = dc.load_manifest(body["data_manifest_id"], scope=scope)
            if data_result.success:
                try:
                    snapshot = data_result.manifest
                    if (not isinstance(snapshot, dict) or snapshot.get("snapshot_id") != body["data_manifest_id"]
                            or snapshot.get("scope") != scope):
                        raise ValueError("History owner returned another input identity")
                    start_date, end_date = _manifest_date_range(body, snapshot)
                except (ValueError, TypeError, KeyError, IndexError):
                    return jsonify({"status": "error", "message": "Manifest does not match the requested input"}), 400
        else:
            data_result = dc.load(symbol, exchange, interval, start_date, end_date)
    except Exception:
        logger.exception("Backtest data load error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500

    if not data_result.success:
        return jsonify(
            {
                "status": "error",
                "message": f"No data available: {data_result.error or 'unknown error'}",
            }
        ), 400

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
        _begin_evaluation(strategy_name, strategy_cls or registry_cls, config, data_result)
    except ModelControlDenied:
        return jsonify(status="refused", code="backtest_run_scope_refused"), 403
    except BacktestScopeUnavailable:
        return jsonify(status="unavailable", code="backtest_run_scope_unavailable"), 503
    except Exception:
        logger.exception("Backtest evidence preparation error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500

    try:
        if registry_cls is not None:
            result = _run_registry_backtest(registry_cls, config, data_result.bars)
        else:
            sim = BacktestSimulator(config)
            strategy_instance = strategy_cls(
                name=strategy_name,
                exchange=exchange,
                symbol=symbol,
            )
            result = sim.run(strategy_instance, data_result.bars)
        if result.error:
            _finish_evaluation("failed", {"stage": "simulation", "reason": result.error,
                              "completed_bars": result.total_bars, "reached_trades": len(result.trades)})
            logger.warning("Backtest did not complete: %s", result.error)
            return jsonify({"status": "error", "message": "Backtest did not complete"}), 500
    except Exception:
        _finish_evaluation("failed", {"stage": "simulation", "reason": "Simulation raised"})
        logger.exception("Backtest simulation error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500

    try:
        report = PerformanceMetrics.compute(result)
        # Keys match the frontend BacktestMetrics contract (sharpe_ratio /
        # sortino_ratio / expectancy). The terminal's BacktestResultDisplay reads
        # these directly and formats them eagerly, so a renamed or missing key
        # crashes the whole Performance Metrics card — keep them in lockstep.
        metrics = {
            "total_return": report.total_return_pct,
            "cagr": report.cagr,
            "sharpe_ratio": report.sharpe_ratio,
            "sortino_ratio": report.sortino_ratio,
            "max_drawdown": report.drawdown.max_drawdown_pct,
            "win_rate": report.trade_stats.win_rate,
            "profit_factor": report.trade_stats.profit_factor,
            "total_trades": report.trade_stats.total_trades,
            "expectancy": report.trade_stats.expectancy,
        }
    except Exception as exc:
        _finish_evaluation("failed", {"stage": "metrics", "reason": "Metrics computation failed"})
        logger.warning("Metrics computation error: %s", exc)
        return jsonify({"status": "error", "message": "Backtest metrics computation failed"}), 500

    try:
        _finish_evaluation("completed", {"stage": "metrics", "metrics": metrics, "qualified": False})
    except Exception:
        logger.exception("Immutable evaluation evidence write failed")
        return jsonify({"status": "error", "message": "Evaluation evidence unavailable"}), 503

    # Record what actually completed, but never deliver its private result to a
    # retired run/data permission or follow a replacement persistence owner.
    try:
        with backtest_run_fence(getattr(g, "backtest_run_selection", None)):
            _require_history_scope(getattr(data_result, "manifest", None))
    except ModelControlDenied:
        return jsonify(status="refused", code="backtest_run_scope_refused"), 403
    except Exception:
        return jsonify(status="unavailable", code="backtest_run_scope_unavailable"), 503

    # Persist this run's metrics keyed by strategy so the overnight optimiser can
    # refine on real performance instead of an empty dict. Best-effort:
    # persistence must never fail the backtest response. The metrics dict already
    # uses the refiner's ``sharpe_ratio``/``sortino_ratio`` keys (its rule-based
    # path reads those plus ``max_drawdown``/``win_rate``), so no aliasing needed.
    _bt_store = current_app.config.get("BACKTEST_RESULT_STORE")
    if _bt_store is not None:
        try:
            _bt_store.save(
                strategy_name,
                dict(metrics),
                context={
                    "symbol": symbol,
                    "exchange": exchange,
                    "interval": interval,
                    "start_date": start_date,
                    "end_date": end_date,
                },
            )
        except Exception as exc:  # noqa: BLE001 - persistence is best-effort
            logger.warning("Could not persist backtest result for %s: %s", strategy_name, exc)

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

    # The compatibility write can block or fail after changing authority. Check
    # again at materialisation, not merely before that I/O. Keep immutable truth.
    try:
        with backtest_run_fence(getattr(g, "backtest_run_selection", None)):
            _require_history_scope(getattr(data_result, "manifest", None))
            return jsonify(
                {
                    "status": "success",
                    "data": {
                        "trades": trades,
                        "equity_curve": equity_curve,
                        "metrics": metrics,
                        "total_bars": result.total_bars,
                        "final_equity": result.final_equity,
                    },
                }
            ), 200
    except ModelControlDenied:
        return jsonify(status="refused", code="backtest_run_scope_refused"), 403
    except Exception:
        return jsonify(status="unavailable", code="backtest_run_scope_unavailable"), 503


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
    try:
        from flinttrade_backtest.portfolio_backtest import PortfolioBacktester
    except Exception:
        logger.exception("portfolio_backtest module load error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500

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
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid request"}), 400

    try:
        result = backtester.run(
            start_date=start_date,
            end_date=end_date,
            allocation_strategy=allocation_strategy,
            momentum_lookback=momentum_lookback,
            vol_lookback=vol_lookback,
            top_n=top_n,
        )
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid request"}), 400
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
        registry = {}
        try:
            from flinttrade_backtest.strategies import STRATEGY_REGISTRY  # noqa: PLC0415

            registry = STRATEGY_REGISTRY
        except Exception:  # noqa: BLE001 - registry import must not break the listing
            registry = {}
        # Simulator strategies + the registry strategies (run on BacktestEngine);
        # both are runnable via /backtest/run, so both are listed. BUILTIN wins a
        # name clash (so its curated description shows).
        merged = {**registry, **BUILTIN_STRATEGIES}
        strategies = [
            {"name": name, "description": cls.__doc__.split("\n")[0].strip() if cls.__doc__ else name}
            for name, cls in merged.items()
        ]
    except Exception as exc:
        logger.warning("Could not load BUILTIN_STRATEGIES: %s", exc)
        # Hardcoded fallback list matching the known 12 strategies
        strategies = [
            {"name": "EMACrossover", "description": "EMA crossover strategy: buy when fast EMA > slow EMA"},
            {"name": "Supertrend", "description": "Supertrend indicator strategy"},
            {"name": "MACD_RSI", "description": "MACD + RSI combined momentum strategy"},
            {"name": "BollingerMR", "description": "Bollinger Bands mean-reversion strategy"},
            {"name": "VWAPDev", "description": "VWAP deviation mean-reversion strategy"},
            {"name": "StraddleSell", "description": "Short straddle options-selling strategy"},
            {"name": "StrangleSell", "description": "Short strangle options-selling strategy"},
            {"name": "IronCondor", "description": "Iron condor multi-leg options strategy"},
            {"name": "BullPutSpread", "description": "Bull put spread credit strategy"},
            {"name": "BearCallSpread", "description": "Bear call spread credit strategy"},
            {"name": "MomentumBreakout", "description": "Momentum breakout strategy on volume surge"},
            {"name": "ORB", "description": "Opening Range Breakout intraday strategy"},
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
        strategies_list = [{"name": name, **info} for name, info in status_map.items()]
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
    from flinttrade_engine.scheduler import (  # noqa: PLC0415
        StrategyScheduler,
        StrategyStartTimeoutError,
    )

    _scheduler: StrategyScheduler | None = current_app.config.get("SCHEDULER")
    if _scheduler is None:
        return jsonify({"status": "error", "message": "Scheduler not available"}), 503

    if _scheduler.get_runner(name) is None:
        return jsonify({"status": "error", "message": f"Strategy '{name}' not registered"}), 404

    try:
        _scheduler.start_one_threadsafe(name)
        return jsonify({"status": "success", "data": {"message": f"Strategy '{name}' started"}}), 200
    except StrategyStartTimeoutError:
        logger.warning("strategy_start timed out and rolled back for %s", name)
        return (
            jsonify(
                {
                    "status": "error",
                    "code": "strategy_start_timeout",
                    "message": "Strategy start timed out and was rolled back",
                }
            ),
            504,
        )
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
    from flinttrade_engine.scheduler import (  # noqa: PLC0415
        StrategyScheduler,
        StrategyStopTimeoutError,
    )

    _scheduler: StrategyScheduler | None = current_app.config.get("SCHEDULER")
    if _scheduler is None:
        return jsonify({"status": "error", "message": "Scheduler not available"}), 503

    try:
        _scheduler.stop_one_threadsafe(name)
        return jsonify({"status": "success", "data": {"message": f"Strategy '{name}' stopped"}}), 200
    except KeyError:
        return jsonify({"status": "error", "message": f"Strategy '{name}' not registered"}), 404
    except StrategyStopTimeoutError:
        logger.warning("strategy_stop cleanup is still in progress for %s", name)
        return (
            jsonify(
                {
                    "status": "error",
                    "code": "strategy_stop_in_progress",
                    "message": "Strategy stop is still in progress",
                }
            ),
            504,
        )
    except Exception:
        logger.exception("strategy_stop error for %s", name)
        return jsonify({"status": "error", "message": "Internal server error"}), 500
