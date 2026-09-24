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

import json
import logging
import re
import tomllib
from collections.abc import Callable
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .source_root import discover_source_root

logger = logging.getLogger("flinttrade.core.broker_sdk_attest")

_PLACEHOLDER = "PLACEHOLDER"

STATUS_OK = "ok"
STATUS_MISMATCH = "version_mismatch"
STATUS_MISSING = "missing"
STATUS_PROVENANCE_MISMATCH = "provenance_mismatch"
STATUS_CONFLICT = "conflict"
STATUS_SKIPPED = "skipped"  # pin not yet populated (placeholder) — broker not live
STATUS_NOT_REQUIRED = "not_required"  # REST-native broker has no third-party SDK to attest
STATUS_UNKNOWN = "unknown"

# brokers.lock pin name → installed distribution name for version lookup.
_DIST_NAMES: dict[str, str] = {
    "dhanhq": "dhanhq",
    "growwapi": "growwapi",
    "upstox-python-sdk": "upstox-python-sdk",
    "kotakneoapi": "kotakneoapi",
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
    return discover_source_root() / "brokers.lock"


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


def _distribution_name(dist: metadata.Distribution) -> str:
    """Normalise installed distribution names per Python packaging conventions."""
    return re.sub(r"[-_.]+", "-", str(dist.metadata.get("Name", "")).lower())


def _owns_neo_namespace(dist: metadata.Distribution) -> bool:
    top_level = dist.read_text("top_level.txt") or ""
    if "neo_api_client" in top_level.splitlines():
        return True
    return any(str(file).replace("\\", "/").split("/")[0] == "neo_api_client" for file in (dist.files or ()))


def _kotak_provenance_matches(dist: metadata.Distribution, source_commit: str) -> bool:
    raw = dist.read_text("direct_url.json")
    if not raw:
        return False
    try:
        data = json.loads(raw)
        vcs = data["vcs_info"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(vcs, dict):
        return False
    try:
        url = urlsplit(data["url"])
        origin_ok = (
            url.scheme == "https" and url.hostname == "github.com"
            and url.username is None and url.password is None and url.port is None
            and url.path == "/Kotak-Neo/kotak-neo-python.git"
            and not url.query and not url.fragment
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
    if not origin_ok or vcs.get("vcs") != "git" or vcs.get("commit_id") != source_commit:
        return False
    requested = vcs.get("requested_revision")
    return requested is None or requested == source_commit


def _attest_kotak(pin: dict[str, Any]) -> tuple[str | None, str]:
    distributions = list(metadata.distributions())
    kotak = [dist for dist in distributions if _distribution_name(dist) == "kotakneoapi"]
    old = [dist for dist in distributions if _distribution_name(dist) == "neo-api-client"]
    other_owners = [
        dist for dist in distributions
        if _distribution_name(dist) not in {"kotakneoapi", "neo-api-client"} and _owns_neo_namespace(dist)
    ]
    if old or other_owners or len(kotak) > 1:
        return (kotak[0].version if kotak else None), STATUS_CONFLICT
    if not kotak:
        return None, STATUS_MISSING
    installed = kotak[0].version
    if not _owns_neo_namespace(kotak[0]):
        return installed, STATUS_CONFLICT
    if installed != str(pin.get("version", "")):
        return installed, STATUS_MISMATCH
    source_commit = str(pin.get("source_commit", ""))
    if not source_commit or not _kotak_provenance_matches(kotak[0], source_commit):
        return installed, STATUS_PROVENANCE_MISMATCH
    return installed, STATUS_OK


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
        if name == "kotakneoapi" and version_resolver is None:
            installed, status = _attest_kotak(pin)
        else:
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
    return [
        r for r in results
        if r.status in (STATUS_MISMATCH, STATUS_MISSING, STATUS_PROVENANCE_MISMATCH, STATUS_CONFLICT)
    ]


def attest_all_ok(results: list[AttestationResult]) -> bool:
    """True when no non-skipped pin is missing or mismatched."""
    return not required_failures(results)


def attestations_by_pin(
    lock_path: Path | None = None,
    version_resolver: Callable[[str], str | None] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return serialisable attestation rows keyed by brokers.lock pin name."""
    return {
        result.broker: {
            "pin": result.broker,
            "pinned_version": result.pinned_version,
            "installed_version": result.installed_version,
            "status": result.status,
        }
        for result in attest_all(lock_path=lock_path, version_resolver=version_resolver)
    }


def sdk_attestation_fields(
    sdk_pin: str | None,
    *,
    attestations: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the public catalogue SDK fields for one native broker.

    ``sdk_pin=None`` is intentional for REST-native brokers such as INDmoney:
    activation is credential-gated, not SDK-gated. Missing attestation data is
    surfaced as ``unknown`` rather than throwing from read-only catalogue routes.
    """
    if sdk_pin is None:
        return {
            "sdk_pin": None,
            "sdk_attestation": {
                "pin": None,
                "pinned_version": None,
                "installed_version": None,
                "status": STATUS_NOT_REQUIRED,
            },
        }
    rows = attestations if attestations is not None else attestations_by_pin()
    attestation = rows.get(sdk_pin)
    if attestation is None:
        attestation = {
            "pin": sdk_pin,
            "pinned_version": None,
            "installed_version": None,
            "status": STATUS_UNKNOWN,
        }
    return {"sdk_pin": sdk_pin, "sdk_attestation": attestation}


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
