"""FlintTrade application entry point — wires all packages together.

Includes a lightweight Flask API server (port 5100) for FlintTrade-specific
endpoints that are separate from the OpenAlgo API (port 5000).

Usage:
    python packages/core/core/src/app.py
    # or: make start
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# UTF-8 stdout/stderr reconfigure — must happen BEFORE any import that may
# emit to the console (structlog, Flask, etc.).  On Windows the default
# console encoding is cp1252, which crashes when log records contain emojis
# or ANSI colour codes.  We flip stdout/stderr to UTF-8 early; if the
# attribute is not available (Python <3.7 / non-stream stdout) we fall back
# silently so this never breaks startup.
# ---------------------------------------------------------------------------
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

import asyncio
import json
import logging
import os
import secrets
import signal
import threading
from collections.abc import Callable, Mapping
from contextlib import nullcontext, suppress
from functools import wraps
from pathlib import Path
from typing import Any

# Frozen-mode detection — when packaged by PyInstaller for the native desktop
# app, every ``flinttrade_*`` package is collected into the bundle, so the
# source-tree ``sys.path`` wiring below is both unnecessary and wrong (the
# ``packages/<group>/<pkg>/src`` directories do not exist inside the bundle).
# ``sys.frozen`` is set by PyInstaller; ``sys._MEIPASS`` points at the unpacked
# bundle root.  See ``flinttrade_core.desktop`` for the desktop entry point.
_FROZEN = bool(getattr(sys, "frozen", False))
_BUNDLE_DIR = getattr(sys, "_MEIPASS", None)

# Ensure repo root is on sys.path for cross-package imports (source runs only).
_REPO_ROOT = str(Path(__file__).resolve().parents[5]) if not _FROZEN else (_BUNDLE_DIR or "")
if not _FROZEN:
    if _REPO_ROOT not in sys.path:
        sys.path.insert(0, _REPO_ROOT)

    # Add sibling package ``src`` directories after the stdlib/site paths.  Keeping
    # these as appends avoids local modules such as ``statistics.py`` shadowing
    # Python's standard library while still supporting non-installed source runs.
    for _package_src in [
        "packages/core/data/src",
        "packages/core/historical/src",
        "packages/core/indicators/src",
        "packages/core/ticks/python",
        "packages/services/engine/src",
        "packages/services/screener/src",
        "packages/services/backtest/src",
        "packages/services/ai/src",
        "packages/services/ditto/src",
        "packages/services/automation/src",
        "packages/services/journal/src",
        "packages/integrations/gateway/src",
        "packages/integrations/webhooks/src",
    ]:
        _src_path = str(Path(_REPO_ROOT) / _package_src)
        if _src_path not in sys.path:
            sys.path.append(_src_path)

import hmac  # noqa: E402
import time  # noqa: E402

import structlog  # noqa: E402
from flask import Flask, g as _flask_g, jsonify, request  # noqa: E402
from flask_cors import CORS  # noqa: E402
from flask_limiter import Limiter  # noqa: E402
from flask_limiter.util import get_remote_address  # noqa: E402
import sentry_sdk  # noqa: E402
from sentry_sdk.integrations.flask import FlaskIntegration  # noqa: E402

from .config import DEFAULT_OPENALGO_PORT, DEFAULT_OPENALGO_WS_PORT, Settings, openalgo_ws_base_url  # noqa: E402
from .csp import (  # noqa: E402
    build_csp_header as _build_csp_header,
    csp_report_bp as _csp_report_bp,
    generate_nonce as _generate_csp_nonce,
    inject_csp_nonce as _inject_csp_nonce,
)
from .openalgo_client import OpenAlgoClient  # noqa: E402
from .secure_file import write_secret_text as _write_secret_text  # noqa: E402
from .version import APP_VERSION_TAG  # noqa: E402
from .workspace import workspace_dir as _workspace_dir  # noqa: E402
from flinttrade_data.audit_logger import AuditLogger  # noqa: E402
# engine imports are deferred into FlintTradeApp.__init__() to break the
# core↔engine circular import.  See PLC0415 comments throughout this file.
# Heavy optional modules are imported lazily inside FlintTradeApp.__init__()
# to avoid a 2-5 s startup penalty when ChromaDB / LLM / Telegram deps load.
# CronManager, TelegramBot, LLMClient, LLMConfig, RAGPipeline

# Ensure the gateway src directory is on sys.path so bare gateway imports resolve.
_GATEWAY_SRC = str(Path(_REPO_ROOT) / "packages" / "integrations" / "gateway" / "src")
if _GATEWAY_SRC not in sys.path:
    sys.path.append(_GATEWAY_SRC)

from flinttrade_gateway.registry import BrokerRegistry  # noqa: E402
from flinttrade_gateway.credentials import CredentialStore  # noqa: E402
from flinttrade_gateway.auth import gateway_bp  # noqa: E402
from flinttrade_gateway.contracts import ContractManager  # noqa: E402

logger = logging.getLogger("flinttrade")

DEFAULT_BACKEND_PORT = 5100


def _resolve_backend_port() -> int:
    """Resolve the standalone backend loopback port from env, then default.

    ``make start`` and ``make dev`` expose ``FLINTTRADE_BACKEND_PORT`` to let a
    contributor run FlintTrade beside another local backend. The serve path must
    honour the same contract the Makefile prints.
    """
    raw = os.environ.get("FLINTTRADE_BACKEND_PORT", "").strip()
    if not raw:
        return DEFAULT_BACKEND_PORT
    try:
        port = int(raw)
    except ValueError:
        logger.warning("Ignoring non-integer FLINTTRADE_BACKEND_PORT=%r", raw)
        return DEFAULT_BACKEND_PORT
    # Out-of-range ports would make waitress raise inside the daemon serve
    # thread AFTER the "started on" log line — the app keeps running with no
    # API server and no visible error. (Port 0 is desktop.py's ephemeral-port
    # contract; the standalone serve path has no way to discover the real port.)
    if not 1 <= port <= 65535:
        logger.warning("Ignoring out-of-range FLINTTRADE_BACKEND_PORT=%r", raw)
        return DEFAULT_BACKEND_PORT
    return port


class _RuntimeRequestAdmission:
    """One idempotently releasable request admitted by the runtime tracker."""

    def __init__(self, tracker: _RuntimeRequestTracker) -> None:
        self._tracker = tracker
        self._lock = threading.Lock()
        self._released = False

    def release(self) -> None:
        """Release this admission exactly once, including response-close races."""
        with self._lock:
            if self._released:
                return
            self._released = True
        self._tracker._release()  # noqa: SLF001 - admission is the tracker's token


class _RuntimeRequestTracker:
    """Serialise shutdown admission with draining of already-running requests."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._accepting = True
        self._active = 0

    def try_admit(self) -> _RuntimeRequestAdmission | None:
        """Admit one request unless shutdown has closed the admission gate."""
        with self._condition:
            if not self._accepting:
                return None
            self._active += 1
        return _RuntimeRequestAdmission(self)

    def stop_admitting(self) -> None:
        """Atomically close admission before shutdown begins waiting."""
        with self._condition:
            self._accepting = False

    def wait_for_idle(self, timeout: float) -> bool:
        """Wait up to ``timeout`` seconds for every admitted request to leave."""
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            while self._active:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    def _release(self) -> None:
        with self._condition:
            if self._active <= 0:  # pragma: no cover - defensive token invariant
                return
            self._active -= 1
            if self._active == 0:
                self._condition.notify_all()


def _install_runtime_request_tracking(app: Flask) -> _RuntimeRequestTracker:
    """Install request admission/draining hooks and return their shared tracker."""
    tracker = _RuntimeRequestTracker()
    app.config["RUNTIME_ACCEPTING_REQUESTS"] = True
    app.config["RUNTIME_REQUEST_TRACKER"] = tracker

    @app.before_request
    def _require_running_runtime() -> Any:
        """Reject every request before it can touch dependencies being closed."""
        admission = (
            tracker.try_admit()
            if app.config.get("RUNTIME_ACCEPTING_REQUESTS", True)
            else None
        )
        if admission is not None:
            _flask_g._runtime_request_admission = admission
            return None
        response = jsonify({
            "status": "error",
            "message": "Application is shutting down",
        })
        response.status_code = 503
        response.headers["Retry-After"] = "1"
        return response

    @app.after_request
    def _release_completed_runtime_request(response: Any) -> Any:
        admission = getattr(_flask_g, "_runtime_request_admission", None)
        if admission is None:
            return response
        if response.is_streamed:
            # SSE/file iterators may outlive Flask's request dispatch. Their
            # dependencies remain owned until the WSGI server closes the body.
            response.call_on_close(admission.release)
            _flask_g._runtime_request_release_deferred = True
        else:
            admission.release()
        return response

    @app.teardown_request
    def _release_failed_runtime_request(_error: BaseException | None) -> None:
        admission = getattr(_flask_g, "_runtime_request_admission", None)
        if admission is not None and not getattr(
            _flask_g, "_runtime_request_release_deferred", False
        ):
            admission.release()

    return tracker


