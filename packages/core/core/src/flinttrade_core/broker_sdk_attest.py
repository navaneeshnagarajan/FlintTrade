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

import hashlib
import json
import logging
import re
import tomllib
from collections.abc import Callable
from dataclasses import asdict, dataclass
from importlib import metadata, util
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
    # Configured policy kind, not an additional provenance/eligibility verdict.
    # An explicit version-only test resolver never populates this field.
    source_kind: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        if self.source_kind is None:
            result.pop("source_kind")
        return result


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
            url.scheme == "https"
            and url.hostname == "github.com"
            and url.username is None
            and url.password is None
            and url.port is None
            and url.path == "/Kotak-Neo/kotak-neo-python.git"
            and not url.query
            and not url.fragment
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
        dist
        for dist in distributions
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


_SOURCE_IDENTITIES = {
    "dhanhq": ("dhanhq", "https://github.com/dhan-oss/DhanHQ-py.git"),
    "upstox-python-sdk": ("upstox_client", "https://github.com/upstox/upstox-python.git"),
    "kotakneoapi": ("neo_api_client", "https://github.com/Kotak-Neo/kotak-neo-python.git"),
    "growwapi": ("growwapi", None),
}


# Explicit Groww-only policy: official SDK Git source and publisher attestation
# are unavailable. These independently reviewed wheel pins are not Git identity.
# The inventory seal is SHA256 of sorted, compact JSON for all original wheel
# files except installer-rewritten RECORD. Includes package resources and build/
# licence metadata. Updating this release requires reviewing new official bytes.
_GROWW_RELEASE_ARTIFACT = {
    "filename": "growwapi-1.5.0-py3-none-any.whl",
    "url": "https://files.pythonhosted.org/packages/e1/69/7dd0766c3a9dcf2688eb363a90fadca7a8388ac947efebd737b830bd478a/growwapi-1.5.0-py3-none-any.whl",
    "sha256": "b4871ed19415b6ad7434bee2178f53aa1e180fbddd4a25693c458440f66939cc",
}
_GROWW_RELEASE_FILES_SHA256 = "550a790160b9cb2e905b2885d38eab6cdab3a40e6998154242cc8478f3d2fc25"


def _published_release_pin_matches(pin: dict[str, Any]) -> bool:
    """Bind installed bytes to one trusted release pin, not publisher provenance."""
    files = pin.get("build_files")
    if (
        pin.get("name") != "growwapi"
        or pin.get("version") != "1.5.0"
        or pin.get("source_kind") != "published-release"
        or pin.get("source_module") != "growwapi"
        or any(key in pin for key in ("source_url", "source_commit", "source_tree"))
        or pin.get("release_artifact") != _GROWW_RELEASE_ARTIFACT
        or pin.get("sha256") != _GROWW_RELEASE_ARTIFACT["sha256"]
        or pin.get("build_wheel_sha256") != _GROWW_RELEASE_ARTIFACT["sha256"]
        or type(files) is not dict
        or any(type(k) is not str or type(v) is not str for k, v in files.items())
    ):
        return False
    inventory = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(inventory).hexdigest() == _GROWW_RELEASE_FILES_SHA256


def _published_release_direct_url_matches(raw: str | None) -> bool:
    """A registry install has no PEP610 URL; a supplied URL must corroborate it."""
    if raw is None:
        return True

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = dict(pairs)
        if len(result) != len(pairs):
            raise ValueError("Duplicate direct URL field")
        return result

    try:
        direct = json.loads(raw, object_pairs_hook=unique_object)
        if type(direct) is not dict or set(direct) != {"url", "archive_info"}:
            return False
        if direct["url"] != _GROWW_RELEASE_ARTIFACT["url"]:
            return False
        archive = direct["archive_info"]
        if type(archive) is not dict or not archive or set(archive) - {"hash", "hashes"}:
            return False
        digest = _GROWW_RELEASE_ARTIFACT["sha256"]
        return (
            ("hash" not in archive or archive["hash"] == "sha256=" + digest)
            and ("hashes" not in archive or archive["hashes"] == {"sha256": digest})
        )
    except (TypeError, ValueError):
        return False


