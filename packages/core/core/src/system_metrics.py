"""System resource metrics for the /admin route.

Collects CPU, memory, disk, network, and process metrics via psutil.
psutil is an optional dependency — if absent, all fields return zero/empty
values so the admin panel degrades gracefully.

Usage::

    from flinttrade_core.system_metrics import get_system_metrics

    metrics = get_system_metrics()
    print(metrics.cpu_percent, metrics.memory_percent)
"""

from __future__ import annotations

import logging
import time
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("flinttrade.core.system_metrics")

# ---------------------------------------------------------------------------
# Optional psutil import — graceful fallback when not installed
# ---------------------------------------------------------------------------

try:
    import psutil as _psutil  # type: ignore[import]

    _PSUTIL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _psutil = None  # type: ignore[assignment]
    _PSUTIL_AVAILABLE = False
    logger.debug("psutil not installed — system metrics will return empty values")


# ---------------------------------------------------------------------------
# Pydantic model
# ---------------------------------------------------------------------------


class SystemMetrics(BaseModel):
    """Snapshot of host-level resource usage.

    All numeric fields default to ``0.0`` so that callers can safely read
    them even when psutil is unavailable.
    """

    cpu_percent: float = Field(default=0.0, description="CPU utilisation as a percentage (0–100).")
    memory_percent: float = Field(default=0.0, description="RAM utilisation as a percentage (0–100).")
    memory_used_gb: float = Field(default=0.0, description="RAM currently in use, in GiB.")
    memory_total_gb: float = Field(default=0.0, description="Total physical RAM, in GiB.")
    disk_percent: float = Field(default=0.0, description="Root-disk utilisation as a percentage (0–100).")
    disk_used_gb: float = Field(default=0.0, description="Root-disk space used, in GiB.")
    disk_total_gb: float = Field(default=0.0, description="Root-disk total space, in GiB.")
    uptime_seconds: float = Field(default=0.0, description="System uptime in seconds since last boot.")
    process_count: int = Field(default=0, description="Number of running processes on the host.")
    network_bytes_sent: int = Field(default=0, description="Cumulative bytes sent on all interfaces.")
    network_bytes_recv: int = Field(default=0, description="Cumulative bytes received on all interfaces.")
    psutil_available: bool = Field(
        default=False,
        description="Whether psutil was available when metrics were collected.",
    )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary of all metrics.

        Returns:
            Dict with all metric field names mapped to their current values.
        """
        return self.model_dump()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_system_metrics() -> SystemMetrics:
    """Collect a snapshot of host-level resource usage.

    Uses ``psutil`` when available.  Returns a ``SystemMetrics`` instance with
    all fields set to zero when psutil is not installed, so callers never have
    to guard against ``None``.

    Returns:
        A :class:`SystemMetrics` instance populated with current values (or
        zeroed defaults if psutil is absent).
    """
    if not _PSUTIL_AVAILABLE:
        logger.debug("psutil unavailable — returning empty SystemMetrics")
        return SystemMetrics(psutil_available=False)

    try:
        cpu = _psutil.cpu_percent(interval=0.1)

        mem = _psutil.virtual_memory()
        _GIB = 1024 ** 3
        memory_used_gb = round(mem.used / _GIB, 2)
        memory_total_gb = round(mem.total / _GIB, 2)

        disk = _psutil.disk_usage("/")
        disk_used_gb = round(disk.used / _GIB, 2)
        disk_total_gb = round(disk.total / _GIB, 2)

        boot_time = _psutil.boot_time()
        uptime = round(time.time() - boot_time, 1)

        proc_count = len(_psutil.pids())

        net = _psutil.net_io_counters()
        net_sent = net.bytes_sent
        net_recv = net.bytes_recv

        return SystemMetrics(
            cpu_percent=round(cpu, 1),
            memory_percent=round(mem.percent, 1),
            memory_used_gb=memory_used_gb,
            memory_total_gb=memory_total_gb,
            disk_percent=round(disk.percent, 1),
            disk_used_gb=disk_used_gb,
            disk_total_gb=disk_total_gb,
            uptime_seconds=uptime,
            process_count=proc_count,
            network_bytes_sent=net_sent,
            network_bytes_recv=net_recv,
            psutil_available=True,
        )
    except Exception as exc:
        logger.error("Failed to collect system metrics: %s", exc)
        return SystemMetrics(psutil_available=False)
