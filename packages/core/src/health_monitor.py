"""Comprehensive infrastructure health monitor.

Provides :class:`HealthMonitor` — a consolidated health-check engine that
interrogates every significant subsystem and returns a structured
:class:`HealthReport`.

Usage::

    monitor = HealthMonitor()
    report = monitor.check_all()
    print(report.overall_status)   # "healthy" | "degraded" | "unhealthy"

The monitor relies on:

- ``psutil`` — process/system memory, file-descriptor counts, thread counts
- Standard library ``shutil`` — disk usage
- ``socket`` — WebSocket reachability probe
- Optional DuckDB check via :meth:`HealthMonitor.check_database`

All check methods are safe to call independently and never raise; errors
surface in the :attr:`HealthCheck.status` field and :attr:`HealthCheck.message`.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger("flinttrade.health_monitor")

# IST = UTC+5:30
_IST = timezone(timedelta(hours=5, minutes=30))

# Warn when fewer than this many GB are free on any watched directory
_DISK_WARN_GB: float = 2.0
# Warn when fewer than this many GB are free on any watched directory (critical)
_DISK_CRIT_GB: float = 0.5
# Warn when open FD count exceeds this fraction of the rlimit
_FD_WARN_FRACTION: float = 0.80
# Thread count growth that triggers a warning (new threads vs baseline)
_THREAD_GROWTH_WARN: int = 50


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class HealthCheck:
    """Result of a single infrastructure health check.

    Attributes:
        name: Short identifier for the check (e.g. ``"memory"``).
        status: One of ``"healthy"``, ``"degraded"``, or ``"unhealthy"``.
        message: Human-readable summary of the result.
        metrics: Arbitrary key/value metrics captured during the check.
        checked_at: Timestamp when the check was executed.
    """

    name: str
    status: Literal["healthy", "degraded", "unhealthy"]
    message: str
    metrics: dict[str, Any]
    checked_at: datetime = field(default_factory=lambda: datetime.now(_IST))

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict.

        Returns:
            Dict with ``name``, ``status``, ``message``, ``metrics``,
            and ``checked_at`` (ISO 8601 string).
        """
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "metrics": self.metrics,
            "checked_at": self.checked_at.isoformat(),
        }


