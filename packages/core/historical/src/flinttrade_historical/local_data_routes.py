"""Local data-store Flask endpoints — browse downloaded bars, bhavcopy fetch.

Registered as a Blueprint in ``create_flask_app()``. These are the read/fetch
surfaces over the LOCAL historical store: until now downloaded OHLCV lived in
DuckDB reachable only in-process (the backtest connector), and no full-market
EOD (bhavcopy) download existed at all.

Endpoints
---------
GET  /v1/historify/bars           — query locally-downloaded OHLCV bars.
GET  /v1/historify/bars/summary   — per-interval row/symbol counts of the local store.
POST /v1/historify/bhavcopy/download — fetch NSE bhavcopy archives for a date range.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request

from .pipeline import INTERVAL_TABLES, DataPipeline

logger = logging.getLogger("flinttrade.historical.local_data_routes")

local_data_bp = Blueprint("local_data", __name__)

_DEFAULT_LIMIT = 500
_MAX_LIMIT = 10_000

# Module-level pipeline singleton (injected in tests via init_local_data_routes).
_pipeline: DataPipeline | None = None

# Bhavcopy destination directory override (tests inject a tmp dir).
_bhavcopy_dir: Path | None = None


def init_local_data_routes(
    pipeline: DataPipeline | None = None,
    bhavcopy_dir: Path | None = None,
) -> None:
    """Inject the pipeline/bhavcopy-dir singletons (tests and app factory)."""
    global _pipeline, _bhavcopy_dir  # noqa: PLW0603
    if pipeline is not None:
        _pipeline = pipeline
    if bhavcopy_dir is not None:
        _bhavcopy_dir = bhavcopy_dir


def _get_pipeline() -> DataPipeline:
    from flask import current_app, has_app_context

    if has_app_context() and "HISTORY_PIPELINE" in current_app.config:
        return current_app.config["HISTORY_PIPELINE"]
    global _pipeline  # noqa: PLW0603
    if _pipeline is None:
        _pipeline = DataPipeline()
        _pipeline.initialise()
    return _pipeline


def _get_bhavcopy_dir() -> Path:
    global _bhavcopy_dir  # noqa: PLW0603
    if _bhavcopy_dir is None:
        from flinttrade_core.workspace import bhavcopy_dir  # noqa: PLC0415

        _bhavcopy_dir = bhavcopy_dir()
    return _bhavcopy_dir


@local_data_bp.route("/v1/historify/bars", methods=["GET"])
def query_local_bars() -> tuple[Any, int]:
    """Query locally-downloaded OHLCV bars.

    Query params:
        symbol (str, required), exchange (str, required),
        interval (str, optional, default ``1d`` — one of 1m/5m/15m/1h/D/1d),
        start (str, optional, YYYY-MM-DD), end (str, optional, YYYY-MM-DD),
        limit (int, optional, default 500, cap 10000 — most recent kept).
    """
    symbol = str(request.args.get("symbol", "")).strip().upper()
    exchange = str(request.args.get("exchange", "")).strip().upper()
    interval = str(request.args.get("interval", "1d")).strip()
    if not symbol or not exchange:
        return jsonify({"status": "error", "message": "symbol and exchange are required"}), 400

    table = INTERVAL_TABLES.get(interval)
    if table is None:
        return jsonify(
            {
                "status": "error",
                "message": f"Unknown interval {interval!r}. Known: {sorted(INTERVAL_TABLES)}",
            }
        ), 400

    try:
        limit = int(request.args.get("limit", _DEFAULT_LIMIT))
    except (TypeError, ValueError):
        limit = _DEFAULT_LIMIT
    limit = max(1, min(_MAX_LIMIT, limit))

    try:
        rows = _get_pipeline().get_bars(
            table,
            symbol,
            exchange,
            start_date=request.args.get("start") or None,
            end_date=request.args.get("end") or None,
        )
    except Exception as exc:
        logger.warning("Local bars query failed for %s:%s: %s", exchange, symbol, exc)
        return jsonify({"status": "error", "message": "Local bars query failed"}), 500

    truncated = len(rows) > limit
    if truncated:
        rows = rows[-limit:]
    for row in rows:
        ts = row.get("timestamp")
        if ts is not None and not isinstance(ts, (str, int, float)):
            row["timestamp"] = str(ts)

    return jsonify(
        {
            "status": "success",
            "data": {
                "symbol": symbol,
                "exchange": exchange,
                "interval": interval,
                "count": len(rows),
                "truncated": truncated,
                "bars": rows,
                "provenance_status": "unqualified_legacy",
                "availability": "available" if rows else "unavailable",
                "label": "Local downloaded bars — source/calendar metadata not attested",
                "execution_authority": False,
            },
        }
    ), 200


def _data_owner_and_scope() -> tuple[Any, dict[str, Any]]:
    from flask import current_app

    owner = current_app.config.get("DATA_RUNTIME") or current_app.config.get("DATA_ACQUISITION_OWNER")
    resolver = current_app.config.get("DATA_SCOPE_RESOLVER")
    if owner is None or not callable(resolver):
        raise RuntimeError("data_owner_unavailable")
    return owner, resolver()


def _lease_response(operation: Any, *, created: bool = False) -> tuple[Any, int]:
    try:
        owner, scope = _data_owner_and_scope()
        result = operation(owner, scope)
    except PermissionError:
        return jsonify({"status": "error", "code": "data_scope_unavailable"}), 403
    except KeyError:
        return jsonify({"status": "unavailable", "code": "dataset_or_lease_retired"}), 404
    except (ValueError, TypeError):
        return jsonify({"status": "error", "code": "invalid_data_request"}), 400
    except Exception:
        return jsonify({"status": "unavailable", "code": "data_owner_unavailable"}), 503
    response = jsonify({"status": "success", "data": result})
    response.headers["Cache-Control"] = "no-store"
    return response, 201 if created else 200


@local_data_bp.route("/api/v1/data/leases", methods=["POST"])
def acquire_data_lease() -> tuple[Any, int]:
    """Acquire only a configured dataset; body-supplied authority is refused."""
    body = request.get_json(silent=True)
    if type(body) is not dict or set(body) != {"dataset_id"} or type(body["dataset_id"]) is not str:
        return jsonify({"status": "error", "code": "invalid_data_request"}), 400
    return _lease_response(lambda owner, scope: owner.acquire(body["dataset_id"], scope=scope), created=True)


@local_data_bp.route("/api/v1/data/leases/<lease_id>", methods=["GET", "DELETE"])
def read_or_release_data_lease(lease_id: str) -> tuple[Any, int]:
    """Read ordered updates or release the exact server-authorised view lease."""
    if request.method == "DELETE":
        return _lease_response(lambda owner, scope: {"released": owner.release(lease_id, scope=scope)})
    try:
        after = int(request.args["after_sequence"]) if "after_sequence" in request.args else None
    except ValueError:
        return jsonify({"status": "error", "code": "invalid_data_request"}), 400
    return _lease_response(lambda owner, scope: owner.read(lease_id, scope=scope, after_sequence=after))


@local_data_bp.route("/api/v1/data/portfolio/evidence", methods=["GET", "POST"])
def portfolio_evidence() -> tuple[Any, int]:
    """Read/import declared portfolio facts; never proxy a broker book or write."""
    from flask import current_app

    from flinttrade_data.portfolio_evidence import EvidenceConflict

    owner = current_app.config.get("PORTFOLIO_EVIDENCE_OWNER")
    resolver = current_app.config.get("DATA_SCOPE_RESOLVER")
    if owner is None or not callable(resolver):
        return jsonify({"status": "unavailable", "code": "portfolio_evidence_owner_unavailable"}), 503
    try:
        scope = resolver()
        if request.method == "GET":
            result = owner.read(scope)
        else:
            authorised = current_app.config.get("DATA_EVIDENCE_WRITE_ALLOWED")
            if not callable(authorised) or authorised() is not True:
                raise PermissionError
            body = request.get_json(silent=True)
            if type(body) is not dict or set(body) not in ({"origin", "source_id", "records"},
                                                          {"origin", "source_id", "csv"}):
                raise ValueError
            result = owner.append(scope=scope, origin=body["origin"], source_id=body["source_id"],
                                  records=body.get("records"), csv_text=body.get("csv"))
    except EvidenceConflict:
        return jsonify({"status": "error", "code": "portfolio_evidence_conflict"}), 409
    except PermissionError:
        return jsonify({"status": "error", "code": "portfolio_evidence_not_authorised"}), 403
    except (ValueError, TypeError, KeyError):
        return jsonify({"status": "error", "code": "invalid_portfolio_evidence"}), 422
    except Exception:
        return jsonify({"status": "unavailable", "code": "portfolio_evidence_store_unavailable"}), 503
    response = jsonify({"status": "success", "data": result})
    response.headers["Cache-Control"] = "no-store"
    return response, 201 if request.method == "POST" else 200


@local_data_bp.route("/v1/historify/snapshots/<snapshot_id>", methods=["GET"])
def history_snapshot(snapshot_id: str) -> tuple[Any, int]:
    """Read a pinned history; request parameters cannot authorise a new scope."""
    from flask import current_app

    resolver = current_app.config.get("DATA_SCOPE_RESOLVER")
    if not callable(resolver):
        return jsonify({"status": "unavailable", "code": "data_scope_unavailable"}), 503
    try:
        snapshot = _get_pipeline().history_snapshot(snapshot_id, scope=resolver())
    except PermissionError:
        return jsonify({"status": "error", "code": "data_scope_mismatch"}), 403
    except (ValueError, TypeError, KeyError):
        return jsonify({"status": "error", "code": "invalid_history_manifest"}), 422
    except Exception:
        return jsonify({"status": "unavailable", "code": "history_store_unavailable"}), 503
    if snapshot is None:
        return jsonify({"status": "unavailable", "code": "history_snapshot_missing"}), 404
    response = jsonify({"status": "success", "data": snapshot})
    response.headers["Cache-Control"] = "no-store"
    return response, 200


@local_data_bp.route("/v1/historify/bars/summary", methods=["GET"])
def local_bars_summary() -> tuple[Any, int]:
    """Summarise the local OHLCV store (per-interval rows/symbols/span)."""
    try:
        summary = _get_pipeline().summary()
    except Exception as exc:
        logger.warning("Local store summary failed: %s", exc)
        return jsonify({"status": "error", "message": "Local store summary failed"}), 500
    return jsonify({"status": "success", "data": {"tables": summary}}), 200


@local_data_bp.route("/v1/historify/bhavcopy/download", methods=["POST"])
def download_bhavcopy() -> tuple[Any, int]:
    """Download NSE bhavcopy archives for a date range to local storage.

    Request JSON:
        start (str, required): YYYY-MM-DD.
        end (str, required): YYYY-MM-DD (inclusive; max 31 calendar days per call).
        segments (list, optional): subset of ``equity``/``fo``/``index``/``full``
            (default: all four).

    Weekends are skipped; NSE holidays surface as per-day errors rather than
    failing the batch. Re-runs skip files already on disk.
    """
    from .bhavcopy import SEGMENTS, BhavcopyDownloader  # noqa: PLC0415

    body = request.get_json(silent=True) or {}
    try:
        start = date.fromisoformat(str(body.get("start", "")))
        end = date.fromisoformat(str(body.get("end", "")))
    except ValueError:
        return jsonify({"status": "error", "message": "start and end must be YYYY-MM-DD"}), 400

    raw_segments = body.get("segments") or list(SEGMENTS)
    segments = [str(s).strip().lower() for s in raw_segments if str(s).strip().lower() in SEGMENTS]
    if not segments:
        return jsonify(
            {
                "status": "error",
                "message": f"segments must be a subset of {list(SEGMENTS)}",
            }
        ), 400

    downloader = BhavcopyDownloader(_get_bhavcopy_dir())
    try:
        result = downloader.download_range(start, end, segments)
    except ValueError as exc:
        logger.info("Bhavcopy range rejected: %s", exc)
        return jsonify(
            {
                "status": "error",
                "message": "Invalid range: end must not precede start and the span is capped at 31 days per call",
            }
        ), 400
    except Exception as exc:
        logger.warning("Bhavcopy download failed: %s", exc)
        return jsonify({"status": "error", "message": "Bhavcopy download failed"}), 500

    return jsonify(
        {
            "status": "success",
            "data": {
                "dest_dir": str(_get_bhavcopy_dir()),
                **result.to_dict(),
            },
        }
    ), 200