def _rag_auto_index_enabled() -> bool:
    """Return whether startup should auto-index docs into the RAG store."""
    raw = os.environ.get("FLINTTRADE_RAG_AUTO_INDEX", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _rag_runtime_enabled() -> bool:
    """Return whether the startup path should construct the RAG runtime."""
    raw = os.environ.get("FLINTTRADE_RAG_ENABLED")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return _rag_auto_index_enabled()


def _tick_capture_enabled() -> bool:
    """Return whether the startup path should launch live tick capture.

    The environment setting is authoritative when present, including explicit
    false. Otherwise, read the UI-owned workspace setting. Capture stays off
    by default because the recorder opens an OpenAlgo WebSocket on boot.
    """
    raw = os.environ.get("FLINTTRADE_TICK_CAPTURE")
    if raw is None:
        raw = _read_workspace_section("data", "tick_capture", "enabled")
    if isinstance(raw, bool):
        return raw
    return str(raw or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


_TICK_CAPTURE_LIFECYCLE_LOCK = "TICK_CAPTURE_LIFECYCLE_LOCK"


def _tick_capture_lifecycle_lock(flask_app: Flask) -> threading.RLock:
    """Return the per-app lock serialising recorder lifecycle transitions."""
    lock = flask_app.config.get(_TICK_CAPTURE_LIFECYCLE_LOCK)
    if lock is None:
        lock = threading.RLock()
        lock = flask_app.config.setdefault(_TICK_CAPTURE_LIFECYCLE_LOCK, lock)
    return lock


def _set_tick_capture_intent(flask_app: Flask, enabled: bool) -> None:
    """Expose capture intent before the API server accepts status requests."""
    with _tick_capture_lifecycle_lock(flask_app):
        flask_app.config["TICK_CAPTURE_ENABLED"] = enabled
        flask_app.config["TICK_CAPTURE_ERROR"] = ""


def _sanitise_tick_capture_error(error: Any, api_key: str) -> str:
    """Return a single-line startup diagnostic without the OpenAlgo API key."""
    diagnostic = str(error).strip() or type(error).__name__
    if api_key:
        diagnostic = diagnostic.replace(api_key, "[redacted]")
    return " ".join(diagnostic.splitlines())


def _record_tick_capture_failure(flask_app: Flask, error: Any, api_key: str) -> None:
    """Persist and log a redacted tick-capture startup failure."""
    diagnostic = _sanitise_tick_capture_error(error, api_key)
    with _tick_capture_lifecycle_lock(flask_app):
        flask_app.config["TICK_CAPTURE_ERROR"] = diagnostic
    logger.warning("Tick capture failed to start (%s); not recording ticks", diagnostic)


def _close_tick_storage(storage: Any, storage_lock: Any | None = None) -> None:
    """Close tick storage after serialising with any in-flight maintenance."""
    if storage is None:
        return
    if storage_lock is None:
        storage.close()
        return
    with storage_lock:
        storage.close()


_ORDERFLOW_CHECKPOINT_INTERVAL_SECONDS = 30.0


class _OrderFlowCheckpointOwner:
    """Publish cursor-bound order-flow state at recorder consistency barriers."""

    def __init__(
        self,
        storage: Any,
        orderflow: Any,
        *,
        workspace_dir: Path,
        storage_lock: Any | None = None,
        interval_seconds: float = _ORDERFLOW_CHECKPOINT_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.storage = storage
        self.orderflow = orderflow
        self.workspace_dir = workspace_dir
        self.storage_lock = storage_lock
        self.interval_seconds = max(0.0, float(interval_seconds))
        self.clock = clock
        self._last_persisted_at: float | None = None

    def persist_locked(self, *, force: bool = False) -> bool:
        """Persist while the caller owns the storage/ingestion barrier."""
        now = self.clock()
        if (
            not force
            and self._last_persisted_at is not None
            and 0 <= now - self._last_persisted_at < self.interval_seconds
        ):
            return False
        from flinttrade_data.orderflow_checkpoint import (  # noqa: PLC0415
            store_orderflow_checkpoint,
        )

        cursor = self.storage.get_tick_replay_cursor()
        state = self.orderflow.export_state()
        store_orderflow_checkpoint(self.workspace_dir, state, cursor)
        self._last_persisted_at = now
        return True

    def persist(self, *, force: bool = False) -> bool:
        """Acquire the storage lock and publish one checkpoint."""
        lock_context = nullcontext() if self.storage_lock is None else self.storage_lock
        with lock_context:
            return self.persist_locked(force=force)


def _checkpoint_identities(state: Mapping[str, Any]) -> set[tuple[str, str]]:
    """Return canonical identities from a validated checkpoint payload."""
    rows = state.get("identities")
    if not isinstance(rows, list):
        return set()
    return {
        (
            str(row.get("exchange") or "").strip().upper(),
            str(row.get("symbol") or "").strip().upper(),
        )
        for row in rows
        if isinstance(row, Mapping)
    }


def _prepare_tick_orderflow_state(
    storage: Any,
    orderflow: Any,
    watchlist: list[dict[str, str]],
    *,
    storage_lock: Any | None = None,
    retention_days: int = 90,
    now: float | None = None,
    workspace_dir: Path | None = None,
) -> dict[str, int]:
    """Prune ticks and restore only cursor- or complete-prefix-proven state."""
    from datetime import datetime  # noqa: PLC0415
    from zoneinfo import ZoneInfo  # noqa: PLC0415

    from flinttrade_data.orderflow_aggregator import (  # noqa: PLC0415
        DEFAULT_RESTORE_MAX_TICKS,
    )
    from flinttrade_data.orderflow_checkpoint import (  # noqa: PLC0415
        load_orderflow_checkpoint,
    )

    now_timestamp = time.time() if now is None else float(now)
    session = datetime.fromtimestamp(
        now_timestamp,
        tz=ZoneInfo("Asia/Kolkata"),
    ).date().isoformat()
    summary = {
        "pruned_ticks": 0,
        "restored_ticks": 0,
        "skipped_ticks": 0,
        "restore_failures": 0,
        "checkpoint_restored": 0,
        "checkpoint_failures": 0,
        "unavailable_identities": 0,
    }

    lock_context = nullcontext() if storage_lock is None else storage_lock
    with lock_context:
        prune_ticks = getattr(storage, "prune_ticks", None)
        if callable(prune_ticks) and retention_days > 0:
            summary["pruned_ticks"] = int(prune_ticks(retention_days))

        get_ticks = getattr(storage, "get_ticks", None)
        restore_prefix = getattr(orderflow, "restore_current_session", None)
        replay_tail = getattr(orderflow, "replay_current_session_tail", None)
        restore_checkpoint = getattr(orderflow, "restore_state", None)
        retain_identities = getattr(orderflow, "retain_identities", None)
        reset_identity = getattr(orderflow, "reset", None)
        if not callable(get_ticks) or not callable(restore_prefix):
            return summary

        identities = {
            (
                str(instrument.get("exchange") or "").strip().upper(),
                str(instrument.get("symbol") or "").strip().upper(),
            )
            for instrument in watchlist
            if isinstance(instrument, dict)
        }
        valid_identities = {
            (exchange, symbol)
            for exchange, symbol in identities
            if exchange and symbol
        }
        summary["skipped_ticks"] += len(identities - valid_identities)

        checkpoint = None
        checkpoint_identities: set[tuple[str, str]] = set()
        try:
            checkpoint = load_orderflow_checkpoint(workspace_dir or _workspace_dir())
            if checkpoint is not None:
                validate_cursor = getattr(storage, "validate_tick_replay_cursor", None)
                if not callable(validate_cursor) or not callable(restore_checkpoint):
                    raise RuntimeError("checkpoint restore APIs are unavailable")
                validate_cursor(checkpoint.cursor)
                restore_checkpoint(checkpoint.orderflow_state, now=now_timestamp)
                checkpoint_identities = _checkpoint_identities(
                    checkpoint.orderflow_state
                )
                if callable(retain_identities):
                    retain_identities(valid_identities)
                summary["checkpoint_restored"] = 1
        except Exception as exc:  # noqa: BLE001 - invalid restart state fails closed
            summary["checkpoint_failures"] += 1
            checkpoint = None
            checkpoint_identities.clear()
            if callable(reset_identity):
                reset_identity()
            logger.warning(
                "Order-flow checkpoint rejected (%s); requiring complete session prefixes",
                type(exc).__name__,
            )

        get_tail = getattr(storage, "get_ticks_after_cursor", None)
        for exchange, symbol in sorted(valid_identities):
            try:
                if (
                    checkpoint is not None
                    and (exchange, symbol) in checkpoint_identities
                    and callable(get_tail)
                    and callable(replay_tail)
                ):
                    ticks = get_tail(
                        checkpoint.cursor,
                        symbol,
                        exchange,
                        session,
                        limit=DEFAULT_RESTORE_MAX_TICKS + 1,
                    )
                    if len(ticks) > DEFAULT_RESTORE_MAX_TICKS:
                        raise RuntimeError("cursor-bound tick tail is incomplete")
                    result = replay_tail(
                        ticks,
                        now=now_timestamp,
                        max_ticks=DEFAULT_RESTORE_MAX_TICKS,
                        history_complete=True,
                    )
                else:
                    ticks = get_ticks(
                        symbol,
                        exchange,
                        session,
                        session,
                        limit=DEFAULT_RESTORE_MAX_TICKS + 1,
                    )
                    if len(ticks) > DEFAULT_RESTORE_MAX_TICKS:
                        raise RuntimeError("persisted session prefix is incomplete")
                    result = restore_prefix(
                        ticks,
                        now=now_timestamp,
                        max_ticks=DEFAULT_RESTORE_MAX_TICKS,
                        history_complete=True,
                    )
            except Exception as exc:  # noqa: BLE001 - one instrument must not block capture
                summary["restore_failures"] += 1
                summary["unavailable_identities"] += 1
                if callable(reset_identity):
                    reset_identity(symbol, exchange=exchange)
                logger.warning(
                    "Order-flow restore skipped for %s:%s (%s)",
                    exchange,
                    symbol,
                    type(exc).__name__,
                )
                continue
            summary["restored_ticks"] += int(result.get("restored_ticks", 0))
            summary["skipped_ticks"] += int(result.get("skipped_ticks", 0))

    return summary


def _handle_tick_recorder_completion(
    flask_app: Flask,
    recorder: Any,
    task: Any,
    *,
    api_key: str,
    is_shutting_down: Callable[[], bool] | None = None,
    on_unpublished: Callable[[], None] | None = None,
    before_storage_close: Callable[[], None] | None = None,
    on_storage_closed: Callable[[], None] | None = None,
) -> bool:
    """Unpublish a full-app recorder that terminated outside normal shutdown."""
    if task.cancelled():
        return False
    try:
        if is_shutting_down is not None and is_shutting_down():
            return False
    except Exception:
        pass
    try:
        error = task.exception()
    except asyncio.CancelledError:
        return False
    failure = error if error is not None else RuntimeError("Tick recorder stopped unexpectedly")
    sanitise_error = getattr(recorder, "sanitise_error", None)
    try:
        diagnostic_source = sanitise_error(failure) if callable(sanitise_error) else failure
    except Exception:
        diagnostic_source = failure
    diagnostic = _sanitise_tick_capture_error(diagnostic_source, api_key)
    storage: Any | None = None
    storage_lock: Any | None = None
    with _tick_capture_lifecycle_lock(flask_app):
        if flask_app.config.get("TICK_RECORDER") is not recorder:
            return False
        flask_app.config.pop("TICK_RECORDER", None)
        storage = flask_app.config.pop("TICK_STORAGE", None)
        storage_lock = flask_app.config.pop("TICK_STORAGE_LOCK", None)
        flask_app.config.pop("ORDERFLOW_AGGREGATOR", None)
        flask_app.config["TICK_CAPTURE_ERROR"] = diagnostic
        if on_unpublished is not None:
            try:
                on_unpublished()
            except Exception as exc:  # noqa: BLE001 - done callbacks must not escape
                logger.warning("Tick runtime unpublish callback failed (%s)", type(exc).__name__)
    try:
        pending_tick_count = int(getattr(recorder, "pending_tick_count", 0))
    except (TypeError, ValueError, OverflowError):
        pending_tick_count = 0
    if pending_tick_count > 0:
        logger.warning(
            "Tick storage retained after recorder exit with %d unflushed ticks",
            pending_tick_count,
        )
        logger.warning("Tick capture stopped unexpectedly (%s); not recording ticks", diagnostic)
        return True
    if before_storage_close is not None:
        try:
            before_storage_close()
        except Exception as exc:  # noqa: BLE001 - retain storage for shutdown retry
            logger.warning(
                "Tick order-flow checkpoint failed after recorder exit (%s)",
                type(exc).__name__,
            )
            logger.warning("Tick capture stopped unexpectedly (%s); not recording ticks", diagnostic)
            return True
    try:
        _close_tick_storage(storage, storage_lock)
    except Exception as exc:  # noqa: BLE001 - done callbacks must not escape
        logger.warning("Tick storage close failed after recorder exit (%s)", type(exc).__name__)
    else:
        if on_storage_closed is not None:
            try:
                on_storage_closed()
            except Exception as exc:  # noqa: BLE001 - done callbacks must not escape
                logger.warning("Tick storage close callback failed (%s)", type(exc).__name__)
    logger.warning("Tick capture stopped unexpectedly (%s); not recording ticks", diagnostic)
    return True


def _build_tick_recorder(
    *,
    recorder_factory: Callable[..., Any],
    signal_hub: Any,
    settings: Settings,
    storage: Any,
    storage_lock: Any,
    orderflow: Any,
    watchlist: list[dict[str, str]],
    mode: str,
    post_flush_callback: Callable[[], None] | None = None,
) -> Any:
    """Build a recorder wired to the existing application signal hub."""
    ltp_sink = getattr(signal_hub, "process_tick", None)
    update_config = getattr(signal_hub, "update_config", None)
    if not callable(ltp_sink) or not callable(update_config):
        raise RuntimeError("Signal hub is unavailable; tick capture remains disabled")

    recorder = recorder_factory(
        storage=storage,
        ws_url=openalgo_ws_base_url(settings),
        storage_lock=storage_lock,
        orderflow_aggregator=orderflow,
        post_flush_callback=post_flush_callback,
        api_key=settings.openalgo_api_key,
        ltp_sink=ltp_sink,
    )
    recorder.add_symbols(watchlist, mode=mode)
    update_config(
        instruments=[
            f"{instrument['exchange'].upper()}:{instrument['symbol'].upper()}"
            for instrument in watchlist
        ]
    )
    return recorder


_DEFAULT_TICK_WATCHLIST: list[dict[str, str]] = [
    {"exchange": "NSE_INDEX", "symbol": "NIFTY"},
    {"exchange": "NSE_INDEX", "symbol": "BANKNIFTY"},
    {"exchange": "BSE_INDEX", "symbol": "SENSEX"},
]


def _tick_capture_watchlist() -> list[dict[str, str]]:
    """Resolve the tick-capture watchlist from workspace.json, else defaults.

    workspace.json shape::

        {"data": {"tick_capture": {"symbols": [
            {"exchange": "NSE", "symbol": "RELIANCE"}, ...
        ]}}}

    Malformed entries are skipped; an empty/missing list falls back to the
    default major-index watchlist so enabling capture always records something.
    """
    import json  # noqa: PLC0415

    path = _workspace_dir() / "workspace.json"
    if not path.exists():
        return list(_DEFAULT_TICK_WATCHLIST)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read workspace.json for tick watchlist: %s", exc)
        return list(_DEFAULT_TICK_WATCHLIST)

    raw = (((data.get("data") or {}).get("tick_capture") or {}).get("symbols")) or []
    symbols: list[dict[str, str]] = []
    for inst in raw if isinstance(raw, list) else []:
        if not isinstance(inst, dict):
            continue
        symbol = str(inst.get("symbol", "")).strip().upper()
        exchange = str(inst.get("exchange", "")).strip().upper()
        if symbol and exchange:
            symbols.append({"exchange": exchange, "symbol": symbol})
    return symbols or list(_DEFAULT_TICK_WATCHLIST)


def _read_workspace_section(*keys: str) -> Any:
    """Read a nested section from workspace.json (None when absent/unreadable)."""
    import json  # noqa: PLC0415

    path = _workspace_dir() / "workspace.json"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            node: Any = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _tick_capture_mode() -> str:
    """Capture mode from workspace.json data.tick_capture.mode (default quote).

    ``depth`` records the full top-5 book; ``ltp`` is the lightest. Invalid
    values fall back to ``quote`` so a typo cannot silently disable capture.
    """
    raw = _read_workspace_section("data", "tick_capture", "mode")
    mode = str(raw or "").strip().lower()
    return mode if mode in ("ltp", "quote", "depth") else "quote"


def _auto_sync_enabled() -> bool:
    """Whether the EOD historical delta-sync cron is enabled (workspace.json)."""
    raw = _read_workspace_section("data", "auto_sync", "enabled")
    if isinstance(raw, bool):
        return raw
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def _auto_sync_lookback_days() -> int:
    """Delta-sync lookback window in days (default 7, clamped 1–90)."""
    raw = _read_workspace_section("data", "auto_sync", "lookback_days")
    try:
        days = int(raw) if raw is not None else 7
    except (TypeError, ValueError):
        days = 7
    return max(1, min(90, days))


def _index_rag_docs_safely(rag: Any) -> None:
    """Index docs for RAG without letting background thread errors escape."""
    try:
        count = rag.index_directory("docs/")
        logger.info("RAG background indexing completed (%s document chunks)", count)
    except Exception as exc:
        logger.warning("RAG background indexing failed: %s", exc)


def _initialise_rag_runtime(flinttrade_dir: Path) -> Any | None:
    """Construct the canonical RAG runtime when enabled and installed."""
    if not _rag_runtime_enabled():
        logger.info("RAG runtime disabled (set FLINTTRADE_RAG_ENABLED=true to enable)")
        return None

    rag_dir = flinttrade_dir / "rag"
    rag_dir.mkdir(exist_ok=True)
    try:
        import chromadb  # noqa: F401, PLC0415

        from flinttrade_ai.llm_client import LLMClient, LLMConfig  # noqa: PLC0415
        from flinttrade_ai.rag_pipeline import PipelineConfig, RAGPipeline  # noqa: PLC0415

        try:
            config = LLMConfig.from_env()
            llm_configured = bool(config.provider)
        except Exception:
            llm_configured = False
        llm_client = LLMClient() if llm_configured else None
        rag = RAGPipeline(
            config=PipelineConfig(persist_directory=str(rag_dir)),
            llm_client=llm_client,
        )
        if rag.document_count() == 0:
            if _rag_auto_index_enabled():
                logger.info("RAG database empty — indexing docs/ directory in background...")
                threading.Thread(
                    target=lambda: _index_rag_docs_safely(rag),
                    daemon=True,
                    name="rag-indexer",
                ).start()
            else:
                logger.info(
                    "RAG database empty — automatic docs indexing disabled "
                    "(set FLINTTRADE_RAG_AUTO_INDEX=true to enable)",
                )
        return rag
    except Exception as exc:
        logger.warning("RAG initialisation failed: %s", exc)
        return None


def _reconnect_saved_accounts(
    registry: BrokerRegistry,
    credential_store: CredentialStore,
    reconnect_logger: logging.Logger,
) -> None:
    """Reconnect previously saved broker accounts on startup.

    Iterates over every account persisted in the CredentialStore and attempts
    to re-authenticate each one against the registry.  Failures are logged as
    warnings so that a single bad account does not block the rest.

    Args:
        registry: The live BrokerRegistry to populate with sessions.
        credential_store: The CredentialStore that holds persisted credentials.
        reconnect_logger: Logger instance to use for progress messages.
    """
    from flinttrade_gateway.adapter import BROKER_CATALOG  # noqa: PLC0415
    from flinttrade_gateway.log_safety import account_ref  # noqa: PLC0415
    from flinttrade_gateway.session import BrokerSession  # noqa: PLC0415

    saved = credential_store.list_accounts()
    if not saved:
        reconnect_logger.info("No saved broker accounts to reconnect")
        return

    reconnect_logger.info("Reconnecting %d saved broker account(s)...", len(saved))
    for acct in saved:
        account_id: str = acct["account_id"]
        broker: str = acct["broker"]
        adapter_id = str(acct.get("adapter_id") or broker)
        label: str = acct["label"]
        info = BROKER_CATALOG.get(adapter_id) or BROKER_CATALOG.get(broker)
        safe_account = account_ref(account_id)
        if info is not None and info.native:
            reconnect_logger.info("  Skipped native account: %s (%s)", safe_account, adapter_id)
            continue
        try:
            creds = credential_store.retrieve(account_id)
            session = BrokerSession(account_id, broker, label)
            session.authenticate(creds)
            registry._sessions[account_id] = session
            if acct.get("is_primary"):
                registry._primary = account_id
            reconnect_logger.info("  Connected: %s (%s)", safe_account, broker)
        except Exception as exc:
            reconnect_logger.warning("  Failed: %s (%s): %s", safe_account, broker, exc)


def _read_version() -> str:
    """Return the central FlintTrade product version tag."""
    return APP_VERSION_TAG


# ---------------------------------------------------------------------------
# Master password — cached module-level so all call-sites share a single
# value within a process.  File-backed so it survives restarts.
# ---------------------------------------------------------------------------

_MASTER_PASSWORD: str | None = None
_API_KEY_PEPPER: str | None = None
_SAFETY_GATE_SECRET: bytes | None = None


def _get_api_key_pepper() -> str:
    """Get or generate the OpenAlgo-compatible ``API_KEY_PEPPER``.

    Source of truth (NO environment variable — secrets out of env):
      1. Persisted hardened secret at ``<workspace>/api_key_pepper``.
      2. Generate a fresh ``secrets.token_urlsafe(64)``, persist it hardened.
    The value is re-exported to ``os.environ`` only as an in-process transport
    for the upstream OpenAlgo modules (their ``utils.config`` reads env).

    Upstream OpenAlgo's v2.0.0.6 hardening rejected the publicly leaked
    placeholder pepper and auto-rotates on first run. FlintTrade's broker
    shim (``packages/integrations/gateway/src/shims/config_shim.py``) re-exports this
    value as ``utils.config.API_KEY_PEPPER`` so the OpenAlgo broker
    modules get the same pepper on both code paths.

    Returns the secret string; subsequent calls within the same process
    return the cached value. A best-effort persist on disk is attempted
    so restarts pick up the same pepper.
    """
    global _API_KEY_PEPPER
    if _API_KEY_PEPPER:
        return _API_KEY_PEPPER

    # Source of truth is the hardened at-rest file — NEVER the API_KEY_PEPPER env
    # var (secrets out of env, decision B/C). The pepper is an app-generated
    # random, so auto-generating it on first run is fine (unlike the operator's
    # master passphrase). It IS re-exported into os.environ below purely as an
    # in-process transport for the upstream OpenAlgo broker modules, whose
    # ``utils.config`` can only read API_KEY_PEPPER from the environment — the
    # value originates from the hardened file, never from a committed .env.
    pepper_file = _workspace_dir() / "api_key_pepper"
    try:
        if pepper_file.exists():
            stored = pepper_file.read_text().strip()
            if stored:
                _API_KEY_PEPPER = stored
                os.environ["API_KEY_PEPPER"] = stored  # in-process OpenAlgo transport
                return _API_KEY_PEPPER
    except OSError:
        pass

    new_pepper = secrets.token_urlsafe(64)
    try:
        pepper_file.parent.mkdir(parents=True, exist_ok=True)
        _write_secret_text(pepper_file, new_pepper)  # SC-04: icacls/0600 owner-only
        logger.info("Generated new API_KEY_PEPPER (hardened) at %s", pepper_file)
    except OSError as exc:
        logger.warning(
            "Could not persist API_KEY_PEPPER to %s: %s — using ephemeral value",
            pepper_file,
            exc,
        )

    _API_KEY_PEPPER = new_pepper
    os.environ["API_KEY_PEPPER"] = new_pepper  # in-process OpenAlgo transport
    return _API_KEY_PEPPER


def _get_safety_gate_secret_bytes() -> bytes:
    """Get or generate the dedicated safety-gate HMAC secret (contract §8.0b).

    Source of truth (NO environment variable — secrets out of env):
      1. Persisted hardened secret at ``<workspace>/safety_gate_secret`` (hex).
      2. Generate a fresh 32 random bytes, persist it hex-encoded and hardened.

    This MUST be a SEPARATE key from jwt_secret / webhook_hmac_secret /
    api_key_pepper: it signs every one-shot :class:`SafetyContext`, so reusing
    another subsystem's secret would let a leak there forge order-gate tickets.
    Like the pepper it is app-generated random (not operator material), so
    auto-generating on first run is safe; an ephemeral fallback is acceptable
    because the short SafetyContext TTL drains in-flight tickets across a restart.
    """
    global _SAFETY_GATE_SECRET
    if _SAFETY_GATE_SECRET is not None:
        return _SAFETY_GATE_SECRET

    key_file = _workspace_dir() / "safety_gate_secret"
    try:
        if key_file.exists():
            stored = key_file.read_text().strip()
            if stored:
                candidate = bytes.fromhex(stored)
                if len(candidate) >= 32:
                    _SAFETY_GATE_SECRET = candidate
                    return _SAFETY_GATE_SECRET
                logger.warning(
                    "Safety-gate key file at %s is too short (<32 bytes) — regenerating",
                    key_file,
                )
    except (OSError, ValueError):
        # Unreadable or non-hex file — regenerate rather than fail closed forever.
        logger.warning("Safety-gate key file at %s unreadable/invalid — regenerating", key_file)

    new_secret = secrets.token_bytes(32)
    try:
        key_file.parent.mkdir(parents=True, exist_ok=True)
        _write_secret_text(key_file, new_secret.hex())  # SC-04: icacls/0600 owner-only
        logger.info("Generated new safety-gate key file (hardened) at %s", key_file)
    except OSError as exc:
        logger.warning(
            "Could not persist safety-gate key file at %s: %s — using ephemeral value",
            key_file,
            exc,
        )

    _SAFETY_GATE_SECRET = new_secret
    return _SAFETY_GATE_SECRET


def set_master_password(password: str) -> None:
    """Inject the master password into the process cache (TTY/fd readers, tests).

    The only supported inputs are an operator-typed passphrase (TTY getpass),
    a file descriptor (``FLINTTRADE_MASTER_PASSWORD_FD``), or the hardened
    at-rest file. NEVER an environment variable or an auto-generated default
    (locked decision #13)."""
    global _MASTER_PASSWORD
    _MASTER_PASSWORD = password


def _read_master_password_interactive() -> str:
    """Read the master passphrase from a pipe FD or a TTY prompt (locked #13).

    NEVER from ``MASTER_PASSWORD`` env var — env leaks to process listings,
    shell history, CI logs, and tracebacks that dump ``os.environ``.
    """
    import getpass  # noqa: PLC0415

    fd_env = os.environ.get("FLINTTRADE_MASTER_PASSWORD_FD")
    if fd_env:
        with os.fdopen(int(fd_env), "r") as fd:
            return fd.readline().rstrip("\n")
    if not sys.stdin.isatty():
        raise RuntimeError(
            "master password required but no TTY available; set the hardened "
            "~/.flinttrade/master_password file or pass FLINTTRADE_MASTER_PASSWORD_FD"
        )
    return getpass.getpass("FlintTrade master password: ")


def _get_master_password() -> str:
    """Return the credential-store master password (locked decision #13).

    Resolution order — NO environment variable, NO auto-generated default:
      1. process cache (set via TTY/fd reader or ``set_master_password``)
      2. the hardened at-rest file ``<workspace>/master_password`` (operator
         material per data-layer §8.1; ACL-hardened via ``secure_file.harden``)
      3. operator prompt — TTY getpass or ``FLINTTRADE_MASTER_PASSWORD_FD`` —
         then persisted to the hardened at-rest file for subsequent starts.
    """
    global _MASTER_PASSWORD
    if _MASTER_PASSWORD:
        return _MASTER_PASSWORD

    store_key_file = _workspace_dir() / "master_password"
    try:
        if store_key_file.exists():
            stored = store_key_file.read_text().strip()
            if stored:
                _MASTER_PASSWORD = stored
                return _MASTER_PASSWORD
    except OSError:
        pass

    password = _read_master_password_interactive()
    if not password:
        raise RuntimeError("master password required (empty input rejected)")

    try:
        _write_secret_text(store_key_file, password)  # SC-04: icacls/0600 owner-only
        logger.info("Persisted credential-store key file (hardened) at %s", store_key_file)
    except OSError as exc:
        logger.warning(
            "Could not persist credential-store key file at %s: %s — using session value",
            store_key_file, exc,
        )

    _MASTER_PASSWORD = password
    return _MASTER_PASSWORD


# ---------------------------------------------------------------------------
# workspace.json reader — OpenAlgo overrides from user config
# ---------------------------------------------------------------------------


def _read_openalgo_from_workspace() -> dict[str, Any]:
    """Read OpenAlgo overrides from ``~/.flinttrade/workspace.json``.

    Returns a dict with any of ``api_key``, ``host``, ``port``, ``ws_port`` keys that
    are present and non-empty.  Returns an empty dict if the file is
    missing, unreadable, or doesn't contain an ``openalgo`` section.

    workspace.json wins over .env because it's user-edited through the UI
    (Setup wizard, Settings page) while .env is the dev-machine fallback.
    """
    import json  # noqa: PLC0415

    try:
        from .workspace import Workspace  # noqa: PLC0415
        ws = Workspace()
        path = ws.config_path
    except Exception:
        # Fallback: direct workspace.json path (respects FLINTTRADE_WORKSPACE_DIR)
        path = _workspace_dir() / "workspace.json"

    if not path.exists():
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read workspace.json at %s: %s", path, exc)
        return {}

    openalgo = data.get("openalgo") or {}
    if not isinstance(openalgo, dict):
        return {}

    result: dict[str, Any] = {}
    for key in ("api_key", "host", "port", "ws_port"):
        val = openalgo.get(key)
        if val:
            result[key] = val
    return result


def _log_workspace_openalgo_overrides() -> None:
    """Log UI-owned OpenAlgo overrides available in workspace.json.

    Settings reads these values directly from the workspace. They are no
    longer copied into ``os.environ`` as native-runtime configuration.
    """
    overrides = _read_openalgo_from_workspace()
    if not overrides:
        return

    logger.info(
        "OpenAlgo settings available from workspace.json (%s)",
        ", ".join(sorted(overrides.keys())),
    )


# ---------------------------------------------------------------------------
# DuckDB stale .wal cleanup — remove orphan write-ahead-log files on boot
# ---------------------------------------------------------------------------


def _cleanup_stale_duckdb_wals() -> None:
    """Remove ``*.wal`` lock files whose ``.db`` is not actively locked.

    When the backend crashes ungracefully DuckDB's write-ahead-log files
    can linger and block the next startup with ``IOException: The process
    cannot access the file because it is being used by another process``.

    For every ``*.wal`` in ``~/.flinttrade/`` we probe the sibling ``.db``
    by opening it read-only.  If that succeeds the lock is stale and we
    delete the ``.wal``; if it fails another process holds the lock and
    we leave it alone.
    """
    flinttrade_dir = _workspace_dir()
    if not flinttrade_dir.exists():
        return

    try:
        wal_files = list(flinttrade_dir.glob("*.wal"))
    except OSError:
        return

    if not wal_files:
        return

    try:
        import duckdb  # noqa: PLC0415
    except ImportError:
        # DuckDB not installed — nothing to validate against
        return

    cleaned = 0
    for wal in wal_files:
        db_file = wal.with_suffix("")  # strip .wal → leaves .db / .duckdb etc.
        # If the .wal pairs with a file that doesn't exist, just clear it.
        if not db_file.exists():
            try:
                wal.unlink()
                cleaned += 1
            except OSError:
                pass
            continue

        # Probe: can we open the DB read-only?  If yes → no live process
        # holds the write lock → the .wal is stale.
        try:
            conn = duckdb.connect(str(db_file), read_only=True)
            conn.close()
        except Exception as exc:
            # Another process holds the lock, or the DB is corrupt — skip.
            logger.warning(
                "Skipping stale-WAL cleanup for %s (DB appears locked or broken): %s",
                db_file.name,
                exc,
            )
            continue

        try:
            wal.unlink()
            cleaned += 1
        except OSError as exc:
            logger.warning("Could not delete stale WAL %s: %s", wal, exc)

    if cleaned:
        logger.info("Cleaned %d stale DuckDB write-ahead-log file(s)", cleaned)


# ---------------------------------------------------------------------------
# Broker router wiring (selector-bound principal; contract §13 / §11.4)
# ---------------------------------------------------------------------------


def _read_workspace_brokers() -> dict[str, Any] | None:
    """Return the ``brokers`` block from workspace.json, or ``None`` if absent.

    ``None`` (no real config) lets the caller fall back to the spec defaults
    without writing a rollback snapshot for an empty config.
    """
    try:
        path = _workspace_dir() / "workspace.json"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        brokers = data.get("brokers")
        return brokers if isinstance(brokers, dict) and brokers else None
    except Exception as exc:
        logger.warning("Could not read brokers from workspace.json: %s", exc)
        return None


def _snapshot_brokers_bak(brokers_config: dict[str, Any]) -> None:
    """Write the last-known-good brokers config to ``workspace.brokers.bak.json``.

    Atomic (tmp -> fsync -> os.replace, with the same Windows retry as the
    workspace writer) so a crash mid-write can never leave a torn rollback
    artefact: the file is always either the previous-complete or the
    new-complete config — which is exactly when the operator needs it
    (contract §13.3).
    """
    from .workspace_migrations import _atomic_write  # noqa: PLC0415

    bak = _workspace_dir() / "workspace.brokers.bak.json"
    _atomic_write(bak, json.dumps(brokers_config, indent=2))


def _native_activation_checks(
    credential_store: CredentialStore | None,
) -> tuple[Callable[[str], bool], Callable[[str], bool]]:
    """Build the ``(attest_ok, has_credentials)`` gates for native activation.

    ``attest_ok(broker_id)`` is true only when the broker's pinned SDK
    (``brokers.lock``) is installed at the exact pinned version; ``has_credentials``
    is true only when the encrypted vault holds an account for that broker. Both
    fail closed: any error (no lock, no vault) yields ``False`` so a native stays
    dormant. In the default no-SDK / no-creds environment every native is
    correctly skipped.
    """
    from flinttrade_gateway.brokers.native_factory import SDK_PIN_BY_BROKER  # noqa: PLC0415

    try:
        from .broker_sdk_attest import STATUS_OK, attest_all  # noqa: PLC0415

        attest_status = {r.broker: r.status for r in attest_all()}
    except Exception as exc:  # pragma: no cover - attestation must never brick boot
        logger.warning("Native attestation unavailable (%s) — natives stay dormant", exc)
        attest_status = {}

    def attest_ok(broker_id: str) -> bool:
        if broker_id not in SDK_PIN_BY_BROKER:
            return False
        pin = SDK_PIN_BY_BROKER[broker_id]
        if pin is None:
            # REST-only native (no third-party SDK, currently INDmoney): nothing to
            # attest — activation is gated by stored credentials alone.
            return True
        return attest_status.get(pin) == STATUS_OK

    credentialled: set[str] = set()
    if credential_store is not None:
        try:
            for account in credential_store.list_accounts():
                adapter_id = account.get("adapter_id") or account.get("broker")
                if adapter_id:
                    credentialled.add(str(adapter_id))
        except Exception as exc:  # pragma: no cover - vault read must never brick boot
            logger.warning("Credential vault read failed (%s) — natives stay dormant", exc)

    def has_credentials(broker_id: str) -> bool:
        return broker_id in credentialled

    return attest_ok, has_credentials


def _lazy_dhan_security_resolver() -> Callable[[str, str], str]:
    """Build a Dhan scrip-master resolver on first use.

    Dhan order and market-data calls take numeric security ids. The standalone
    live probe warms this resolver before market reads; the app-activated native
    adapter needs the same behaviour so broker routes and gated writes do not
    fail after a successful connect.
    """
    lock = threading.Lock()
    resolver: Callable[[str, str], str] | None = None

    def _resolve(symbol: str, exchange: str) -> str:
        nonlocal resolver
        if resolver is None:
            with lock:
                if resolver is None:
                    # Reuse the adapter's canonical public fetch+parse helper —
                    # no cross-package reach into module-private symbols and no
                    # second copy of the download+CSV composition to drift.
                    from flinttrade_gateway.brokers import dhan_mapping as dhan_map  # noqa: PLC0415
                    from flinttrade_gateway.brokers.dhan import load_scrip_master_rows  # noqa: PLC0415

                    rows = load_scrip_master_rows("compact")
                    resolver = dhan_map.build_security_resolver(rows)
                    logger.info("Dhan security resolver loaded from compact scrip master rows=%s", len(rows))
        return resolver(symbol, exchange)

    return _resolve


def _native_adapter_kwargs_for(
    local_state_provider: Callable[[Any], Any],
) -> Callable[[str], dict[str, Any]]:
    """Return per-native adapter constructor kwargs for app activation."""
    dhan_security_resolver = _lazy_dhan_security_resolver()

    def _kwargs(broker_id: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"local_state_provider": local_state_provider}
        if broker_id == "dhan":
            kwargs["security_resolver"] = dhan_security_resolver
        return kwargs

    return _kwargs


def _build_reconcile_targets_provider(
    registry: BrokerRegistry,
    native_adapters: dict[str, Any],
    registered_selectors: list[str],
) -> Callable[[], list[tuple[Any, Any]]]:
    """Build the ``(adapter, session)`` enumerator the reconciliation runner polls.

    Resolved AT CALL TIME so natives that authenticate after boot (the
    credential-replay login step) are picked up on the runner's next cycle: a
    registered selector yields a target only when its adapter is active in
    ``native_adapters`` AND the registry holds an adapter-layer session for it.
    The bridge adapter (``openalgo``) is excluded by construction — only native
    broker ids ever appear in ``native_adapters``.

    Args:
        registry: The broker registry holding adapter-layer sessions.
        native_adapters: Live ``broker_id -> adapter`` map (mutated in place by
            the ``on_native_activated`` sink as natives activate).
        registered_selectors: The workspace ``brokers.registered`` selectors.

    Returns:
        Zero-argument callable returning the current reconcile targets.
    """

    def _targets() -> list[tuple[Any, Any]]:
        from flinttrade_engine.request_context import parse_selector  # noqa: PLC0415

        pairs: list[tuple[Any, Any]] = []
        for selector in registered_selectors:
            try:
                adapter_id, account_id = parse_selector(selector)
            except ValueError:
                continue
            adapter = native_adapters.get(adapter_id)
            if adapter is None:
                continue
            try:
                session = registry.get_session_for(adapter_id, account_id)
            except Exception:
                continue  # no live session yet — not an error, just dormant
            pairs.append((adapter, session))
        return pairs

    return _targets


def build_broker_router(
    registry: BrokerRegistry,
    brokers_config: dict[str, Any],
    *,
    adapters: dict[str, Any] | None = None,
    openalgo_client: Any | None = None,
    native_attest_ok: Callable[[str], bool] | None = None,
    native_has_credentials: Callable[[str], bool] | None = None,
    native_adapter_kwargs: Callable[[str], dict[str, Any]] | None = None,
    on_native_activated: Callable[[dict[str, Any]], None] | None = None,
) -> Any:
    """Construct a config-driven :class:`BrokerRouter` (contract §13 / §11.4).

    Parses ``brokers_config`` into a :class:`RoutingConfig` (raising
    ``RoutingConfigError`` on a malformed block), wires an
    :class:`AuthenticatingSessionProvider` over the config's ``account_acls`` and
    a process-local one-shot :class:`SafetyGate`.

    When ``openalgo_client`` is supplied, an :class:`OpenAlgoAdapter` is
    registered under the ``openalgo`` adapter id and a Session is put in the
    registry for every ``openalgo:<account>`` selector in ``registered`` — so the
    gated path can dispatch to ALL of the operator's brokers through OpenAlgo
    (the actor still needs an entry in ``account_acls`` to be authorised).

    Native SDK adapters activate the moment their prerequisites hold: when both
    ``native_attest_ok`` (SDK installed + pinned-match) and
    ``native_has_credentials`` (vault holds creds) are supplied, the native
    selectors in ``registered`` are run through ``build_native_adapters`` and the
    survivors registered alongside OpenAlgo. With either callable omitted — the
    default — no native is constructed, so the natives stay dormant exactly as
    before. ``adapters`` still lets a caller inject adapters directly (and wins
    over the factory for the same id). A registered native has no live Session
    until the credential-replay login step establishes one; an unauthenticated
    native selector simply has no session to dispatch to.

    ``on_native_activated`` (when supplied) is called once with the final
    ``broker_id -> adapter`` map of ACTIVE native adapters (factory-built or
    injected) so the caller can wire engine-side consumers — the reconciliation
    runner — without reaching into the router's internals. Best-effort: a sink
    failure is logged and never bricks routing.

    Raises:
        RoutingConfigError: If ``brokers_config`` is malformed.
    """
    from flinttrade_engine.request_context import parse_selector  # noqa: PLC0415
    from flinttrade_engine.safety import SafetyGate  # noqa: PLC0415
    from flinttrade_gateway.adapter import BROKER_CATALOG  # noqa: PLC0415
    from flinttrade_gateway.brokers.native_factory import (  # noqa: PLC0415
        build_native_adapters,
        is_native_broker,
    )
    from flinttrade_gateway.router import BrokerRouter  # noqa: PLC0415
    from flinttrade_gateway.routing_config import RoutingConfig  # noqa: PLC0415
    from flinttrade_gateway.session_provider import (  # noqa: PLC0415
        AuthenticatingSessionProvider,
    )

    config = RoutingConfig.from_workspace(brokers_config)
    session_provider = AuthenticatingSessionProvider(registry, config.account_acls)
    gate = SafetyGate()

    resolved_adapters: dict[str, Any] = dict(adapters or {})

    # Native-adapter activation (dormant -> live bridge). Only runs when the
    # caller supplies both prerequisite checks; otherwise natives stay dormant.
    if native_attest_ok is not None and native_has_credentials is not None:
        native_ids: list[str] = []
        for selector in config.registered:
            try:
                adapter_id, _account = parse_selector(selector)
            except ValueError:
                continue
            info = BROKER_CATALOG.get(adapter_id)
            if info is not None and info.native and not info.connectable:
                logger.info("Native adapter %s dormant: coming-soon-not-live-verified", adapter_id)
                continue
            native_ids.append(adapter_id)
        activated = build_native_adapters(
            native_ids,
            attest_ok=native_attest_ok,
            has_credentials=native_has_credentials,
            adapter_kwargs=native_adapter_kwargs,
            on_skip=lambda bid, why: logger.info("Native adapter %s dormant: %s", bid, why),
        )
        for adapter_id, adapter in activated.items():
            resolved_adapters.setdefault(adapter_id, adapter)
        if activated:
            logger.info("Native adapters activated: %s", ", ".join(sorted(activated)))
    if openalgo_client is not None and "openalgo" not in resolved_adapters:
        from flinttrade_gateway.brokers._base import Session as _AdapterSession  # noqa: PLC0415
        from flinttrade_gateway.brokers.openalgo import OpenAlgoAdapter  # noqa: PLC0415

        resolved_adapters["openalgo"] = OpenAlgoAdapter(default_client=openalgo_client)
        # Register a Session for each openalgo:<account> selector so the
        # AuthenticatingSessionProvider can resolve it (the actor still has to be
        # authorised in account_acls).
        for selector in config.registered:
            try:
                adapter_id, account_id = parse_selector(selector)
            except ValueError:
                continue
            if adapter_id == "openalgo":
                registry.put_session(
                    "openalgo",
                    account_id,
                    _AdapterSession(
                        access_token="",
                        expires_at=4_102_444_800.0,
                        account_id=account_id,
                        adapter_id="openalgo",
                    ),
                )

    # Report the ACTIVE native adapters (factory-built or injected) to the
    # caller's sink so the engine-side reconciliation runner can enumerate them
    # without reaching into the router. The bridge (openalgo) never qualifies.
    if on_native_activated is not None:
        try:
            on_native_activated(
                {aid: adapter for aid, adapter in resolved_adapters.items() if is_native_broker(aid)}
            )
        except Exception as exc:  # pragma: no cover - observability only
            logger.warning("Native-adapter activation sink failed (%s)", exc)

    # Per-broker API rate limiter (DATA & INFRA: customizable rate limits). Built
    # from each registered adapter's capability metadata, with operator overrides
    # from workspace.json brokers.rate_limits[broker_id].{order,data}. A pure
    # below-the-gate throttle — it only delays a dispatch, never bypasses safety.
    rate_limiter = None
    try:
        from flinttrade_gateway.rate_limiter import BrokerRateLimiter  # noqa: PLC0415

        caps = {
            aid: adapter.capabilities
            for aid, adapter in resolved_adapters.items()
            if hasattr(adapter, "capabilities")
        }
        overrides = brokers_config.get("rate_limits", {}) if isinstance(brokers_config, dict) else {}
        if caps or overrides:
            rate_limiter = BrokerRateLimiter.from_capabilities(caps, overrides=overrides)
    except Exception as exc:  # pragma: no cover - a bad limit must not brick routing
        logger.warning("Broker rate limiter not built (%s); dispatch will be unthrottled", exc)

    # Algo-tag guard (SEBI algo-id relay + per-(broker, exchange) per-second
    # algo-order ceiling) for adapters advertising ``algo_tag_required``
    # (Dhan/IndMoney). Built only when the operator configured their
    # broker-registered algo ids in workspace.json
    # ``brokers.algo_tags[broker_id].{algo_id, max_orders_per_sec}``.
    #
    # Parsed LENIENTLY per-entry: an invalid or unknown-broker entry is dropped
    # with a loud error and the remaining valid entries still apply. A dropped
    # entry is safe — the adapter/mapping retail default takes over (Dhan places
    # untagged, IndMoney injects its per-exchange default id), so no order ever
    # dispatches in a broker-flagging state. Crucially the guard is NOT allowed
    # to brick the whole BrokerRouter: a bad algo_tags block must not take down
    # broker READS, reconciliation, and bridge dispatch (only the custom
    # ceiling/relay is forfeited until the operator fixes workspace.json).
    algo_tag_guard = None
    algo_tags_cfg = brokers_config.get("algo_tags", {}) if isinstance(brokers_config, dict) else {}
    if isinstance(algo_tags_cfg, dict) and algo_tags_cfg:
        from flinttrade_engine.algo_tag_guard import AlgoTagConfig, AlgoTagGuard  # noqa: PLC0415

        # Only adapters that actually consult the guard (algo_tag_required) can
        # be tagged; a typo'd/non-algo broker key is inert, so reject it loudly
        # rather than logging it as "active".
        taggable = {
            aid for aid, adapter in resolved_adapters.items()
            if getattr(getattr(adapter, "capabilities", None), "algo_tag_required", False)
        }
        tag_configs: dict[str, AlgoTagConfig] = {}
        for broker_id, spec in algo_tags_cfg.items():
            bid = str(broker_id)
            if not isinstance(spec, dict):
                logger.error("brokers.algo_tags[%r] ignored — must be an object", bid)
                continue
            algo_id = str(spec.get("algo_id", "")).strip()
            try:
                max_per_sec = int(spec.get("max_orders_per_sec", 0) or 0)
            except (TypeError, ValueError):
                max_per_sec = 0
            if not algo_id or max_per_sec <= 0:
                logger.error(
                    "brokers.algo_tags[%r] ignored — needs a non-empty algo_id and a "
                    "positive max_orders_per_sec", bid,
                )
                continue
            if taggable and bid not in taggable:
                logger.error(
                    "brokers.algo_tags[%r] ignored — %r is not an active algo-tag broker "
                    "(algo_tag_required). Active: %s", bid, bid, sorted(taggable),
                )
                continue
            tag_configs[bid] = AlgoTagConfig(algo_id=algo_id, max_orders_per_sec=max_per_sec)
        if tag_configs:
            algo_tag_guard = AlgoTagGuard(tag_configs)
            logger.info("Algo-tag guard active for: %s", ", ".join(sorted(tag_configs)))

    return BrokerRouter(
        resolved_adapters, session_provider, consume_gate=gate.consume, config=config,
        rate_limiter=rate_limiter, algo_tag_guard=algo_tag_guard,
    )


def _broker_router_drain_timeout(app: Flask) -> float:
    """Return the configured bounded generation-drain timeout."""
    raw_timeout = app.config.get("BROKER_ROUTER_DRAIN_TIMEOUT_SECONDS", 10.0)
    try:
        return max(0.0, float(raw_timeout))
    except (TypeError, ValueError):
        return 10.0


def retire_broker_router_generation(app: Flask, *, timeout: float | None = None) -> bool:
    """Unpublish and permanently retire the current routing generation.

    A timed-out generation remains strongly referenced in app config so a
    later rebuild or shutdown retry must finish draining that exact instance
    before any replacement can be published.
    """
    rebuild_lock = app.config.setdefault(
        "BROKER_ROUTER_REBUILD_LOCK", threading.RLock()
    )
    with rebuild_lock:
        active_router = app.config.get("BROKER_ROUTER")
        draining_router = app.config.get("BROKER_ROUTER_DRAINING")
        if active_router is not None:
            if draining_router is not None and draining_router is not active_router:
                app.config["BROKER_ROUTER"] = None
                logger.critical(
                    "Multiple BrokerRouter generations require draining; routing is disabled"
                )
                return False
            app.config["BROKER_ROUTER"] = None
            draining_router = active_router
            app.config["BROKER_ROUTER_DRAINING"] = active_router

        if draining_router is None:
            app.config["BROKER_ROUTER_DRAINING"] = None
            return True

        revoke_and_drain = getattr(draining_router, "revoke_and_drain", None)
        if not callable(revoke_and_drain):
            logger.critical(
                "BrokerRouter generation cannot be revoked; routing is disabled"
            )
            return False

        drain_timeout = _broker_router_drain_timeout(app) if timeout is None else max(0.0, timeout)
        try:
            drained = bool(revoke_and_drain(timeout=drain_timeout))
        except Exception as exc:  # noqa: BLE001 - stale writes fail closed
            logger.critical(
                "BrokerRouter generation revocation failed (%s)",
                type(exc).__name__,
            )
            return False
        if not drained:
            return False

        if app.config.get("BROKER_ROUTER_DRAINING") is draining_router:
            app.config["BROKER_ROUTER_DRAINING"] = None
        return True


def configure_broker_router(
    app: Flask,
    registry: Any,
    credential_store: Any,
    openalgo_client: Any,
) -> bool:
    """Build (or rebuild) the BrokerRouter and store it + friends on app.config.

    Extracted from ``create_flask_app`` so it can be re-invoked at runtime after
    the credential vault or the ``brokers.registered``/``account_acls`` config
    changes (an interactive "connect native broker" action) — rebuilding
    re-reads the vault + config, so a native that just gained credentials
    activates. A rebuild publishes one complete routing generation atomically.
    The prior generation is revoked and drained before the candidate becomes
    reachable, so retained background references cannot dispatch through stale
    credentials or ACLs. Any failure leaves routing unavailable.
    """
    rebuild_lock = app.config.setdefault(
        "BROKER_ROUTER_REBUILD_LOCK", threading.RLock()
    )
    with rebuild_lock:
        if not app.config.get("RUNTIME_ACCEPTING_REQUESTS", True):
            logger.warning("BrokerRouter rebuild refused while the runtime is shutting down")
            retire_broker_router_generation(app)
            app.config["SMART_ROUTING"] = {}
            app.config["NATIVE_ADAPTERS"] = {}
            app.config["RECONCILE_TARGETS"] = None
            return False
        if not retire_broker_router_generation(app):
            app.config["SMART_ROUTING"] = {}
            app.config["NATIVE_ADAPTERS"] = {}
            app.config["RECONCILE_TARGETS"] = None
            logger.critical(
                "BrokerRouter rebuild aborted because the prior generation did not drain"
            )
            return False

        candidate_router = None
        candidate_smart_routing: dict[str, Any] = {}
        candidate_native_adapters: dict[str, Any] = {}
        candidate_reconcile_targets = None
        brokers_cfg: dict[str, Any] | None = None
        build_error: Exception | None = None
        try:
            from .workspace_migrations import default_workspace_config  # noqa: PLC0415
            from flinttrade_engine.local_state_provider import JournalLocalStateProvider  # noqa: PLC0415

            brokers_cfg = _read_workspace_brokers()
            effective_brokers = brokers_cfg or default_workspace_config()["brokers"]
            candidate_smart_routing = dict(
                effective_brokers.get("smart_routing") or {}
            )
            native_attest_ok, native_has_credentials = _native_activation_checks(
                credential_store
            )
            local_state_provider = JournalLocalStateProvider(
                storage_provider=lambda: app.config.get("TRADE_STORAGE"),
                lock_provider=lambda: app.config.get("TRADE_STORAGE_LOCK"),
            )
            candidate_router = build_broker_router(
                registry,
                effective_brokers,
                openalgo_client=openalgo_client,
                native_attest_ok=native_attest_ok,
                native_has_credentials=native_has_credentials,
                native_adapter_kwargs=_native_adapter_kwargs_for(local_state_provider),
                on_native_activated=candidate_native_adapters.update,
            )
            candidate_reconcile_targets = _build_reconcile_targets_provider(
                registry,
                candidate_native_adapters,
                [str(s) for s in (effective_brokers.get("registered") or [])],
            )
        except Exception as exc:  # noqa: BLE001 - malformed routing fails closed
            build_error = exc

        if build_error is not None or candidate_router is None:
            app.config["SMART_ROUTING"] = {}
            app.config["NATIVE_ADAPTERS"] = {}
            app.config["RECONCILE_TARGETS"] = None
            if build_error is not None:
                logger.critical(
                    "BrokerRouter not built — workspace.json brokers routing is invalid: %s. "
                    "Order routing is unavailable until you fix brokers.routing; the rest of "
                    "the app is up. Last known-good config: "
                    "~/.flinttrade/workspace.brokers.bak.json",
                    build_error,
                )
            return False

        if not app.config.get("RUNTIME_ACCEPTING_REQUESTS", True):
            logger.warning("BrokerRouter candidate discarded because shutdown began during rebuild")
            return False

        app.config["OPENALGO_CLIENT"] = openalgo_client
        app.config["SMART_ROUTING"] = candidate_smart_routing
        app.config["NATIVE_ADAPTERS"] = candidate_native_adapters
        app.config["RECONCILE_TARGETS"] = candidate_reconcile_targets
        app.config["BROKER_ROUTER"] = candidate_router
        if brokers_cfg is not None:
            _snapshot_brokers_bak(brokers_cfg)
        return True


def _bind_runtime_emergency_dispatcher(
    app: Flask,
    safety: Any,
    telegram: Any,
    client: Any,
) -> Any:
    """Bind background emergency writes to the current gated router generation.

    Telegram authenticates the human command through its configured chat id,
    but it has no Flask request/JWT context. The application owner therefore
    supplies a fresh command principal using the single operator profile. The
    router still enforces the configured account ACL, and every dispatch
    resolves the current default selector and router generation independently.
    """
    from flinttrade_engine.request_context import RequestContext, parse_selector  # noqa: PLC0415
    from flinttrade_engine.safety import (  # noqa: PLC0415
        EmergencyBrokerTarget,
        GatedEmergencyBrokerDispatcher,
    )

    run_sync = getattr(client, "run_sync", None)
    if not callable(run_sync):
        raise RuntimeError("Emergency dispatcher requires the shared broker event-loop owner")

    def target_provider() -> EmergencyBrokerTarget:
        router = app.config.get("BROKER_ROUTER")
        selector = str(getattr(router, "default_selector", None) or "").strip()
        if not selector:
            raise ValueError("no configured emergency execution selector")
        adapter_id, account_id = parse_selector(selector)

        auth_service = app.config.get("AUTH_SERVICE")
        if auth_service is None:
            raise ValueError("operator profile is unavailable")
        profile = auth_service.get_profile()
        actor_id = str(profile.get("username") or "").strip()
        if not actor_id:
            raise ValueError("operator profile has no ACL identity")

        request_ctx = RequestContext(
            jti=f"telegram-{secrets.token_urlsafe(24)}",
            actor_type="human",
            actor_id=actor_id,
            mode="live",
            selector=f"{adapter_id}:{account_id}",
        )
        return EmergencyBrokerTarget(
            request_ctx=request_ctx,
            adapter_id=adapter_id,
            account_id=account_id,
        )

    dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: app.config.get("BROKER_ROUTER"),
        target_provider=target_provider,
        run_awaitable=run_sync,
    )
    safety.bind_emergency_dispatcher(dispatcher)
    if telegram is not None:
        telegram.emergency_dispatcher = dispatcher
    app.config["EMERGENCY_DISPATCHER"] = dispatcher
    return dispatcher


def _reestablish_native_sessions(app: Flask, *, verify: bool = True) -> dict[str, Any]:
    """Log in every active native selector whose credentials are in the vault.

    Runs the credential-replay login step (G3) for the natives that
    ``configure_broker_router`` just activated. Sync wrapper around the async
    ``establish_native_sessions`` — safe to call from the factory and from a
    Flask route (both run outside an event loop). Never raises.

    ``verify`` probes each freshly-established session with a cheap
    authenticated read so a dead token surfaces honestly as ``needs_relogin``
    instead of a false "connected". Transient broker/service-window failures
    are treated as inconclusive and keep the session.
    """
    import asyncio  # noqa: PLC0415
    import threading  # noqa: PLC0415

    from flinttrade_gateway.native_login import establish_native_sessions  # noqa: PLC0415

    native_adapters = app.config.get("NATIVE_ADAPTERS") or {}
    registry = app.config.get("REGISTRY")
    credential_store = app.config.get("CREDENTIAL_STORE")
    if not native_adapters or registry is None or credential_store is None:
        return {}
    try:
        brokers_cfg = _read_workspace_brokers() or {}
        selectors = [str(s) for s in (brokers_cfg.get("registered") or [])]
        async def _run() -> dict[str, Any]:
            return await establish_native_sessions(
                native_adapters, registry, credential_store, selectors, verify=verify,
            )

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            results = asyncio.run(_run())
        else:
            box: dict[str, Any] = {}

            def _thread_run() -> None:
                try:
                    box["results"] = asyncio.run(_run())
                except BaseException as exc:  # noqa: BLE001 - re-raise in caller thread
                    box["error"] = exc

            thread = threading.Thread(target=_thread_run, name="native-session-replay", daemon=True)
            thread.start()
            thread.join()
            if "error" in box:
                raise box["error"]
            results = box.get("results", {})
        # G7 — surface per-selector login outcomes so the accounts list can say
        # "needs fresh login: <reason>" instead of a bare red "no live session".
        # Merged (not replaced) so a boot result survives later partial reruns.
        status: dict[str, Any] = app.config.setdefault("NATIVE_SESSION_STATUS", {})
        status.update(results)
        return results
    except Exception as exc:  # noqa: BLE001 - session establishment must never brick boot/route
        logger.warning("Native session re-establishment failed: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Flask API server — FlintTrade-specific endpoints (port 5100)
# ---------------------------------------------------------------------------


def _wire_ml_signal_runtime(
    app: Flask,
    cron: Any,
    time_scheduler: Any,
) -> bool:
    """Register the canonical scheduled ML producer when it was configured."""
    pipeline = app.config.get("ML_SIGNAL_PIPELINE")
    if pipeline is None:
        logger.info("Scheduled ML signals inactive - no OpenAlgo-backed producer")
        return False

    from flinttrade_ai.signal_routes import make_ml_signal_job  # noqa: PLC0415

    def market_session_for(
        exchange: str,
        symbol: str,
        session_date: Any,
    ) -> Any:
        return time_scheduler.get_market_session(
            exchange,
            on=session_date,
            symbol=symbol,
        )

    set_market_session_provider = getattr(
        pipeline,
        "set_market_session_provider",
        None,
    )
    if callable(set_market_session_provider):
        set_market_session_provider(market_session_for)

    cron.register(
        "ml_signal_cycle",
        handler=make_ml_signal_job(
            pipeline,
            lambda exchange, symbol: bool(
                time_scheduler.is_market_open(exchange, symbol=symbol)
            ),
        ),
        description="Publish scheduled LightGBM signals into the canonical feed",
        trigger_type="interval",
        trigger_args={"minutes": 5},
    )
    app.config["ML_SIGNAL_JOB"] = "ml_signal_cycle"

    try:
        from flinttrade_ai.signal_retraining import (  # noqa: PLC0415
            RetrainConfig,
            SignalRetrainer,
            plan_retraining_roster,
        )

        configured_retrain = app.config.get("ML_SIGNAL_RETRAIN_CONFIG")
        if configured_retrain is None:
            retrain_config = RetrainConfig(model_dir=Path(pipeline.model_path).parent)
        elif isinstance(configured_retrain, RetrainConfig):
            retrain_config = configured_retrain
        elif isinstance(configured_retrain, Mapping):
            config_values = dict(configured_retrain)
            config_values.setdefault("model_dir", Path(pipeline.model_path).parent)
            retrain_config = RetrainConfig(**config_values)
        else:
            raise TypeError("ML_SIGNAL_RETRAIN_CONFIG must be a RetrainConfig or mapping")

        retrain_cancel_event = threading.Event()
        retrainer = SignalRetrainer(
            retrain_config,
            instruments=pipeline.instruments,
            data_fetcher=pipeline.fetch_bars,
            pipeline=pipeline,
            instrument_provider=lambda: pipeline.instruments,
            cancel_requested=retrain_cancel_event.is_set,
            market_session_provider=market_session_for,
        )
        retry_jobs: set[str] = set()

        def _schedule_retrain_retry(retry: Any, *, run_at: Any | None = None) -> None:
            scheduled_at = run_at or retry.retry_at
            job_name = (
                "ml_signal_retrain_retry:"
                f"{retry.target.exchange}:{retry.target.symbol}:"
                f"{retry.session_date.isoformat()}:{int(scheduled_at.timestamp())}"
            )

            def _run_retry() -> list[Any]:
                retry_jobs.discard(job_name)
                if retrain_cancel_event.is_set():
                    return []
                results = retrainer.run_all(
                    instruments=[retry.instrument],
                    session_date=retry.session_date,
                )
                if any(not bool(getattr(result, "completed", True)) for result in results):
                    from datetime import timedelta as _timedelta  # noqa: PLC0415

                    _schedule_retrain_retry(
                        retry,
                        run_at=time_scheduler.now_ist() + _timedelta(minutes=1),
                    )
                return results

            retry_jobs.add(job_name)
            try:
                cron.schedule_once(
                    name=job_name,
                    handler=_run_retry,
                    run_at=scheduled_at,
                    description=(
                        "Retry canonical signal training after the dated effective session close"
                    ),
                )
            except Exception:
                retry_jobs.discard(job_name)
                raise

        def _run_signal_retrain(*, roster: str = "regular") -> list[Any]:
            try:
                from datetime import time as _wall_time  # noqa: PLC0415
                from datetime import timedelta as _timedelta  # noqa: PLC0415

                now = time_scheduler.now_ist()
                session_date = now.date()
                if roster == "late" and now.time().replace(tzinfo=None) < _wall_time(12):
                    session_date -= _timedelta(days=1)
                plan = plan_retraining_roster(
                    pipeline.instruments,
                    roster=roster,
                    session_date=session_date,
                    run_at=now,
                    is_continuous=lambda exchange: bool(
                        (schedule := time_scheduler.get_schedule(exchange))
                        and schedule.is_24x7
                    ),
                    session_for=market_session_for,
                )
                for retry in plan.retries:
                    _schedule_retrain_retry(retry)
                results = retrainer.run_all(
                    instruments=plan.ready_instruments,
                    session_date=session_date,
                )
                if any(not bool(getattr(result, "completed", True)) for result in results):
                    logger.info("Signal retraining remains pending on its active fetch owner")
                return results
            except Exception as exc:  # noqa: BLE001 - scheduler and app must remain available
                logger.warning("Scheduled signal retraining failed: %s", exc)
                return []

        def _run_late_signal_retrain() -> list[Any]:
            return _run_signal_retrain(roster="late")

        cron.register(
            "ml_signal_retrain",
            handler=_run_signal_retrain,
            description="Retrain canonical per-instrument signal models after market close",
            trigger_type="cron",
            trigger_args={
                "hour": 16,
                "minute": 0,
                "timezone": "Asia/Kolkata",
            },
        )
        cron.register(
            "ml_signal_retrain_late",
            handler=_run_late_signal_retrain,
            description="Retrain late-closing and continuous-market signal models",
            trigger_type="cron",
            trigger_args={
                "hour": 0,
                "minute": 30,
                "timezone": "Asia/Kolkata",
            },
        )
    except Exception as exc:  # noqa: BLE001 - optional ML runtime must not prevent app boot
        logger.warning("Scheduled signal retraining not wired: %s", exc)
    else:
        app.config["ML_SIGNAL_RETRAIN_CONFIG"] = retrain_config
        app.config["ML_SIGNAL_RETRAINER"] = retrainer
        app.config["ML_SIGNAL_RETRAIN_JOB"] = "ml_signal_retrain"
        app.config["ML_SIGNAL_RETRAIN_JOBS"] = (
            "ml_signal_retrain",
            "ml_signal_retrain_late",
        )
        app.config["ML_SIGNAL_RETRAIN_CANCEL_EVENT"] = retrain_cancel_event
        app.config["ML_SIGNAL_RETRAIN_RETRY_JOBS"] = retry_jobs
    return True


def create_flask_app(
    safety: Any | None = None,
    scheduler: Any | None = None,
    cron: Any | None = None,
    audit: AuditLogger | None = None,
    client: OpenAlgoClient | None = None,
    registry: BrokerRegistry | None = None,
    credential_store: CredentialStore | None = None,
    contract_manager: ContractManager | None = None,
    rag: Any | None = None,
    cron_strategy_scheduler: Any | None = None,
    time_scheduler: Any | None = None,
) -> Flask:
    """Create the Flask app with FlintTrade API routes.

    Args:
        safety: SafetySystem instance to expose via safety endpoints.
        scheduler: StrategyScheduler instance for strategy lifecycle endpoints.
        cron: CronManager instance for cron job management endpoints.
        audit: AuditLogger instance for audit log endpoints.
        client: OpenAlgoClient instance for MCP bridge and backtest data.
        registry: BrokerRegistry for multi-broker account management.
        credential_store: CredentialStore for encrypted credential persistence.
        contract_manager: ContractManager for broker symbol contract data.
        rag: RAGPipeline instance for knowledge base queries.
        cron_strategy_scheduler: Shared market-aware strategy cron scheduler.
        time_scheduler: Shared effective-session calendar owner.

    Returns:
        Flask application with all FlintTrade API endpoints registered.
    """
    # ------------------------------------------------------------------
    # Pre-init hygiene:
    #   * Clear stale DuckDB .wal files from a previous crashed process.
    #   * Log workspace.json OpenAlgo overrides when present; Settings reads
    #     those values directly and uses .env only as a fallback.
    # Both are best-effort — failures here must never prevent startup.
    # ------------------------------------------------------------------
    try:
        _cleanup_stale_duckdb_wals()
    except Exception as exc:
        logger.warning("DuckDB WAL cleanup failed: %s", exc)

    try:
        _log_workspace_openalgo_overrides()
    except Exception as exc:
        logger.warning("workspace.json override failed: %s", exc)

    # ------------------------------------------------------------------
    # Static frontend — serve the built React bundle from
    # packages/apps/terminal/dist/ with SPA fallback for client-side routes.
    # If the build output is missing we fall back to API-only mode and
    # log a clear warning.
    # ------------------------------------------------------------------
    # Resolve the built React bundle. Three sources, in priority order:
    #   1. ``FLINTTRADE_FRONTEND_DIST`` env override (any deployment).
    #   2. Frozen desktop build — the bundle ships ``frontend/`` alongside the
    #      packaged code (PyInstaller unpacks it under ``sys._MEIPASS``).
    #   3. Source tree — ``packages/apps/terminal/dist``.
    _dist_override = os.environ.get("FLINTTRADE_FRONTEND_DIST")
    if _dist_override:
        _dist_path = Path(_dist_override)
    elif _FROZEN and _BUNDLE_DIR:
        _dist_path = Path(_BUNDLE_DIR) / "frontend"
    else:
        _dist_path = Path(_REPO_ROOT) / "packages" / "apps" / "terminal" / "dist"
    _dist_index = _dist_path / "index.html"
    _frontend_available = _dist_index.exists()

    if _frontend_available:
        # Point Flask's built-in static_folder at the React build.  We use
        # a dedicated static_url_path (``/_static_flask``) so Flask's
        # default catch-all route does not pre-empt the SPA fallback
        # registered later — we serve all of the root-level dist files
        # (assets/, favicon.svg, index.html) through our fallback so
        # the NotFound → index.html redirect can work cleanly.
        app = Flask(
            __name__,
            static_folder=str(_dist_path),
            static_url_path="/_static_flask",
        )
    else:
        app = Flask(__name__)
        logger.warning(
            "Frontend not built — run `npm run build` in packages/apps/terminal. "
            "Backend will serve API only."
        )
    app.config["_FRONTEND_AVAILABLE"] = _frontend_available
    app.config["_DIST_PATH"] = _dist_path
    _install_runtime_request_tracking(app)
    app.config["SIGNAL_STREAM_SHUTDOWN_EVENT"] = threading.Event()
    app.config["AUTONOMOUS_AGENT_SHUTDOWN_EVENT"] = threading.Event()
    _tick_capture_lifecycle_lock(app)

    # ------------------------------------------------------------------
    # Structured logging — ONE pipeline for both structlog calls and
    # stdlib logging calls.  Dual-emit bug (same event logged twice,
    # once pretty + once JSON) was caused by PrintLoggerFactory writing
    # to stdout *and* a bridge handler on root *also* writing to stdout.
    # Fix: route structlog through stdlib (LoggerFactory), then format
    # at the stdlib handler using ProcessorFormatter.  One event → one
    # line.
    #
    # Also disable click's ANSI colouring so Werkzeug's request log
    # doesn't embed escape codes in the log file.  Must be set BEFORE
    # werkzeug's first import triggers click initialisation.
    # ------------------------------------------------------------------
    os.environ.setdefault("ANSI_COLORS_DISABLED", "1")
    os.environ.setdefault("NO_COLOR", "1")

    _render_processor = (
        structlog.dev.ConsoleRenderer(colors=False)
        if app.debug
        else structlog.processors.JSONRenderer()
    )

    # Shared pre-chain applied to every event from either source.
    _shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
    ]

    structlog.configure(
        processors=[
            *_shared_processors,
            # Hand off to stdlib's ProcessorFormatter for the final render.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    _sentinel_attr = "_flinttrade_structlog_bridge"
    _root_logger = logging.getLogger()
    # Kill any pre-existing handler (e.g. from an earlier basicConfig call
    # or a previous create_flask_app() invocation) so we can't double-emit.
    for _h in list(_root_logger.handlers):
        _root_logger.removeHandler(_h)

    _formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            # Drop the raw LogRecord and _from_structlog meta keys before
            # rendering, otherwise JSON output leaks the absolute install
            # path (C:\Users\...\app.py, line numbers) into every event.
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            _render_processor,
        ],
        foreign_pre_chain=_shared_processors,
    )
    _handler = logging.StreamHandler()
    _handler.setFormatter(_formatter)
    setattr(_handler, _sentinel_attr, True)
    _root_logger.addHandler(_handler)
    _root_logger.setLevel(logging.INFO)

    # ------------------------------------------------------------------
    # Production-mode path rewrite (WSGI-level, runs before URL dispatch).
    # In dev, Vite strips the `/ft-api` prefix before requests reach us
    # (see packages/apps/terminal/vite.config.ts server.proxy). When the
    # backend serves the built frontend directly, no such proxy exists,
    # so the backend receives the full `/ft-api/v1/...` path while all
    # blueprints are registered under `/v1/...` or `/api/v1/...`.
    # A before_request handler runs AFTER Flask's URL match, so we wrap
    # wsgi_app instead to mutate the environ before routing.
    # ------------------------------------------------------------------
    _inner_wsgi = app.wsgi_app

    def _ft_api_prefix_stripper(environ: dict, start_response: Any) -> Any:
        raw_path = environ.get("PATH_INFO", "") or ""
        if raw_path.startswith("/ft-api/"):
            environ["PATH_INFO"] = raw_path[len("/ft-api"):]
        elif raw_path == "/ft-api":
            environ["PATH_INFO"] = "/"
        return _inner_wsgi(environ, start_response)

    app.wsgi_app = _ft_api_prefix_stripper  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # Trusted forwarded-IP handling — gated behind TRUST_PROXY_HEADERS.
    # Without this, deployments behind Nginx see `request.remote_addr ==
    # 127.0.0.1` for every request, which collapses rate-limit buckets,
    # brute-force tracking, and 404 flood guards onto the loopback origin.
    # When the env flag is truthy we wrap wsgi_app with Werkzeug's ProxyFix
    # so `request.remote_addr` reflects the original client IP.
    # Default is FALSE because trusting forwarded headers from an
    # untrusted upstream would let any client spoof its source IP.
    # Mirrors the upstream OpenAlgo behaviour added in v2.0.0.7
    # (see TRUST_PROXY_HEADERS in .local/external/openalgo/utils/ip_helper.py).
    # ------------------------------------------------------------------
    if os.environ.get("TRUST_PROXY_HEADERS", "").lower() in {"1", "true", "yes", "on"}:
        try:
            from werkzeug.middleware.proxy_fix import ProxyFix  # noqa: PLC0415

            _proxy_for = int(os.environ.get("TRUST_PROXY_HEADERS_X_FOR", "1") or "1")
            _proxy_proto = int(os.environ.get("TRUST_PROXY_HEADERS_X_PROTO", "1") or "1")
            _proxy_host = int(os.environ.get("TRUST_PROXY_HEADERS_X_HOST", "0") or "0")
            _proxy_port = int(os.environ.get("TRUST_PROXY_HEADERS_X_PORT", "0") or "0")
            _proxy_prefix = int(os.environ.get("TRUST_PROXY_HEADERS_X_PREFIX", "0") or "0")
            app.wsgi_app = ProxyFix(  # type: ignore[assignment]
                app.wsgi_app,
                x_for=_proxy_for,
                x_proto=_proxy_proto,
                x_host=_proxy_host,
                x_port=_proxy_port,
                x_prefix=_proxy_prefix,
            )
            logger.info(
                "TRUST_PROXY_HEADERS active — ProxyFix: x_for=%d x_proto=%d "
                "x_host=%d x_port=%d x_prefix=%d",
                _proxy_for, _proxy_proto, _proxy_host, _proxy_port, _proxy_prefix,
            )
        except Exception as exc:  # pragma: no cover - import/config edge case
            logger.warning(
                "TRUST_PROXY_HEADERS requested but ProxyFix could not be installed: %s",
                exc,
            )

    # ------------------------------------------------------------------
    # CORS — allow requests from the Vite dev server and any origins
    # configured via the CORS_ORIGINS environment variable.
    # ------------------------------------------------------------------
    CORS(
        app,
        origins=os.environ.get(
            "CORS_ORIGINS", "http://127.0.0.1:5173"
        ).split(","),
        methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=[
            "Content-Type",
            "X-API-Key",
            "X-FlintTrade-Mode",
            "Authorization",
        ],
    )

    # ------------------------------------------------------------------
    # Rate limiting — 50 req/s default; tighter limits applied per-route
    # via @limiter.limit() on individual blueprints/views.
    # ------------------------------------------------------------------
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=["50 per second"],
        storage_uri="memory://",
    )
    app.config["LIMITER"] = limiter

    # Custom token-bucket rate limiter — HTTP-layer DoS / fat-finger guard
    # (429) via ``@rate_limit``; the SEBI per-second broker-submission cap is
    # enforced below the gate by ``BrokerRouter._throttle``, which every gated
    # order traverses. Applied to the core order routes + smart-route start +
    # engine basket/split/bracket + strategy-start (orders 10/s user, 100/s
    # global; smart_orders 2/s, 20/s). Webhooks use WebhookReceiver's limiter.
    from .rate_limiter import RateLimiter as _RateLimiter  # noqa: PLC0415
    _rate_limiter = _RateLimiter(global_rate=100, per_user_rate=10)
    _rate_limiter.set_limit("orders", user_rate=10, global_rate=100)
    _rate_limiter.set_limit("smart_orders", user_rate=2, global_rate=20)
    _rate_limiter.set_limit("webhook", user_rate=5, global_rate=50)
    app.config["RATE_LIMITER"] = _rate_limiter

    # ------------------------------------------------------------------
    # Error tracking — Sentry SDK pointing at a Glitchtip instance (MIT).
    # Only initialised when GLITCHTIP_DSN is set in the environment; safe
    # to leave unset in development.
    # ------------------------------------------------------------------
    _glitchtip_dsn = os.environ.get("GLITCHTIP_DSN", "")
    if _glitchtip_dsn:
        sentry_sdk.init(
            dsn=_glitchtip_dsn,
            integrations=[FlaskIntegration()],
            traces_sample_rate=0.1,
            environment="production" if not app.debug else "development",
        )
        logger.info("Glitchtip error tracking initialised")

    # Store injected instances on app.config so endpoint closures can access them
    app.config["SAFETY"] = safety
    app.config["SCHEDULER"] = scheduler
    app.config["CRON"] = cron
    app.config["AUDIT"] = audit
    app.config["CLIENT"] = client

    # --- Gateway initialization ---
    if registry is None:
        registry = BrokerRegistry()

    # Ensure API_KEY_PEPPER is set in os.environ BEFORE the OpenAlgo
    # broker modules are imported via the gateway shim. Upstream's
    # ``utils.config.API_KEY_PEPPER`` is captured at import time, so a
    # later os.environ tweak is too late.
    _get_api_key_pepper()

    # Bind the dedicated safety-gate HMAC secret (contract §8.0b) BEFORE the
    # broker router is built and before any SafetyContext can be minted/verified.
    # Without it gate_order() fails closed and every live routed order would 403.
    from flinttrade_engine.safety import set_safety_gate_secret  # noqa: PLC0415

    set_safety_gate_secret(_get_safety_gate_secret_bytes())

    if credential_store is None:
        flinttrade_dir = _workspace_dir()
        master_password = _get_master_password()
        credential_store = CredentialStore(flinttrade_dir / "credentials.db", master_password)

    if contract_manager is None:
        flinttrade_dir = _workspace_dir()
        contracts_dir = flinttrade_dir / "contracts"
        contracts_dir.mkdir(exist_ok=True)
        contract_manager = ContractManager(contracts_dir)

    app.config["REGISTRY"] = registry
    app.config["CREDENTIAL_STORE"] = credential_store
    app.config["CONTRACT_MANAGER"] = contract_manager
    app.config["OAUTH_STATES"] = {}

    # Ditto multi-account api_keys live in a Ditto-scoped vault (the canonical
    # CredentialStore crypto: per-row salt + PBKDF2 from the master password),
    # NOT the shared native store — whose boot reconnect would otherwise try to
    # authenticate each ditto:openalgo row as a bridge session. Optional: a
    # missing vault must never block startup (Ditto routes 503 without it).
    try:
        app.config["DITTO_CREDENTIAL_STORE"] = CredentialStore(
            _workspace_dir() / "ditto_credentials.db", _get_master_password()
        )
    except Exception as exc:  # noqa: BLE001 - Ditto is optional
        logger.warning("Ditto credential vault unavailable: %s", exc)
        app.config["DITTO_CREDENTIAL_STORE"] = None

    # --- Broker router (selector-bound principal; contract §13 / §11.4) ---
    # Best-effort like the other startup steps: a malformed brokers block must
    # NOT brick the app — the operator needs the UI up to fix it. On failure we
    # log loudly and leave BROKER_ROUTER as None so the gated order path returns
    # a clear 503 rather than dispatching. A successfully-parsed config is
    # snapshotted to workspace.brokers.bak.json for operator rollback (§13.3).
    configure_broker_router(app, registry, credential_store, client)
    # Re-establish native sessions for any selector whose credentials are
    # already in the vault (a restart after the operator connected a broker
    # earlier). First boot with an empty vault is a no-op. Best-effort — a
    # broker whose token expired overnight is marked as needing re-login while
    # transient service-window/network failures keep the session.
    _reestablish_native_sessions(app, verify=True)

    # Store RAG instance
    app.config["RAG"] = rag
    app.config["RAG_STATUS"] = (
        "ready" if rag is not None else "disabled" if not _rag_runtime_enabled() else "unavailable"
    )
    # Optional zero-argument callable returning a non-empty market-data mapping.
    # The sentiment route degrades to RSS when no provider is installed.
    app.config["MARKET_SENTIMENT_DATA_PROVIDER"] = None

    # Register gateway blueprint (mounts at /v1/)
    app.register_blueprint(gateway_bp)

    # G9 — broker-management write guard: every POST/PUT/DELETE on the gateway
    # blueprint (accounts, credential capture, OAuth start, rate-limit config)
    # must carry a valid operator session JWT. The gateway package cannot
    # import core's JWT machinery, so the guard is injected here.
    from .auth_routes import require_operator_session  # noqa: PLC0415
    app.config["BROKER_MGMT_WRITE_GUARD"] = require_operator_session

    # Native broker account capture + activation (Phase 1 G4) — /api/v1/native/*
    from .native_account_routes import native_accounts_bp  # noqa: PLC0415
    app.register_blueprint(native_accounts_bp)

    # Daily broker session refresh (Phase 1 G5) — rotator + 08:05 IST jobs +
    # /admin/credentials/rotation/* admin routes. The scheduler is created
    # unstarted; _run_flask_server starts it on the serve path only.
    from .native_rotation import configure_session_rotation  # noqa: PLC0415
    rotation_bp = configure_session_rotation(app)
    if rotation_bp is not None:
        app.register_blueprint(rotation_bp)

    # Register analysis blueprint (/api/v1/gex, /api/v1/volsurface, etc.)
    from flinttrade_screener.analysis_routes import analysis_bp  # noqa: PLC0415
    app.register_blueprint(analysis_bp)

    # Register sample-data placeholder blueprint — eight endpoints whose real
    # implementations are not yet built. Each returns is_sample_data=true so
    # widgets show their "Demo" badge instead of 404-ing. See
    # packages/services/screener/src/sample_data_routes.py.
    from flinttrade_screener.sample_data_routes import sample_data_bp  # noqa: PLC0415
    app.register_blueprint(sample_data_bp)

    # Register stock screener blueprint (/v1/stocks/*)
    from flinttrade_screener.stock_routes import stock_bp  # noqa: PLC0415
    app.register_blueprint(stock_bp)

    # Register market scanner blueprint (/v1/scanner/* — external: /ft-api/v1/scanner/*)
    from flinttrade_screener.scanner_routes import scanner_bp  # noqa: PLC0415
    app.register_blueprint(scanner_bp)

    # Register OI analytics blueprint (/v1/oi/* — external: /ft-api/v1/oi/*)
    from flinttrade_screener.oi_analytics_routes import oi_analytics_bp  # noqa: PLC0415
    app.register_blueprint(oi_analytics_bp)

    # Register Mutual Fund NAV blueprint (/api/v1/mf/search, /mf/nav, /mf/categories)
    from flinttrade_screener.mf_routes import mf_bp  # noqa: PLC0415
    app.register_blueprint(mf_bp)

    # Register breadth + volatility cone blueprints (/v1/breadth/*, /v1/analytics/volcone — external: /ft-api/v1/*)
    from flinttrade_screener.breadth_routes import breadth_bp  # noqa: PLC0415
    app.register_blueprint(breadth_bp)

    # Register Action Center blueprint (/api/v1/action-center/*)
    from flinttrade_engine.action_center import ActionCenter  # noqa: PLC0415
    from flinttrade_engine.action_center_routes import action_center_bp  # noqa: PLC0415
    action_center = ActionCenter()
    app.config["ACTION_CENTER"] = action_center
    app.register_blueprint(action_center_bp)

    # Register Security blueprint and middleware (/api/v1/security/*)
    from .security import SecurityMonitor  # noqa: PLC0415
    from .security_routes import register_security_middleware, security_bp  # noqa: PLC0415
    security_monitor = SecurityMonitor()
    app.config["SECURITY_MONITOR"] = security_monitor
    app.register_blueprint(security_bp)
    register_security_middleware(app, security_monitor)

    # Register persistent SecurityTracker (DuckDB-backed 404/IP-ban log)
    from flinttrade_data.security_tracker import SecurityTracker as _SecurityTracker  # noqa: PLC0415
    _security_db = _workspace_dir() / "security.db"
    app.config["SECURITY_TRACKER"] = _SecurityTracker(str(_security_db))

    # Register LoginActivity + SessionTracker (DuckDB-backed)
    from flinttrade_data.activity_log import LoginActivity as _LoginActivity  # noqa: PLC0415
    from flinttrade_data.activity_log import SessionTracker as _SessionTracker  # noqa: PLC0415
    _login_db = _workspace_dir() / "activity.db"
    app.config["LOGIN_ACTIVITY"] = _LoginActivity(str(_login_db))
    app.config["SESSION_TRACKER"] = _SessionTracker(str(_login_db))

    # Shared trade-journal store (DuckDB). The gated order dispatch writes every
    # executed live order here and the /trades/journal route reads the SAME
    # store, so the journal + P&L analytics populate in Live (previously the
    # producer was missing → permanently empty journal). One shared, pre-
    # initialised connection keeps the per-order cost to a single INSERT (latency
    # is paramount). A lock serialises the writer against the route's reads —
    # DuckDB connections are not safe for concurrent use. Best-effort: a storage
    # failure degrades to "no journalling", never blocks boot.
    try:
        from flinttrade_data.storage import StorageManager as _TradeStore  # noqa: PLC0415

        _trade_storage = _TradeStore()
        _trade_storage.initialise()
        app.config["TRADE_STORAGE"] = _trade_storage
        app.config["TRADE_STORAGE_LOCK"] = threading.Lock()
    except Exception:  # pragma: no cover — defensive: never let storage break boot
        logger.warning(
            "Trade journal storage unavailable; live trades will not be journalled",
            exc_info=True,
        )
        app.config["TRADE_STORAGE"] = None
        app.config["TRADE_STORAGE_LOCK"] = None

    # Annotated Trade Journal (SQLite + FTS5, own journal.sqlite). Distinct from
    # the TRADE_STORAGE execution records above: this holds the operator's notes,
    # emotions, quality scores, and tags with full-text search. Best-effort — a
    # storage failure degrades to "journal unavailable" (503s), never blocks boot.
    try:
        from flinttrade_journal.journal_routes import init_journal_routes, journal_bp  # noqa: PLC0415
        from flinttrade_journal.trade_journal import TradeJournal  # noqa: PLC0415

        _journal = TradeJournal()
        _journal.initialise()
        app.config["JOURNAL"] = _journal
        init_journal_routes(_journal)
        app.register_blueprint(journal_bp)
    except Exception:  # pragma: no cover — defensive: never let the journal break boot
        logger.warning("Trade journal unavailable; /api/v1/journal returns 503", exc_info=True)
        app.config["JOURNAL"] = None

    # Register Order Flow blueprint (synthetic footprint data)
    from flinttrade_data.orderflow_routes import orderflow_bp  # noqa: PLC0415
    app.register_blueprint(orderflow_bp)

    # Register Tick Capture blueprint (/api/v1/data/ticks/*) — status, recorded
    # tick queries and runtime watchlist management for the opt-in recorder.
    from flinttrade_data.tick_routes import ticks_bp  # noqa: PLC0415
    app.register_blueprint(ticks_bp)

    # Register Tax Report blueprint (/v1/tax/*)
    from flinttrade_data.tax_routes import tax_bp  # noqa: PLC0415
    app.register_blueprint(tax_bp)

    # Register Historify watchlist blueprint
    from flinttrade_historical.watchlist_routes import historify_bp  # noqa: PLC0415
    app.register_blueprint(historify_bp)

    # Register TradingView signals blueprint (/v1/tv/*)
    from flinttrade_screener.tv_routes import tv_bp  # noqa: PLC0415
    app.register_blueprint(tv_bp)

    # Register monitoring blueprint (/api/v1/traffic/*, /api/v1/latency/*).
    # Aggregated /api/v1/health lives in health_bp (the canonical health surface).
    from .monitoring_routes import monitoring_bp  # noqa: PLC0415
    app.register_blueprint(monitoring_bp)

    # Register frontend error ingestion + changelog reader (/v1/errors, /v1/changelog
    # — external URLs: /ft-api/v1/errors, /ft-api/v1/changelog). Previously referenced
    # by the terminal but not wired, causing 404s on fire-and-forget error reports.
    # Initialise the persistent error log ONCE (always active — not gated by
    # dev mode). The try/except guard means a DuckDB failure degrades to
    # warning-only logging rather than crashing startup. The same instance is
    # stored on app.config (so admin_routes and frontend_errors_bp can reach
    # it) and reused by the global error handler below.
    from .error_log import ErrorLog as _ErrorLog  # noqa: PLC0415
    from .frontend_error_routes import frontend_errors_bp  # noqa: PLC0415
    _error_db = _workspace_dir() / "error_log.duckdb"
    try:
        _error_log = _ErrorLog(db_path=str(_error_db))
    except Exception as exc:
        logger.warning("ErrorLog initialisation failed (%s); /v1/errors will log warnings only", exc)
        _error_log = None
    app.config["ERROR_LOG"] = _error_log
    app.register_blueprint(frontend_errors_bp)

    # Register Strategy Runner blueprint (/api/v1/strategies/*)
    from flinttrade_engine.strategy_routes import strategy_bp  # noqa: PLC0415
    app.register_blueprint(strategy_bp)

    # Wire the Strategy Runner + Cron scheduler the strategy routes require so
    # upload/start/stop/logs/schedule work in production — without these config
    # keys every /api/v1/strategies write returned 503 "Strategy runner not
    # configured" (feature audit H1/M13). Construction is side-effect-light: the
    # runner only creates its own dirs, and CronStrategyScheduler does not start
    # APScheduler until .start() is called.
    if "STRATEGY_RUNNER" not in app.config:
        try:
            from flinttrade_engine.strategy_runner import UserStrategyRunner  # noqa: PLC0415

            app.config["STRATEGY_RUNNER"] = UserStrategyRunner(_workspace_dir() / "strategies")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Strategy runner wiring failed (%s); /strategies writes will 503", exc)
    resolved_time_scheduler = time_scheduler
    if cron_strategy_scheduler is not None:
        resolved_time_scheduler = (
            getattr(cron_strategy_scheduler, "time_scheduler", None)
            or resolved_time_scheduler
        )
    if resolved_time_scheduler is None:
        try:
            from flinttrade_engine.scheduler import TimeScheduler  # noqa: PLC0415

            resolved_time_scheduler = TimeScheduler(client=client)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Time scheduler wiring failed (%s); market-aware work will 503", exc)
    if "CRON_SCHEDULER" not in app.config:
        try:
            from flinttrade_engine.scheduler import CronStrategyScheduler  # noqa: PLC0415

            app.config["CRON_SCHEDULER"] = (
                cron_strategy_scheduler
                if cron_strategy_scheduler is not None
                else CronStrategyScheduler(time_scheduler=resolved_time_scheduler)
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Cron scheduler wiring failed (%s); strategy scheduling will 503", exc)
    if resolved_time_scheduler is None:
        resolved_time_scheduler = getattr(
            app.config.get("CRON_SCHEDULER"),
            "time_scheduler",
            None,
        )
    app.config["TIME_SCHEDULER"] = resolved_time_scheduler

    # Execution-quality analytics (POST /api/v1/analytics/execution) and strategy
    # comparison (POST /api/v1/backtest/compare) — both fully built + tested but were
    # never registered (404 in production; feature audit H6/M2). Their blueprints
    # carry no prefix, so register under /api/v1 to match the frontend convention.
    from flinttrade_journal.order_analytics import order_analytics_bp  # noqa: PLC0415
    app.register_blueprint(order_analytics_bp, url_prefix="/api/v1")
    from flinttrade_backtest.strategy_comparison import strategy_comparison_bp  # noqa: PLC0415
    app.register_blueprint(strategy_comparison_bp, url_prefix="/api/v1")

    # Register Engine Sandbox blueprint (/v1/sandbox-config/*) — config/leverage/squareoff.
    # Uses the /v1/sandbox-config prefix to avoid collision with the data sandbox
    # blueprint below, which owns /v1/sandbox.
    from flinttrade_engine.sandbox_routes import sandbox_bp  # noqa: PLC0415
    from flinttrade_engine.sandbox import SandboxEngine as _EngineSandboxEngine  # noqa: PLC0415
    app.config["SANDBOX_ENGINE"] = _EngineSandboxEngine(account_id="default")
    app.register_blueprint(sandbox_bp)

    # Register Data Sandbox blueprint (/v1/sandbox/*) — paper trading engine
    # (capital, orders, positions, P&L, reset, export/import)
    from flinttrade_data.sandbox_routes import data_sandbox_bp  # noqa: PLC0415
    from flinttrade_data.sandbox_engine import SandboxEngine as _DataSandboxEngine  # noqa: PLC0415
    app.config["DATA_SANDBOX_ENGINE"] = _DataSandboxEngine()
    app.register_blueprint(data_sandbox_bp)

    # ------------------------------------------------------------------
    # Global unhandled-exception handler — persists errors to DuckDB
    # before re-raising so Flask's default 500 handler takes over.
    # ------------------------------------------------------------------
    @app.errorhandler(Exception)
    def _log_unhandled_exception(exc: Exception) -> Any:
        """Persist every unhandled exception to the structured error log.

        Werkzeug ``HTTPException`` instances (404, 405, 415, …) are not
        real errors — they represent deliberately returned HTTP status
        codes and must be passed straight through with their own payload,
        otherwise a simple 404 bubbles up as a misleading 500.  Real
        exceptions are logged and converted to a plain HTTP 500 JSON
        response so we never leak internal tracebacks to clients.
        """
        from werkzeug.exceptions import HTTPException  # noqa: PLC0415

        if isinstance(exc, HTTPException):
            return exc  # Flask will render the HTTPException normally.

        try:
            if _error_log is not None:
                _error_log.log(
                    route=request.path,
                    method=request.method,
                    status_code=500,
                    request_body=request.get_json(silent=True, force=True),
                    error=exc,
                    user_id=None,  # user context not available at this layer
                )
        except Exception:
            # Never let the error logger itself crash the request.
            pass
        return jsonify({"status": "error", "message": "Internal server error"}), 500

    # Initialise TrafficLogger (DuckDB-backed, always active).
    # @before_request / @after_request hooks record every HTTP request.
    from .traffic_logger import TrafficLogger as _TrafficLogger, should_skip_path as _skip_path  # noqa: PLC0415

    _traffic_log_path = _workspace_dir() / "traffic_log.duckdb"
    _traffic_logger = _TrafficLogger(_traffic_log_path)
    app.config["TRAFFIC_LOGGER"] = _traffic_logger

    @app.before_request
    def _traffic_start() -> None:
        """Record the request start time for traffic duration measurement."""
        import time as _time  # noqa: PLC0415
        _flask_g._traffic_start = _time.monotonic()

    @app.after_request
    def _traffic_log(response: Any) -> Any:
        """Persist request details to TrafficLogger after each response."""
        try:
            if not _skip_path(request.path):
                import time as _time  # noqa: PLC0415
                start = getattr(_flask_g, "_traffic_start", None)
                duration_ms = (_time.monotonic() - start) * 1000 if start is not None else 0.0
                _traffic_logger.log(
                    ip=request.remote_addr or "unknown",
                    method=request.method,
                    path=request.path,
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                    user_agent=request.headers.get("User-Agent"),
                    request_size=request.content_length,
                    response_size=response.content_length,
                )
        except Exception as _exc:
            logger.debug("suppressed: %s", _exc)  # Never let traffic logging break the response
        return response

    # Initialise LatencyMonitor (DuckDB-backed, always active).
    # The order router wraps this via monitoring_routes.get_latency_tracker()
    # for in-memory stats; this provides persistent DuckDB-backed storage.
    from flinttrade_engine.latency_monitor import LatencyMonitor as _LatencyMonitor  # noqa: PLC0415

    _latency_log_path = _workspace_dir() / "latency_log.duckdb"
    _latency_monitor = _LatencyMonitor(_latency_log_path)
    app.config["LATENCY_MONITOR"] = _latency_monitor

    # Initialise APIAnalyzer (DuckDB-backed, opt-in via ENABLE_ANALYZER=true).
    _analyzer_enabled = os.environ.get("ENABLE_ANALYZER", "").lower() in ("1", "true", "yes")
    if _analyzer_enabled:
        from .api_analyzer import APIAnalyzer as _APIAnalyzer  # noqa: PLC0415

        _analyzer_path = _workspace_dir() / "api_analyzer.duckdb"
        _api_analyzer = _APIAnalyzer(_analyzer_path)
        app.config["API_ANALYZER"] = _api_analyzer

        @app.after_request
        def _analyzer_log(response: Any) -> Any:
            """Persist full request + response to APIAnalyzer when enabled."""
            try:
                import time as _time  # noqa: PLC0415
                start = getattr(_flask_g, "_traffic_start", None)
                duration_ms = (_time.monotonic() - start) * 1000 if start is not None else 0.0
                _api_analyzer.log_call(
                    route=request.path,
                    method=request.method,
                    request_body=request.get_json(silent=True, force=True),
                    response_status=response.status_code,
                    response_body=None,  # Not parsing response body to avoid re-reading stream
                    duration_ms=duration_ms,
                )
            except Exception as _exc:
                logger.debug("suppressed: %s", _exc)
            return response

        logger.info("API Analyser enabled — capturing all requests")

    # Initialise module-level EventBus singleton.
    from .event_bus import bus as _event_bus  # noqa: PLC0415
    app.config["EVENT_BUS"] = _event_bus
    logger.info("EventBus initialised")

    # Register admin blueprint (dev/debug only)
    if app.debug or os.environ.get("FLINTTRADE_DEV"):
        from .admin_routes import admin_bp  # noqa: PLC0415
        app.register_blueprint(admin_bp)
        # Register infrastructure admin routes (traffic/latency/analyzer)
        from .infra_routes import infra_bp  # noqa: PLC0415
        app.register_blueprint(infra_bp)
        # Workspace backup/restore admin routes (/admin/backup/*)
        from .backup_routes import create_backup_blueprint  # noqa: PLC0415
        app.register_blueprint(create_backup_blueprint(workspace_dir=_workspace_dir()))
        logger.info("Admin endpoints registered (dev mode)")

    # Register Activity Log blueprint (/api/v1/admin/activity)
    # Always registered — audit access is not restricted to dev mode.
    from flinttrade_data.activity_routes import activity_bp  # noqa: PLC0415
    _activity_db = _workspace_dir() / "activity.db"
    from flinttrade_data.activity_log import ActivityLog as _ActivityLog  # noqa: PLC0415
    app.config["ACTIVITY_LOG"] = _ActivityLog(str(_activity_db))
    app.register_blueprint(activity_bp)
    logger.info("Activity log endpoint registered at /api/v1/admin/activity")

    # Register extracted inline-route blueprints
    from .indicators_routes import indicators_bp  # noqa: PLC0415
    app.register_blueprint(indicators_bp)

    from flinttrade_ai.advisor_routes import advisor_bp  # noqa: PLC0415
    app.register_blueprint(advisor_bp)

    from flinttrade_ai.ai_routes import ai_bp  # noqa: PLC0415
    app.register_blueprint(ai_bp)

    from flinttrade_ai.obsidian_routes import obsidian_bp  # noqa: PLC0415
    app.register_blueprint(obsidian_bp)

    from flinttrade_ai.signal_routes import (  # noqa: PLC0415
        configure_signal_sources,
        signal_bp,
    )
    app.register_blueprint(signal_bp)
    configure_signal_sources(app, client)

    from .backtest_routes import backtest_bp  # noqa: PLC0415
    app.register_blueprint(backtest_bp)

    from .operations_routes import operations_bp  # noqa: PLC0415
    app.register_blueprint(operations_bp)

    # Register Order proxy blueprint (/v1/orders/*) — CRITICAL SAFETY LAYER.
    # All order requests from the frontend must pass through here so that
    # mode enforcement (explore/practice/live) is applied before any
    # real-money order reaches OpenAlgo.
    from .order_routes import orders_bp  # noqa: PLC0415
    app.register_blueprint(orders_bp)

    # Register smart-order routing blueprint (/api/v1/orders/smart-route).
    # OFF by default (workspace brokers.smart_routing.enabled); every child
    # order still traverses the full gated path via GatedChildExecutor.
    from .smart_order_routes import smart_order_bp  # noqa: PLC0415
    app.register_blueprint(smart_order_bp)

    # Register the autonomous-agent control plane (/api/v1/ai/agent/*).
    # OFF by default (workspace ai.autonomous_agent.enabled); the agent runs
    # as its own ACL'd principal and orders only via GatedChildExecutor.
    from .agent_routes import agent_bp  # noqa: PLC0415
    app.register_blueprint(agent_bp)

    # Register AI Team blueprint (/api/v1/ai/team/*)
    from flinttrade_ai.team_routes import team_bp  # noqa: PLC0415
    app.register_blueprint(team_bp)

    # Register Fundamental Screener blueprint (/api/v1/fundamentals/*)
    from flinttrade_screener.fundamental_routes import fundamental_bp  # noqa: PLC0415
    app.register_blueprint(fundamental_bp)

    # Register IPO Tracker blueprint (/api/v1/ipo/*)
    from flinttrade_screener.ipo_routes import ipo_bp  # noqa: PLC0415
    app.register_blueprint(ipo_bp)

    # Register Earnings Calendar blueprint (/api/v1/earnings/* — external:
    # /ft-api/api/v1/earnings/*). Prefix flipped 2026-05-19 (was /v1/) so the
    # frontend's ftApi.helpers /api/v1 path lines up with the registered route.
    from flinttrade_screener.earnings_routes import earnings_bp  # noqa: PLC0415
    app.register_blueprint(earnings_bp)

    # Register Pivot Calculator blueprint (/v1/pivots/* — external: /ft-api/v1/pivots/*)
    from flinttrade_screener.pivot_routes import pivot_bp  # noqa: PLC0415
    app.register_blueprint(pivot_bp)

    # Register Economic Calendar blueprint (/v1/economic/* — external: /ft-api/v1/economic/*)
    from flinttrade_screener.economic_routes import economic_bp  # noqa: PLC0415
    app.register_blueprint(economic_bp)

    # Register Audit Trail blueprint (/v1/audit/* — external: /ft-api/v1/audit/*)
    from flinttrade_data.audit_routes import audit_bp  # noqa: PLC0415
    app.register_blueprint(audit_bp)

    # Register Analytics extensions blueprint (/v1/indicators/vwap, /v1/analytics/pairs,
    # /v1/analytics/mtf — external: /ft-api/v1/indicators/*, /ft-api/v1/analytics/*)
    from flinttrade_screener.analytics_routes import analytics_bp  # noqa: PLC0415
    app.register_blueprint(analytics_bp)

    # Register WhatsApp Alerts blueprint (/api/v1/alerts/whatsapp/*)
    from flinttrade_automation.whatsapp_routes import whatsapp_bp  # noqa: PLC0415
    app.register_blueprint(whatsapp_bp)

    # Register Telegram Alerts blueprint (/api/v1/telegram)
    from .telegram_routes import telegram_bp  # noqa: PLC0415
    app.register_blueprint(telegram_bp)

    # Register Historical Expiry Tracker blueprint (/api/v1/historical/*)
    from flinttrade_historical.expiry_tracker_routes import expiry_tracker_bp  # noqa: PLC0415
    app.register_blueprint(expiry_tracker_bp)

    # Register Holidays + Market Timings blueprint (/api/v1/holidays, /api/v1/market/timings)
    from flinttrade_historical.holidays_routes import holidays_bp  # noqa: PLC0415
    app.register_blueprint(holidays_bp)

    # Register Intervals blueprint (/api/v1/intervals)
    from flinttrade_historical.intervals_routes import intervals_bp  # noqa: PLC0415
    app.register_blueprint(intervals_bp)

    # Register Local Data Store blueprint (/v1/historify/bars*, bhavcopy download)
    # — browse locally-downloaded OHLCV and fetch full-market NSE bhavcopies.
    from flinttrade_historical.local_data_routes import local_data_bp  # noqa: PLC0415
    app.register_blueprint(local_data_bp)

    # Register Instruments blueprint (/api/v1/instruments)
    from flinttrade_historical.instruments_routes import instruments_bp  # noqa: PLC0415
    app.register_blueprint(instruments_bp)

    # Register Symbol Search blueprint (/api/v1/search)
    from flinttrade_historical.search_routes import search_bp  # noqa: PLC0415
    app.register_blueprint(search_bp)

    # Register Broker Capabilities blueprint (/api/v1/broker/capabilities)
    from flinttrade_gateway.capabilities_routes import capabilities_bp  # noqa: PLC0415
    app.register_blueprint(capabilities_bp)

    # Register Leverage / Margin blueprint (/api/v1/leverage/margin/current)
    from flinttrade_engine.leverage_routes import leverage_bp  # noqa: PLC0415
    app.register_blueprint(leverage_bp)

    # Register Chart Preferences blueprint (/api/v1/chart)
    from .chart_prefs_routes import chart_prefs_bp  # noqa: PLC0415
    app.register_blueprint(chart_prefs_bp)

    # Register Bracket Order blueprint (/api/v1/orders/bracket*) and construct
    # the service it delegates to. Every bracket leg WRITE traverses the same
    # gated chain as a human /place order — SafetySystem L1-L5 -> gate_order
    # (one-shot HMAC SafetyContext) -> BrokerRouter -> adapter — through the
    # injected dispatchers; the service never holds a raw broker/OpenAlgo
    # client for writes (gateway/tests/test_no_legacy_order_path.py pins it).
    # Practice-mode JWTs are refused 403 practice_unsupported at the route
    # boundary (mode_guard.require_live_unlocked): the sandbox cannot execute
    # multi-leg brackets, so an honest refusal beats a silent live order.
    from flinttrade_engine.bracket_order import (  # noqa: PLC0415
        BracketOrderService,
        build_gated_leg_dispatchers,
    )
    from flinttrade_engine.bracket_routes import bracket_bp  # noqa: PLC0415
    _bracket_place_leg, _bracket_cancel_leg = build_gated_leg_dispatchers(app)
    app.config["BRACKET_SERVICE"] = BracketOrderService(
        place_leg=_bracket_place_leg,
        cancel_leg=_bracket_cancel_leg,
    )
    app.register_blueprint(bracket_bp)

    # Wire the advanced-order executors (basket / split) that back the engine
    # order_bp routes (/api/v1/orders/{basket,split,options-strategy}). Each
    # routes every leg/chunk through the SAME gated dispatcher as a bracket leg
    # (build_gated_leg_dispatchers -> gate_order -> BrokerRouter), so they hold
    # no broker client and no ungated path exists. Pinned by
    # test_executors_stay_gated and gateway/tests/test_no_legacy_order_path.py.
    from flinttrade_engine.basket_orders import BasketOrderExecutor  # noqa: PLC0415
    from flinttrade_engine.split_orders import SplitOrderExecutor  # noqa: PLC0415
    app.config["BASKET_EXECUTOR"] = BasketOrderExecutor(place_leg=_bracket_place_leg)
    app.config["SPLIT_EXECUTOR"] = SplitOrderExecutor(place_leg=_bracket_place_leg)

    # Register Position Sizer blueprint (/api/v1/position/*)
    from flinttrade_engine.position_sizer_routes import position_bp  # noqa: PLC0415
    app.register_blueprint(position_bp)

    # Register Voice Orders blueprint (/api/v1/voice/*)
    from flinttrade_webhooks.voice_orders import voice_bp  # noqa: PLC0415
    app.register_blueprint(voice_bp)

    # Register n8n bridge blueprint (/api/v1/automation/n8n/*)
    from flinttrade_automation.n8n_routes import n8n_bp  # noqa: PLC0415
    app.register_blueprint(n8n_bp)

    # Register QuestDB bridge blueprint (/api/v1/data/questdb/*)
    from flinttrade_data.questdb_routes import questdb_bp  # noqa: PLC0415
    app.register_blueprint(questdb_bp)

    # Register Excel bridge blueprint (/api/v1/integration/excel/*)
    from flinttrade_webhooks.excel_routes import excel_bp  # noqa: PLC0415
    app.register_blueprint(excel_bp)

    # ------------------------------------------------------------------
    # Blueprints discovered as defined-but-not-registered during the
    # 2026-05-19 multi-agent audit (Python audit, API contract audit).
    # Registering them activates their routes:
    #
    #   webhook_bp                — /v1/webhook/<source>, /v1/webhook/log
    #                               (TradingView + ChartInk webhook receivers)
    #   payoff_bp                 — /api/v1/payoff/{analyse,curve}, /api/v1/regime/current,
    #                               /api/v1/analytics/correlation
    #                               (prefix flipped 2026-05-19 to align with ftApi.helpers)
    #   health_bp                 — /health, /health/detail, /healthz, /readyz,
    #                               /api/v1/ping, /api/v1/health (K8s + LB probes
    #                               + aggregated subsystem health; canonical health
    #                               surface; /api/v1/ping is already in
    #                               `_PUBLIC_V1_PREFIXES`)
    #   optimiser_bp              — /v1/portfolio/{optimise,frontier}
    #   permutation_bp            — /v1/backtest/{permutation,walkforward}
    #   admin_action_center_bp    — /admin/action-center/{pending,approve,reject,history}
    #                               (separate from `action_center_bp` which lives
    #                               under /api/v1/action-center for normal users)
    #   (the advanced-order routes /api/v1/orders/{basket,split,options-strategy}
    #    were folded into core's orders_bp on 2026-07-09 — one blueprint now owns
    #    the whole /api/v1/orders/* surface.)
    # ------------------------------------------------------------------
    from flinttrade_webhooks.webhook_receiver import WebhookConfig, WebhookReceiver  # noqa: PLC0415
    from flinttrade_webhooks.webhook_routes import init_webhook_routes, webhook_bp  # noqa: PLC0415
    from flinttrade_webhooks.webhook_secret_store import WebhookSecretStore  # noqa: PLC0415
    from .operations_routes import webhook_endpoint_enabled  # noqa: PLC0415
    from .webhook_dispatch import WebhookOrderDispatcher  # noqa: PLC0415
    webhook_secret_store = WebhookSecretStore(_workspace_dir() / "webhook_secrets.db", _get_master_password())
    app.config["WEBHOOK_SECRET_STORE"] = webhook_secret_store
    webhook_order_dispatcher = WebhookOrderDispatcher(app)
    init_webhook_routes(
        WebhookReceiver(
            WebhookConfig(),
            order_dispatcher=webhook_order_dispatcher.place_order,
            cancel_dispatcher=webhook_order_dispatcher.cancel_order,
        ),
        secret_store=webhook_secret_store,
        endpoint_status_provider=webhook_endpoint_enabled,
    )
    app.register_blueprint(webhook_bp)

    from flinttrade_screener.payoff_routes import payoff_bp  # noqa: PLC0415
    app.register_blueprint(payoff_bp)

    from .health_routes import health_bp  # noqa: PLC0415
    app.register_blueprint(health_bp)

    # Backtest route blueprints — imported from the installed flinttrade_backtest
    # package (no sys.path injection: the workspace package is installed editable).
    from flinttrade_backtest.optimiser_routes import optimiser_bp  # noqa: PLC0415
    app.register_blueprint(optimiser_bp)
    from flinttrade_backtest.permutation_routes import permutation_bp  # noqa: PLC0415
    app.register_blueprint(permutation_bp)

    from flinttrade_engine.action_center_routes import admin_action_center_bp  # noqa: PLC0415
    app.register_blueprint(admin_action_center_bp)

    # Register Workspace Preset blueprint (/v1/presets/* — external: /ft-api/v1/presets/*)
    from .preset_routes import preset_bp  # noqa: PLC0415
    app.register_blueprint(preset_bp)

    # Register Log Stream blueprint (/v1/logs/*) — SSE + REST log streaming
    from .log_stream import log_stream_bp  # noqa: PLC0415
    app.register_blueprint(log_stream_bp)

    # Register Keyboard Shortcuts blueprint (/v1/shortcuts/*) — per-user DuckDB persistence
    from .shortcuts_routes import shortcuts_bp  # noqa: PLC0415
    app.register_blueprint(shortcuts_bp)

    # Register Docs Search blueprint (/v1/docs/*) — full-text search + changelog
    from .docs_search_routes import docs_search_bp  # noqa: PLC0415
    app.register_blueprint(docs_search_bp)

    # Register the CSP violation-report endpoint (POST /csp-report; matches the
    # report-uri the nonce-based CSP header declares) — DS-CSP-09.
    app.register_blueprint(_csp_report_bp)

    # Register Auth blueprint (/v1/auth/*) — public endpoints, no API key required
    from .auth_service import AuthService as _AuthService  # noqa: PLC0415
    from .auth_routes import auth_bp, install_auth_rate_limits  # noqa: PLC0415
    _auth_db = _workspace_dir() / "auth.db"
    app.config["AUTH_SERVICE"] = _AuthService(db_path=_auth_db)
    app.register_blueprint(auth_bp)
    # Wire the deferred @_rate_limit limits onto Flask-Limiter AFTER the auth
    # views are registered (they aren't present in view_functions during the
    # blueprint's record hook), so login/PIN/setup brute-force is actually
    # throttled — not merely registered against a discarded wrapper.
    install_auth_rate_limits(app)

    # (Multi-user /api/v1/users/* CRUD removed 2026-06-10 as overscope — FlintTrade
    # is a single-operator tool; operator == user == data principal. Archived to
    # .local/archive/user-multi-2026-06-10/.)

    # Reconnect saved accounts (best-effort, don't block startup)
    try:
        _reconnect_saved_accounts(registry, credential_store, logger)
    except Exception as exc:
        logger.error("Account reconnection failed: %s", exc)

    # Paths that are legitimately public (no API key needed):
    # - Health check endpoint (also exempted by endpoint name in require_auth)
    # - Admin introspect (already gated by FLINTTRADE_DEV in admin_routes)
    # - OAuth callbacks (browser redirect — no API key in URL)
    # - Frontend error reporting (/api/v1/errors — must be reachable before auth)
    # - Signed external webhook POSTs (/v1/webhook/*) — HMAC/replay/endpoint
    #   state is enforced inside webhook_routes before dispatch.
    _PUBLIC_V1_PREFIXES = (
        "/v1/admin/health",
        "/v1/admin/introspect",
        "/v1/auth/",          # Auth endpoints are public (login, setup, status)
        "/v1/auth/callback",
        "/v1/errors",         # Frontend error reporting — public, rate-limited.
                              # Blueprint mounted at /v1/errors (see
                              # frontend_error_routes.py:Blueprint(..., url_prefix="/v1")).
                              # Persists to ErrorLog (DuckDB) for post-mortem.
        "/api/v1/errors",     # Same purpose, different sink: this path is
                              # handled by `operations_bp.receive_frontend_error`
                              # which forwards to structlog + Sentry/Glitchtip
                              # instead of DuckDB. Kept public so the React app
                              # and external automation can fire-and-forget
                              # error reports without an API key — neither sink
                              # leaks sensitive data
                              # back to the caller.
        "/v1/changelog",      # Frontend changelog viewer — public, paired with /v1/errors.
        "/api/v1/ping",       # Liveness probe — no auth required
        "/v1/config/openalgo",          # Localhost-only; self-authenticates after setup
        "/v1/test-connection",          # Setup wizard — public, localhost-only
    )

    @app.before_request
    def _bind_request_context() -> None:
        """Bind per-request fields into the structlog context variable store.

        Attaches a unique request ID (from the X-Request-ID header, or a
        freshly generated hex token), the HTTP method, and the path so that
        every log line emitted during this request carries them automatically.
        """
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request.headers.get(
                "X-Request-ID", secrets.token_hex(8)
            ),
            method=request.method,
            path=request.path,
        )

    @app.after_request
    def _log_request(response: Any) -> Any:
        """Emit a structured log line for every completed HTTP response."""
        _req_log = structlog.get_logger()
        _req_log.info(
            "request",
            status=response.status_code,
            content_length=response.content_length,
        )
        return response

    @app.before_request
    def _set_csp_nonce() -> None:
        """Mint a fresh per-request CSP nonce for the served HTML + CSP header.

        Read by :func:`_add_security_headers` (header) and the SPA fallback
        (``<script nonce>`` injection) so the bootstrap script the gateway serves
        carries the same nonce the policy declares (DS-CSP-09).
        """
        _flask_g.csp_nonce = _generate_csp_nonce()

    @app.after_request
    def _add_security_headers(response: Any) -> Any:
        """Add security headers to every response (only when not already set).

        CSP is delivered here, as a per-request HTTP header carrying a fresh nonce
        (DS-CSP-09). It is an HTTP header — not a <meta> tag — because only the gateway
        can mint a per-render nonce and weave it into both the policy and the served
        index.html's <script> tags. The script directive forbids inline scripts (DS-CSP-01).
        """
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-XSS-Protection", "1; mode=block")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            _build_csp_header(getattr(_flask_g, "csp_nonce", None)),
        )
        return response

    @app.before_request
    def require_auth() -> Any:
        """Require API key authentication on all endpoints.

        Only specific public paths are exempted:
        - Health check and admin introspect (dev-gated)
        - OAuth callback (browser redirect, no API key in URL)
        - Static files and SPA HTML fallback (React bundle)
        All other /v1/ endpoints require the same API key auth.
        """
        # Allow health check, static files, and SPA fallback without auth
        if request.endpoint in ("health_detail.health_aggregated", "static", "_spa_fallback"):
            return None
        # Allow OPTIONS for CORS preflight
        if request.method == "OPTIONS":
            return None
        # External signal providers cannot send the FlintTrade API key. Keep
        # only POST intake public; the route itself enforces HMAC signatures,
        # replay defence, endpoint enabled-state, and fail-closed dispatch.
        if request.method == "POST" and request.path.startswith("/v1/webhook/"):
            return None
        # Allow specific public /v1/ paths only
        if any(request.path.startswith(prefix) for prefix in _PUBLIC_V1_PREFIXES):
            return None

        auth_header = request.headers.get("Authorization", "")
        bearer = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else ""
        if bearer:
            try:
                from .auth_routes import decode_token  # noqa: PLC0415

                payload = decode_token(bearer)
                if payload.get("type") == "session":
                    return None
            except Exception:
                # Preserve the legacy ``Authorization: Bearer <api-key>`` path
                # below when the bearer is not a FlintTrade session JWT.
                pass

        api_key = request.headers.get("X-API-Key") or bearer

        expected_key = os.environ.get("FLINTTRADE_API_KEY", "") or os.environ.get("OPENALGO_API_KEY", "")
        if not expected_key:
            remote = request.remote_addr or ""
            if remote in ("127.0.0.1", "::1", "localhost"):
                logger.debug(
                    "FLINTTRADE_API_KEY/OPENALGO_API_KEY not set — allowing loopback local request",
                )
                return None
            logger.warning("FLINTTRADE_API_KEY/OPENALGO_API_KEY not set — remote requests will be rejected")
            return jsonify({"status": "error", "message": "Backend API key not configured"}), 503

        if not api_key or not hmac.compare_digest(api_key, expected_key):
            # Record auth failure for brute-force detection
            try:
                sec = app.config.get("SECURITY_MONITOR")
                if sec:
                    sec.record_auth_failure(request.remote_addr or "unknown")
            except Exception as _exc:
                logger.debug("suppressed: %s", _exc)
            return jsonify({"status": "error", "message": "Unauthorized"}), 401

        return None

    @app.before_request
    def _require_json_content_type() -> Any:
        """Reject POST/PUT/PATCH requests that don't send JSON."""
        if request.method in ("POST", "PUT", "PATCH") and request.content_length:
            content_type = request.content_type or ""
            if "json" not in content_type and "text/event-stream" not in content_type:
                return jsonify({
                    "status": "error",
                    "message": "Content-Type must be application/json",
                }), 415
        return None

    @app.before_request
    def _record_request_start() -> None:
        """Store request start time for latency calculation."""
        _flask_g._request_start = time.monotonic()

    @app.after_request
    def _record_traffic(response: Any) -> Any:
        """Record method, path, status, and duration in TrafficCounter."""
        try:
            from .monitoring_routes import get_traffic_counter  # noqa: PLC0415

            start = getattr(_flask_g, "_request_start", None)
            duration_ms = (time.monotonic() - start) * 1000 if start is not None else 0.0
            get_traffic_counter().record(
                method=request.method,
                path=request.path,
                status=response.status_code,
                duration_ms=duration_ms,
            )
        except Exception as _exc:
            logger.debug("suppressed: %s", _exc)  # Never let monitoring break the response
        return response

    @app.after_request
    def _track_404s(response: Any) -> Any:
        """Persist 404 events in SecurityTracker for flood detection.

        Runs after the response is built so we know the real status code.
        Best-effort — never disrupts the response pipeline.
        """
        if response.status_code == 404:
            try:
                skt = app.config.get("SECURITY_TRACKER")
                if skt is not None:
                    skt.track_404(request.remote_addr or "unknown", request.path)
            except Exception as _exc:
                logger.debug("suppressed: %s", _exc)
        return response

    @app.before_request
    def _session_heartbeat() -> None:
        """Update last_active for the session carried in the Authorization header.

        Only fires when a valid Bearer token is present AND a SessionTracker
        has been registered.  Best-effort — never blocks the request.
        """
        try:
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return
            token = auth_header.removeprefix("Bearer ").strip()
            if not token:
                return
            st = app.config.get("SESSION_TRACKER")
            if st is not None:
                st.heartbeat(token)
        except Exception as _exc:
            logger.debug("suppressed: %s", _exc)

    # --- inline route handlers extracted to blueprints ---
    # indicators_bp  → packages/core/core/src/indicators_routes.py
    # advisor_bp     → packages/services/ai/src/advisor_routes.py
    # ai_bp          → packages/services/ai/src/ai_routes.py
    # signal_bp      → packages/services/ai/src/signal_routes.py
    # backtest_bp    → packages/core/core/src/backtest_routes.py
    # operations_bp  → packages/core/core/src/operations_routes.py

    # ------------------------------------------------------------------
    # MCP bridge — intentionally NOT wired here.
    #
    # A dormant bridge used to register an UNGATED ``place_order`` handler that
    # built a fresh OpenAlgoClient and submitted live orders without passing
    # through the SafetySystem / gate_order / BrokerRouter and mode guard. It
    # was unreachable today but a latent ungated-order risk, so it has been
    # removed. Any future MCP order path MUST route through the gated execution
    # layer rather than calling OpenAlgoClient.place_order directly.
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Config persistence endpoint — /ft-api/v1/config/openalgo
    # Accepts {api_key, host, port, ws_port} from the Setup wizard, persists
    # them to workspace.json, and hot-reloads app.config["CLIENT"] so no
    # process restart is needed.
    # ------------------------------------------------------------------
    # Registered at /v1/... (not /ft-api/v1/...) because the WSGI prefix
    # stripper normalises /ft-api/v1/X → /v1/X before URL dispatch, and the
    # Vite dev proxy does the same rewrite. So a single /v1/... registration
    # is reachable from both environments.
    openalgo_config_lock = threading.RLock()

    def _serialise_openalgo_config(handler: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(handler)
        def serialised(*args: Any, **kwargs: Any) -> Any:
            with openalgo_config_lock:
                return handler(*args, **kwargs)

        return serialised

    def _openalgo_config_request_authenticated() -> bool:
        auth_header = request.headers.get("Authorization", "")
        bearer = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else ""
        if bearer:
            try:
                from .auth_routes import decode_token  # noqa: PLC0415

                if decode_token(bearer).get("type") == "session":
                    return True
            except Exception:
                pass

        expected = os.environ.get("FLINTTRADE_API_KEY", "") or os.environ.get("OPENALGO_API_KEY", "")
        supplied = request.headers.get("X-API-Key") or bearer
        return bool(expected and supplied and secrets.compare_digest(str(supplied), expected))

    @app.route("/v1/config/openalgo", methods=["GET", "POST"])
    @limiter.limit("10 per minute")
    @_serialise_openalgo_config
    def _set_openalgo_config() -> Any:
        """Persist OpenAlgo connection settings from the UI.

        Security: this setup-exempt route remains loopback-only. Before the
        operator account exists, GET returns redacted metadata and POST must
        carry an explicit OpenAlgo API key. After setup, both methods require
        a session JWT or the configured backend/OpenAlgo API key; only an
        authenticated GET may return the raw key for the local WebSocket.

        Request JSON: ``{"api_key": "...", "host": "...", "port": 5000, "ws_port": 8765}``
        """
        def _coerce_port(value: Any, label: str) -> int:
            try:
                port_value = int(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{label} must be an integer") from exc
            if not 1 <= port_value <= 65535:
                raise ValueError(f"{label} must be between 1 and 65535")
            return port_value

        remote = request.remote_addr or ""
        if remote not in ("127.0.0.1", "::1", "localhost"):
            return jsonify({
                "status": "error",
                "message": "This endpoint is only reachable from localhost",
            }), 403

        authenticated = _openalgo_config_request_authenticated()
        auth_service = app.config.get("AUTH_SERVICE")
        try:
            operator_is_setup = bool(auth_service is None or auth_service.is_setup())
        except Exception:
            operator_is_setup = True
        if operator_is_setup and not authenticated:
            return jsonify({"status": "error", "message": "Authentication required"}), 401

        if request.method == "GET":
            try:
                from .workspace import Workspace  # noqa: PLC0415
                ws = Workspace()
                if not ws.config_path.exists():
                    ws.initialise()
                config = ws.as_dict()
                openalgo = config.get("openalgo") if isinstance(config, dict) else {}
                if not isinstance(openalgo, dict):
                    openalgo = {}
                api_key = str(openalgo.get("api_key", "") or "")
                data = {
                    "api_key_configured": bool(api_key),
                    "api_key_last4": api_key[-4:] if api_key else "",
                    "host": str(openalgo.get("host", "") or ""),
                    "port": openalgo.get("port", DEFAULT_OPENALGO_PORT),
                    "ws_port": openalgo.get("ws_port", DEFAULT_OPENALGO_WS_PORT),
                }
                # The terminal needs the bridge key in memory for its direct
                # OpenAlgo WebSocket. Only an authenticated operator session (or
                # explicit backend API key) may rehydrate it; pre-setup status
                # probes receive redacted metadata only.
                if authenticated:
                    data["api_key"] = api_key
                return jsonify({
                    "status": "success",
                    "data": data,
                }), 200
            except Exception as exc:
                logger.error("Failed to read OpenAlgo config from workspace.json: %s", exc)
                return jsonify({
                    "status": "error",
                    "message": "Could not read config",
                }), 500

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({
                "status": "error",
                "message": "Request body must be a JSON object",
            }), 400
        has_api_key = "api_key" in payload
        has_host = "host" in payload
        has_port = "port" in payload
        has_ws_port = "ws_port" in payload
        api_key = str(payload.get("api_key", "")).strip()
        host = str(payload.get("host", "")).strip()
        port = payload.get("port")
        ws_port = payload.get("ws_port")

        if not authenticated and (not has_api_key or not api_key):
            return jsonify({
                "status": "error",
                "message": "Initial OpenAlgo setup must include the API key",
            }), 401

        if not has_api_key and not has_host and not has_port and not has_ws_port:
            return jsonify({
                "status": "error",
                "message": "At least one of api_key, host, port, ws_port is required",
            }), 400

        try:
            normalised_port = _coerce_port(port, "port") if has_port else None
            normalised_ws_port = _coerce_port(ws_port, "ws_port") if has_ws_port else None
        except ValueError:
            # Fixed message — never echo exception text into a response.
            return jsonify({
                "status": "error",
                "message": "port and ws_port must be integers between 1 and 65535",
            }), 400

        # Persist to workspace.json
        try:
            from .workspace import Workspace  # noqa: PLC0415
            ws = Workspace()

            candidate: dict[str, Settings] = {}

            def update_openalgo(config: dict[str, Any]) -> None:
                current_openalgo = config.get("openalgo")
                openalgo = dict(current_openalgo) if isinstance(current_openalgo, dict) else {}
                if has_api_key:
                    openalgo["api_key"] = api_key
                if has_host:
                    openalgo["host"] = host
                if has_port:
                    openalgo["port"] = normalised_port
                if has_ws_port:
                    openalgo["ws_port"] = normalised_ws_port
                config["openalgo"] = openalgo
                candidate["settings"] = Settings.from_workspace_data(config)

            ws.update(update_openalgo)
            candidate_settings = candidate["settings"]
        except (TypeError, ValueError):
            return jsonify({
                "status": "error",
                "message": "OpenAlgo settings are invalid",
            }), 400
        except Exception as exc:
            logger.error("Failed to persist OpenAlgo config to workspace.json: %s", exc)
            return jsonify({
                "status": "error",
                "message": "Could not persist config",
            }), 500

        # Settings reads workspace.json directly; log the fresh UI-owned
        # settings for diagnostics without copying secrets into os.environ.
        try:
            _log_workspace_openalgo_overrides()
        except Exception:
            pass

        # Reconfigure the shared client in place. BrokerRouter, schedulers, cron
        # and Telegram all retain this object, so replacing/closing it would
        # strand live callers on stale credentials or a closed HTTP pool.
        old_client = app.config.get("CLIENT")
        old_settings = getattr(old_client, "settings", None)
        old_api_key_value = getattr(old_settings, "openalgo_api_key", "")
        old_api_key = old_api_key_value if isinstance(old_api_key_value, str) else ""
        try:
            new_settings = candidate_settings
            if isinstance(old_client, OpenAlgoClient):
                new_client = old_client.reconfigure(new_settings)
            else:
                new_client = OpenAlgoClient(new_settings)
            app.config["CLIENT"] = new_client
            app.config["OPENALGO_CLIENT"] = new_client
            if old_client is not new_client:
                configure_broker_router(app, registry, credential_store, new_client)
        except Exception as exc:
            diagnostic = _sanitise_tick_capture_error(exc, api_key)
            diagnostic = _sanitise_tick_capture_error(diagnostic, old_api_key)
            logger.warning(
                "OpenAlgo config saved but client reinitialisation failed: %s", diagnostic
            )
            return jsonify({
                "status": "partial",
                "message": "Config saved but client not reloaded",
            }), 200

        # The desktop and full-app boot paths both expose the active recorder on
        # app.config. Reconfigure it only after Settings and the REST client are
        # valid, so one save moves both transports to the same endpoint/key.
        with _tick_capture_lifecycle_lock(app):
            recorder = app.config.get("TICK_RECORDER")
            if recorder is not None:
                capture_reconfigured = False
                try:
                    # Register the new key with the desktop runtime before the
                    # recorder can use it or fail, so every diagnostic is redacted.
                    desktop_runtime = app.config.get("DESKTOP_TICK_CAPTURE_RUNTIME")
                    update_runtime_api_key = getattr(desktop_runtime, "update_api_key", None)
                    if callable(update_runtime_api_key):
                        update_runtime_api_key(new_settings.openalgo_api_key)

                    reconfigure_connection = getattr(recorder, "reconfigure_connection", None)
                    if not callable(reconfigure_connection):
                        raise RuntimeError("Tick recorder does not support connection reconfiguration")
                    reconfigure_connection(
                        ws_url=openalgo_ws_base_url(new_settings),
                        api_key=new_settings.openalgo_api_key,
                    )
                    capture_reconfigured = True
                    if app.config.get("TICK_RECORDER") is not recorder:
                        diagnostic = str(app.config.get("TICK_CAPTURE_ERROR", "") or "").strip()
                        if not diagnostic:
                            diagnostic = "Tick recorder stopped during connection reconfiguration"
                        diagnostic = _sanitise_tick_capture_error(diagnostic, new_settings.openalgo_api_key)
                        diagnostic = _sanitise_tick_capture_error(diagnostic, old_api_key)
                        app.config["TICK_CAPTURE_ERROR"] = diagnostic
                        logger.warning("OpenAlgo config saved after tick recorder stopped (%s)", diagnostic)
                        return jsonify({
                            "status": "partial",
                            "message": "OpenAlgo config saved and client reloaded, but tick capture reload was incomplete",
                            "data": {
                                "client_reloaded": True,
                                "tick_capture_reconfigured": False,
                            },
                        }), 200
                except Exception as exc:  # noqa: BLE001 - saved REST config remains usable
                    diagnostic = _sanitise_tick_capture_error(exc, new_settings.openalgo_api_key)
                    diagnostic = _sanitise_tick_capture_error(diagnostic, old_api_key)
                    app.config["TICK_CAPTURE_ERROR"] = diagnostic
                    logger.warning("OpenAlgo config saved but tick capture hot-reload failed (%s)", diagnostic)
                    return jsonify({
                        "status": "partial",
                        "message": "OpenAlgo config saved and client reloaded, but tick capture reload was incomplete",
                        "data": {
                            "client_reloaded": True,
                            "tick_capture_reconfigured": capture_reconfigured,
                        },
                    }), 200
                app.config["TICK_CAPTURE_ERROR"] = ""
            elif app.config.get("TICK_CAPTURE_ENABLED") and app.config.get("TICK_CAPTURE_ERROR"):
                return jsonify({
                    "status": "partial",
                    "message": "OpenAlgo config saved and client reloaded, but tick capture requires a restart",
                    "data": {
                        "client_reloaded": True,
                        "tick_capture_reconfigured": False,
                    },
                }), 200

        return jsonify({
            "status": "ok",
            "message": "OpenAlgo config saved and client reloaded",
        }), 200

    @app.route("/v1/config/llm", methods=["GET", "POST"])
    @limiter.limit("10 per minute")
    def _llm_config() -> Any:
        """Persist redacted LLM settings from the UI."""
        remote = request.remote_addr or ""
        if remote not in ("127.0.0.1", "::1", "localhost"):
            return jsonify({
                "status": "error",
                "message": "This endpoint is only reachable from localhost",
            }), 403

        try:
            from .llm_config import persist_llm_config, read_llm_config  # noqa: PLC0415

            if request.method == "GET":
                return jsonify({"status": "success", "data": read_llm_config()}), 200

            payload = request.get_json(silent=True) or {}
            data = persist_llm_config(payload)
            return jsonify({
                "status": "ok",
                "message": "LLM config saved",
                "data": data,
            }), 200
        except ValueError as exc:
            logger.warning("Invalid LLM config payload: %s", exc)
            return jsonify({
                "status": "error",
                "message": "At least one of provider, host, model, api_key is required",
            }), 400
        except Exception as exc:
            logger.error("Failed to persist LLM config: %s", exc)
            return jsonify({
                "status": "error",
                "message": "Could not persist LLM config",
            }), 500

    # ------------------------------------------------------------------
    # Connection-test endpoint — /ft-api/v1/test-connection
    # Used by the Setup wizard + Settings › Connection. The browser cannot
    # call OpenAlgo's /api/v1/ping directly because OpenAlgo does not send
    # CORS headers for our origin (and we will not modify OpenAlgo). We
    # proxy the test through our backend so it runs server-to-server with
    # no CORS involvement.
    # ------------------------------------------------------------------
    @app.route("/v1/test-connection", methods=["POST"])
    @limiter.limit("10 per minute")
    def _test_openalgo_connection() -> Any:
        """Server-side OpenAlgo connectivity + auth test.

        Accepts the exact ``{host, api_key}`` the user typed in the wizard,
        pings OpenAlgo, and returns a structured result. HTTP status is
        always 200 — the real outcome lives in the JSON body so the
        frontend can distinguish reachable/unreachable/auth-failed without
        tripping on HTTP error handling.
        """
        remote = request.remote_addr or ""
        if remote not in ("127.0.0.1", "::1", "localhost"):
            return jsonify({
                "status": "error",
                "message": "This endpoint is only reachable from localhost",
            }), 403

        payload = request.get_json(silent=True) or {}
        # Strip one or more trailing slashes; setup wizard sometimes posts
        # the host with "/" or "//".
        host = str(payload.get("host", "")).strip().rstrip("/")
        api_key = str(payload.get("api_key", "")).strip()

        if not host or not api_key:
            return jsonify({
                "status": "error",
                "message": "host and api_key are required",
            }), 400

        import httpx as _httpx  # noqa: PLC0415

        try:
            resp = _httpx.post(
                f"{host}/api/v1/ping",
                json={"apikey": api_key},
                timeout=5.0,
            )
        except (_httpx.ConnectError, _httpx.ConnectTimeout) as exc:
            logger.warning("OpenAlgo connection test could not reach configured host: %s", exc)
            return jsonify({
                "status": "error",
                "reachable": False,
                "message": "Cannot reach OpenAlgo at the configured host",
            }), 200
        except _httpx.TimeoutException:
            return jsonify({
                "status": "error",
                "reachable": False,
                "message": f"OpenAlgo at {host} did not respond within 5s",
            }), 200
        except Exception:  # noqa: BLE001
            return jsonify({
                "status": "error",
                "reachable": False,
                "message": "Connection test failed",
            }), 200

        if resp.status_code == 200:
            broker = "unknown"
            try:
                data = resp.json()
                if isinstance(data, dict):
                    broker = data.get("data", {}).get("broker") or data.get("broker") or "unknown"
            except Exception:  # noqa: BLE001
                pass
            return jsonify({
                "status": "ok",
                "reachable": True,
                "authenticated": True,
                "broker": broker,
                "message": f"Connected — broker: {broker}",
            }), 200

        if resp.status_code in (401, 403):
            msg = "Invalid API key"
            try:
                body = resp.json()
                if isinstance(body, dict):
                    msg = body.get("message", msg)
            except Exception:  # noqa: BLE001
                pass
            return jsonify({
                "status": "error",
                "reachable": True,
                "authenticated": False,
                "http_status": resp.status_code,
                "message": f"Reachable but auth failed (HTTP {resp.status_code}): {msg}",
            }), 200

        return jsonify({
            "status": "error",
            "reachable": True,
            "authenticated": False,
            "http_status": resp.status_code,
            "message": f"OpenAlgo returned unexpected HTTP {resp.status_code}",
        }), 200

    # ------------------------------------------------------------------
    # SPA fallback — registered LAST so it only matches unclaimed routes.
    # Returns 404 for API paths (so unknown /api/ or /v1/ endpoints still
    # look like 404s to clients) and serves the React bundle for every
    # other path.  Matches at most one path segment so deep React-router
    # paths like `/trade/scalper` all fall through to index.html.
    # ------------------------------------------------------------------
    if _frontend_available:
        from flask import Response as _Response, send_from_directory  # noqa: PLC0415
        from werkzeug.utils import safe_join as _safe_join  # noqa: PLC0415

        _API_PREFIXES = ("/api/", "/ft-api/", "/v1/")

        def _serve_index_with_nonce() -> Any:
            """Serve index.html with the per-request CSP nonce woven into <script> tags.

            The matching ``'nonce-…'`` is added to the response's CSP header by
            ``_add_security_headers``; together they let the bootstrap script run under a
            nonce-based policy that forbids inline scripts (DS-CSP-01/09).
            """
            html = _dist_index.read_text(encoding="utf-8")
            nonce = getattr(_flask_g, "csp_nonce", None)
            if nonce:
                html = _inject_csp_nonce(html, nonce)
            return _Response(html, mimetype="text/html")

        @app.route("/", defaults={"path": ""}, endpoint="_spa_fallback")
        @app.route("/<path:path>", endpoint="_spa_fallback")
        def _spa_fallback(path: str) -> Any:
            """Serve the React SPA for any non-API path."""
            # API paths must never be intercepted — let Flask 404 them.
            req_path = request.path
            if any(req_path.startswith(p) for p in _API_PREFIXES):
                return jsonify({
                    "status": "error",
                    "message": "Not found",
                }), 404

            # If the exact file exists under dist/, serve it (favicon, assets/*).
            if path:
                try:
                    joined = _safe_join(str(_dist_path), path)
                    if joined is None:
                        return jsonify({
                            "status": "error",
                            "message": "Not found",
                        }), 404
                    # Guard against path traversal: resolved path must be
                    # inside _dist_path.
                    resolved = Path(joined).resolve()
                    if (
                        resolved.is_file()
                        and _dist_path.resolve() in resolved.parents
                    ):
                        relative = resolved.relative_to(_dist_path.resolve())
                        return send_from_directory(
                            str(_dist_path), str(relative)
                        )
                except Exception:
                    pass

            # Otherwise serve index.html (SPA client-side routing) with the CSP nonce.
            return _serve_index_with_nonce()

    return app


def _run_flask_server(app: Flask, port: int = 5100) -> None:
    """Run the Flask API server in a daemon thread.

    Uses Waitress — a pure-Python, cross-platform production WSGI server
    (works identically on Windows, macOS, Linux).  Replaces Flask's
    built-in Werkzeug dev server, which emits a loud "this is a
    development server" warning and is not production-safe.

    Args:
        app: Flask application instance.
        port: Port to bind (default 5100).
    """
    try:
        from waitress import serve as _waitress_serve  # noqa: PLC0415
    except ImportError:
        # Graceful fallback if waitress isn't installed — still works
        # for local dev, just prints the dev-server warning.
        logger.warning(
            "Waitress not installed; falling back to Werkzeug dev server. "
            "Install with: pip install waitress"
        )

        def _run() -> None:
            app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
    else:
        # Quiet Waitress's per-request access log — our structlog middleware
        # already logs requests via the traffic logger at a structured level.
        logging.getLogger("waitress").setLevel(logging.WARNING)

        def _run() -> None:
            # ident="FlintTrade" sets the Server: header instead of "waitress".
            # threads=8 is enough for a single-user dev/desktop setup.
            _waitress_serve(
                app,
                host="127.0.0.1",
                port=port,
                ident="FlintTrade",
                threads=8,
            )

    thread = threading.Thread(target=_run, name="flinttrade-api", daemon=True)
    thread.start()
    logger.info("FlintTrade API server started on http://127.0.0.1:%d", port)

    # Arm the daily session-refresh jobs (G5) — started here, on the serve path
    # only, so create_flask_app stays side-effect-light for tests.
    rotation_scheduler = app.config.get("ROTATION_SCHEDULER")
    if rotation_scheduler is not None and not getattr(rotation_scheduler, "running", False):
        try:
            rotation_scheduler.start()
            logger.info("Native session-refresh scheduler started (08:05 IST daily)")
        except Exception as exc:  # noqa: BLE001 - rotation must never block serving
            logger.warning("Session-refresh scheduler failed to start: %s", exc)


def _shutdown_rotation_scheduler(app: Flask) -> None:
    """Stop the native-session rotation owner when it was started."""
    rotation_scheduler = app.config.get("ROTATION_SCHEDULER")
    if rotation_scheduler is None or not getattr(rotation_scheduler, "running", False):
        return
    rotation_scheduler.shutdown(wait=False)


def _market_calendar_refresh_delay(*, loaded: bool) -> float:
    """Return seconds until the next calendar refresh or short failure retry."""
    if not loaded:
        return 300.0

    from datetime import datetime, timedelta  # noqa: PLC0415
    from zoneinfo import ZoneInfo  # noqa: PLC0415

    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    refresh_at = now.replace(hour=0, minute=5, second=0, microsecond=0)
    if refresh_at <= now:
        refresh_at += timedelta(days=1)
    return max(1.0, (refresh_at - now).total_seconds())


def _current_market_calendar_year() -> int:
    """Return the current exchange-calendar year in IST."""
    from datetime import datetime  # noqa: PLC0415
    from zoneinfo import ZoneInfo  # noqa: PLC0415

    return datetime.now(ZoneInfo("Asia/Kolkata")).year


class FlintTradeApp:
    """Main application — creates and wires all FlintTrade subsystems.

    Startup is resilient: if OpenAlgo is unreachable or optional services
    (Telegram, AI) are not configured, the app starts with warnings
    instead of crashing.

    Usage::

        app = FlintTradeApp()
        app.run()  # blocking — runs until Ctrl+C or SIGTERM
    """

    def __init__(self) -> None:
        self.version = _read_version()

        # Audit logger first — must be available before anything else
        self.audit = AuditLogger()
        self.audit.log_event("APP_START", version=self.version)

        # Core — settings + API client
        self.settings = Settings.from_env()
        self.client = OpenAlgoClient(self.settings)

        # Engine — safety + scheduler (deferred to avoid circular import
        # between core↔engine at module level). Live order dispatch is the
        # gateway BrokerRouter (gate_order → BrokerRouter → adapter); the legacy
        # ungated OrderRouter was removed 2026-07-09.
        from flinttrade_engine.safety import SafetyConfig, SafetySystem  # noqa: PLC0415
        from flinttrade_engine.scheduler import (  # noqa: PLC0415
            CronStrategyScheduler,
            StrategyScheduler,
            TimeScheduler,
        )

        self.safety = SafetySystem(SafetyConfig(check_market_hours=True))
        self.time_scheduler = TimeScheduler(client=self.client)
        self.scheduler = StrategyScheduler(
            client=self.client,
            time_scheduler=self.time_scheduler,
        )
        self.strategy_cron_scheduler = CronStrategyScheduler(
            time_scheduler=self.time_scheduler,
        )

        # Automation — cron manager (lazy import avoids loading APScheduler at
        # module level, which accounts for ~0.3 s of the startup penalty).
        from flinttrade_automation.cron_manager import CronManager  # noqa: PLC0415

        self.cron = CronManager(
            openalgo_client=self.client,
            audit_logger=self.audit,
        )

        # Automation — Telegram bot (optional — token may not be set).
        # Lazy import avoids pulling in the python-telegram-bot dependency
        # (and its event-loop initialisation) until it is actually needed.
        from flinttrade_automation.telegram_bot import TelegramBot  # noqa: PLC0415

        self.telegram = TelegramBot(
            client=self.client,
            safety_system=self.safety,
            scheduler=self.scheduler,
            audit_logger=self.audit,
        )
        # Wire Telegram into cron so jobs can send alerts
        self.cron.telegram_bot = self.telegram

        # Gateway — broker registry + credential store + contract manager
        flinttrade_dir = _workspace_dir()
        master_password = _get_master_password()
        self.credential_store = CredentialStore(
            flinttrade_dir / "credentials.db", master_password
        )
        contracts_dir = flinttrade_dir / "contracts"
        contracts_dir.mkdir(exist_ok=True)
        self.contract_manager = ContractManager(contracts_dir)
        self.registry = BrokerRegistry()

        # RAG — knowledge base (persistent).
        # LLMClient and RAGPipeline are imported lazily here to avoid loading
        # ChromaDB, sentence-transformers, and the LLM HTTP client at module
        # level, which would add 2-5 s to startup time even when the AI
        # features are not yet used.
        self.rag = _initialise_rag_runtime(flinttrade_dir)

        # Live tick capture (opt-in via FLINTTRADE_TICK_CAPTURE) — wired in start().
        self._tick_recorder: Any | None = None
        self._tick_recorder_task: Any | None = None
        self._tick_storage: Any | None = None
        self._tick_storage_lock: Any | None = None
        self._orderflow_checkpoint_owner: _OrderFlowCheckpointOwner | None = None
        self._flask_app: Flask | None = None
        self._stop_started = False
        self._stop_completed = False
        self._shutdown_task: asyncio.Task[Any] | None = None
        self._shutdown_request_task: asyncio.Task[Any] | None = None
        self._holiday_refresh_task: asyncio.Task[Any] | None = None
        self._start_claim_lock = threading.Lock()
        self._start_claimed = False
        self._calendar_loaded = False
        self._calendar_runtime_ready = False
        self._calendar_schedulers_started = False
        self._strategy_cron_started = False
        self._cron_jobs_registered = False
        self._cron_started = False

        # Broker reconciliation runner (contract §14.2) — wired in start().
        self._reconciliation_runner: Any | None = None
        self._reconciliation_task: Any | None = None

        self._stop_event = asyncio.Event()
        self._shutdown_failed_event = asyncio.Event()

        logger.info("FlintTradeApp initialised — %s", self.version)

    async def _refresh_market_calendar(self) -> bool:
        """Refresh and apply one authoritative market-calendar payload."""
        calendar_year = _current_market_calendar_year()
        before_generation = getattr(self.cron, "holiday_generation", None)
        before_year = getattr(self.cron, "holiday_year", None)
        fail_closed = before_year != calendar_year
        calendar_invalidated = False
        if self._calendar_loaded and fail_closed:
            self._fail_closed_calendar_year(calendar_year)
            calendar_invalidated = True
        try:
            await self.cron.load_holidays()
        except Exception as exc:
            logger.warning("Could not load holidays (OpenAlgo may be starting): %s", exc)
            if fail_closed and not calendar_invalidated:
                self._fail_closed_calendar_year(calendar_year)
            return False

        if self._stop_started:
            return False

        after_generation = getattr(self.cron, "holiday_generation", None)
        loaded_year = getattr(self.cron, "holiday_year", None)
        fresh_generation = (
            isinstance(before_generation, int)
            and isinstance(after_generation, int)
            and after_generation > before_generation
        )
        if not fresh_generation or loaded_year != calendar_year:
            logger.warning(
                "Market calendar refresh did not produce current-year authority; retaining a fail-closed year"
            )
            if fail_closed and not calendar_invalidated:
                self._fail_closed_calendar_year(calendar_year)
            return False

        calendar_payload = getattr(self.cron, "holiday_payload", None)
        if not isinstance(calendar_payload, dict | list | tuple | set):
            logger.warning(
                "Market calendar was not returned; retaining the current calendar until retry"
            )
            return False
        try:
            self.time_scheduler.set_holidays(
                calendar_payload,
                year=str(calendar_year),
            )
        except Exception as exc:
            logger.warning("Could not apply loaded market holidays: %s", exc)
            self._fail_closed_calendar_year(calendar_year)
            return False
        self._calendar_loaded = True
        if self._calendar_runtime_ready:
            self._start_calendar_schedulers()
        return True

    def _fail_closed_calendar_year(self, year: int) -> None:
        """Block calendar-gated work until an authoritative year is loaded."""
        blocked_dates = self.cron.fail_closed_calendar_year(year)
        self._calendar_loaded = False
        try:
            self.time_scheduler.set_holidays(blocked_dates, year=str(year))
        except Exception as exc:
            logger.error("Could not apply fail-closed market calendar: %s", exc)
            if self._strategy_cron_started:
                self.strategy_cron_scheduler.stop()
                self._strategy_cron_started = False
                self._calendar_schedulers_started = False

    def _start_calendar_schedulers(self) -> None:
        """Start market-sensitive schedulers after an authoritative calendar."""
        if self._calendar_schedulers_started or not self._calendar_loaded:
            return
        if not self._strategy_cron_started:
            self.strategy_cron_scheduler.start()
            self._strategy_cron_started = True
        if not self._cron_jobs_registered:
            self.cron.register_builtin_jobs()
            self._cron_jobs_registered = True
        if not self._cron_started:
            self.cron.start()
            self._cron_started = True
        self._calendar_schedulers_started = (
            self._strategy_cron_started
            and self._cron_jobs_registered
            and self._cron_started
        )

    async def _market_calendar_refresh_loop(self, *, loaded: bool) -> None:
        """Retry failed loads promptly and refresh successful calendars daily."""
        while True:
            delay = _market_calendar_refresh_delay(loaded=loaded)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
                return
            except TimeoutError:
                loaded = await self._refresh_market_calendar()

    async def start(self) -> None:
        """Start all services and wait until stopped."""
        start_claim_lock = getattr(self, "_start_claim_lock", None)
        if start_claim_lock is None:
            start_claim_lock = threading.Lock()
            self._start_claim_lock = start_claim_lock
        with start_claim_lock:
            if getattr(self, "_start_claimed", False):
                raise RuntimeError("FlintTrade runtime already started")
            self._start_claimed = True

        if await self._wait_for_shutdown_if_started():
            return

        from .smart_order_routes import start_smart_order_jobs  # noqa: PLC0415

        if not start_smart_order_jobs():
            raise RuntimeError("an earlier smart-order runtime still owns a worker")

        # Start FlintTrade API server (Flask, configurable loopback port).
        flask_app = create_flask_app(
            safety=self.safety,
            scheduler=self.scheduler,
            cron=self.cron,
            audit=self.audit,
            client=self.client,
            registry=self.registry,
            credential_store=self.credential_store,
            contract_manager=self.contract_manager,
            rag=self.rag,
            cron_strategy_scheduler=self.strategy_cron_scheduler,
            time_scheduler=self.time_scheduler,
        )
        self._flask_app = flask_app
        _bind_runtime_emergency_dispatcher(
            flask_app,
            self.safety,
            self.telegram,
            self.client,
        )
        # Start polling only after /kill owns a current-router dispatcher. This
        # is a no-op unless Telegram has a token and authorised chat id.
        if self.telegram is not None:
            self.telegram.start_background()
        tick_capture_enabled = _tick_capture_enabled()
        _set_tick_capture_intent(flask_app, tick_capture_enabled)
        _run_flask_server(flask_app, port=_resolve_backend_port())

        # Load the market calendar once, then keep retrying failed loads and
        # refresh it daily so year rollover and newly-published sessions apply.
        calendar_loaded = await self._refresh_market_calendar()

        if await self._wait_for_shutdown_if_started():
            return

        self._holiday_refresh_task = asyncio.create_task(
            self._market_calendar_refresh_loop(loaded=calendar_loaded)
        )

        # Hand the cron manager the shared trade store (created by the Flask
        # factory above) so the nightly DuckDB maintenance job can CHECKPOINT +
        # ANALYZE the same connection under its lock.
        self.cron.trade_storage = flask_app.config.get("TRADE_STORAGE")
        self.cron.trade_storage_lock = flask_app.config.get("TRADE_STORAGE_LOCK")

        # Wire the "optimise overnight" feature to a real engine. The cron slot
        # (make_overnight_optimise_job) existed but nothing injected an optimiser,
        # so the nightly job never ran. Build an OvernightOptimiser over the
        # registered strategies + a rule-based StrategyRefiner and inject its
        # run() as the job. Best-effort: a missing runner/refiner just leaves the
        # job unregistered (as before) rather than failing boot.
        try:
            from flinttrade_ai.optimiser_report_store import OptimiserReportStore  # noqa: PLC0415
            from flinttrade_ai.overnight_optimiser import (  # noqa: PLC0415
                OvernightOptimiser,
                enrich_strategies,
            )
            from flinttrade_ai.strategy_refiner import StrategyRefiner  # noqa: PLC0415
            from flinttrade_backtest.result_store import BacktestResultStore  # noqa: PLC0415

            # The report store is created unconditionally so the Lab UI can read
            # past reports even when the optimiser isn't wired this boot.
            _report_store = OptimiserReportStore(_workspace_dir() / "optimiser-reports")
            flask_app.config["OPTIMISER_REPORT_STORE"] = _report_store

            # Per-strategy backtest-results store: written on every backtest run
            # (backtest_routes), read here so the optimiser refines on REAL
            # metrics instead of an empty dict. Before this the refiner only ever
            # saw {} and produced generic rule-based output (R16).
            _bt_result_store = BacktestResultStore(_workspace_dir() / "backtest-results")
            flask_app.config["BACKTEST_RESULT_STORE"] = _bt_result_store

            _runner = flask_app.config.get("STRATEGY_RUNNER")

            def _strategy_provider() -> list[dict[str, Any]]:
                """Live roster joined to each strategy's latest backtest metrics."""
                roster: list[dict[str, Any]] = []
                if _runner is not None and hasattr(_runner, "list_strategies"):
                    try:
                        roster = _runner.list_strategies()
                    except Exception:  # noqa: BLE001 - a broken runner falls back to stored-only
                        roster = []
                return enrich_strategies(roster, _bt_result_store)

            # Wired unconditionally now: even with no uploaded strategies, any
            # strategy that has been backtested gets refined overnight.
            _optimiser = OvernightOptimiser(
                strategy_provider=_strategy_provider,
                refiner=StrategyRefiner(),  # rule-based by default (no LLM required)
                report_sink=_report_store.write,  # persist each night's report
            )
            self.cron.overnight_optimiser = _optimiser.run
        except Exception as exc:
            logger.warning("Overnight optimiser not wired (%s); nightly optimisation will not run", exc)

        # EOD historical-data auto-sync (opt-in via workspace.json
        # data.auto_sync.enabled). Reuses the SAME start_watchlist_download core
        # the Settings download button calls — one download path.
        if _auto_sync_enabled():
            try:
                from datetime import date as _date  # noqa: PLC0415
                from datetime import timedelta as _timedelta  # noqa: PLC0415

                from flinttrade_historical.watchlist_routes import (  # noqa: PLC0415
                    start_watchlist_download,
                )

                lookback = _auto_sync_lookback_days()

                def _start_eod_sync() -> Any:
                    today = _date.today()
                    return start_watchlist_download(today - _timedelta(days=lookback), today)

                self.cron.eod_sync_starter = _start_eod_sync
                logger.info("EOD auto-sync wired (lookback %d days)", lookback)
            except Exception as exc:
                logger.warning("EOD auto-sync not wired (%s); scheduled sync will not run", exc)

        # Scheduled LightGBM/EMA signal source. The app factory has already
        # connected its output to the canonical rule+ML signal hub. Registering
        # here places the cycle under the same observable CronManager as every
        # other background job and keeps it fail-closed outside NSE hours.
        try:
            _wire_ml_signal_runtime(flask_app, self.cron, self.time_scheduler)
        except Exception as exc:
            logger.warning("Scheduled ML signals not wired (%s)", exc)

        # Register built-in cron jobs AND start the scheduler. Without start()
        # APScheduler never runs, so none of the built-in jobs fire — the
        # nightly DuckDB CHECKPOINT+ANALYZE (db_optimise_job), square-off
        # warning, EOD logout, and health check were all inert. Wrapped so a
        # missing/broken APScheduler degrades to "no cron" instead of failing
        # the whole boot.
        self._calendar_runtime_ready = True
        if calendar_loaded:
            try:
                self._start_calendar_schedulers()
            except Exception as exc:
                logger.warning(
                    "Calendar-owned schedulers failed to start (%s); scheduled jobs will not run",
                    exc,
                )
        else:
            logger.warning(
                "Market calendar unavailable; market-sensitive schedulers remain disarmed until retry"
            )

        # Live tick capture (opt-in). Uses its OWN StorageManager (a separate
        # DuckDB file) so the recorder's async-loop writes never share a
        # connection with the Flask-thread trade journal (DuckDB connections are
        # not safe for concurrent use). Launched as a background task on this
        # loop; auto-reconnects to the OpenAlgo WebSocket.
        if tick_capture_enabled:
            tick_storage: Any | None = None
            recorder: Any | None = None
            recorder_task: asyncio.Task[Any] | None = None
            checkpoint_owner: _OrderFlowCheckpointOwner | None = None
            try:
                from flinttrade_data.storage import StorageManager as _TickStore  # noqa: PLC0415
                from flinttrade_data.tick_recorder import TickRecorder  # noqa: PLC0415

                tick_db = str(_workspace_dir() / "ticks.duckdb")
                tick_storage = _TickStore(tick_db)
                tick_storage.initialise()
                # One lock guards this tick store's single DuckDB connection: the
                # recorder writes on the async loop, the nightly db_optimise job
                # CHECKPOINTs it on the scheduler thread. Both must serialise.
                tick_lock = threading.Lock()
                # Live order-flow aggregator: fed from each tick and exposed to
                # the orderflow route so the footprint widget shows REAL buy/sell
                # delta (not synthetic) while tick capture is running.
                from flinttrade_data.orderflow_aggregator import (  # noqa: PLC0415
                    create_live_market_orderflow_aggregator,
                )

                orderflow = create_live_market_orderflow_aggregator()
                with _tick_capture_lifecycle_lock(flask_app):
                    # The Flask server is already accepting local setup requests.
                    # Refresh inside the lifecycle lock so a concurrent config save
                    # either precedes this build or reconfigures the published recorder.
                    capture_settings = Settings.from_env()
                    watchlist = _tick_capture_watchlist()
                    signal_hub = flask_app.config.get("SIGNAL_HUB")
                    restore_summary = _prepare_tick_orderflow_state(
                        tick_storage,
                        orderflow,
                        watchlist,
                        storage_lock=tick_lock,
                        retention_days=90,
                    )
                    checkpoint_owner = _OrderFlowCheckpointOwner(
                        tick_storage,
                        orderflow,
                        workspace_dir=_workspace_dir(),
                        storage_lock=tick_lock,
                    )
                    recorder = _build_tick_recorder(
                        recorder_factory=TickRecorder,
                        signal_hub=signal_hub,
                        settings=capture_settings,
                        storage=tick_storage,
                        storage_lock=tick_lock,
                        orderflow=orderflow,
                        watchlist=watchlist,
                        mode=_tick_capture_mode(),
                        post_flush_callback=checkpoint_owner.persist_locked,
                    )
                    recorder_task = asyncio.create_task(recorder.run())
                    self._tick_recorder = recorder
                    self._tick_recorder_task = recorder_task
                    self._tick_storage = tick_storage
                    self._tick_storage_lock = tick_lock
                    self._orderflow_checkpoint_owner = checkpoint_owner
                    # Hand the tick store to the cron so nightly maintenance keeps the
                    # highest-volume DuckDB file from growing unbounded. register_
                    # builtin_jobs already ran, but the job resolves this lazily.
                    self.cron.tick_storage = tick_storage
                    self.cron.tick_storage_lock = tick_lock
                    # Keep ~90 days of ticks by default so the store stays bounded;
                    # the nightly tick_retention_job prunes older rows.
                    self.cron.tick_retention_days = 90
                    # Expose the recorder + store to the tick routes (status /
                    # query / watchlist) so the terminal can see and manage capture.
                    flask_app.config["ORDERFLOW_AGGREGATOR"] = orderflow
                    flask_app.config["TICK_RECORDER"] = recorder
                    flask_app.config["TICK_STORAGE"] = tick_storage
                    flask_app.config["TICK_STORAGE_LOCK"] = tick_lock
                    flask_app.config["TICK_CAPTURE_ERROR"] = ""
                    def handle_recorder_completion(
                        completed: Any,
                        active: Any = recorder,
                        key: str = capture_settings.openalgo_api_key,
                    ) -> None:
                        def unpublish_runtime_handles() -> None:
                            self._tick_recorder_task = None
                            self.cron.tick_storage = None
                            self.cron.tick_storage_lock = None

                        def clear_closed_storage() -> None:
                            self._tick_recorder = None
                            self._tick_storage = None
                            self._tick_storage_lock = None
                            self._orderflow_checkpoint_owner = None

                        _handle_tick_recorder_completion(
                            flask_app,
                            active,
                            completed,
                            api_key=key,
                            is_shutting_down=lambda: self._stop_started,
                            on_unpublished=unpublish_runtime_handles,
                            before_storage_close=(
                                lambda: checkpoint_owner.persist(force=True)
                                if checkpoint_owner is not None
                                else None
                            ),
                            on_storage_closed=clear_closed_storage,
                        )

                    recorder_task.add_done_callback(handle_recorder_completion)
                logger.info(
                    "Live tick capture started → %s (pruned=%d restored=%d restore_failures=%d)",
                    tick_db,
                    restore_summary["pruned_ticks"],
                    restore_summary["restored_ticks"],
                    restore_summary["restore_failures"],
                )
            except Exception as exc:
                sanitise_error = getattr(recorder, "sanitise_error", None)

                def sanitise_rollback_error(error: Any) -> str:
                    try:
                        if callable(sanitise_error):
                            return sanitise_error(error)
                    except Exception:
                        pass
                    return _sanitise_tick_capture_error(error, self.settings.openalgo_api_key)

                diagnostic = sanitise_rollback_error(exc)
                with _tick_capture_lifecycle_lock(flask_app):
                    self.cron.tick_storage = None
                    self.cron.tick_storage_lock = None
                    self._tick_recorder = None
                    self._tick_recorder_task = None
                    self._tick_storage = None
                    self._tick_storage_lock = None
                    self._orderflow_checkpoint_owner = None
                    for key in ("TICK_RECORDER", "TICK_STORAGE", "TICK_STORAGE_LOCK", "ORDERFLOW_AGGREGATOR"):
                        flask_app.config.pop(key, None)
                    flask_app.config["TICK_CAPTURE_ERROR"] = diagnostic
                logger.warning("Tick capture failed to start (%s); not recording ticks", diagnostic)

                if recorder_task is not None:
                    recorder.stop()
                    recorder_task.cancel()
                    try:
                        with suppress(asyncio.CancelledError):
                            await recorder_task
                    except Exception as cleanup_exc:
                        logger.warning(
                            "Tick recorder rollback failed (%s)",
                            sanitise_rollback_error(cleanup_exc),
                        )
                if tick_storage is not None:
                    try:
                        tick_storage.close()
                    except Exception as cleanup_exc:
                        logger.warning(
                            "Tick storage rollback failed (%s)",
                            sanitise_rollback_error(cleanup_exc),
                        )

        if await self._wait_for_shutdown_if_started():
            return

        # Broker reconciliation runner (contract §14.2): reconciles every ACTIVE
        # native (adapter, session) pair on start and then every
        # Capabilities.reconcile_recommended_seconds — persisting JSONL under
        # <home>/reconciliation/<broker>/<account>.jsonl and auditing
        # RECONCILIATION_MISMATCH on drift. Launched as a background task on
        # this loop (mirrors the tick recorder): never blocks boot, polls so
        # sessions established after boot are picked up, cancelled in stop().
        try:
            _reconcile_targets = flask_app.config.get("RECONCILE_TARGETS")
            if _reconcile_targets is not None:
                from flinttrade_engine.reconciliation_runner import ReconciliationRunner  # noqa: PLC0415

                _reconciler = ReconciliationRunner(_reconcile_targets, audit_logger=self.audit)
                self._reconciliation_runner = _reconciler
                self._reconciliation_task = asyncio.create_task(_reconciler.run())
                # Exposed on app.config for observability/manual-trigger routes.
                flask_app.config["RECONCILIATION_RUNNER"] = _reconciler
            else:
                logger.info(
                    "Reconciliation runner inactive — broker routing was not built this boot"
                )
        except Exception as exc:
            logger.warning(
                "Reconciliation runner failed to start (%s); broker reconciliation inactive", exc
            )

        # Broker SDK attestation — log which native broker SDKs match brokers.lock
        # so the operator can see what is / isn't ready to go live. No native
        # adapter is wired into the router yet, so this is informational here;
        # the halt loop (attest_loop + on_failure) is ready for when they are.
        try:
            from .broker_sdk_attest import attest_all, log_report  # noqa: PLC0415

            log_report(attest_all())
        except Exception as exc:  # pragma: no cover - never let attestation break boot
            logger.warning("Broker SDK attestation failed (%s)", exc)

        # Verify OpenAlgo connectivity (non-fatal). Distinguish three
        # cases so the boot log is not misleading: REACHABLE_AUTHENTICATED,
        # REACHABLE_AUTH_FAILED, UNREACHABLE.
        try:
            import httpx  # noqa: PLC0415
            from .exceptions import OpenAlgoAuthError  # noqa: PLC0415

            try:
                result = await self.client.ping()
                broker = (
                    result.get("data", {}).get("broker", "unknown")
                    if isinstance(result, dict)
                    else "unknown"
                )
                logger.info(
                    "FlintTrade %s started — OpenAlgo %s REACHABLE, authenticated (broker: %s)",
                    self.version, self.settings.openalgo_host, broker,
                )
            except OpenAlgoAuthError as exc:
                # Server responded but rejected the API key — reachable,
                # auth failed.  Don't confuse users with "UNREACHABLE".
                logger.warning(
                    "FlintTrade %s started — OpenAlgo %s REACHABLE but AUTH FAILED "
                    "(status %d): %s. Configure the API key in /setup or ~/.flinttrade/workspace.json.",
                    self.version,
                    self.settings.openalgo_host,
                    exc.status_code,
                    exc.message,
                )
            except (httpx.ConnectError, httpx.TimeoutException, OSError) as exc:
                logger.warning(
                    "FlintTrade %s started — OpenAlgo %s UNREACHABLE (%s: %s). "
                    "Start OpenAlgo on that host/port and FlintTrade will reconnect on next call.",
                    self.version,
                    self.settings.openalgo_host,
                    type(exc).__name__,
                    exc,
                )
        except Exception as exc:
            # Any other unexpected error — log full class + message so we
            # don't pretend we know what happened.
            logger.warning(
                "FlintTrade %s started — OpenAlgo %s verification failed (%s: %s).",
                self.version,
                self.settings.openalgo_host,
                type(exc).__name__,
                exc,
            )

        # Wait for either successful teardown or a fail-closed shutdown error.
        await self._wait_for_shutdown_result()

    async def _wait_for_shutdown_result(self) -> None:
        """Wait for shutdown completion and propagate a failed attempt."""
        failed_event = getattr(self, "_shutdown_failed_event", None)
        if failed_event is None:
            failed_event = asyncio.Event()
            self._shutdown_failed_event = failed_event
        stopped = asyncio.create_task(self._stop_event.wait())
        failed = asyncio.create_task(failed_event.wait())
        try:
            await asyncio.wait(
                {stopped, failed},
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for waiter in (stopped, failed):
                if not waiter.done():
                    waiter.cancel()
            await asyncio.gather(stopped, failed, return_exceptions=True)
        if failed_event.is_set():
            shutdown_task = getattr(self, "_shutdown_task", None)
            if shutdown_task is not None:
                await asyncio.shield(shutdown_task)
            raise RuntimeError("shutdown failed before completion")

    async def _wait_for_shutdown_if_started(self) -> bool:
        """Let an in-progress stop retain ownership across startup await points."""
        if not self._stop_started:
            return False
        await self._wait_for_shutdown_result()
        return True

    async def stop(self) -> None:
        """Gracefully shut down all services, sharing concurrent attempts."""
        if getattr(self, "_stop_completed", False):
            return

        task = getattr(self, "_shutdown_task", None)
        if task is None or task.done():
            failed_event = getattr(self, "_shutdown_failed_event", None)
            if failed_event is None:
                failed_event = asyncio.Event()
                self._shutdown_failed_event = failed_event
            failed_event.clear()
            task = asyncio.create_task(self._stop_once())
            self._shutdown_task = task
        try:
            await asyncio.shield(task)
        except Exception:
            self._shutdown_failed_event.set()
            raise

    async def _stop_once(self) -> None:
        """Run one complete, best-effort shutdown attempt."""
        self._stop_started = True
        flask_app = getattr(self, "_flask_app", None)
        request_tracker = None
        if flask_app is not None:
            request_tracker = flask_app.config.get("RUNTIME_REQUEST_TRACKER")
            stop_admitting = getattr(request_tracker, "stop_admitting", None)
            if callable(stop_admitting):
                stop_admitting()
            flask_app.config["RUNTIME_ACCEPTING_REQUESTS"] = False
        logger.info("FlintTrade shutting down...")
        errors: list[tuple[str, str]] = []
        deferred_errors: list[tuple[str, str]] = []

        def attempt(label: str, callback: Callable[[], Any]) -> bool:
            try:
                callback()
                return True
            except Exception as exc:  # noqa: BLE001 - shutdown must continue
                errors.append((label, type(exc).__name__))
                return False

        async def attempt_async(label: str, callback: Callable[[], Any]) -> None:
            try:
                await callback()
            except Exception as exc:  # noqa: BLE001 - shutdown must continue
                errors.append((label, type(exc).__name__))

        strategy_cron_scheduler = getattr(self, "strategy_cron_scheduler", None)
        strategy_cron_stopped = (
            attempt("strategy cron scheduler", strategy_cron_scheduler.stop)
            if strategy_cron_scheduler is not None
            else True
        )

        # Long-lived streams and background writers are not represented by a
        # short request handler. Quiesce them before waiting on the request
        # tracker, otherwise an SSE response can hold the drain open forever
        # and a tick recorder can miss its final flush on timeout.
        if flask_app is not None:
            for label, config_key in (
                ("signal stream", "SIGNAL_STREAM_SHUTDOWN_EVENT"),
                ("signal retraining cancellation", "ML_SIGNAL_RETRAIN_CANCEL_EVENT"),
            ):
                shutdown_event = flask_app.config.get(config_key)
                set_event = getattr(shutdown_event, "set", None)
                if callable(set_event):
                    attempt(label, set_event)

            retrainer = flask_app.config.get("ML_SIGNAL_RETRAINER")
            wait_for_fetch_owner = getattr(retrainer, "wait_for_fetch_owner", None)
            if callable(wait_for_fetch_owner):
                raw_retrain_timeout = flask_app.config.get(
                    "ML_SIGNAL_RETRAIN_SHUTDOWN_TIMEOUT_SECONDS",
                    30.0,
                )
                try:
                    retrain_timeout = max(0.0, float(raw_retrain_timeout))
                except (TypeError, ValueError):
                    retrain_timeout = 30.0
                try:
                    retrain_stopped = await asyncio.to_thread(
                        wait_for_fetch_owner,
                        timeout=retrain_timeout,
                    )
                except Exception as exc:  # noqa: BLE001 - retain dependencies for retry
                    errors.append(("signal retraining fetch owner", type(exc).__name__))
                else:
                    if not retrain_stopped:
                        errors.append(("signal retraining fetch owner", "TimeoutError"))

            from .agent_routes import shutdown_agent_runtime  # noqa: PLC0415
            from .smart_order_routes import shutdown_smart_order_jobs  # noqa: PLC0415
            from flinttrade_engine.strategy_routes import (  # noqa: PLC0415
                shutdown_strategy_runtime,
            )

            uploaded_strategies_stopped = attempt(
                "uploaded strategy runner",
                lambda: shutdown_strategy_runtime(flask_app),
            )
            live_write_owners_stopped = (
                strategy_cron_stopped and uploaded_strategies_stopped
            )
            raw_smart_timeout = flask_app.config.get(
                "SMART_ORDER_SHUTDOWN_TIMEOUT_SECONDS", 30.0
            )
            try:
                smart_timeout = max(0.0, float(raw_smart_timeout))
            except (TypeError, ValueError):
                smart_timeout = 30.0
            try:
                smart_stopped = shutdown_smart_order_jobs(timeout=smart_timeout)
            except Exception as exc:  # noqa: BLE001 - retain router for a retry
                live_write_owners_stopped = False
                errors.append(("smart-order jobs", type(exc).__name__))
            else:
                if not smart_stopped:
                    live_write_owners_stopped = False
                    errors.append(("smart-order jobs", "TimeoutError"))

            raw_agent_timeout = flask_app.config.get(
                "AUTONOMOUS_AGENT_SHUTDOWN_TIMEOUT_SECONDS", 30.0
            )
            try:
                agent_timeout = max(0.0, float(raw_agent_timeout))
            except (TypeError, ValueError):
                agent_timeout = 30.0
            try:
                agent_stopped = shutdown_agent_runtime(
                    flask_app,
                    timeout=agent_timeout,
                )
            except Exception as exc:  # noqa: BLE001 - fail closed on agent ownership loss
                live_write_owners_stopped = False
                errors.append(("autonomous agent", type(exc).__name__))
            else:
                if not agent_stopped:
                    live_write_owners_stopped = False
                    errors.append(("autonomous agent", "TimeoutError"))

            if live_write_owners_stopped:
                try:
                    router_retired = await asyncio.to_thread(
                        retire_broker_router_generation,
                        flask_app,
                    )
                except Exception as exc:  # noqa: BLE001 - fail closed on router ownership loss
                    errors.append(("broker router", type(exc).__name__))
                else:
                    if not router_retired:
                        errors.append(("broker router", "TimeoutError"))

            attempt(
                "native session rotation scheduler",
                lambda: _shutdown_rotation_scheduler(flask_app),
            )

        tick_recorder = self._tick_recorder
        tick_task = self._tick_recorder_task
        tick_storage = getattr(self, "_tick_storage", None)
        tick_storage_lock = getattr(self, "_tick_storage_lock", None)
        checkpoint_owner = getattr(self, "_orderflow_checkpoint_owner", None)

        holiday_refresh_task = getattr(self, "_holiday_refresh_task", None)
        if holiday_refresh_task is not None:
            holiday_refresh_task.cancel()
            try:
                await holiday_refresh_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # noqa: BLE001 - shutdown must continue
                errors.append(("market calendar refresh", type(exc).__name__))
            finally:
                self._holiday_refresh_task = None

        if tick_recorder is not None:
            attempt("tick recorder", tick_recorder.stop)
        tick_task_error: Exception | None = None
        if tick_task is not None:
            tick_task.cancel()
            try:
                await tick_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # noqa: BLE001 - retain dependencies for a retry
                tick_task_error = exc
                sanitise_error = getattr(tick_recorder, "sanitise_error", None)
                try:
                    diagnostic = (
                        sanitise_error(exc)
                        if callable(sanitise_error)
                        else type(exc).__name__
                    )
                except Exception:  # pragma: no cover - diagnostics must not block shutdown
                    diagnostic = type(exc).__name__
                logger.warning(
                    "Tick recorder task ended with an error during shutdown (%s)",
                    diagnostic,
                )
            finally:
                # A completed failed task can only replay the same exception.
                # Clear process ownership so a later stop() retries the
                # recorder's retained buffer directly instead.
                self._tick_recorder_task = None

        if tick_recorder is not None and (tick_task is None or tick_task_error is not None):
            flush_pending = getattr(tick_recorder, "flush_pending", None)
            if callable(flush_pending):
                try:
                    flush_pending()
                except Exception as exc:  # noqa: BLE001 - report after independent cleanup
                    deferred_errors.append(
                        ("tick recorder retained buffer", type(exc).__name__)
                    )
                else:
                    tick_task_error = None
            elif tick_task_error is not None:
                deferred_errors.append(
                    ("tick recorder task", type(tick_task_error).__name__)
                )

        if errors:
            summary = ", ".join(
                f"{label} ({error_type})" for label, error_type in errors
            )
            logger.error("FlintTrade shutdown quiesce failed: %s", summary)
            raise RuntimeError(f"shutdown encountered errors: {summary}")

        if request_tracker is not None:
            raw_timeout = flask_app.config.get(
                "RUNTIME_REQUEST_DRAIN_TIMEOUT_SECONDS", 60.0
            )
            try:
                drain_timeout = max(0.0, float(raw_timeout))
            except (TypeError, ValueError):
                drain_timeout = 60.0
            wait_for_idle = getattr(request_tracker, "wait_for_idle", None)
            drained = bool(
                await asyncio.to_thread(wait_for_idle, drain_timeout)
                if callable(wait_for_idle)
                else True
            )
            if not drained:
                # Do not close any dependency while a handler still owns it. A
                # later stop() retry can complete teardown after the request
                # leaves; the process exits non-zero if it never does.
                logger.error("FlintTrade shutdown timed out draining active requests")
                raise RuntimeError(
                    "shutdown encountered errors: active requests (TimeoutError)"
                )

        if flask_app is not None:
            from flinttrade_engine.strategy_routes import (  # noqa: PLC0415
                shutdown_strategy_runtime,
            )

            uploaded_stopped = attempt(
                "uploaded strategy runner after request drain",
                lambda: shutdown_strategy_runtime(flask_app),
            )
            if uploaded_stopped:
                try:
                    router_retired = await asyncio.to_thread(
                        retire_broker_router_generation,
                        flask_app,
                    )
                except Exception as exc:  # noqa: BLE001 - fail closed on late publication
                    errors.append(("broker router after request drain", type(exc).__name__))
                else:
                    if not router_retired:
                        errors.append(("broker router after request drain", "TimeoutError"))

        if errors:
            summary = ", ".join(
                f"{label} ({error_type})" for label, error_type in errors
            )
            logger.error("FlintTrade shutdown request drain failed: %s", summary)
            raise RuntimeError(f"shutdown encountered errors: {summary}")

        errors.extend(deferred_errors)
        try:
            # Stop strategies
            await attempt_async("scheduler", self.scheduler.stop_all)

            # Stop cron
            attempt("cron", self.cron.stop)

            # Stop the Telegram polling loop before the shared client closes, so it
            # is not left long-polling and dispatching commands against a torn-down
            # backend during shutdown.
            telegram = getattr(self, "telegram", None)
            if telegram is not None:
                attempt("telegram", telegram.stop)

            # The recorder was stopped and flushed before request draining;
            # unpublish and close its storage only after admitted handlers left.
            if flask_app is not None:
                with _tick_capture_lifecycle_lock(flask_app):
                    published_recorder = flask_app.config.get("TICK_RECORDER")
                    published_storage = flask_app.config.get("TICK_STORAGE")
                    if published_recorder is tick_recorder or published_storage is tick_storage:
                        for key in (
                            "TICK_RECORDER",
                            "TICK_STORAGE",
                            "TICK_STORAGE_LOCK",
                            "ORDERFLOW_AGGREGATOR",
                        ):
                            flask_app.config.pop(key, None)
                        flask_app.config["TICK_CAPTURE_ERROR"] = "Application is shutting down"
            if tick_storage is not None:
                self.cron.tick_storage = None
                self.cron.tick_storage_lock = None
                checkpoint_ready = True
                if checkpoint_owner is not None:
                    try:
                        pending_tick_count = int(
                            getattr(tick_recorder, "pending_tick_count", 0)
                        )
                    except (TypeError, ValueError, OverflowError):
                        pending_tick_count = 1
                    if pending_tick_count:
                        checkpoint_ready = False
                        errors.append(("tick checkpoint pending buffer", "RuntimeError"))
                    else:
                        try:
                            checkpoint_owner.persist(force=True)
                        except Exception as exc:  # noqa: BLE001 - retain for retry
                            checkpoint_ready = False
                            errors.append(("tick order-flow checkpoint", type(exc).__name__))
                if checkpoint_ready and attempt(
                    "tick storage",
                    lambda: _close_tick_storage(tick_storage, tick_storage_lock),
                ):
                    self._tick_storage = None
                    self._tick_storage_lock = None
                    self._orderflow_checkpoint_owner = None

            # Stop the reconciliation runner (signal the loop, then cancel the task).
            reconciliation_runner = self._reconciliation_runner
            reconciliation_task = self._reconciliation_task
            if reconciliation_runner is not None:
                attempt("reconciliation runner", reconciliation_runner.stop)
            if reconciliation_task is not None:
                attempt("reconciliation task", reconciliation_task.cancel)
                try:
                    await reconciliation_task
                except asyncio.CancelledError:
                    self._reconciliation_task = None
                except Exception as exc:  # noqa: BLE001 - shutdown must continue
                    errors.append(("reconciliation task", type(exc).__name__))
                    self._reconciliation_task = None
                else:
                    self._reconciliation_task = None

            # Log shutdown to audit before closing.
            attempt("audit event", lambda: self.audit.log_event("APP_STOP", version=self.version))

            # Close API client and audit logger independently.
            async def close_openalgo_client() -> None:
                if isinstance(self.client, OpenAlgoClient):
                    await self.client.shutdown()
                    return
                await self.client.close()

            await attempt_async("OpenAlgo client", close_openalgo_client)
            attempt("audit logger", self.audit.close)
        finally:
            self._stop_event.set()

        if errors:
            summary = ", ".join(f"{label} ({error_type})" for label, error_type in errors)
            logger.error("FlintTrade shutdown encountered errors: %s", summary)
            raise RuntimeError(f"shutdown encountered errors: {summary}")

        self._stop_completed = True
        logger.info("FlintTrade %s stopped", self.version)

    def run(self) -> None:
        """Run the application (blocking). Handles Ctrl+C gracefully."""
        # NOTE: stdlib logging is already configured by create_flask_app()
        # with a structlog-backed formatter. Calling basicConfig() here
        # would add a second root handler and re-introduce the dual-emit
        # bug. Don't do it.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Handle signals
        def request_stop() -> None:
            task = getattr(self, "_shutdown_request_task", None)
            if task is None or task.done():
                task = loop.create_task(self.stop())
                self._shutdown_request_task = task

                def observe_shutdown(completed: asyncio.Task[Any]) -> None:
                    try:
                        completed.result()
                    except asyncio.CancelledError:
                        pass
                    except Exception as exc:  # noqa: BLE001 - consume signal-task failure
                        logger.error("FlintTrade shutdown failed (%s)", type(exc).__name__)

                task.add_done_callback(observe_shutdown)

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, request_stop)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                pass

        try:
            loop.run_until_complete(self.start())
            shutdown_task = getattr(self, "_shutdown_task", None)
            if shutdown_task is not None:
                loop.run_until_complete(asyncio.shield(shutdown_task))
        except KeyboardInterrupt:
            loop.run_until_complete(self.stop())
        finally:
            loop.close()


if __name__ == "__main__":
    FlintTradeApp().run()


# ---------------------------------------------------------------------------
# Module-level ``app`` for gunicorn / WSGI servers.
#   Usage: ``gunicorn 'flinttrade_core.app:app'``
#
# The Flask app is created LAZILY the first time ``app`` is imported from
# this module.  We avoid eagerly building it at module import because
# running ``python -m flinttrade_core.app`` would create one instance
# here and another inside ``FlintTradeApp.start()``, printing every
# startup log line twice and tripping the CPython "RuntimeWarning: ...
# found in sys.modules after import of package ..." warning.
#
# Python 3.7+ supports module-level ``__getattr__`` (PEP 562) which gives
# us lazy attribute access with no change to the consumer API — WSGI
# servers do ``from flinttrade_core.app import app`` and still get a
# real Flask instance on first use.
# ---------------------------------------------------------------------------

_APP_CACHE: Flask | None = None


def _get_wsgi_app() -> Flask:
    """Lazily construct (and cache) the WSGI Flask app."""
    global _APP_CACHE
    if _APP_CACHE is None:
        _APP_CACHE = create_flask_app()
    return _APP_CACHE


def __getattr__(name: str) -> Any:
    """PEP 562 module __getattr__ — produce ``app`` on first access only."""
    if name == "app":
        return _get_wsgi_app()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