@dataclass
class HealthReport:
    """Consolidated result of all health checks.

    Attributes:
        overall_status: Worst status across all checks:
            ``"healthy"`` if all pass, ``"degraded"`` if any are degraded,
            ``"unhealthy"`` if any are unhealthy.
        checks: Ordered list of individual :class:`HealthCheck` results.
        timestamp: When the report was generated.
    """

    overall_status: Literal["healthy", "degraded", "unhealthy"]
    checks: list[HealthCheck]
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict.

        Returns:
            Dict with ``overall_status``, ``timestamp``, and ``checks``.
        """
        return {
            "overall_status": self.overall_status,
            "timestamp": self.timestamp.isoformat(),
            "checks": [c.to_dict() for c in self.checks],
        }


# ---------------------------------------------------------------------------
# HealthMonitor
# ---------------------------------------------------------------------------


def _overall(checks: list[HealthCheck]) -> Literal["healthy", "degraded", "unhealthy"]:
    """Derive the worst-case status from a list of checks.

    Args:
        checks: List of completed :class:`HealthCheck` instances.

    Returns:
        ``"unhealthy"`` if any check is unhealthy, ``"degraded"`` if any
        is degraded, otherwise ``"healthy"``.
    """
    statuses = {c.status for c in checks}
    if "unhealthy" in statuses:
        return "unhealthy"
    if "degraded" in statuses:
        return "degraded"
    return "healthy"


class HealthMonitor:
    """Comprehensive infrastructure health tracking.

    Args:
        ws_host: WebSocket host to probe (default ``"127.0.0.1"``).
        ws_port: WebSocket port to probe (default ``8765``).
        data_dirs: Directories to check for free disk space.  Defaults to
            ``~/.flinttrade``.  Pass additional log/data dirs as needed.
        duckdb_paths: List of DuckDB file paths to verify readability.
        cache: Optional dict-like cache instance that exposes ``keys()``.

    Example::

        monitor = HealthMonitor()
        report = monitor.check_all()
        for check in report.checks:
            print(check.name, check.status, check.message)
    """

    def __init__(
        self,
        ws_host: str = "127.0.0.1",
        ws_port: int = 8765,
        data_dirs: list[str | Path] | None = None,
        duckdb_paths: list[str | Path] | None = None,
        cache: Any | None = None,
    ) -> None:
        self._ws_host = ws_host
        self._ws_port = ws_port
        self._data_dirs: list[Path] = (
            [Path(d) for d in data_dirs]
            if data_dirs
            else [Path.home() / ".flinttrade"]
        )
        self._duckdb_paths: list[Path] = (
            [Path(p) for p in duckdb_paths] if duckdb_paths else []
        )
        self._cache = cache
        self._thread_baseline: int | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_all(self) -> HealthReport:
        """Run all checks and return a consolidated :class:`HealthReport`.

        Checks are executed sequentially.  Each check is individually
        guarded against exceptions so that a failure in one probe does not
        prevent the others from running.

        Returns:
            A :class:`HealthReport` with ``overall_status`` and the full
            list of individual checks.
        """
        checks: list[HealthCheck] = [
            self.check_memory(),
            self.check_disk(),
            self.check_file_descriptors(),
            self.check_thread_count(),
            self.check_database(),
            self.check_websocket(),
            self.check_broker_connections(),
            self.check_cache_health(),
        ]
        return HealthReport(
            overall_status=_overall(checks),
            checks=checks,
            timestamp=datetime.now(_IST),
        )

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def check_memory(self) -> HealthCheck:
        """Report process RSS and system memory usage.

        Uses ``psutil`` to capture both process-level RSS and the system
        memory percentage.  If ``psutil`` is unavailable the check
        returns ``"healthy"`` with a note.

        Returns:
            :class:`HealthCheck` with metrics ``rss_mb``, ``vms_mb``,
            ``process_percent``, ``system_total_mb``,
            ``system_available_mb``, ``system_percent``.
        """
        try:
            import psutil  # type: ignore[import]

            proc = psutil.Process()
            mem = proc.memory_info()
            rss_mb = round(mem.rss / (1024 * 1024), 1)
            vms_mb = round(mem.vms / (1024 * 1024), 1)
            proc_pct = round(proc.memory_percent(), 2)

            sys_mem = psutil.virtual_memory()
            sys_total_mb = round(sys_mem.total / (1024 * 1024), 1)
            sys_avail_mb = round(sys_mem.available / (1024 * 1024), 1)
            sys_pct = round(sys_mem.percent, 1)

            if proc_pct > 80 or sys_pct > 90:
                status: Literal["healthy", "degraded", "unhealthy"] = "unhealthy"
                msg = f"High memory: process={proc_pct}% system={sys_pct}%"
            elif proc_pct > 50 or sys_pct > 75:
                status = "degraded"
                msg = f"Elevated memory: process={proc_pct}% system={sys_pct}%"
            else:
                status = "healthy"
                msg = f"Memory OK: process={proc_pct}% system={sys_pct}%"

            return HealthCheck(
                name="memory",
                status=status,
                message=msg,
                metrics={
                    "rss_mb": rss_mb,
                    "vms_mb": vms_mb,
                    "process_percent": proc_pct,
                    "system_total_mb": sys_total_mb,
                    "system_available_mb": sys_avail_mb,
                    "system_percent": sys_pct,
                },
            )
        except ImportError:
            return HealthCheck(
                name="memory",
                status="healthy",
                message="psutil not installed — memory check skipped",
                metrics={},
            )
        except Exception as exc:
            return HealthCheck(
                name="memory",
                status="degraded",
                message=f"Memory check error: {exc}",
                metrics={},
            )

    def check_disk(self) -> HealthCheck:
        """Check free disk space in every watched directory.

        Warns if any directory has less than :data:`_DISK_WARN_GB` GB free;
        marks unhealthy below :data:`_DISK_CRIT_GB` GB.

        Returns:
            :class:`HealthCheck` with per-directory metrics.
        """
        import shutil

        dir_results: list[dict[str, Any]] = []
        worst: Literal["healthy", "degraded", "unhealthy"] = "healthy"
        messages: list[str] = []

        for d in self._data_dirs:
            check_path = d if d.exists() else (d.parent if d.parent.exists() else Path.home())
            try:
                usage = shutil.disk_usage(str(check_path))
                free_gb = round(usage.free / (1024 ** 3), 2)
                total_gb = round(usage.total / (1024 ** 3), 2)
                pct_used = round((usage.used / usage.total) * 100, 1) if usage.total > 0 else 0.0

                if free_gb < _DISK_CRIT_GB:
                    dir_status: Literal["healthy", "degraded", "unhealthy"] = "unhealthy"
                    worst = "unhealthy"
                    messages.append(f"{d}: {free_gb:.1f}GB free (CRITICAL)")
                elif free_gb < _DISK_WARN_GB:
                    dir_status = "degraded"
                    if worst != "unhealthy":
                        worst = "degraded"
                    messages.append(f"{d}: {free_gb:.1f}GB free (LOW)")
                else:
                    dir_status = "healthy"

                dir_results.append(
                    {
                        "path": str(d),
                        "status": dir_status,
                        "free_gb": free_gb,
                        "total_gb": total_gb,
                        "percent_used": pct_used,
                    }
                )
            except Exception as exc:
                worst = "degraded" if worst == "healthy" else worst
                dir_results.append({"path": str(d), "status": "degraded", "error": str(exc)})
                messages.append(f"{d}: error — {exc}")

        msg = "; ".join(messages) if messages else "Disk space OK"
        return HealthCheck(
            name="disk",
            status=worst,
            message=msg,
            metrics={"directories": dir_results},
        )

    def check_file_descriptors(self) -> HealthCheck:
        """Report open file descriptor count vs the process rlimit.

        Warns at :data:`_FD_WARN_FRACTION` (80 %) of the soft limit.

        Returns:
            :class:`HealthCheck` with metrics ``open_fds``, ``soft_limit``,
            ``hard_limit``, ``utilisation_percent``.
        """
        try:
            import psutil  # type: ignore[import]

            proc = psutil.Process()
            open_fds = proc.num_fds() if hasattr(proc, "num_fds") else len(proc.open_files())

            try:
                import resource  # Unix only

                soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
            except ImportError:
                # Windows — psutil provides a rough count but no rlimit
                soft, hard = 1024, 1024  # conservative estimate

            utilisation = (open_fds / soft) if soft > 0 else 0.0
            pct = round(utilisation * 100, 1)

            if utilisation >= _FD_WARN_FRACTION:
                status: Literal["healthy", "degraded", "unhealthy"] = "degraded"
                msg = f"FD utilisation {pct}% (warn threshold {int(_FD_WARN_FRACTION*100)}%)"
            else:
                status = "healthy"
                msg = f"FD utilisation {pct}% ({open_fds}/{soft})"

            return HealthCheck(
                name="file_descriptors",
                status=status,
                message=msg,
                metrics={
                    "open_fds": open_fds,
                    "soft_limit": soft,
                    "hard_limit": hard,
                    "utilisation_percent": pct,
                },
            )
        except ImportError:
            return HealthCheck(
                name="file_descriptors",
                status="healthy",
                message="psutil not installed — FD check skipped",
                metrics={},
            )
        except Exception as exc:
            return HealthCheck(
                name="file_descriptors",
                status="degraded",
                message=f"FD check error: {exc}",
                metrics={},
            )

    def check_thread_count(self) -> HealthCheck:
        """Monitor thread count growth since first call.

        Establishes a baseline on the first invocation, then warns if
        the count has grown by more than :data:`_THREAD_GROWTH_WARN`.

        Returns:
            :class:`HealthCheck` with metrics ``thread_count``,
            ``baseline``, ``growth``.
        """
        try:
            import psutil  # type: ignore[import]

            proc = psutil.Process()
            count = proc.num_threads()

            with self._lock:
                if self._thread_baseline is None:
                    self._thread_baseline = count
                baseline = self._thread_baseline

            growth = count - baseline

            if growth > _THREAD_GROWTH_WARN:
                status: Literal["healthy", "degraded", "unhealthy"] = "degraded"
                msg = f"Thread count growth: +{growth} since baseline ({count} total)"
            else:
                status = "healthy"
                msg = f"Thread count OK: {count} (baseline {baseline}, +{growth})"

            return HealthCheck(
                name="thread_count",
                status=status,
                message=msg,
                metrics={
                    "thread_count": count,
                    "baseline": baseline,
                    "growth": growth,
                },
            )
        except ImportError:
            return HealthCheck(
                name="thread_count",
                status="healthy",
                message="psutil not installed — thread check skipped",
                metrics={},
            )
        except Exception as exc:
            return HealthCheck(
                name="thread_count",
                status="degraded",
                message=f"Thread check error: {exc}",
                metrics={},
            )

    def check_database(self) -> HealthCheck:
        """Verify readability of registered DuckDB files.

        Attempts a ``SELECT 1`` on each path in ``duckdb_paths``.  If no
        paths were configured the check is skipped and returns
        ``"healthy"``.

        Returns:
            :class:`HealthCheck` with ``files`` metrics list.
        """
        if not self._duckdb_paths:
            return HealthCheck(
                name="database",
                status="healthy",
                message="No DuckDB paths configured — check skipped",
                metrics={},
            )

        results: list[dict[str, Any]] = []
        readable = 0
        unreadable = 0

        for p in self._duckdb_paths:
            try:
                import duckdb  # type: ignore[import]

                conn = duckdb.connect(str(p), read_only=True)
                conn.execute("SELECT 1").fetchone()
                conn.close()
                results.append({"path": str(p), "readable": True})
                readable += 1
            except Exception as exc:
                results.append({"path": str(p), "readable": False, "error": str(exc)})
                unreadable += 1

        if unreadable == 0:
            status: Literal["healthy", "degraded", "unhealthy"] = "healthy"
            msg = f"All {readable} DuckDB file(s) readable"
        elif readable > 0:
            status = "degraded"
            msg = f"{unreadable} DuckDB file(s) unreadable, {readable} OK"
        else:
            status = "unhealthy"
            msg = f"All {unreadable} DuckDB file(s) unreadable"

        return HealthCheck(
            name="database",
            status=status,
            message=msg,
            metrics={"readable": readable, "unreadable": unreadable, "files": results},
        )

    def check_websocket(self) -> HealthCheck:
        """Probe TCP reachability of the OpenAlgo WebSocket port.

        A simple ``socket.connect_ex`` probe — does not perform the WS
        handshake.  Times out after 1 second.

        Returns:
            :class:`HealthCheck` with metrics ``host``, ``port``,
            ``reachable``, ``latency_ms``.
        """
        host = self._ws_host
        port = self._ws_port
        try:
            t0 = time.monotonic()
            with socket.create_connection((host, port), timeout=1.0):
                pass
            latency_ms = round((time.monotonic() - t0) * 1000, 2)
            return HealthCheck(
                name="websocket",
                status="healthy",
                message=f"WebSocket {host}:{port} reachable ({latency_ms}ms)",
                metrics={"host": host, "port": port, "reachable": True, "latency_ms": latency_ms},
            )
        except OSError as exc:
            return HealthCheck(
                name="websocket",
                status="degraded",
                message=f"WebSocket {host}:{port} unreachable: {exc}",
                metrics={"host": host, "port": port, "reachable": False, "latency_ms": None},
            )

    def check_broker_connections(self) -> HealthCheck:
        """Check broker session status via the Flask app config.

        Reads the ``REGISTRY`` key from ``flask.current_app.config`` if
        running inside a request context.  Falls back to a ``"healthy"``
        no-op when called outside Flask.

        Returns:
            :class:`HealthCheck` with ``connected``, ``disconnected``,
            ``total`` metrics.
        """
        try:
            from flask import current_app  # noqa: PLC0415

            registry = current_app.config.get("REGISTRY")
        except RuntimeError:
            # Outside application context
            registry = None

        if registry is None:
            return HealthCheck(
                name="broker_connections",
                status="healthy",
                message="No broker registry available",
                metrics={},
            )

        try:
            sessions = registry.list_sessions()
            connected = sum(1 for s in sessions if s.get("is_connected", False))
            disconnected = len(sessions) - connected

            if len(sessions) == 0:
                status: Literal["healthy", "degraded", "unhealthy"] = "healthy"
                msg = "No broker accounts configured"
            elif disconnected == 0:
                status = "healthy"
                msg = f"All {connected} broker(s) connected"
            elif connected > 0:
                status = "degraded"
                msg = f"{connected} connected, {disconnected} disconnected"
            else:
                status = "unhealthy"
                msg = f"All {disconnected} broker(s) disconnected"

            return HealthCheck(
                name="broker_connections",
                status=status,
                message=msg,
                metrics={
                    "connected": connected,
                    "disconnected": disconnected,
                    "total": len(sessions),
                },
            )
        except Exception as exc:
            return HealthCheck(
                name="broker_connections",
                status="degraded",
                message=f"Broker registry error: {exc}",
                metrics={},
            )

    def check_cache_health(self) -> HealthCheck:
        """Report cache entry count if a cache was supplied.

        If no cache instance was provided at construction the check is
        skipped and returns ``"healthy"``.

        Returns:
            :class:`HealthCheck` with ``entry_count`` metric.
        """
        if self._cache is None:
            return HealthCheck(
                name="cache",
                status="healthy",
                message="No cache configured — check skipped",
                metrics={},
            )
        try:
            count = len(list(self._cache.keys()))
            return HealthCheck(
                name="cache",
                status="healthy",
                message=f"Cache OK — {count} entries",
                metrics={"entry_count": count},
            )
        except Exception as exc:
            return HealthCheck(
                name="cache",
                status="degraded",
                message=f"Cache health check error: {exc}",
                metrics={},
            )
