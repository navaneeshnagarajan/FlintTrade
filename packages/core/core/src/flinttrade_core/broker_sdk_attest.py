"""Broker SDK attestation.

Native broker adapters that place live orders must run against the exact SDK
version pinned in ``brokers.lock`` so the runtime can record which SDK built an
order-capable request. This module verifies the installed broker SDKs against
those pins and exposes the result so the runtime can:

* log an honest attestation report at boot, and
* halt orders for a broker whose SDK is missing or version-mismatched
  (``attest_loop`` + an ``on_failure`` hook) once that broker is wired live.

It is intentionally dependency-light and injectable: ``attest_all`` takes a
``version_resolver`` so it can be unit-tested without the SDKs installed.
"""

from __future__ import annotations

import logging
import tomllib
from collections.abc import Callable
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

logger = logging.getLogger("flinttrade.core.broker_sdk_attest")

_PLACEHOLDER = "PLACEHOLDER"

STATUS_OK = "ok"
STATUS_MISMATCH = "mismatch"
STATUS_MISSING = "missing"
STATUS_SKIPPED = "skipped"  # pin not yet populated (placeholder) — broker not live

# brokers.lock pin name → installed distribution name for version lookup.
_DIST_NAMES: dict[str, str] = {
    "dhanhq": "dhanhq",
    "upstox-python-sdk": "upstox-python-sdk",
    "neo-api-client": "neo-api-client",
}


@dataclass
class AttestationResult:
    broker: str
    pinned_version: str
    installed_version: str | None
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _default_brokers_lock() -> Path:
    # packages/core/core/src/flinttrade_core/broker_sdk_attest.py → repo root.
    return Path(__file__).resolve().parents[5] / "brokers.lock"


def load_pins(lock_path: Path | None = None) -> list[dict[str, Any]]:
    """Parse ``brokers.lock`` and return its ``[[broker]]`` entries."""
    path = lock_path or _default_brokers_lock()
    if not path.exists():
        logger.warning("brokers.lock not found at %s — no SDK attestation possible", path)
        return []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        logger.warning("Could not parse brokers.lock (%s)", exc)
        return []
    brokers = data.get("broker", [])
    return brokers if isinstance(brokers, list) else []


def _installed_version(dist: str) -> str | None:
    try:
        return metadata.version(dist)
    except metadata.PackageNotFoundError:
        return None


def attest_all(
    lock_path: Path | None = None,
    version_resolver: Callable[[str], str | None] | None = None,
) -> list[AttestationResult]:
    """Attest every pinned broker SDK against the installed version.

    Args:
        lock_path: Override the brokers.lock location (tests).
        version_resolver: ``dist_name -> installed_version|None`` (tests).

    Returns:
        One :class:`AttestationResult` per pin. Placeholder pins (broker not yet
        live) are ``skipped``.
    """
    resolve = version_resolver or _installed_version
    results: list[AttestationResult] = []
    for pin in load_pins(lock_path):
        name = str(pin.get("name", "")).strip()
        pinned = str(pin.get("version", "")).strip()
        if not name:
            continue
        if not pinned or _PLACEHOLDER in pinned.upper():
            results.append(AttestationResult(name, pinned, None, STATUS_SKIPPED))
            continue
        installed = resolve(_DIST_NAMES.get(name, name))
        if installed is None:
            status = STATUS_MISSING
        elif installed == pinned:
            status = STATUS_OK
        else:
            status = STATUS_MISMATCH
        results.append(AttestationResult(name, pinned, installed, status))
    return results


def required_failures(results: list[AttestationResult]) -> list[AttestationResult]:
    """Results that would block a live broker (missing / version mismatch)."""
    return [r for r in results if r.status in (STATUS_MISMATCH, STATUS_MISSING)]


def attest_all_ok(results: list[AttestationResult]) -> bool:
    """True when no non-skipped pin is missing or mismatched."""
    return not required_failures(results)


def log_report(results: list[AttestationResult]) -> None:
    """Emit a human-readable attestation summary to the log."""
    if not results:
        logger.info("Broker SDK attestation: no pins to check")
        return
    for r in results:
        if r.status == STATUS_OK:
            logger.info("Broker SDK attest: %s %s OK", r.broker, r.pinned_version)
        elif r.status == STATUS_SKIPPED:
            logger.info("Broker SDK attest: %s not yet pinned (skipped)", r.broker)
        elif r.status == STATUS_MISSING:
            logger.warning(
                "Broker SDK attest: %s SDK NOT INSTALLED (pinned %s) — cannot go live",
                r.broker, r.pinned_version,
            )
        else:  # mismatch
            logger.warning(
                "Broker SDK attest: %s version MISMATCH (pinned %s, installed %s) — "
                "orders for this broker must be halted",
                r.broker, r.pinned_version, r.installed_version,
            )


async def attest_loop(
    interval_seconds: float = 3600.0,
    on_failure: Callable[[list[AttestationResult]], None] | None = None,
    lock_path: Path | None = None,
) -> None:
    """Re-attest periodically; call ``on_failure`` when a live broker's SDK fails.

    Runs until cancelled. ``on_failure`` receives the failing results so the
    caller can halt the affected brokers' order routing.
    """
    import asyncio  # noqa: PLC0415

    while True:
        results = attest_all(lock_path)
        log_report(results)
        fails = required_failures(results)
        if fails and on_failure is not None:
            on_failure(fails)
        await asyncio.sleep(interval_seconds)
