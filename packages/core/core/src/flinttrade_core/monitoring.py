"""Monitoring: health checks, traffic counting, latency tracking.

Three classes:

- :class:`HealthAggregator` — aggregate health status of broker
  connections, DuckDB files, and install-host resources (disk, memory,
  CPU, GPU, network).
- :class:`TrafficCounter` — circular-buffer request tracker with
  per-path statistics.
- :class:`LatencyTracker` — per-broker order RTT statistics
  (p50/p95/p99).
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("flinttrade.monitoring")


def _default_data_dir() -> Path:
    """Resolve the default disk-probe directory under the active workspace.

    Read-only probe target — no legacy migration is attempted, and the
    path is resolved at call time so environment overrides set after
    import are honoured.

    Returns:
        The ``data`` directory inside the active workspace.
    """
    from flinttrade_core.workspace import workspace_dir

    return workspace_dir() / "data"


_MIB = 1024 * 1024


def _load_psutil() -> Any | None:
    """Import psutil when it is installed.

    Returns:
        The psutil module, or ``None`` when it cannot be imported.
    """
    try:
        import psutil  # type: ignore[import]
    except ImportError:
        return None
    return psutil


def _utilisation_status(percent: float, *, degraded_above: float, error_above: float) -> str:
    """Map a host utilisation percentage to a health status.

    Args:
        percent: Utilisation from 0 to 100.
        degraded_above: Exclusive lower bound for ``"degraded"``.
        error_above: Exclusive lower bound for ``"error"``.

    Returns:
        ``"error"``, ``"degraded"``, or ``"ok"``.
    """
    if percent > error_above:
        return "error"
    if percent > degraded_above:
        return "degraded"
    return "ok"


def _unavailable(note: str) -> dict[str, Any]:
    """Return a host reading that must not be painted as a zero measurement.

    Args:
        note: Short reason the figure is absent.

    Returns:
        Dict with ``status`` and ``scope`` ``"unavailable"`` and no numeric
        totals.
    """
    return {"status": "unavailable", "scope": "unavailable", "note": note}


def _parse_nvidia_smi_csv(stdout: str) -> dict[str, Any] | None:
    """Parse ``nvidia-smi`` CSV rows into host GPU totals.

    Args:
        stdout: CSV text from ``--format=csv,noheader,nounits``.

    Returns:
        Dict with summed memory and peak utilisation, or ``None`` when no
        row yields a real memory total.
    """
    names: list[str] = []
    utils: list[float] = []
    used_mb = 0.0
    total_mb = 0.0
    counted = 0
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 4:
            continue
        name = ",".join(parts[:-3]).strip()
        try:
            used = float(parts[-2])
            total = float(parts[-1])
        except ValueError:
            continue
        if total <= 0 or used < 0:
            continue
        counted += 1
        used_mb += used
        total_mb += total
        if name:
            names.append(name)
        try:
            util = float(parts[-3])
        except ValueError:
            continue
        if util >= 0:
            utils.append(util)
    if counted == 0:
        return None
    result: dict[str, Any] = {
        "used_mb": round(used_mb, 1),
        "total_mb": round(total_mb, 1),
        "count": counted,
    }
    if utils:
        result["used_pct"] = round(max(utils), 1)
    if names:
        result["name"] = names[0] if counted == 1 else f"{counted} GPUs"
    return result


# ---------------------------------------------------------------------------
# HealthAggregator
# ---------------------------------------------------------------------------


class HealthAggregator:
    """Aggregate health checks for all FlintTrade subsystems.

    All check methods return a dict with at least ``status``
    (``"ok"``, ``"degraded"``, ``"error"``, or ``"unavailable"``) and
    relevant diagnostic fields. Host resource readings set ``scope`` to
    ``"host"``. This process's RSS/VMS use ``scope`` ``"process"``.

    Example::

        agg = HealthAggregator()
        health = agg.get_health()
        assert health["status"] in ("ok", "degraded", "error")
    """

    def check_broker_connections(self, registry: Any) -> dict[str, Any]:
        """Check broker connection states from a BrokerRegistry.

        Args:
            registry: A ``BrokerRegistry`` instance (or any object that
                exposes ``list_sessions()`` returning dicts with an
                ``is_connected`` key).

        Returns:
            Dict with ``status``, ``connected``, ``disconnected``,
            ``total``, and ``accounts`` list.
        """
        try:
            sessions = registry.list_sessions()
        except Exception:
            logger.exception("Broker connection health check failed")
            return {
                "status": "error",
                "message": "Broker connection health check failed",
                "connected": 0,
                "disconnected": 0,
                "total": 0,
            }

        connected = sum(1 for s in sessions if s.get("is_connected", False))
        disconnected = len(sessions) - connected
        status = "ok" if disconnected == 0 else ("degraded" if connected > 0 else "error")
        return {
            "status": status,
            "connected": connected,
            "disconnected": disconnected,
            "total": len(sessions),
            "accounts": [
                {"account_id": s.get("account_id", ""), "connected": s.get("is_connected", False)}
                for s in sessions
            ],
        }

    def check_duckdb(self, paths: list[str | Path]) -> dict[str, Any]:
        """Verify that DuckDB files are readable.

        Args:
            paths: List of paths to DuckDB files to check.

        Returns:
            Dict with ``status``, ``checked``, ``readable``,
            ``unreadable``, and ``files`` list.
        """
        results: list[dict[str, Any]] = []
        readable = 0
        unreadable = 0

        for p in paths:
            path = Path(p)
            try:
                import duckdb  # type: ignore[import]

                conn = duckdb.connect(str(path), read_only=True)
                conn.execute("SELECT 1").fetchone()
                conn.close()
                results.append({"path": str(path), "readable": True})
                readable += 1
            except Exception as exc:
                results.append({"path": str(path), "readable": False, "error": str(exc)})
                unreadable += 1

        status = "ok" if unreadable == 0 else ("degraded" if readable > 0 else "error")
        return {
            "status": status,
            "checked": len(paths),
            "readable": readable,
            "unreadable": unreadable,
            "files": results,
        }

    def check_disk_space(self, data_dir: str | Path | None = None) -> dict[str, Any]:
        """Check free disk space on the data directory.

        Args:
            data_dir: Directory to check.  Defaults to the ``data``
                directory inside the active workspace (resolved at call
                time via :func:`flinttrade_core.workspace.workspace_dir`).

        Returns:
            Dict with ``status``, ``scope`` ``"host"``, ``total_gb``,
            ``used_gb``, ``free_gb``, ``percent_used``, and ``used_pct``.
            When the volume cannot be measured, ``scope`` is
            ``"unavailable"`` and the numeric totals are omitted.
        """
        if data_dir is None:
            data_dir = _default_data_dir()
        data_dir = Path(data_dir)

        try:
            usage = shutil.disk_usage(str(data_dir) if data_dir.exists() else str(data_dir.parent.parent))
            if usage.total <= 0:
                return _unavailable("Host disk unavailable")
            total_gb = usage.total / (1024 ** 3)
            used_gb = usage.used / (1024 ** 3)
            free_gb = usage.free / (1024 ** 3)
            pct = (usage.used / usage.total) * 100
            rounded_pct = round(pct, 1)

            return {
                "status": _utilisation_status(pct, degraded_above=80, error_above=95),
                "scope": "host",
                "total_gb": round(total_gb, 2),
                "used_gb": round(used_gb, 2),
                "free_gb": round(free_gb, 2),
                "percent_used": rounded_pct,
                "used_pct": rounded_pct,
            }
        except Exception:
            logger.exception("Disk health check failed")
            return {"status": "error", "scope": "unavailable", "message": "Disk health check failed"}

    def check_memory(self) -> dict[str, Any]:
        """Report install-host RAM, with this process recorded separately.

        Host totals use ``used_mb``, ``total_mb``, and ``used_pct`` with
        ``scope`` ``"host"``. Process RSS and VMS are nested under
        ``process`` and are never copied into those host fields. When the
        OS cannot provide host RAM, the result is ``scope`` ``"process"``
        or ``"unavailable"`` and does not invent ``0`` totals.

        Returns:
            Host memory dict, optionally including a ``process`` object.
            Missing host RAM omits ``used_mb`` / ``total_mb`` / ``used_pct``.
        """
        psutil = _load_psutil()
        if psutil is None:
            return _unavailable("Host memory unavailable")

        host = self._read_host_memory(psutil)
        process = self._read_process_memory(psutil)
        if host is not None:
            if process is not None:
                host["process"] = process
            return host
        if process is not None:
            return {
                "status": "unavailable",
                "scope": "process",
                "note": "Host memory unavailable",
                "process": process,
            }
        return _unavailable("Host memory unavailable")

    def check_cpu(self) -> dict[str, Any] | None:
        """Read install-host CPU utilisation.

        Returns:
            Dict with ``scope`` ``"host"`` and ``used_pct``, or ``None``
            when the OS cannot provide a reading. The first meaningless
            psutil sample is not returned as zero.
        """
        psutil = _load_psutil()
        if psutil is None:
            return None
        try:
            # interval=None's first call is a meaningless 0.0. A short
            # blocking sample is a real reading for this host.
            used_pct = float(psutil.cpu_percent(interval=0.1))
            cores = psutil.cpu_count(logical=True)
        except Exception:
            logger.exception("Host CPU health check failed")
            return None
        if used_pct < 0:
            return None
        result: dict[str, Any] = {
            "status": _utilisation_status(used_pct, degraded_above=90, error_above=98),
            "scope": "host",
            "used_pct": round(used_pct, 1),
        }
        if isinstance(cores, int) and cores > 0:
            result["cores"] = cores
        return result

    def check_gpu(self) -> dict[str, Any] | None:
        """Read install-host GPU memory when nvidia-smi can report it.

        Returns:
            Dict with ``scope`` ``"host"`` and measured memory totals, or
            ``None`` when no GPU reading is available.
        """
        binary = shutil.which("nvidia-smi")
        if not binary:
            return None
        try:
            completed = subprocess.run(
                [
                    binary,
                    "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=1.5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            logger.debug("Host GPU probe did not complete", exc_info=True)
            return None
        if completed.returncode != 0:
            return None
        parsed = _parse_nvidia_smi_csv(completed.stdout)
        if parsed is None:
            return None
        used_pct = parsed.get("used_pct")
        status = "ok"
        if isinstance(used_pct, (int, float)):
            status = _utilisation_status(float(used_pct), degraded_above=90, error_above=98)
        return {"status": status, "scope": "host", **parsed}

    def check_network(self) -> dict[str, Any] | None:
        """Read cumulative install-host network counters.

        Returns:
            Dict with ``scope`` ``"host"``, ``bytes_sent``, and
            ``bytes_recv``, or ``None`` when counters cannot be read.
        """
        psutil = _load_psutil()
        if psutil is None:
            return None
        try:
            counters = psutil.net_io_counters()
        except Exception:
            logger.exception("Host network health check failed")
            return None
        if counters is None:
            return None
        try:
            sent = int(counters.bytes_sent)
            received = int(counters.bytes_recv)
        except (TypeError, ValueError):
            return None
        if sent < 0 or received < 0:
            return None
        return {
            "status": "ok",
            "scope": "host",
            "bytes_sent": sent,
            "bytes_recv": received,
        }

    @staticmethod
    def _read_host_memory(psutil: Any) -> dict[str, Any] | None:
        """Read physical RAM totals from psutil.

        Args:
            psutil: Imported psutil module.

        Returns:
            Host memory dict, or ``None`` when totals are unavailable.
        """
        try:
            sys_mem = psutil.virtual_memory()
            total = int(getattr(sys_mem, "total", 0) or 0)
            if total <= 0:
                return None
            available = int(getattr(sys_mem, "available", 0) or 0)
            used_bytes = max(total - available, 0)
            used_pct = float(getattr(sys_mem, "percent", 0.0) or 0.0)
        except Exception:
            logger.exception("Host memory health check failed")
            return None
        return {
            "status": _utilisation_status(used_pct, degraded_above=80, error_above=95),
            "scope": "host",
            "used_mb": round(used_bytes / _MIB, 1),
            "total_mb": round(total / _MIB, 1),
            "used_pct": round(used_pct, 1),
        }

    @staticmethod
    def _read_process_memory(psutil: Any) -> dict[str, Any] | None:
        """Read this process's RSS and VMS.

        Args:
            psutil: Imported psutil module.

        Returns:
            Process memory dict with ``scope`` ``"process"``, or ``None``.
        """
        try:
            proc = psutil.Process()
            mem = proc.memory_info()
            return {
                "scope": "process",
                "rss_mb": round(mem.rss / _MIB, 1),
                "vms_mb": round(mem.vms / _MIB, 1),
                "percent": round(float(proc.memory_percent()), 2),
            }
        except Exception:
            logger.exception("Process memory health check failed")
            return None

    def get_health(
        self,
        registry: Any | None = None,
        duckdb_paths: list[str | Path] | None = None,
        data_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        """Aggregate all health checks into a single response.

        Args:
            registry: Optional BrokerRegistry to check connections.
            duckdb_paths: Optional list of DuckDB paths to verify.
            data_dir: Optional data directory for disk space check.

        Returns:
            Dict with top-level ``status`` (``"ok"``, ``"degraded"``,
            ``"error"``) and sub-keys ``broker``, ``duckdb``,
            ``disk``, and ``memory``. ``cpu``, ``gpu``, and ``network``
            are included only when the install host can be read. They do
            not change the top-level status. Missing host figures are
            omitted or marked ``unavailable`` — never zero totals.
        """
        checks: dict[str, Any] = {}

        if registry is not None:
            checks["broker"] = self.check_broker_connections(registry)
        else:
            checks["broker"] = {"status": "ok", "note": "no registry provided"}

        if duckdb_paths is not None:
            checks["duckdb"] = self.check_duckdb(duckdb_paths)
        else:
            checks["duckdb"] = {"status": "ok", "note": "no paths provided"}

        checks["disk"] = self.check_disk_space(data_dir)
        checks["memory"] = self.check_memory()
        for key, reading in (
            ("cpu", self.check_cpu()),
            ("gpu", self.check_gpu()),
            ("network", self.check_network()),
        ):
            if reading is not None:
                checks[key] = reading

        # Service and disk/RAM faults roll up. CPU, GPU, and network stay
        # on their own rows so a busy host does not mark the backend down.
        statuses = [checks[key].get("status", "ok") for key in ("broker", "duckdb", "disk", "memory")]
        if "error" in statuses:
            overall = "error"
        elif "degraded" in statuses:
            overall = "degraded"
        else:
            overall = "ok"

        return {"status": overall, **checks}


# ---------------------------------------------------------------------------
# TrafficCounter
# ---------------------------------------------------------------------------


@dataclass
class _RequestRecord:
    """Internal record of a single HTTP request."""

    timestamp: float
    method: str
    path: str
    status: int
    duration_ms: float


class TrafficCounter:
    """Thread-safe HTTP traffic counter with a circular buffer.

    Tracks recent requests and computes per-window statistics.

    Args:
        buffer_size: Maximum number of request records to retain.

    Example::

        counter = TrafficCounter()
        counter.record("GET", "/v1/health", 200, 12.3)
        stats = counter.get_stats(minutes=5)
    """

    def __init__(self, buffer_size: int = 10_000) -> None:
        self._buffer: deque[_RequestRecord] = deque(maxlen=buffer_size)
        self._lock = threading.Lock()

    def record(
        self,
        method: str,
        path: str,
        status: int,
        duration_ms: float,
    ) -> None:
        """Add a request record to the buffer.

        Args:
            method: HTTP method (e.g. ``"GET"``, ``"POST"``).
            path: Request path (e.g. ``"/v1/health"``).
            status: HTTP status code.
            duration_ms: Request duration in milliseconds.
        """
        record = _RequestRecord(
            timestamp=time.time(),
            method=method,
            path=path,
            status=status,
            duration_ms=duration_ms,
        )
        with self._lock:
            self._buffer.append(record)

    def get_stats(self, minutes: int = 5) -> dict[str, Any]:
        """Compute traffic statistics over the last N minutes.

        Args:
            minutes: Lookback window in minutes.

        Returns:
            Dict with ``window_minutes``, ``total_requests``,
            ``requests_per_sec``, ``error_rate``, ``avg_latency_ms``,
            ``top_paths`` (list of ``{path, count}``).
        """
        cutoff = time.time() - minutes * 60
        with self._lock:
            window = [r for r in self._buffer if r.timestamp >= cutoff]

        total = len(window)
        if total == 0:
            return {
                "window_minutes": minutes,
                "total_requests": 0,
                "requests_per_sec": 0.0,
                "error_rate": 0.0,
                "avg_latency_ms": 0.0,
                "top_paths": [],
            }

        errors = sum(1 for r in window if r.status >= 400)
        avg_latency = sum(r.duration_ms for r in window) / total
        rps = total / (minutes * 60)

        path_counts: dict[str, int] = {}
        for r in window:
            path_counts[r.path] = path_counts.get(r.path, 0) + 1
        top_paths = sorted(
            [{"path": p, "count": c} for p, c in path_counts.items()],
            key=lambda x: x["count"],
            reverse=True,
        )[:10]

        return {
            "window_minutes": minutes,
            "total_requests": total,
            "requests_per_sec": round(rps, 4),
            "error_rate": round(errors / total, 4) if total > 0 else 0.0,
            "avg_latency_ms": round(avg_latency, 2),
            "top_paths": top_paths,
        }

    def get_recent(self, n: int = 100) -> list[dict[str, Any]]:
        """Return the last N request records.

        Args:
            n: Number of records to return.

        Returns:
            List of dicts with ``timestamp``, ``method``, ``path``,
            ``status``, ``duration_ms``, most recent last.
        """
        with self._lock:
            records = list(self._buffer)[-n:]
        return [
            {
                "timestamp": r.timestamp,
                "method": r.method,
                "path": r.path,
                "status": r.status,
                "duration_ms": r.duration_ms,
            }
            for r in records
        ]


# ---------------------------------------------------------------------------
# LatencyTracker
# ---------------------------------------------------------------------------


def _percentile(sorted_latencies: list[float], percentile: float) -> float:
    """Return one percentile of an already-sorted latency series.

    Defined at module level rather than inside the per-broker loop it serves.
    A nested helper closed over the loop's ``sorted_lat`` and ``n``, which was
    harmless because it was called in the same iteration - but only until
    someone stored or deferred it. Taking the series as an argument removes the
    question, and makes the calculation directly testable.

    Args:
        sorted_latencies: Latencies in ascending order.
        percentile: The percentile to read, 0-100.

    Returns:
        The percentile value rounded to two decimal places, or ``0.0`` when the
        series is empty.
    """
    if not sorted_latencies:
        return 0.0
    index = int(percentile / 100 * (len(sorted_latencies) - 1))
    return round(sorted_latencies[index], 2)


@dataclass
class _LatencyRecord:
    """Internal record of a single order RTT measurement."""

    timestamp: float
    broker: str
    symbol: str
    latency_ms: float


class LatencyTracker:
    """Track order round-trip latency per broker.

    Stores recent latency measurements and computes p50/p95/p99
    percentile statistics per broker.

    Example::

        tracker = LatencyTracker()
        tracker.record_order_latency("ZERODHA", "NIFTY", 42.5)
        stats = tracker.get_stats()
    """

    def __init__(self, buffer_size: int = 5_000) -> None:
        self._records: deque[_LatencyRecord] = deque(maxlen=buffer_size)
        self._lock = threading.Lock()

    def record_order_latency(
        self,
        broker: str,
        symbol: str,
        latency_ms: float,
    ) -> None:
        """Record an order round-trip latency measurement.

        Args:
            broker: Broker identifier (e.g. ``"ZERODHA"``).
            symbol: Instrument symbol.
            latency_ms: Round-trip latency in milliseconds.
        """
        rec = _LatencyRecord(
            timestamp=time.time(),
            broker=broker,
            symbol=symbol,
            latency_ms=latency_ms,
        )
        with self._lock:
            self._records.append(rec)

    def get_stats(self) -> dict[str, Any]:
        """Return latency statistics grouped by broker.

        Computes ``avg``, ``p50``, ``p95``, ``p99`` for each broker
        that has at least one recorded measurement.

        Returns:
            Dict mapping broker names to their statistics dict.
            Each stats dict has ``count``, ``avg_ms``, ``p50_ms``,
            ``p95_ms``, ``p99_ms``.
        """
        with self._lock:
            all_records = list(self._records)

        broker_map: dict[str, list[float]] = {}
        for r in all_records:
            broker_map.setdefault(r.broker, []).append(r.latency_ms)

        result: dict[str, Any] = {}
        for broker, latencies in broker_map.items():
            sorted_lat = sorted(latencies)
            n = len(sorted_lat)
            result[broker] = {
                "count": n,
                "avg_ms": round(sum(latencies) / n, 2),
                "p50_ms": _percentile(sorted_lat, 50),
                "p95_ms": _percentile(sorted_lat, 95),
                "p99_ms": _percentile(sorted_lat, 99),
            }

        return result

    def get_recent(self, n: int = 50) -> list[dict[str, Any]]:
        """Return the last N latency records.

        Args:
            n: Number of records to return.

        Returns:
            List of dicts with ``timestamp``, ``broker``, ``symbol``,
            ``latency_ms``, most recent last.
        """
        with self._lock:
            records = list(self._records)[-n:]
        return [
            {
                "timestamp": r.timestamp,
                "broker": r.broker,
                "symbol": r.symbol,
                "latency_ms": r.latency_ms,
            }
            for r in records
        ]