def _attest_source(pin: dict[str, Any]) -> tuple[str | None, str]:
    """Check source, installed build bytes and import ownership, not just version."""
    name = pin.get("name")
    identity = _SOURCE_IDENTITIES.get(name) if type(name) is str else None
    if identity is None:
        return None, STATUS_PROVENANCE_MISMATCH
    module, source_url = identity
    distributions = list(metadata.distributions())
    selected = [dist for dist in distributions if _distribution_name(dist) == name]
    if len(selected) > 1:
        return selected[0].version, STATUS_CONFLICT
    if not selected:
        return None, STATUS_MISSING
    dist = selected[0]
    installed = dist.version
    if installed != pin.get("version"):
        return installed, STATUS_MISMATCH
    for other in distributions:
        if other is dist:
            continue
        top_level = (other.read_text("top_level.txt") or "").splitlines()
        if module in top_level or any(str(file).split("/")[0] == module for file in (other.files or ())):
            return installed, STATUS_CONFLICT
    release = name == "growwapi"
    if release:
        if not _published_release_pin_matches(pin):
            return installed, STATUS_PROVENANCE_MISMATCH
    elif (
        pin.get("source_url") != source_url
        or pin.get("source_module") != module
        or any(not re.fullmatch(r"[0-9a-f]{40}", str(pin.get(key, ""))) for key in ("source_commit", "source_tree"))
        or not re.fullmatch(r"[0-9a-f]{64}", str(pin.get("build_wheel_sha256", "")))
    ):
        return installed, STATUS_PROVENANCE_MISMATCH
    if not release and pin.get("source_kind") == "git":
        try:
            direct = json.loads(dist.read_text("direct_url.json") or "null")
            vcs = direct["vcs_info"]
            if (
                direct["url"] != source_url
                or vcs.get("vcs") != "git"
                or vcs.get("commit_id") != pin["source_commit"]
                or vcs.get("requested_revision", pin["source_commit"]) != pin["source_commit"]
            ):
                return installed, STATUS_PROVENANCE_MISMATCH
        except (KeyError, TypeError, ValueError, AttributeError):
            return installed, STATUS_PROVENANCE_MISMATCH
    elif not release and not (name == "dhanhq" and pin.get("source_kind") == "published-rc"):
        return installed, STATUS_PROVENANCE_MISMATCH
    files = pin.get("build_files")
    if type(files) is not dict or not files or f"{module}/__init__.py" not in files:
        return installed, STATUS_PROVENANCE_MISMATCH
    try:
        root = Path(str(dist.locate_file(""))).resolve(strict=True)
        package = root / module
        if release:
            info = root / "growwapi-1.5.0.dist-info"
            for base in (package, info):
                if base.is_symlink() or not base.is_dir():
                    return installed, STATUS_PROVENANCE_MISMATCH
                for path in base.rglob("*"):
                    if path.is_symlink() or not (path.is_file() or path.is_dir()):
                        return installed, STATUS_PROVENANCE_MISMATCH
            # Only installer bookkeeping may accompany the original wheel metadata.
            # Its RECORD is not a source of resource hashes or completeness authority.
            generated = {f"{info.name}/{name}" for name in ("RECORD", "INSTALLER", "REQUESTED", "direct_url.json")}
            actual_metadata = {path.relative_to(root).as_posix() for path in info.rglob("*") if path.is_file()}
            expected_metadata = {key for key in files if key.startswith(info.name + "/")}
            if actual_metadata - generated != expected_metadata:
                return installed, STATUS_PROVENANCE_MISMATCH
            if not _published_release_direct_url_matches(dist.read_text("direct_url.json")):
                return installed, STATUS_PROVENANCE_MISMATCH
        spec = util.find_spec(module)
        if spec is None or spec.origin is None or Path(spec.origin).resolve() != package / "__init__.py":
            return installed, STATUS_CONFLICT
        # RECORD is not an authority: compare physical package resources with
        # the independently locked built wheel, including unrecorded additions.
        expected = {path for path in files if type(path) is str and path.startswith(module + "/")}
        actual = {
            path.relative_to(root).as_posix()
            for path in package.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
        }
        if actual != expected:
            return installed, STATUS_PROVENANCE_MISMATCH
        for relative, digest in files.items():
            if type(relative) is not str or type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest):
                return installed, STATUS_PROVENANCE_MISMATCH
            path = root / relative
            if Path(relative).is_absolute() or ".." in Path(relative).parts or path.is_symlink():
                return installed, STATUS_PROVENANCE_MISMATCH
            if not path.resolve(strict=True).is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                return installed, STATUS_PROVENANCE_MISMATCH
    except (OSError, ValueError, TypeError, ImportError, AttributeError):
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
        # The explicit release exception requires a concrete version; it cannot
        # be converted into a non-blocking placeholder by incomplete metadata.
        release_claim = version_resolver is None and (name == "growwapi" or pin.get("source_kind") == "published-release")
        if (not pinned or _PLACEHOLDER in pinned.upper()) and not release_claim:
            results.append(AttestationResult(name, pinned, None, STATUS_SKIPPED))
            continue
        source_kind = None
        if version_resolver is None and (name in _DIST_NAMES or pin.get("source_kind")):
            installed, status = _attest_source(pin)
            kind = pin.get("source_kind")
            if type(kind) is str and kind in ("git", "published-rc", "published-release"):
                source_kind = kind
        else:
            installed = resolve(_DIST_NAMES.get(name, name))
            if installed is None:
                status = STATUS_MISSING
            elif installed == pinned:
                status = STATUS_OK
            else:
                status = STATUS_MISMATCH
        results.append(AttestationResult(name, pinned, installed, status, source_kind))
    return results


def required_failures(results: list[AttestationResult]) -> list[AttestationResult]:
    """Results that would block a live broker (missing / version mismatch)."""
    return [
        r for r in results if r.status in (STATUS_MISMATCH, STATUS_MISSING, STATUS_PROVENANCE_MISMATCH, STATUS_CONFLICT)
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
            **({"source_kind": result.source_kind} if result.source_kind is not None else {}),
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
                r.broker,
                r.pinned_version,
            )
        else:  # mismatch
            logger.warning(
                "Broker SDK attest: %s version MISMATCH (pinned %s, installed %s) — "
                "orders for this broker must be halted",
                r.broker,
                r.pinned_version,
                r.installed_version,
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
