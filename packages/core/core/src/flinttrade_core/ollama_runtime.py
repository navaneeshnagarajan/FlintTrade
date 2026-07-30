"""FlintTrade-managed Ollama server runtime."""

from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.request
import weakref
import zipfile
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Callable, Iterator
from urllib.parse import urlsplit

import psutil
from filelock import BaseFileLock, Timeout as FileLockTimeout

from .owner_file_lock import OwnerSafeFileLock, UnsafeFileLockPathError
from .secure_file import durable_replace, durable_unlink, fsync_parent_directory, harden, harden_directory


class OllamaRuntimeError(RuntimeError):
    """Raised when the managed local inference runtime cannot proceed."""


class _OllamaOperationCancelled(OllamaRuntimeError):
    """Raised internally when an operator cancels background runtime work."""


class _OllamaLifecycleCleanupTimedOut(OllamaRuntimeError):
    """Raised when mutation outcome is known only up to lifecycle cleanup."""


class _RuntimeFileLock(OwnerSafeFileLock):  # type: ignore[misc, valid-type]
    """Translate shared lock-path validation into the runtime error contract."""

    def _acquire(self) -> None:
        try:
            super()._acquire()
        except UnsafeFileLockPathError as exc:
            raise OllamaRuntimeError("managed Ollama lease path is unsafe") from exc


@dataclass(frozen=True)
class OllamaAsset:
    """One pinned official Ollama server archive."""

    name: str
    sha256: str
    url: str
    max_extracted_bytes: int
    size_bytes: int = 0
    executable_candidates: tuple[str, ...] = ("ollama", "bin/ollama", "ollama.exe", "bin/ollama.exe")


@dataclass(frozen=True)
class ManagedOllamaAdmission:
    """One model-and-endpoint admission held for a complete inference."""

    base_url: str
    model: str
    digest: str


_OLLAMA_VERSION = "v0.32.0"
_OLLAMA_SERVER_VERSION = _OLLAMA_VERSION.removeprefix("v")
_OLLAMA_ROLLBACK_VERSIONS = ("v0.31.2",)
_LIFECYCLE_LOCK_NAME = ".ollama-lifecycle.lock"
_ASSETS_BY_VERSION: dict[str, dict[tuple[str, str], tuple[str, str, int, int]]] = {
    "v0.32.0": {
        ("darwin", "arm64"): (
            "ollama-darwin.tgz",
            "3b12a49c6c4cbafd7ffba5ccba60cbf80274cdc22eea3ead79c646aba888174c",
            145_356_966,
            512 * 1024 * 1024,
        ),
        ("darwin", "x86_64"): (
            "ollama-darwin.tgz",
            "3b12a49c6c4cbafd7ffba5ccba60cbf80274cdc22eea3ead79c646aba888174c",
            145_356_966,
            512 * 1024 * 1024,
        ),
        ("linux", "x86_64"): (
            "ollama-linux-amd64.tar.zst",
            "56362d7609dfa9e35aaebb7c9cab25605d8f0528ec3d5d585dc83d6642002bab",
            1_436_128_693,
            6 * 1024 * 1024 * 1024,
        ),
        ("linux", "arm64"): (
            "ollama-linux-arm64.tar.zst",
            "2c1fbc47a5351c74f5400d7e4b1104bb470291af5d2f425c37c151487a477ad6",
            1_556_234_636,
            6 * 1024 * 1024 * 1024,
        ),
        ("windows", "x86_64"): (
            "ollama-windows-amd64.zip",
            "56561a8f0a904483303c610e61af61c5a7b6f5496ce3707e207d25d4ff67b89e",
            1_503_047_573,
            6 * 1024 * 1024 * 1024,
        ),
        ("windows", "arm64"): (
            "ollama-windows-arm64.zip",
            "82b7d36b63e62a44d3f9853c2f8edb829cf871eaf722ce20070e09e96922c0cc",
            16_346_970,
            256 * 1024 * 1024,
        ),
    },
    "v0.31.2": {
        ("darwin", "arm64"): (
            "ollama-darwin.tgz",
            "d72381baa260f6ce014c8e942e605eac76cac5313fcb3401eaf5495f659cfd6d",
            128_859_228,
            512 * 1024 * 1024,
        ),
        ("darwin", "x86_64"): (
            "ollama-darwin.tgz",
            "d72381baa260f6ce014c8e942e605eac76cac5313fcb3401eaf5495f659cfd6d",
            128_859_228,
            512 * 1024 * 1024,
        ),
        ("linux", "x86_64"): (
            "ollama-linux-amd64.tar.zst",
            "2c88f0f31a959bac5a3cad4cc5296ec568551d4aa79f548f554adb2b575b3133",
            1_435_434_289,
            6 * 1024 * 1024 * 1024,
        ),
        ("linux", "arm64"): (
            "ollama-linux-arm64.tar.zst",
            "07a0adfcf3ed48ff110e2a3bcec897ca4d3f77d6f817d6ff63e83debfd102a31",
            1_556_004_266,
            6 * 1024 * 1024 * 1024,
        ),
        ("windows", "x86_64"): (
            "ollama-windows-amd64.zip",
            "6988b58d2223ae3f9d5766b46b0be614dec36524b80317159718b5adf3006f3b",
            1_502_730_186,
            6 * 1024 * 1024 * 1024,
        ),
        ("windows", "arm64"): (
            "ollama-windows-arm64.zip",
            "52d2273a05e1d939f112aff9f160e87d64ee01a47c81d93c1549fe22ffe8773a",
            16_060_468,
            256 * 1024 * 1024,
        ),
    },
}
_ACCELERATOR_ASSETS_BY_VERSION: dict[
    str,
    dict[tuple[str, str, str], tuple[str, str, int, int]],
] = {
    "v0.32.0": {
        ("linux", "x86_64", "rocm"): (
            "ollama-linux-amd64-rocm.tar.zst",
            "f0fad39e184daab11d172a855580abd7338b2f049afa462435fee15d76b4e437",
            1_047_646_096,
            5 * 1024 * 1024 * 1024,
        ),
        ("linux", "arm64", "jetpack5"): (
            "ollama-linux-arm64-jetpack5.tar.zst",
            "37001e09512e68e7e205dcfff0876e43e631b546c9b19a77a68b9115dd67b19b",
            299_324_082,
            2 * 1024 * 1024 * 1024,
        ),
        ("linux", "arm64", "jetpack6"): (
            "ollama-linux-arm64-jetpack6.tar.zst",
            "89244534ec56a68093334d3957dd968a53328a02a8f155cbabc1f977c7c4537b",
            274_009_059,
            2 * 1024 * 1024 * 1024,
        ),
    },
    "v0.31.2": {
        ("linux", "x86_64", "rocm"): (
            "ollama-linux-amd64-rocm.tar.zst",
            "f0fad39e184daab11d172a855580abd7338b2f049afa462435fee15d76b4e437",
            1_047_646_096,
            5 * 1024 * 1024 * 1024,
        ),
        ("linux", "arm64", "jetpack5"): (
            "ollama-linux-arm64-jetpack5.tar.zst",
            "37001e09512e68e7e205dcfff0876e43e631b546c9b19a77a68b9115dd67b19b",
            299_324_082,
            2 * 1024 * 1024 * 1024,
        ),
        ("linux", "arm64", "jetpack6"): (
            "ollama-linux-arm64-jetpack6.tar.zst",
            "1879c2132193098e6f0ae7c0d5489583779ee06f5a4a1dbdcb509ff46837324a",
            274_016_552,
            2 * 1024 * 1024 * 1024,
        ),
    },
}

_INSTALL_DISK_RESERVE_BYTES = 512 * 1024 * 1024
_MAX_RUNTIME_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
_DEFAULT_EXTRACTION_BUDGET_BYTES = 8 * 1024 * 1024 * 1024
_MAX_EXTRACTED_MEMBERS = 50_000
_MAX_RUNTIME_TREE_ENTRIES = (_MAX_EXTRACTED_MEMBERS * 2) + 2
_MAX_RUNTIME_TREE_BYTES = 16 * 1024 * 1024 * 1024
_MAX_RUNTIME_ROOT_ENTRIES = 1_024
_INSTALL_MANIFEST_NAME = ".flinttrade-executable-manifest.json"
_INSTALL_MARKER_NAME = ".flinttrade-install-complete.json"
_MAX_INSTALL_MANIFEST_BYTES = 32 * 1024 * 1024
_MAX_INSTALL_MARKER_BYTES = 16 * 1024
_MODEL_DIGESTS_NAME = ".flinttrade-model-digests.json"
_MODEL_DIGEST = re.compile(r"(?:sha256:)?([0-9a-fA-F]{64})\Z")
_MAX_MODEL_PULL_BYTES = 64 * 1024 * 1024 * 1024
_MAX_MODEL_STORE_BYTES = 128 * 1024 * 1024 * 1024
_MAX_MODEL_STORE_ENTRIES = 1_000_000
_MAX_MANAGED_STORAGE_BYTES = 128 * 1024 * 1024 * 1024
_MAX_MANAGED_STORAGE_ENTRIES = 1_100_000
_MODEL_PULL_DISK_RESERVE_BYTES = 2 * 1024 * 1024 * 1024
_RUNTIME_DOWNLOAD_DEADLINE_SECONDS = 2 * 60 * 60
_PROCESS_TREE_STOP_TIMEOUT_SECONDS = 20.0
_INFERENCE_STOP_GRACE_SECONDS = 5.0
_SYNC_LIFECYCLE_WAIT_SECONDS = 30.0
_PROBE_DEADLINE_SECONDS = 0.5
_MAX_PROBE_RESPONSE_BYTES = 16 * 1024
_MAX_PROBE_HEADER_BYTES = 8 * 1024
_MAX_OLLAMA_API_RESPONSE_BYTES = 16 * 1024 * 1024
_PROCESS_OWNER_STATE_NAME = ".flinttrade-process-owner.json"
_RUNTIME_STATE_NAME = ".flinttrade-runtime-state.json"
_MAX_RUNTIME_STATE_BYTES = 4096
_OPERATION_STATE_NAME = ".flinttrade-operation-state.json"
_OPERATION_STATE_SCHEMA = 4
_OPERATION_JOURNAL_MARKER_NAME = ".flinttrade-operation-journal.json"
_MAX_OPERATION_JOURNAL_MARKER_BYTES = 128
_OPERATION_LOCK_NAME = ".flinttrade-operation.lock"
_OPERATION_OWNER_LOCK_NAME = ".flinttrade-operation-owner.lock"
_MAX_OPERATION_RECEIPTS = 4096
_OPERATION_SPENT_FILTER_BYTES = 4 * 1024 * 1024
_OPERATION_SPENT_FILTER_HASHES = 7
_MAX_OPERATION_STATE_BYTES = 32 * 1024 * 1024
_MAX_OPERATION_RESULT_MODELS = 500
_UNINSTALL_STATE_NAME = ".flinttrade-uninstall-state.json"
_MAX_UNINSTALL_STATE_BYTES = 16 * 1024
_REPAIR_STATE_NAME = ".flinttrade-repair-state.json"
_MAX_REPAIR_STATE_BYTES = 4096
_RESIDUE_MARKER_NAME = ".flinttrade-residue-owner.json"
_STALE_RESIDUE_SECONDS = 24 * 60 * 60
_MAX_LOG_FILE_BYTES = 8 * 1024 * 1024
_LOG_BACKUP_COUNT = 4
_MAX_LOG_STORAGE_BYTES = _MAX_LOG_FILE_BYTES * (_LOG_BACKUP_COUNT + 1)
_LOCKED_MODEL_PREFIX = "flinttrade/sha256-"
_LOCKED_MODEL_SUFFIX = ":locked"
_MANAGED_RUNTIME_OWNER_LOCK = threading.RLock()
_MANAGED_RUNTIME_OWNER: weakref.ReferenceType[Any] | None = None
_LOOPBACK_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_OPERATION_ID = re.compile(r"op_[0-9a-f]{32}\Z")
_ADMISSION_ID = re.compile(r"adm_[0-9a-f]{32}\Z")
_OPERATION_OWNER_TOKEN = re.compile(r"[0-9a-f]{32}\Z")
_OPERATION_KINDS = {
    "install",
    "update",
    "repair",
    "rollback",
    "uninstall",
    "start",
    "pull_model",
    "delete_model",
    "prune_models",
    "reset_model_digests",
    "accept_model_digest",
    "provider_transition",
}
_OPERATION_STATES = {"running", "succeeded", "failed", "cancelled", "indeterminate"}
_OPERATION_RESULT_KINDS = {
    "pull_model",
    "delete_model",
    "prune_models",
    "reset_model_digests",
    "accept_model_digest",
}
_OPERATION_SUBJECT_KINDS = {"pull_model", "delete_model", "accept_model_digest"}
_INDETERMINATE_OPERATION_ERROR = "Managed Ollama operation outcome is unknown; do not retry with a new admission ID"


def _spent_admission_positions(admission_id: str) -> tuple[int, ...]:
    """Return stable Bloom-filter positions for one consumed admission ID."""
    digest = hashlib.sha256(admission_id.encode("ascii")).digest()
    first = int.from_bytes(digest[:8], "big")
    second = int.from_bytes(digest[8:16], "big") | 1
    bit_count = _OPERATION_SPENT_FILTER_BYTES * 8
    return tuple((first + index * second) % bit_count for index in range(_OPERATION_SPENT_FILTER_HASHES))


def _publish_managed_ollama_owner(runtime: Any) -> None:
    global _MANAGED_RUNTIME_OWNER  # noqa: PLW0603
    with _MANAGED_RUNTIME_OWNER_LOCK:
        _MANAGED_RUNTIME_OWNER = weakref.ref(runtime)


def _clear_managed_ollama_owner(runtime: Any) -> None:
    global _MANAGED_RUNTIME_OWNER  # noqa: PLW0603
    with _MANAGED_RUNTIME_OWNER_LOCK:
        current = _MANAGED_RUNTIME_OWNER() if _MANAGED_RUNTIME_OWNER is not None else None
        if current is runtime:
            _MANAGED_RUNTIME_OWNER = None


def managed_ollama_is_ready(model: str = "") -> bool:
    """Return whether this process owns a ready server and accepted model."""
    with _MANAGED_RUNTIME_OWNER_LOCK:
        runtime = _MANAGED_RUNTIME_OWNER() if _MANAGED_RUNTIME_OWNER is not None else None
    if runtime is None:
        return False
    try:
        if runtime._managed_server_version() is None:
            return False
        return not model or runtime.model_is_accepted(model)
    except Exception:  # noqa: BLE001 - ownership checks fail closed
        return False


def managed_ollama_base_url() -> str:
    """Return the private endpoint only while this process proves ownership."""
    with _MANAGED_RUNTIME_OWNER_LOCK:
        runtime = _MANAGED_RUNTIME_OWNER() if _MANAGED_RUNTIME_OWNER is not None else None
    if runtime is None:
        return ""
    try:
        return runtime.base_url if runtime._managed_server_version() is not None else ""
    except Exception:  # noqa: BLE001 - endpoint resolution fails closed
        return ""


@contextmanager
def managed_ollama_session(model: str) -> Iterator[ManagedOllamaAdmission]:
    """Hold the owned runtime and accepted model stable for one inference."""
    with _MANAGED_RUNTIME_OWNER_LOCK:
        runtime = _MANAGED_RUNTIME_OWNER() if _MANAGED_RUNTIME_OWNER is not None else None
    if runtime is None:
        raise OllamaRuntimeError("managed Ollama runtime is not ready")
    with runtime.inference_session(model) as admission:
        yield admission


def _normalise_machine(machine: str) -> str:
    value = machine.strip().lower()
    if value in {"amd64", "x64"}:
        return "x86_64"
    if value in {"aarch64", "arm64"}:
        return "arm64"
    return value


def _asset_for_platform(
    *,
    system: str | None = None,
    machine: str | None = None,
    version: str = _OLLAMA_VERSION,
) -> OllamaAsset:
    system_name = (system or platform.system()).strip().lower()
    machine_name = _normalise_machine(machine or platform.machine())
    release_assets = _ASSETS_BY_VERSION.get(version)
    if release_assets is None:
        raise OllamaRuntimeError(f"unsupported Ollama release: {version}")
    selected = release_assets.get((system_name, machine_name))
    if selected is None:
        raise OllamaRuntimeError(f"unsupported platform: {system_name}/{machine_name}")
    name, sha256, size_bytes, max_extracted_bytes = selected
    return OllamaAsset(
        name=name,
        sha256=sha256,
        url=f"https://github.com/ollama/ollama/releases/download/{version}/{name}",
        size_bytes=size_bytes,
        max_extracted_bytes=max_extracted_bytes,
    )


def _detect_linux_accelerator(system_name: str, machine_name: str) -> str:
    if system_name != "linux":
        return ""
    if machine_name == "arm64":
        try:
            release = Path("/etc/nv_tegra_release").read_text(encoding="utf-8")[:4096]
        except OSError:
            return ""
        if "R36" in release:
            return "jetpack6"
        if "R35" in release:
            return "jetpack5"
        return ""
    if machine_name != "x86_64":
        return ""
    try:
        vendor_files = Path("/sys/bus/pci/devices").glob("*/vendor")
    except OSError:
        return ""
    for index, vendor_file in enumerate(vendor_files):
        if index >= 4096:
            break
        try:
            if vendor_file.read_text(encoding="ascii").strip().lower() == "0x1002":
                return "rocm"
        except OSError:
            continue
    return ""


def _assets_for_platform(
    *,
    system: str | None = None,
    machine: str | None = None,
    accelerator: str | None = None,
    version: str = _OLLAMA_VERSION,
) -> tuple[OllamaAsset, ...]:
    """Return the pinned base archive and any official accelerator overlay."""
    system_name = (system or platform.system()).strip().lower()
    machine_name = _normalise_machine(machine or platform.machine())
    base = _asset_for_platform(system=system_name, machine=machine_name, version=version)
    selected_accelerator = (
        _detect_linux_accelerator(system_name, machine_name)
        if accelerator is None
        else accelerator.strip().lower()
    )
    if not selected_accelerator:
        return (base,)
    selected = _ACCELERATOR_ASSETS_BY_VERSION.get(version, {}).get(
        (system_name, machine_name, selected_accelerator)
    )
    if selected is None:
        raise OllamaRuntimeError(
            f"unsupported Ollama accelerator: {system_name}/{machine_name}/{selected_accelerator}"
        )
    name, sha256, size_bytes, max_extracted_bytes = selected
    overlay = OllamaAsset(
        name=name,
        sha256=sha256,
        url=f"https://github.com/ollama/ollama/releases/download/{version}/{name}",
        size_bytes=size_bytes,
        max_extracted_bytes=max_extracted_bytes,
        executable_candidates=(),
    )
    return base, overlay


def _install_required_bytes(asset: OllamaAsset) -> int:
    archive_size = max(0, int(asset.size_bytes))
    return archive_size + _extraction_required_bytes(asset)


def _install_assets_required_bytes(assets: tuple[OllamaAsset, ...]) -> int:
    return sum(_install_required_bytes(asset) for asset in assets)


def _extraction_required_bytes(asset: OllamaAsset) -> int:
    extracted_size = int(asset.max_extracted_bytes)
    if extracted_size <= 0:
        raise OllamaRuntimeError("Ollama runtime asset has no pinned extraction budget")
    return extracted_size + _INSTALL_DISK_RESERVE_BYTES


def _raise_if_integrity_deadline_expired(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() >= deadline:
        raise OllamaRuntimeError("managed Ollama integrity verification timed out")


def _sha256_file(
    path: Path,
    *,
    deadline: float | None = None,
    check_cancelled: Callable[[], None] | None = None,
) -> str:
    _raise_if_integrity_deadline_expired(deadline)
    if check_cancelled is not None:
        check_cancelled()
    if path.is_symlink():
        raise OllamaRuntimeError("managed Ollama integrity verification failed")
    try:
        file_stat = path.lstat()
    except OSError as exc:
        raise OllamaRuntimeError("managed Ollama integrity verification failed") from exc
    if not stat.S_ISREG(file_stat.st_mode):
        raise OllamaRuntimeError("managed Ollama integrity verification failed")
    _raise_if_integrity_deadline_expired(deadline)

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise OllamaRuntimeError("managed Ollama integrity verification failed") from exc
    digest = hashlib.sha256()
    with os.fdopen(descriptor, "rb") as source:
        while True:
            if check_cancelled is not None:
                check_cancelled()
            chunk = source.read(1024 * 1024)
            _raise_if_integrity_deadline_expired(deadline)
            if check_cancelled is not None:
                check_cancelled()
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _write_private_file(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise OllamaRuntimeError("managed Ollama state could not be written safely") from exc
    try:
        if os.name == "nt":
            harden(path)
        with os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
    finally:
        if descriptor != -1:
            os.close(descriptor)
    harden(path)


def _read_private_regular_file(
    path: Path,
    *,
    max_bytes: int,
    deadline: float | None = None,
    invalid_message: str = "managed Ollama state file is invalid",
    managed_root: Path | None = None,
) -> bytes:
    """Read a bounded regular file through one no-follow descriptor."""
    _raise_if_integrity_deadline_expired(deadline)
    descriptor = _open_private_regular_descriptor(
        path,
        managed_root=managed_root,
        invalid_message=invalid_message,
    )
    try:
        _raise_if_integrity_deadline_expired(deadline)
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > max_bytes:
            raise OllamaRuntimeError(invalid_message)
        with os.fdopen(descriptor, "rb") as source:
            descriptor = -1
            payload = bytearray()
            while len(payload) <= max_bytes:
                _raise_if_integrity_deadline_expired(deadline)
                chunk = source.read(min(1024 * 1024, max_bytes + 1 - len(payload)))
                _raise_if_integrity_deadline_expired(deadline)
                if not chunk:
                    break
                payload.extend(chunk)
    finally:
        if descriptor != -1:
            os.close(descriptor)
    if len(payload) > max_bytes:
        raise OllamaRuntimeError(invalid_message)
    return bytes(payload)


def _same_file_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _stat_is_reparse_point(path_stat: os.stat_result) -> bool:
    reparse_mask = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_mask and getattr(path_stat, "st_file_attributes", 0) & reparse_mask)


def _safe_private_regular_stat(path_stat: os.stat_result) -> bool:
    return (
        stat.S_ISREG(path_stat.st_mode)
        and not stat.S_ISLNK(path_stat.st_mode)
        and not _stat_is_reparse_point(path_stat)
    )


def _open_private_regular_descriptor(
    path: Path,
    *,
    managed_root: Path | None,
    invalid_message: str,
) -> int:
    """Open one state file without permitting a final-path escape."""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if os.name == "nt":
        if managed_root is None:
            raise OllamaRuntimeError(invalid_message)
        return _open_windows_private_regular_descriptor(
            path,
            managed_root=managed_root,
            invalid_message=invalid_message,
        )
    if nofollow and managed_root is not None:
        return _open_posix_private_regular_descriptor(
            path,
            managed_root=managed_root,
            invalid_message=invalid_message,
        )
    if nofollow:
        return os.open(path, flags | nofollow)

    try:
        before = path.lstat()
        if managed_root is not None:
            path.relative_to(managed_root)
            root_stat = managed_root.lstat()
            if (
                not stat.S_ISDIR(root_stat.st_mode)
                or stat.S_ISLNK(root_stat.st_mode)
                or _stat_is_reparse_point(root_stat)
            ):
                raise OllamaRuntimeError(invalid_message)
        if not _safe_private_regular_stat(before):
            raise OllamaRuntimeError(invalid_message)
        descriptor = os.open(path, flags)
    except (OSError, ValueError) as exc:
        raise OllamaRuntimeError(invalid_message) from exc
    try:
        opened = os.fstat(descriptor)
        current = path.lstat()
        if (
            not _safe_private_regular_stat(opened)
            or not _safe_private_regular_stat(current)
            or not _same_file_identity(before, opened)
            or not _same_file_identity(opened, current)
        ):
            raise OllamaRuntimeError(invalid_message)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _open_posix_private_regular_descriptor(
    path: Path,
    *,
    managed_root: Path,
    invalid_message: str,
) -> int:
    """Open every POSIX ancestor through a retained no-follow directory descriptor."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
    file_flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | nofollow
    directory_descriptor = -1
    file_descriptor = -1
    try:
        absolute_root = Path(os.path.abspath(managed_root))
        absolute_path = Path(os.path.abspath(path))
        relative = absolute_path.relative_to(absolute_root)
        if absolute_root.anchor != os.sep or not relative.parts:
            raise OllamaRuntimeError(invalid_message)
        directory_descriptor = os.open(os.sep, directory_flags)
        directory_parts = (*absolute_root.parts[1:], *relative.parts[:-1])
        for part in directory_parts:
            next_descriptor = os.open(part, directory_flags, dir_fd=directory_descriptor)
            opened = os.fstat(next_descriptor)
            if not stat.S_ISDIR(opened.st_mode) or _stat_is_reparse_point(opened):
                os.close(next_descriptor)
                raise OllamaRuntimeError(invalid_message)
            os.close(directory_descriptor)
            directory_descriptor = next_descriptor
        file_descriptor = os.open(relative.parts[-1], file_flags, dir_fd=directory_descriptor)
        opened_file = os.fstat(file_descriptor)
        if not _safe_private_regular_stat(opened_file):
            raise OllamaRuntimeError(invalid_message)
        result = file_descriptor
        file_descriptor = -1
        return result
    except FileNotFoundError:
        raise
    except OllamaRuntimeError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise OllamaRuntimeError(invalid_message) from exc
    finally:
        if file_descriptor != -1:
            os.close(file_descriptor)
        if directory_descriptor != -1:
            os.close(directory_descriptor)


def _normalise_windows_final_path(value: str) -> str:
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return os.path.normcase(os.path.normpath(value))


def _normalise_windows_expected_path(path: Path) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(os.fspath(path))))


def _windows_private_file_api() -> tuple[Any, Any]:
    import msvcrt  # noqa: PLC0415

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    return kernel32, msvcrt


def _open_windows_private_regular_descriptor(
    path: Path,
    *,
    managed_root: Path,
    invalid_message: str,
) -> int:
    """Open a Windows file as a reparse point and verify its native identity."""
    class ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("file_attributes", ctypes.c_uint32),
            ("creation_time_low", ctypes.c_uint32),
            ("creation_time_high", ctypes.c_uint32),
            ("last_access_time_low", ctypes.c_uint32),
            ("last_access_time_high", ctypes.c_uint32),
            ("last_write_time_low", ctypes.c_uint32),
            ("last_write_time_high", ctypes.c_uint32),
            ("volume_serial_number", ctypes.c_uint32),
            ("file_size_high", ctypes.c_uint32),
            ("file_size_low", ctypes.c_uint32),
            ("number_of_links", ctypes.c_uint32),
            ("file_index_high", ctypes.c_uint32),
            ("file_index_low", ctypes.c_uint32),
        ]

    kernel32, msvcrt = _windows_private_file_api()
    kernel32.CreateFileW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    kernel32.GetFileInformationByHandle.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ByHandleFileInformation),
    ]
    kernel32.GetFileInformationByHandle.restype = ctypes.c_int
    kernel32.GetFinalPathNameByHandleW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_wchar),
        ctypes.c_uint32,
        ctypes.c_uint32,
    ]
    kernel32.GetFinalPathNameByHandleW.restype = ctypes.c_uint32

    generic_read = 0x80000000
    file_read_attributes = 0x00000080
    share_read = 0x00000001
    share_all = share_read | 0x00000002 | 0x00000004
    open_existing = 3
    open_reparse_point = 0x00200000
    backup_semantics = 0x02000000
    directory_attribute = 0x00000010
    reparse_attribute = 0x00000400
    invalid_handle = ctypes.c_void_p(-1).value

    def close_handle(handle: int | None) -> None:
        if handle is not None:
            kernel32.CloseHandle(ctypes.c_void_p(handle))

    def open_handle(candidate: Path, *, directory: bool) -> int:
        handle = kernel32.CreateFileW(
            os.fspath(candidate),
            file_read_attributes if directory else generic_read,
            share_read if directory else share_all,
            None,
            open_existing,
            open_reparse_point | (backup_semantics if directory else 0),
            None,
        )
        if handle in {None, invalid_handle}:
            raise ctypes.WinError(ctypes.get_last_error())  # type: ignore[attr-defined]
        return int(handle)

    def handle_info(handle: int) -> ByHandleFileInformation:
        info = ByHandleFileInformation()
        if not kernel32.GetFileInformationByHandle(
            ctypes.c_void_p(handle),
            ctypes.byref(info),
        ):
            raise ctypes.WinError(ctypes.get_last_error())  # type: ignore[attr-defined]
        return info

    def handle_identity(info: ByHandleFileInformation) -> tuple[int, int, int]:
        return (
            int(info.volume_serial_number),
            int(info.file_index_high),
            int(info.file_index_low),
        )

    def final_path(handle: int) -> str:
        size = 512
        while size <= 32768:
            buffer = ctypes.create_unicode_buffer(size)
            length = kernel32.GetFinalPathNameByHandleW(
                ctypes.c_void_p(handle),
                buffer,
                size,
                0,
            )
            if length == 0:
                raise ctypes.WinError(ctypes.get_last_error())  # type: ignore[attr-defined]
            if length < size:
                return _normalise_windows_final_path(buffer.value)
            size = int(length) + 1
        raise OSError("Windows final path exceeds the supported length")

    root_handle: int | None = None
    ancestor_handles: list[int] = []
    root_verification_handle: int | None = None
    file_handle: int | None = None
    verification_handle: int | None = None
    try:
        relative = path.relative_to(managed_root)
        if not relative.parts:
            raise OllamaRuntimeError(invalid_message)
        root_handle = open_handle(managed_root, directory=True)
        root_info = handle_info(root_handle)
        if (
            not root_info.file_attributes & directory_attribute
            or root_info.file_attributes & reparse_attribute
        ):
            raise OllamaRuntimeError(invalid_message)
        root_final = final_path(root_handle)
        if root_final != _normalise_windows_expected_path(managed_root):
            raise OllamaRuntimeError(invalid_message)

        current_directory = managed_root
        for part in relative.parts[:-1]:
            current_directory /= part
            ancestor_handle = open_handle(current_directory, directory=True)
            ancestor_handles.append(ancestor_handle)
            ancestor_info = handle_info(ancestor_handle)
            if (
                not ancestor_info.file_attributes & directory_attribute
                or ancestor_info.file_attributes & reparse_attribute
            ):
                raise OllamaRuntimeError(invalid_message)
            ancestor_final = final_path(ancestor_handle)
            try:
                ancestor_contained = os.path.commonpath((root_final, ancestor_final)) == root_final
            except ValueError:
                ancestor_contained = False
            if not ancestor_contained or ancestor_final == root_final:
                raise OllamaRuntimeError(invalid_message)

        file_handle = open_handle(path, directory=False)
        file_info = handle_info(file_handle)
        if (
            file_info.file_attributes & directory_attribute
            or file_info.file_attributes & reparse_attribute
            or file_info.number_of_links != 1
        ):
            raise OllamaRuntimeError(invalid_message)
        file_final = final_path(file_handle)
        try:
            contained = os.path.commonpath((root_final, file_final)) == root_final
        except ValueError:
            contained = False
        if not contained or file_final == root_final:
            raise OllamaRuntimeError(invalid_message)

        verification_handle = open_handle(path, directory=False)
        verification_info = handle_info(verification_handle)
        if (
            verification_info.file_attributes & directory_attribute
            or verification_info.file_attributes & reparse_attribute
            or verification_info.number_of_links != 1
            or handle_identity(verification_info) != handle_identity(file_info)
            or final_path(verification_handle) != file_final
        ):
            raise OllamaRuntimeError(invalid_message)

        root_verification_handle = open_handle(managed_root, directory=True)
        root_verification_info = handle_info(root_verification_handle)
        if (
            not root_verification_info.file_attributes & directory_attribute
            or root_verification_info.file_attributes & reparse_attribute
            or handle_identity(root_verification_info) != handle_identity(root_info)
            or final_path(root_verification_handle) != root_final
        ):
            raise OllamaRuntimeError(invalid_message)

        descriptor = msvcrt.open_osfhandle(
            file_handle,
            os.O_RDONLY | getattr(os, "O_BINARY", 0),
        )
        file_handle = None
        opened = os.fstat(descriptor)
        if not _safe_private_regular_stat(opened):
            os.close(descriptor)
            raise OllamaRuntimeError(invalid_message)
        return descriptor
    except FileNotFoundError:
        # Parity with the POSIX descriptor path: a missing file (WinError 2)
        # or missing ancestor (WinError 3) must propagate so callers can treat
        # an absent marker/state file as "not present" rather than "invalid".
        # Wrapping it below broke every absent-file probe on Windows.
        raise
    except OllamaRuntimeError:
        raise
    except (OSError, ValueError) as exc:
        raise OllamaRuntimeError(invalid_message) from exc
    finally:
        close_handle(root_verification_handle)
        close_handle(verification_handle)
        close_handle(file_handle)
        for ancestor_handle in reversed(ancestor_handles):
            close_handle(ancestor_handle)
        close_handle(root_handle)


def _remove_path_without_following_root(path: Path) -> None:
    """Remove one bounded managed tree without traversing links."""
    try:
        path_stat = path.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise OllamaRuntimeError("managed Ollama repair cleanup failed") from exc
    reparse_mask = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)

    def is_reparse(candidate: os.stat_result) -> bool:
        return bool(reparse_mask and getattr(candidate, "st_file_attributes", 0) & reparse_mask)

    try:
        if stat.S_ISDIR(path_stat.st_mode) and not stat.S_ISLNK(path_stat.st_mode) and not is_reparse(path_stat):
            entries = 0
            total_bytes = 0
            pending = [path]
            while pending:
                current = pending.pop()
                current_stat = current.lstat()
                entries += 1
                if entries > _MAX_RUNTIME_TREE_ENTRIES:
                    raise OllamaRuntimeError("managed Ollama cleanup exceeded the entry limit")
                if stat.S_ISLNK(current_stat.st_mode) or is_reparse(current_stat):
                    raise OllamaRuntimeError("managed Ollama cleanup encountered an unsafe link")
                if stat.S_ISDIR(current_stat.st_mode):
                    with os.scandir(current) as children:
                        pending.extend(Path(child.path) for child in children)
                    continue
                if not stat.S_ISREG(current_stat.st_mode):
                    raise OllamaRuntimeError("managed Ollama cleanup encountered an unsafe entry")
                total_bytes += int(current_stat.st_size)
                if total_bytes > _MAX_RUNTIME_TREE_BYTES:
                    raise OllamaRuntimeError("managed Ollama cleanup exceeded the byte limit")
            shutil.rmtree(path)
        elif stat.S_ISDIR(path_stat.st_mode) and is_reparse(path_stat):
            path.rmdir()
        else:
            path.unlink()
    except OllamaRuntimeError:
        raise
    except OSError as exc:
        raise OllamaRuntimeError("managed Ollama repair cleanup failed") from exc


def _managed_process_options(platform_name: str | None = None) -> dict[str, Any]:
    """Return platform process-group options for the managed server tree."""
    if (platform_name or os.name) == "nt":
        return {
            "creationflags": (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                | getattr(subprocess, "CREATE_SUSPENDED", 0x00000004)
            )
        }
    return {"start_new_session": True}


class _WindowsJobHandle:
    """Kernel-owned containment for one directly launched Windows process tree."""

    def __init__(self, handle: int, kernel32: Any, accounting_type: type[ctypes.Structure]) -> None:
        self._handle = handle
        self._kernel32 = kernel32
        self._accounting_type = accounting_type

    def terminate(self, *, deadline: float) -> None:
        if not self._handle or not self._kernel32.TerminateJobObject(self._handle, 1):
            raise OllamaRuntimeError("could not prove managed Ollama teardown")
        while True:
            accounting = self._accounting_type()
            if not self._kernel32.QueryInformationJobObject(
                self._handle,
                1,
                ctypes.byref(accounting),
                ctypes.sizeof(accounting),
                None,
            ):
                raise OllamaRuntimeError("could not prove managed Ollama teardown")
            if int(accounting.ActiveProcesses) == 0:
                return
            remaining = _remaining_teardown_time(deadline)
            if remaining <= 0:
                raise OllamaRuntimeError("could not prove managed Ollama teardown")
            time.sleep(min(0.05, remaining))

    def close(self) -> None:
        handle = self._handle
        if handle and not self._kernel32.CloseHandle(handle):
            raise OllamaRuntimeError("could not release managed Ollama process containment")
        self._handle = 0


def _create_windows_job(process: Any) -> _WindowsJobHandle:
    """Assign a real child to a kill-on-close Job Object before it is trusted."""
    if os.name != "nt":
        raise OllamaRuntimeError("Windows process containment is unavailable")

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class _ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _BasicAccountingInformation(ctypes.Structure):
        _fields_ = [
            ("TotalUserTime", ctypes.c_longlong),
            ("TotalKernelTime", ctypes.c_longlong),
            ("ThisPeriodTotalUserTime", ctypes.c_longlong),
            ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
            ("TotalPageFaultCount", ctypes.c_uint32),
            ("TotalProcesses", ctypes.c_uint32),
            ("ActiveProcesses", ctypes.c_uint32),
            ("TotalTerminatedProcesses", ctypes.c_uint32),
        ]

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        kernel32.SetInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        kernel32.SetInformationJobObject.restype = ctypes.c_int
        kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        kernel32.AssignProcessToJobObject.restype = ctypes.c_int
        kernel32.QueryInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        kernel32.QueryInformationJobObject.restype = ctypes.c_int
        kernel32.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel32.TerminateJobObject.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        limits = _ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            handle,
            9,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")
        process_handle = int(getattr(process, "_handle"))
        if not kernel32.AssignProcessToJobObject(handle, ctypes.c_void_p(process_handle)):
            raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")
        return _WindowsJobHandle(int(handle), kernel32, _BasicAccountingInformation)
    except Exception as exc:
        if "handle" in locals() and handle:
            kernel32.CloseHandle(handle)
        raise OllamaRuntimeError("managed Ollama Windows process containment could not be established") from exc


def _resume_windows_process(process: Any) -> None:
    """Resume a process only after Windows has atomically admitted it to the Job."""
    if os.name != "nt":
        raise OllamaRuntimeError("Windows process containment is unavailable")
    try:
        ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
        ntdll.NtResumeProcess.argtypes = [ctypes.c_void_p]
        ntdll.NtResumeProcess.restype = ctypes.c_long
        status = int(ntdll.NtResumeProcess(ctypes.c_void_p(int(getattr(process, "_handle")))))
        if status != 0:
            raise OSError(status, "NtResumeProcess failed")
    except Exception as exc:
        raise OllamaRuntimeError("managed Ollama Windows process could not be resumed") from exc


def _terminate_suspended_windows_process(process: Any, *, deadline: float) -> None:
    """Terminate a root that has never executed and therefore cannot have descendants."""
    try:
        process.terminate()
        remaining = _remaining_teardown_time(deadline)
        if remaining <= 0:
            raise OllamaRuntimeError("could not prove managed Ollama suspended-process teardown")
        process.wait(timeout=remaining)
    except (OSError, psutil.Error, subprocess.TimeoutExpired) as exc:
        raise OllamaRuntimeError("could not prove managed Ollama suspended-process teardown") from exc
    if process.poll() is None:
        raise OllamaRuntimeError("could not prove managed Ollama suspended-process teardown")


def _contain_suspended_windows_process(
    process: Any,
    *,
    create_job: Callable[[Any], Any] = _create_windows_job,
    resume_process: Callable[[Any], None] = _resume_windows_process,
    deadline: float | None = None,
) -> Any:
    """Assign a never-run child to a Job, then permit its first instruction."""
    stop_deadline = _teardown_deadline(deadline)
    try:
        job = create_job(process)
    except Exception:
        _terminate_suspended_windows_process(process, deadline=stop_deadline)
        raise
    try:
        resume_process(process)
    except Exception as exc:
        try:
            _terminate_windows_process_tree(process, job=job, deadline=stop_deadline)
        except OllamaRuntimeError as teardown_error:
            raise OllamaRuntimeError("could not prove managed Ollama Windows process containment rollback") from (
                teardown_error
            )
        if isinstance(exc, OllamaRuntimeError):
            raise
        raise OllamaRuntimeError("managed Ollama Windows process could not be resumed") from exc
    return job


def _teardown_deadline(deadline: float | None) -> float:
    return deadline if deadline is not None else time.monotonic() + _PROCESS_TREE_STOP_TIMEOUT_SECONDS


def _remaining_teardown_time(deadline: float) -> float:
    return max(0.0, deadline - time.monotonic())


def _terminate_windows_process_tree(
    process: Any,
    *,
    job: _WindowsJobHandle | None = None,
    run_command: Callable[..., Any] | None = None,
    deadline: float | None = None,
) -> None:
    """Terminate a Windows process tree through its retained Job Object."""
    stop_deadline = _teardown_deadline(deadline)
    if job is not None:
        job.terminate(deadline=stop_deadline)
        remaining = _remaining_teardown_time(stop_deadline)
        if remaining <= 0:
            raise OllamaRuntimeError("could not prove managed Ollama teardown")
        try:
            process.wait(timeout=remaining)
        except (OSError, psutil.Error, subprocess.TimeoutExpired) as exc:
            raise OllamaRuntimeError("could not prove managed Ollama teardown") from exc
        job.close()
        return
    if run_command is None:
        raise OllamaRuntimeError("could not prove managed Ollama teardown")

    # Test-only compatibility path for exercising failure budgeting on non-Windows hosts.
    runner = run_command or subprocess.run
    command = ["taskkill", "/PID", str(process.pid), "/T"]

    def fail_closed(cause: BaseException | None = None) -> None:
        root_error: BaseException | None = None
        if process.poll() is None:
            try:
                process.terminate()
            except (OSError, psutil.Error) as exc:
                root_error = exc
        error = OllamaRuntimeError("could not prove managed Ollama teardown")
        if root_error is not None:
            raise error from root_error
        if cause is not None:
            raise error from cause
        raise error

    def run_taskkill(*, force: bool) -> Any:
        remaining = _remaining_teardown_time(stop_deadline)
        if remaining <= 0 or process.poll() is not None:
            fail_closed()
        return runner(
            [*command, "/F"] if force else command,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=remaining / 2,
        )

    graceful_result: Any | None = None
    try:
        graceful_result = run_taskkill(force=False)
    except (OSError, subprocess.TimeoutExpired):
        pass
    if graceful_result is not None and graceful_result.returncode == 0:
        remaining = _remaining_teardown_time(stop_deadline)
        if remaining <= 0:
            fail_closed()
        try:
            process.wait(timeout=min(10.0, remaining / 2))
        except subprocess.TimeoutExpired:
            pass
        except (OSError, psutil.Error) as exc:
            fail_closed(exc)
        if process.poll() is not None:
            return
    elif graceful_result is not None and process.poll() is not None:
        fail_closed()

    try:
        forced_result = run_taskkill(force=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        fail_closed(exc)
    if forced_result.returncode != 0:
        fail_closed()

    remaining = _remaining_teardown_time(stop_deadline)
    if remaining <= 0:
        fail_closed()
    try:
        process.wait(timeout=min(5.0, remaining))
    except (OSError, psutil.Error, subprocess.TimeoutExpired) as exc:
        fail_closed(exc)
    if process.poll() is None:
        fail_closed()


def _terminate_injected_windows_process(process: Any, *, deadline: float) -> None:
    """Bound test/injected process doubles without weakening production containment."""
    try:
        process.terminate()
        process.wait(timeout=max(0.0, deadline - time.monotonic()) / 2)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            process.wait(timeout=max(0.0, deadline - time.monotonic()))
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OllamaRuntimeError("could not prove managed Ollama teardown") from exc
    except OSError as exc:
        raise OllamaRuntimeError("could not prove managed Ollama teardown") from exc
    if process.poll() is None:
        raise OllamaRuntimeError("could not prove managed Ollama teardown")


def _posix_process_group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError as exc:
        raise OllamaRuntimeError("could not prove managed Ollama teardown") from exc
    return True


def _terminate_posix_process_tree(process: Any, *, deadline: float | None = None) -> None:
    process_group = int(process.pid)
    stop_deadline = _teardown_deadline(deadline)
    if process.poll() is not None:
        raise OllamaRuntimeError("could not prove managed Ollama teardown")
    try:
        os.killpg(process_group, signal.SIGTERM)
    except ProcessLookupError:
        if process.poll() is None:
            raise OllamaRuntimeError("could not prove managed Ollama teardown")
    except OSError as exc:
        raise OllamaRuntimeError("could not prove managed Ollama teardown") from exc

    remaining = _remaining_teardown_time(stop_deadline)
    if remaining <= 0:
        raise OllamaRuntimeError("could not prove managed Ollama teardown")
    try:
        process.wait(timeout=min(10.0, remaining / 2))
    except subprocess.TimeoutExpired:
        if process.poll() is not None:
            raise OllamaRuntimeError("could not prove managed Ollama teardown")
        try:
            os.killpg(process_group, signal.SIGKILL)
            remaining = _remaining_teardown_time(stop_deadline)
            if remaining <= 0:
                raise OllamaRuntimeError("could not prove managed Ollama teardown")
            process.wait(timeout=min(5.0, remaining))
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OllamaRuntimeError("could not prove managed Ollama teardown") from exc

    # Once the retained root has been reaped its process-group identifier could
    # eventually be reused. Observe only; never signal that identifier again.
    while _posix_process_group_exists(process_group):
        remaining = _remaining_teardown_time(stop_deadline)
        if remaining <= 0:
            raise OllamaRuntimeError("could not prove managed Ollama teardown")
        time.sleep(min(0.05, remaining))


def _terminate_process_tree(
    process: Any,
    *,
    deadline: float | None = None,
    windows_job: _WindowsJobHandle | None = None,
) -> None:
    if os.name == "nt":
        _terminate_windows_process_tree(process, job=windows_job, deadline=deadline)
    else:
        _terminate_posix_process_tree(process, deadline=deadline)


def _safe_archive_path(name: str) -> PurePosixPath:
    normalised = name.replace("\\", "/")
    path = PurePosixPath(normalised)
    if (
        path.is_absolute()
        or re.match(r"^[A-Za-z]:", normalised)
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise OllamaRuntimeError(f"unsafe archive path: {name!r}")
    return path


def _copy_archive_member(
    source: Any,
    target: Path,
    *,
    expected_size: int,
    extracted_bytes: int,
    max_extracted_bytes: int,
    ensure_capacity: Callable[[int], None] | None,
    check_cancelled: Callable[[], None] | None,
) -> int:
    written = 0
    try:
        with target.open("xb") as output:
            while True:
                if check_cancelled is not None:
                    check_cancelled()
                chunk = source.read(1024 * 1024)
                if check_cancelled is not None:
                    check_cancelled()
                if not chunk:
                    break
                written += len(chunk)
                if extracted_bytes + written > max_extracted_bytes:
                    raise OllamaRuntimeError("Ollama archive exceeded the extracted size limit")
                if ensure_capacity is not None:
                    ensure_capacity(len(chunk))
                if check_cancelled is not None:
                    check_cancelled()
                output.write(chunk)
    except OSError as exc:
        raise OllamaRuntimeError("Ollama archive could not be extracted safely") from exc
    if written != expected_size:
        raise OllamaRuntimeError("Ollama archive member size did not match its declaration")
    return written


@dataclass(frozen=True)
class _TarArchiveEntry:
    relative: PurePosixPath
    kind: str
    link_target: PurePosixPath | None
    size: int
    mode: int


def _tar_link_target(member: tarfile.TarInfo, relative: PurePosixPath) -> PurePosixPath:
    raw = member.linkname.replace("\\", "/")
    target = PurePosixPath(raw)
    if not raw or target.is_absolute() or re.match(r"^[A-Za-z]:", raw):
        raise OllamaRuntimeError(f"unsafe archive link: {member.name!r}")

    parts = list(relative.parent.parts) if member.issym() else []
    for part in target.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                raise OllamaRuntimeError(f"unsafe archive link: {member.name!r}")
            parts.pop()
            continue
        parts.append(part)
    if not parts:
        raise OllamaRuntimeError(f"unsafe archive link: {member.name!r}")
    return PurePosixPath(*parts)


def _tar_archive_entry(member: tarfile.TarInfo) -> _TarArchiveEntry:
    relative = _safe_archive_path(member.name)
    if member.size < 0:
        raise OllamaRuntimeError("Ollama archive reported an invalid member size")
    if member.isdir():
        return _TarArchiveEntry(relative, "directory", None, 0, member.mode)
    if member.isfile():
        return _TarArchiveEntry(relative, "file", None, member.size, member.mode)
    if member.issym() or member.islnk():
        return _TarArchiveEntry(relative, "link", _tar_link_target(member, relative), 0, member.mode)
    raise OllamaRuntimeError(f"unsafe archive member: {member.name!r}")


def _resolve_tar_link(
    entry: _TarArchiveEntry,
    entries: Mapping[str, _TarArchiveEntry],
) -> _TarArchiveEntry:
    current = entry
    visited = {entry.relative.as_posix()}
    while current.kind == "link":
        assert current.link_target is not None
        key = current.link_target.as_posix()
        if key in visited:
            raise OllamaRuntimeError(f"unsafe archive link: {entry.relative.as_posix()!r}")
        visited.add(key)
        target = entries.get(key)
        if target is None:
            raise OllamaRuntimeError(f"unsafe archive link: {entry.relative.as_posix()!r}")
        current = target
    if current.kind != "file":
        raise OllamaRuntimeError(f"unsafe archive link: {entry.relative.as_posix()!r}")
    return current


def _validate_tar_entries(
    entries: Mapping[str, _TarArchiveEntry],
    *,
    max_extracted_bytes: int,
) -> None:
    declared_bytes = 0
    paths = tuple(entry.relative.parts for entry in entries.values())
    for entry in entries.values():
        if entry.kind == "link":
            prefix = entry.relative.parts
            if any(len(path) > len(prefix) and path[: len(prefix)] == prefix for path in paths):
                raise OllamaRuntimeError(f"unsafe archive link: {entry.relative.as_posix()!r}")
            materialised = _resolve_tar_link(entry, entries)
            declared_bytes += materialised.size
        elif entry.kind == "file":
            declared_bytes += entry.size
        if declared_bytes > max_extracted_bytes:
            raise OllamaRuntimeError("Ollama archive exceeded the extracted size limit")


def _validate_tar_members(
    members: list[tarfile.TarInfo],
    *,
    max_extracted_bytes: int,
    check_cancelled: Callable[[], None] | None,
) -> None:
    if len(members) > _MAX_EXTRACTED_MEMBERS:
        raise OllamaRuntimeError("Ollama archive exceeded the member limit")
    entries: dict[str, _TarArchiveEntry] = {}
    for member in members:
        if check_cancelled is not None:
            check_cancelled()
        entry = _tar_archive_entry(member)
        key = entry.relative.as_posix()
        if key in entries:
            raise OllamaRuntimeError("Ollama archive contained a duplicate path")
        entries[key] = entry
    _validate_tar_entries(entries, max_extracted_bytes=max_extracted_bytes)


def _extract_tar_members(
    bundle: tarfile.TarFile,
    destination: Path,
    members: list[tarfile.TarInfo] | None = None,
    *,
    max_extracted_bytes: int,
    ensure_capacity: Callable[[int], None] | None,
    check_cancelled: Callable[[], None] | None,
) -> None:
    extracted_bytes = 0
    member_count = 0
    entries: dict[str, _TarArchiveEntry] = {}
    for member in members if members is not None else bundle:
        if check_cancelled is not None:
            check_cancelled()
        member_count += 1
        if member_count > _MAX_EXTRACTED_MEMBERS:
            raise OllamaRuntimeError("Ollama archive exceeded the member limit")
        entry = _tar_archive_entry(member)
        key = entry.relative.as_posix()
        if key in entries:
            raise OllamaRuntimeError("Ollama archive contained a duplicate path")
        entries[key] = entry
        if entry.kind == "link":
            continue
        if extracted_bytes + entry.size > max_extracted_bytes:
            raise OllamaRuntimeError("Ollama archive exceeded the extracted size limit")
        target = destination.joinpath(*entry.relative.parts)
        if entry.kind == "directory":
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        source = bundle.extractfile(member)
        if source is None:
            raise OllamaRuntimeError("Ollama archive member could not be read")
        with source:
            extracted_bytes += _copy_archive_member(
                source,
                target,
                expected_size=entry.size,
                extracted_bytes=extracted_bytes,
                max_extracted_bytes=max_extracted_bytes,
                ensure_capacity=ensure_capacity,
                check_cancelled=check_cancelled,
            )
        if os.name != "nt":
            target.chmod(member.mode & 0o777)

    _validate_tar_entries(entries, max_extracted_bytes=max_extracted_bytes)
    for entry in entries.values():
        if entry.kind != "link":
            continue
        if check_cancelled is not None:
            check_cancelled()
        materialised = _resolve_tar_link(entry, entries)
        source = destination.joinpath(*materialised.relative.parts)
        target = destination.joinpath(*entry.relative.parts)
        try:
            source_stat = source.lstat()
            if stat.S_ISLNK(source_stat.st_mode) or not stat.S_ISREG(source_stat.st_mode):
                raise OllamaRuntimeError(f"unsafe archive link: {entry.relative.as_posix()!r}")
            if source_stat.st_size != materialised.size:
                raise OllamaRuntimeError("Ollama archive member size did not match its declaration")
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open("rb") as source_stream:
                extracted_bytes += _copy_archive_member(
                    source_stream,
                    target,
                    expected_size=materialised.size,
                    extracted_bytes=extracted_bytes,
                    max_extracted_bytes=max_extracted_bytes,
                    ensure_capacity=ensure_capacity,
                    check_cancelled=check_cancelled,
                )
        except OSError as exc:
            raise OllamaRuntimeError("Ollama archive could not be extracted safely") from exc
        if os.name != "nt":
            target.chmod(materialised.mode & 0o777)


def _extract_archive(
    archive_path: Path,
    destination: Path,
    *,
    max_extracted_bytes: int = _DEFAULT_EXTRACTION_BUDGET_BYTES,
    ensure_capacity: Callable[[int], None] | None = None,
    check_cancelled: Callable[[], None] | None = None,
) -> None:
    if max_extracted_bytes <= 0:
        raise OllamaRuntimeError("Ollama archive has an invalid extraction budget")
    if check_cancelled is not None:
        check_cancelled()
    name = archive_path.name.lower()
    destination.mkdir(parents=True, exist_ok=False)
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive_path) as bundle:
            members = bundle.infolist()
            if len(members) > _MAX_EXTRACTED_MEMBERS:
                raise OllamaRuntimeError("Ollama archive exceeded the member limit")
            declared_bytes = 0
            seen: set[str] = set()
            validated: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
            for member in members:
                if check_cancelled is not None:
                    check_cancelled()
                relative = _safe_archive_path(member.filename)
                file_type = (member.external_attr >> 16) & 0o170000
                if file_type == stat.S_IFLNK:
                    raise OllamaRuntimeError(f"unsafe archive link: {member.filename!r}")
                if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
                    raise OllamaRuntimeError(f"unsafe archive member: {member.filename!r}")
                key = relative.as_posix()
                if key in seen:
                    raise OllamaRuntimeError("Ollama archive contained a duplicate path")
                seen.add(key)
                if member.file_size < 0:
                    raise OllamaRuntimeError("Ollama archive reported an invalid member size")
                declared_bytes += 0 if member.is_dir() else member.file_size
                if declared_bytes > max_extracted_bytes:
                    raise OllamaRuntimeError("Ollama archive exceeded the extracted size limit")
                validated.append((member, relative))

            extracted_bytes = 0
            for member, relative in validated:
                if check_cancelled is not None:
                    check_cancelled()
                target = destination.joinpath(*relative.parts)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source:
                    extracted_bytes += _copy_archive_member(
                        source,
                        target,
                        expected_size=member.file_size,
                        extracted_bytes=extracted_bytes,
                        max_extracted_bytes=max_extracted_bytes,
                        ensure_capacity=ensure_capacity,
                        check_cancelled=check_cancelled,
                    )
        return
    if name.endswith((".tgz", ".tar.gz")):
        with tarfile.open(archive_path, mode="r:gz") as bundle:
            members = bundle.getmembers()
            if check_cancelled is not None:
                check_cancelled()
            _validate_tar_members(
                members,
                max_extracted_bytes=max_extracted_bytes,
                check_cancelled=check_cancelled,
            )
            _extract_tar_members(
                bundle,
                destination,
                members,
                max_extracted_bytes=max_extracted_bytes,
                ensure_capacity=ensure_capacity,
                check_cancelled=check_cancelled,
            )
        return
    if name.endswith(".tar.zst"):
        try:
            import zstandard  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - required dependency guard
            raise OllamaRuntimeError("zstandard support is unavailable") from exc
        with archive_path.open("rb") as compressed:
            with zstandard.ZstdDecompressor().stream_reader(compressed) as stream:
                with tarfile.open(fileobj=stream, mode="r|") as bundle:
                    _extract_tar_members(
                        bundle,
                        destination,
                        max_extracted_bytes=max_extracted_bytes,
                        ensure_capacity=ensure_capacity,
                        check_cancelled=check_cancelled,
                    )
        return
    raise OllamaRuntimeError(f"unsupported archive: {archive_path.name}")


def _merge_extracted_overlay(source: Path, destination: Path) -> None:
    """Merge one already-validated official overlay without following links."""
    try:
        for path in sorted(source.rglob("*"), key=lambda candidate: candidate.as_posix()):
            path_stat = path.lstat()
            relative = path.relative_to(source)
            target = destination / relative
            if stat.S_ISDIR(path_stat.st_mode):
                if target.exists() or target.is_symlink():
                    target_stat = target.lstat()
                    if stat.S_ISLNK(target_stat.st_mode) or not stat.S_ISDIR(target_stat.st_mode):
                        raise OllamaRuntimeError("Ollama accelerator overlay conflicts with the base runtime")
                else:
                    target.mkdir()
                continue
            if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
                raise OllamaRuntimeError("Ollama accelerator overlay contains an unsafe runtime file")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                target_stat = target.lstat()
                if stat.S_ISLNK(target_stat.st_mode) or not stat.S_ISREG(target_stat.st_mode):
                    raise OllamaRuntimeError("Ollama accelerator overlay conflicts with the base runtime")
            durable_replace(path, target)
    except OllamaRuntimeError:
        raise
    except OSError as exc:
        raise OllamaRuntimeError("Ollama accelerator overlay could not be merged safely") from exc


def _raise_if_event_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise _OllamaOperationCancelled("managed Ollama operation was cancelled")


def _interrupt_http_response(response: Any) -> None:
    for attribute_chain in (("fp", "raw", "_sock"), ("fp", "_sock"), ("raw", "_sock"), ("sock",)):
        candidate = response
        for attribute in attribute_chain:
            candidate = getattr(candidate, attribute, None)
            if candidate is None:
                break
        if isinstance(candidate, socket.socket):
            try:
                candidate.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            break
    try:
        response.close()
    except (OSError, ValueError):
        pass


@contextmanager
def _interrupt_response_on_cancel(
    response: Any,
    cancel_event: threading.Event | None,
) -> Iterator[None]:
    if cancel_event is None:
        yield
        return
    finished = threading.Event()

    def watch_for_cancellation() -> None:
        while not finished.wait(0.05):
            if cancel_event.is_set():
                _interrupt_http_response(response)
                return

    watcher = threading.Thread(
        target=watch_for_cancellation,
        name="ollama-http-cancellation",
        daemon=True,
    )
    watcher.start()
    try:
        _raise_if_event_cancelled(cancel_event)
        yield
        _raise_if_event_cancelled(cancel_event)
    except Exception:
        _raise_if_event_cancelled(cancel_event)
        raise
    finally:
        finished.set()
        watcher.join(timeout=0.1)


def _download_asset(
    asset: OllamaAsset,
    destination: Path,
    progress: Callable[[int, int], None],
    *,
    cancel_event: threading.Event | None = None,
) -> None:
    _raise_if_event_cancelled(cancel_event)
    deadline = time.monotonic() + _RUNTIME_DOWNLOAD_DEADLINE_SECONDS
    request = urllib.request.Request(asset.url, headers={"User-Agent": "FlintTrade/OllamaRuntime"})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("xb") as output:  # noqa: S310
        with _interrupt_response_on_cancel(response, cancel_event):
            raw_content_length = response.headers.get("Content-Length")
            content_length: int | None = None
            if raw_content_length is not None:
                try:
                    content_length = int(str(raw_content_length).strip())
                except ValueError as exc:
                    raise OllamaRuntimeError("Ollama download returned an invalid Content-Length") from exc
                if content_length < 0:
                    raise OllamaRuntimeError("Ollama download returned an invalid Content-Length")

            pinned_size = max(0, int(asset.size_bytes))
            hard_limit = pinned_size or _MAX_RUNTIME_ARCHIVE_BYTES
            if hard_limit > _MAX_RUNTIME_ARCHIVE_BYTES:
                raise OllamaRuntimeError("Ollama runtime asset exceeds the download size limit")
            if content_length is not None and content_length > hard_limit:
                raise OllamaRuntimeError("Ollama download exceeds the size limit")
            if content_length is not None and pinned_size and content_length != pinned_size:
                raise OllamaRuntimeError("Ollama download Content-Length does not match the pinned asset")

            total = content_length if content_length is not None else pinned_size
            completed = 0
            read_chunk = getattr(response, "read1", None)
            if read_chunk is None:
                read_chunk = response.read
            while True:
                _raise_if_event_cancelled(cancel_event)
                if deadline - time.monotonic() <= 0:
                    raise OllamaRuntimeError("Ollama runtime download deadline exceeded")
                chunk = read_chunk(1024 * 1024)
                _raise_if_event_cancelled(cancel_event)
                if not chunk:
                    break
                if deadline - time.monotonic() <= 0:
                    raise OllamaRuntimeError("Ollama runtime download deadline exceeded")
                next_completed = completed + len(chunk)
                if next_completed > hard_limit:
                    raise OllamaRuntimeError("Ollama download exceeds the size limit")
                if content_length is not None and next_completed > content_length:
                    raise OllamaRuntimeError("Ollama download exceeded its Content-Length")
                output.write(chunk)
                completed = next_completed
                progress(completed, total)
            if content_length is not None and completed != content_length:
                raise OllamaRuntimeError("Ollama download did not match its Content-Length")
            if pinned_size and completed != pinned_size:
                raise OllamaRuntimeError("Ollama download did not match the pinned asset size")


def _read_loopback_http_json(
    base_url: str,
    path: str,
    *,
    deadline: float | None = None,
) -> Any:
    """Read one small loopback JSON response under absolute time and size caps."""
    parsed = urlsplit(base_url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port is None:
        raise OllamaRuntimeError("managed Ollama endpoint is invalid")
    probe_deadline = time.monotonic() + _PROBE_DEADLINE_SECONDS
    if deadline is not None:
        probe_deadline = min(probe_deadline, deadline)
    remaining = probe_deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("managed Ollama probe exceeded its deadline")
    with socket.create_connection((parsed.hostname, parsed.port), timeout=remaining) as connection:
        request_path = path if path.startswith("/") else f"/{path}"
        remaining = probe_deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("managed Ollama probe exceeded its deadline")
        connection.settimeout(remaining)
        connection.sendall(
            (
                f"GET {request_path} HTTP/1.1\r\n"
                f"Host: {parsed.hostname}:{parsed.port}\r\n"
                "User-Agent: FlintTrade/OllamaRuntime\r\n"
                "Accept: application/json\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
        )
        response = bytearray()
        content_length: int | None = None
        header_end = -1
        while True:
            remaining = probe_deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("managed Ollama probe exceeded its deadline")
            connection.settimeout(remaining)
            chunk = connection.recv(min(4096, _MAX_PROBE_RESPONSE_BYTES + _MAX_PROBE_HEADER_BYTES + 1))
            if not chunk:
                break
            response.extend(chunk)
            if len(response) > _MAX_PROBE_RESPONSE_BYTES + _MAX_PROBE_HEADER_BYTES:
                raise ValueError("managed Ollama probe response is too large")
            if header_end < 0:
                header_end = response.find(b"\r\n\r\n")
                if header_end < 0:
                    if len(response) > _MAX_PROBE_HEADER_BYTES:
                        raise ValueError("managed Ollama probe headers are too large")
                    continue
                if header_end > _MAX_PROBE_HEADER_BYTES:
                    raise ValueError("managed Ollama probe headers are too large")
                header_lines = bytes(response[:header_end]).split(b"\r\n")
                if not header_lines or not header_lines[0].startswith(b"HTTP/1.1 200 "):
                    raise ValueError("managed Ollama probe returned a non-success status")
                for raw_header in header_lines[1:]:
                    name, separator, value = raw_header.partition(b":")
                    if separator and name.strip().lower() == b"content-length":
                        content_length = int(value.strip())
                        if content_length < 0 or content_length > _MAX_PROBE_RESPONSE_BYTES:
                            raise ValueError("managed Ollama probe response is too large")
            if header_end >= 0 and content_length is not None:
                body_size = len(response) - header_end - 4
                if body_size >= content_length:
                    break

    if header_end < 0:
        raise ValueError("managed Ollama probe returned invalid HTTP")
    body = bytes(response[header_end + 4 :])
    if content_length is not None:
        if len(body) != content_length:
            raise ValueError("managed Ollama probe body length is invalid")
    elif len(body) > _MAX_PROBE_RESPONSE_BYTES:
        raise ValueError("managed Ollama probe response is too large")
    if probe_deadline - time.monotonic() <= 0:
        raise TimeoutError("managed Ollama probe exceeded its deadline")
    return json.loads(body)


def _probe_ollama_server(base_url: str, *, deadline: float | None = None) -> str | None:
    try:
        payload = _read_loopback_http_json(base_url, "/api/version", deadline=deadline)
    except Exception:  # noqa: BLE001 - a probe is deliberately best-effort
        return None
    version = payload.get("version") if isinstance(payload, dict) else None
    return str(version).strip() if version else None


def _loopback_request_url(base_url: str, path: str) -> str:
    parsed = urlsplit(base_url)
    parsed_path = urlsplit(path)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or not path.startswith("/")
        or parsed_path.scheme
        or parsed_path.netloc
        or parsed_path.fragment
    ):
        raise OllamaRuntimeError("managed Ollama endpoint is invalid")
    return f"http://127.0.0.1:{parsed.port}{path}"


def _open_loopback_request(request: urllib.request.Request, *, timeout: float) -> Any:
    return _LOOPBACK_OPENER.open(request, timeout=timeout)  # noqa: S310


def _request_ollama_json(
    method: str,
    path: str,
    payload: dict[str, Any] | None,
    *,
    base_url: str,
    cancel_event: threading.Event | None = None,
) -> Any:
    _raise_if_event_cancelled(cancel_event)
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        _loopback_request_url(base_url, path),
        data=body,
        method=method,
        headers={"Content-Type": "application/json", "User-Agent": "FlintTrade/OllamaRuntime"},
    )
    with _open_loopback_request(request, timeout=10) as response:
        with _interrupt_response_on_cancel(response, cancel_event):
            raw_response = response.read(_MAX_OLLAMA_API_RESPONSE_BYTES + 1)
            _raise_if_event_cancelled(cancel_event)
    if len(raw_response) > _MAX_OLLAMA_API_RESPONSE_BYTES:
        raise OllamaRuntimeError("managed Ollama API response exceeded the size limit")
    if not raw_response.strip():
        return None
    try:
        return json.loads(raw_response)
    except (TypeError, ValueError) as exc:
        raise OllamaRuntimeError("managed Ollama API returned invalid JSON") from exc


def _pull_ollama_model(
    model: str,
    progress: Callable[[Any, Any, str, str | None], None],
    *,
    base_url: str,
    cancel_event: threading.Event | None = None,
) -> None:
    _raise_if_event_cancelled(cancel_event)
    request = urllib.request.Request(
        _loopback_request_url(base_url, "/api/pull"),
        data=json.dumps({"model": model, "stream": True}).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "FlintTrade/OllamaRuntime"},
    )
    with _open_loopback_request(request, timeout=10) as response:
        with _interrupt_response_on_cancel(response, cancel_event):
            for raw_line in response:
                _raise_if_event_cancelled(cancel_event)
                if not raw_line.strip():
                    continue
                event = json.loads(raw_line)
                if not isinstance(event, dict):
                    continue
                if event.get("error"):
                    raise OllamaRuntimeError("Ollama model pull failed")
                progress(
                    event.get("completed", 0),
                    event.get("total", 0),
                    str(event.get("status") or "pulling"),
                    str(event["digest"]) if event.get("digest") is not None else None,
                )
            _raise_if_event_cancelled(cancel_event)


_MODEL_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_HARDWARE_CONTROL_VALUE = re.compile(r"[-A-Za-z0-9_.,:/]{1,1024}\Z")
_HSA_OVERRIDE_NAME = re.compile(r"HSA_OVERRIDE_GFX_VERSION(?:_[0-9]{1,3})?\Z")


def _valid_environment_value(value: str, *, max_length: int = 4096) -> bool:
    return bool(value) and len(value) <= max_length and not any(ord(character) < 32 or ord(character) == 127 for character in value)


def _valid_https_proxy(value: str) -> bool:
    if not _valid_environment_value(value):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme.lower() in {"http", "https"}
        and parsed.hostname
        and port is not None
        and not parsed.fragment
    )


def _append_loopback_no_proxy(value: str) -> str:
    entries = [entry.strip() for entry in value.split(",") if entry.strip()]
    for loopback in ("127.0.0.1", "localhost", "::1"):
        if loopback not in entries:
            entries.append(loopback)
    return ",".join(entries)


def _managed_child_environment(
    source: Mapping[str, str],
    *,
    system_name: str | None = None,
) -> dict[str, str]:
    """Copy only documented, non-loader controls into the managed child."""
    environment = {
        key: value
        for key in ("HOME", "PATH", "SystemRoot", "TEMP", "TMP", "TMPDIR", "USERPROFILE")
        if (value := source.get(key)) is not None and _valid_environment_value(value)
    }
    for proxy_name in ("HTTPS_PROXY", "https_proxy"):
        proxy_value = source.get(proxy_name, "")
        if _valid_https_proxy(proxy_value):
            environment[proxy_name] = proxy_value
    for no_proxy_name in ("NO_PROXY", "no_proxy"):
        no_proxy_value = source.get(no_proxy_name, "")
        if not no_proxy_value or _valid_environment_value(no_proxy_value):
            environment[no_proxy_name] = _append_loopback_no_proxy(no_proxy_value)

    if (system_name or platform.system()).strip().lower() != "darwin":
        hardware_names = {
            "CUDA_VISIBLE_DEVICES",
            "HIP_VISIBLE_DEVICES",
            "ROCR_VISIBLE_DEVICES",
            "GGML_VK_VISIBLE_DEVICES",
            "GPU_DEVICE_ORDINAL",
        }
        for name in hardware_names:
            value = source.get(name, "")
            if _HARDWARE_CONTROL_VALUE.fullmatch(value):
                environment[name] = value
        for name, value in source.items():
            if _HSA_OVERRIDE_NAME.fullmatch(name) and re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{1,3}){2}", value):
                environment[name] = value
    return environment


class OllamaRuntime:
    """Own the downloaded Ollama server and its child-process lifecycle."""

    def __init__(
        self,
        workspace_dir: Path,
        *,
        asset: OllamaAsset | None = None,
        overlay_assets: tuple[OllamaAsset, ...] = (),
        releases: Mapping[str, tuple[OllamaAsset, ...]] | None = None,
        target_version: str | None = None,
        downloader: Callable[..., None] | None = None,
        process_factory: Callable[..., Any] = subprocess.Popen,
        probe: Callable[[], str | None] | None = None,
        sleep: Callable[[float], None] | None = None,
        request_json: Callable[[str, str, dict[str, Any] | None], Any] | None = None,
        puller: Callable[[str, Callable[[Any, Any, str, str | None], None]], None] | None = None,
        disk_usage: Callable[[Path], Any] | None = None,
        listener_owner: Callable[[Any], bool] | None = None,
        port_allocator: Callable[[], int] | None = None,
        port_discoverer: Callable[[Any], int] | None = None,
    ) -> None:
        self.workspace_dir = workspace_dir.expanduser().resolve()
        self.runtime_root = self.workspace_dir / "runtime" / "ollama"
        self.target_version = target_version or _OLLAMA_VERSION
        if releases is not None and asset is not None:
            raise ValueError("asset and releases cannot be supplied together")
        if releases is not None:
            self._release_assets = {
                version: tuple(selected_assets)
                for version, selected_assets in releases.items()
            }
        elif asset is None:
            self._release_assets = {
                version: _assets_for_platform(version=version)
                for version in (_OLLAMA_VERSION, *_OLLAMA_ROLLBACK_VERSIONS)
            }
        else:
            self._release_assets = {self.target_version: (asset, *overlay_assets)}
        if self.target_version not in self._release_assets or any(
            not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", version) or not selected_assets
            for version, selected_assets in self._release_assets.items()
        ):
            raise OllamaRuntimeError("managed Ollama release manifest is invalid")
        self._active_version = self.target_version
        self._previous_version: str | None = None
        self._runtime_state_error = ""
        self.assets = self._release_assets[self._active_version]
        self.asset = self.assets[0]
        self.package_variant = ""
        self._select_active_release(self._active_version)
        self.models_dir = self.workspace_dir / "models" / "ollama"
        self.trust_dir = self.workspace_dir / "trust" / "ollama"
        self.log_path = self.workspace_dir / "logs" / "ollama.log"
        self._download = downloader or (
            lambda selected_asset, destination, progress: _download_asset(
                selected_asset,
                destination,
                progress,
                cancel_event=self._cancel_event,
            )
        )
        self._process_factory = process_factory
        self._port = 0
        self._port_allocator = port_allocator
        self._port_discoverer = port_discoverer or self._discover_owned_loopback_port
        self._probe = probe or self._probe_private_endpoint
        self._sleep = sleep or time.sleep
        self._request_json = request_json or (
            lambda method, path, payload: _request_ollama_json(
                method,
                path,
                payload,
                base_url=self.base_url,
                cancel_event=self._cancel_event,
            )
        )
        self._puller = puller or (
            lambda model, progress: _pull_ollama_model(
                model,
                progress,
                base_url=self.base_url,
                cancel_event=self._cancel_event,
            )
        )
        self._disk_usage = disk_usage or shutil.disk_usage
        self._listener_is_owned = listener_owner or (
            lambda process: self._listener_owned_by_process(process, self._port)
        )
        self._process: Any | None = None
        self._windows_job: _WindowsJobHandle | None = None
        self._log_thread: threading.Thread | None = None
        self._log_stream: Any | None = None
        self._log_lock = threading.RLock()
        self._log_error = ""
        self._state_lock = threading.RLock()
        self._process_lock = threading.RLock()
        self._model_trust_lock = threading.RLock()
        self._operation_control_lock = threading.RLock()
        self._lifecycle_lock = threading.RLock()
        self._lifecycle_condition = threading.Condition(self._lifecycle_lock)
        self._lifecycle_transition = False
        self._lifecycle_interrupt = False
        self._active_inferences = 0
        self._cancel_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._operation_context = threading.local()
        self._operation_state_lease_context = threading.local()
        self._operation_owner_lease: BaseFileLock | None = None
        self._operation_journal_observed = False
        self._operation_truth_error = ""
        self._spent_admission_filter = bytes(_OPERATION_SPENT_FILTER_BYTES)
        self._spent_admission_count = 0
        self._operations: list[dict[str, Any]] = []
        self._operation: dict[str, Any] | None = None
        self._phase = "stopped"
        self._error = ""
        self._downloaded_bytes = 0
        self._download_total_bytes = 0
        self._model_pull: dict[str, Any] | None = None
        self._model_digest_drift: dict[str, dict[str, str]] = {}
        self._inference_processor: str | None = None
        self._teardown: dict[str, Any] = {
            "state": "idle",
            "mode": None,
            "active_inferences": 0,
        }
        with self._workspace_lifecycle_lease(
            deadline=time.monotonic() + _SYNC_LIFECYCLE_WAIT_SECONDS,
        ):
            self._recover_repair_transaction()
            self._recover_uninstall_transaction()
            self._load_runtime_state()
            with self._operation_state_lease(
                deadline=time.monotonic() + _SYNC_LIFECYCLE_WAIT_SECONDS,
            ):
                self._load_operation_state()

    @property
    def base_url(self) -> str:
        """Return the private process endpoint, if one has been allocated."""
        return f"http://127.0.0.1:{self._port}" if self._port else ""

    @property
    def install_dir(self) -> Path:
        """Return the selected version directory without an active symlink."""
        return self.runtime_root / self._active_version

    @property
    def server_version(self) -> str:
        return self._active_version.removeprefix("v")

    def _select_active_release(self, version: str) -> None:
        selected = self._release_assets.get(version)
        if selected is None:
            raise OllamaRuntimeError("managed Ollama release is not trusted by this build")
        self._active_version = version
        self.assets = selected
        self.asset = selected[0]
        self.package_variant = next(
            (
                flavour
                for flavour in ("rocm", "jetpack5", "jetpack6")
                if any(f"-{flavour}." in candidate.name for candidate in selected[1:])
            ),
            "",
        )

    def _runtime_state_path(self) -> Path:
        return self.runtime_root / _RUNTIME_STATE_NAME

    def _operation_state_path(self) -> Path:
        return self.runtime_root / _OPERATION_STATE_NAME

    def _operation_journal_marker_path(self) -> Path:
        return self.workspace_dir / _OPERATION_JOURNAL_MARKER_NAME

    def _uninstall_state_path(self) -> Path:
        return self.runtime_root / _UNINSTALL_STATE_NAME

    def _repair_state_path(self) -> Path:
        return self.runtime_root / _REPAIR_STATE_NAME

    def _validate_repair_state(self, payload: Any) -> dict[str, str | int]:
        if not isinstance(payload, dict) or payload.get("schema") != 1:
            raise OllamaRuntimeError("managed Ollama repair state is invalid")
        phase = payload.get("phase")
        version = payload.get("version")
        token = payload.get("token")
        quarantine = payload.get("quarantine")
        if (
            phase not in {"prepared", "committed"}
            or not isinstance(version, str)
            or version not in self._release_assets
            or not isinstance(token, str)
            or re.fullmatch(r"[0-9a-f]{32}", token) is None
            or quarantine != f".repair-{token}"
        ):
            raise OllamaRuntimeError("managed Ollama repair state is invalid")
        return {
            "schema": 1,
            "phase": phase,
            "version": version,
            "token": token,
            "quarantine": quarantine,
        }

    def _read_repair_state(self) -> dict[str, str | int] | None:
        try:
            self._ensure_managed_directory(self.runtime_root, create=False)
        except (FileNotFoundError, OllamaRuntimeError):
            return None
        try:
            raw = _read_private_regular_file(
                self._repair_state_path(),
                max_bytes=_MAX_REPAIR_STATE_BYTES,
                managed_root=self.workspace_dir,
            )
            payload = json.loads(raw)
        except FileNotFoundError:
            return None
        except (OSError, TypeError, ValueError, OllamaRuntimeError) as exc:
            raise OllamaRuntimeError("managed Ollama repair state is invalid") from exc
        return self._validate_repair_state(payload)

    def _write_repair_state(
        self,
        *,
        phase: str,
        version: str,
        token: str,
    ) -> dict[str, str | int]:
        payload = self._validate_repair_state(
            {
                "schema": 1,
                "phase": phase,
                "version": version,
                "token": token,
                "quarantine": f".repair-{token}",
            }
        )
        root = self._ensure_managed_directory(self.runtime_root, create=True)
        path = self._repair_state_path()
        try:
            path_stat = path.lstat()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama repair state could not be inspected") from exc
        else:
            if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
                raise OllamaRuntimeError("managed Ollama repair state is invalid")
        temporary = root / f".{_REPAIR_STATE_NAME}.{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            _write_private_file(temporary, _json_bytes(payload))
            durable_replace(temporary, path)
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama repair state could not be saved") from exc
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        return payload

    def _remove_repair_state(self) -> None:
        path = self._repair_state_path()
        try:
            path_stat = path.lstat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama repair state could not be inspected") from exc
        if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
            raise OllamaRuntimeError("managed Ollama repair state is invalid")
        try:
            durable_unlink(path)
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama repair state could not be removed") from exc

    def _recover_repair_transaction(self) -> None:
        state = self._read_repair_state()
        if state is None:
            return
        version = str(state["version"])
        install_dir = self.runtime_root / version
        quarantine = self.runtime_root / str(state["quarantine"])
        install_exists = install_dir.exists() or install_dir.is_symlink()
        quarantine_exists = quarantine.exists() or quarantine.is_symlink()
        if state["phase"] == "prepared":
            if not install_exists and not quarantine_exists:
                raise OllamaRuntimeError("managed Ollama repair rollback could not be proven")
            if install_exists and quarantine_exists:
                _remove_path_without_following_root(install_dir)
                install_exists = False
            if quarantine_exists:
                try:
                    durable_replace(quarantine, install_dir)
                except OSError as exc:
                    raise OllamaRuntimeError("managed Ollama repair rollback could not be completed") from exc
            self._remove_repair_state()
            return
        if not install_exists:
            raise OllamaRuntimeError("managed Ollama committed repair state is invalid")
        self._verified_executable(rehash=True, version=version)
        if quarantine_exists:
            _remove_path_without_following_root(quarantine)
            fsync_parent_directory(quarantine)
        self._remove_repair_state()

    def _validate_uninstall_state(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict) or payload.get("schema") != 1:
            raise OllamaRuntimeError("managed Ollama uninstall state is invalid")
        phase = payload.get("phase")
        token = payload.get("token")
        raw_releases = payload.get("releases")
        if (
            phase not in {"prepared", "committed"}
            or not isinstance(token, str)
            or re.fullmatch(r"[0-9a-f]{32}", token) is None
            or not isinstance(raw_releases, list)
            or len(raw_releases) > len(self._release_assets)
        ):
            raise OllamaRuntimeError("managed Ollama uninstall state is invalid")
        releases: list[dict[str, str]] = []
        seen: set[str] = set()
        for raw_release in raw_releases:
            if not isinstance(raw_release, dict):
                raise OllamaRuntimeError("managed Ollama uninstall state is invalid")
            version = raw_release.get("version")
            quarantine = raw_release.get("quarantine")
            kind = raw_release.get("kind")
            if (
                not isinstance(version, str)
                or version not in self._release_assets
                or version in seen
                or quarantine != f".uninstall-{token}-{version}"
                or kind not in {"directory", "path"}
            ):
                raise OllamaRuntimeError("managed Ollama uninstall state is invalid")
            seen.add(version)
            releases.append({"version": version, "quarantine": quarantine, "kind": kind})
        return {"schema": 1, "phase": phase, "token": token, "releases": releases}

    def _read_uninstall_state(self) -> dict[str, Any] | None:
        try:
            self._ensure_managed_directory(self.runtime_root, create=False)
        except (FileNotFoundError, OllamaRuntimeError):
            return None
        try:
            raw = _read_private_regular_file(
                self._uninstall_state_path(),
                max_bytes=_MAX_UNINSTALL_STATE_BYTES,
                managed_root=self.workspace_dir,
            )
            payload = json.loads(raw)
        except FileNotFoundError:
            return None
        except (OSError, TypeError, ValueError, OllamaRuntimeError) as exc:
            raise OllamaRuntimeError("managed Ollama uninstall state is invalid") from exc
        return self._validate_uninstall_state(payload)

    def _write_uninstall_state(
        self,
        *,
        phase: str,
        token: str,
        releases: list[dict[str, str]],
    ) -> dict[str, Any]:
        payload = self._validate_uninstall_state(
            {"schema": 1, "phase": phase, "token": token, "releases": releases}
        )
        root = self._ensure_managed_directory(self.runtime_root, create=True)
        path = self._uninstall_state_path()
        try:
            path_stat = path.lstat()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama uninstall state could not be inspected") from exc
        else:
            if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
                raise OllamaRuntimeError("managed Ollama uninstall state is invalid")
        temporary = root / f".{_UNINSTALL_STATE_NAME}.{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            _write_private_file(temporary, _json_bytes(payload))
            durable_replace(temporary, path)
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama uninstall state could not be saved") from exc
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        return payload

    def _remove_uninstall_state(self) -> None:
        path = self._uninstall_state_path()
        try:
            path_stat = path.lstat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama uninstall state could not be inspected") from exc
        if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
            raise OllamaRuntimeError("managed Ollama uninstall state is invalid")
        try:
            durable_unlink(path)
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama uninstall state could not be removed") from exc

    def _remove_runtime_state_for_uninstall(self) -> None:
        path = self._runtime_state_path()
        try:
            path_stat = path.lstat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama runtime version state could not be inspected") from exc
        if stat.S_ISDIR(path_stat.st_mode) and not stat.S_ISLNK(path_stat.st_mode):
            raise OllamaRuntimeError("managed Ollama runtime version state is invalid")
        try:
            durable_unlink(path)
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama runtime version state could not be removed") from exc

    def _rollback_prepared_uninstall(self, state: dict[str, Any]) -> None:
        for release in reversed(state["releases"]):
            original = self.runtime_root / release["version"]
            quarantine = self.runtime_root / release["quarantine"]
            original_exists = original.exists() or original.is_symlink()
            quarantine_exists = quarantine.exists() or quarantine.is_symlink()
            if original_exists and quarantine_exists or not original_exists and not quarantine_exists:
                raise OllamaRuntimeError("managed Ollama uninstall rollback could not be proven")
            if quarantine_exists:
                if release["kind"] == "directory":
                    self._ensure_managed_directory(quarantine, create=False)
                try:
                    durable_replace(quarantine, original)
                except OSError as exc:
                    raise OllamaRuntimeError("managed Ollama uninstall rollback could not be completed") from exc
            if release["kind"] == "directory":
                self._verified_executable(rehash=True, version=release["version"])
        self._remove_uninstall_state()

    def _finish_committed_uninstall(self, state: dict[str, Any]) -> None:
        self._remove_runtime_state_for_uninstall()
        for release in state["releases"]:
            original = self.runtime_root / release["version"]
            quarantine = self.runtime_root / release["quarantine"]
            if original.exists() or original.is_symlink():
                raise OllamaRuntimeError("managed Ollama committed uninstall state is invalid")
            if quarantine.exists() or quarantine.is_symlink():
                if release["kind"] == "directory":
                    self._ensure_managed_directory(quarantine, create=False)
                _remove_path_without_following_root(quarantine)
                fsync_parent_directory(quarantine)
        self._owned_residue_for_uninstall(remove=True)
        self._remove_uninstall_state()

    def _recover_uninstall_transaction(self) -> None:
        state = self._read_uninstall_state()
        if state is None:
            return
        if state["phase"] == "prepared":
            self._rollback_prepared_uninstall(state)
            return
        self._finish_committed_uninstall(state)

    def _infer_runtime_state(self) -> tuple[str, str | None]:
        ordered = (self.target_version, *(
            version for version in self._release_assets if version != self.target_version
        ))
        present = [
            version
            for version in ordered
            if (self.runtime_root / version).exists() or (self.runtime_root / version).is_symlink()
        ]
        active = present[0] if present else self.target_version
        previous = next((version for version in present[1:] if version != active), None)
        return active, previous

    def _load_runtime_state(self) -> None:
        inferred_active, inferred_previous = self._infer_runtime_state()
        try:
            self._ensure_managed_directory(self.runtime_root, create=False)
            raw = _read_private_regular_file(
                self._runtime_state_path(),
                max_bytes=_MAX_RUNTIME_STATE_BYTES,
                managed_root=self.workspace_dir,
            )
        except FileNotFoundError:
            self._select_active_release(inferred_active)
            self._previous_version = inferred_previous
            if inferred_previous is not None:
                self._runtime_state_error = "managed Ollama runtime version state is invalid"
            return
        except (OSError, OllamaRuntimeError):
            self._runtime_state_error = "managed Ollama runtime version state is invalid"
            self._select_active_release(inferred_active)
            self._previous_version = inferred_previous
            return
        try:
            payload = json.loads(raw)
            active = payload.get("active_version") if isinstance(payload, dict) else None
            previous = payload.get("previous_version") if isinstance(payload, dict) else None
            valid = (
                isinstance(payload, dict)
                and payload.get("schema") == 1
                and isinstance(active, str)
                and active in self._release_assets
                and (previous is None or isinstance(previous, str) and previous in self._release_assets)
                and previous != active
            )
            if not valid:
                raise ValueError("invalid runtime state")
        except (TypeError, ValueError):
            self._runtime_state_error = "managed Ollama runtime version state is invalid"
            self._select_active_release(inferred_active)
            self._previous_version = inferred_previous
            return
        self._select_active_release(active)
        self._previous_version = previous

    def _write_runtime_state(self, active: str, previous: str | None) -> None:
        if (
            active not in self._release_assets
            or previous is not None and previous not in self._release_assets
            or previous == active
        ):
            raise OllamaRuntimeError("managed Ollama runtime version state is invalid")
        self._mark_operation_mutation_started()
        root = self._ensure_managed_directory(self.runtime_root, create=True)
        path = self._runtime_state_path()
        if path.is_symlink():
            raise OllamaRuntimeError("managed Ollama runtime version state is invalid")
        temporary = root / f".{_RUNTIME_STATE_NAME}.{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            _write_private_file(
                temporary,
                _json_bytes(
                    {
                        "schema": 1,
                        "active_version": active,
                        "previous_version": previous,
                    }
                ),
            )
            durable_replace(temporary, path)
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama runtime version state could not be saved") from exc
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        self._select_active_release(active)
        self._previous_version = previous
        self._runtime_state_error = ""

    @staticmethod
    def _normalise_operation_subject(kind: str, subject: Any) -> dict[str, str] | None:
        if subject is None:
            return None
        if not isinstance(subject, dict):
            raise ValueError("managed Ollama operation subject is invalid")
        if kind in {"pull_model", "delete_model"}:
            if set(subject) != {"model"}:
                raise ValueError("managed Ollama operation subject is invalid")
            model = subject.get("model")
            if kind == "pull_model":
                _validate_pull_model_identifier(model)
            else:
                _validate_model_identifier(model)
            return {"model": model}
        if kind == "accept_model_digest":
            if set(subject) != {"model", "digest"}:
                raise ValueError("managed Ollama operation subject is invalid")
            model = subject.get("model")
            digest = _normalise_model_digest(subject.get("digest"))
            _validate_model_identifier(model)
            if digest is None:
                raise ValueError("managed Ollama operation subject is invalid")
            return {"model": model, "digest": digest}
        raise ValueError("managed Ollama operation subject is invalid")

    @staticmethod
    def _normalise_operation_result(
        kind: str,
        result: Any,
        subject: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        if not isinstance(result, dict):
            return None
        if kind == "pull_model":
            if set(result) != {
                "model",
                "status",
                "completed",
                "total",
                "error",
                "digest",
                "previous_digest",
                "digest_changed",
                "acceptance_required",
            }:
                return None
            model = result.get("model")
            status = result.get("status")
            completed = result.get("completed")
            total = result.get("total")
            digest = _normalise_model_digest(result.get("digest"))
            previous_digest = _normalise_model_digest(result.get("previous_digest"))
            digest_changed = result.get("digest_changed")
            acceptance_required = result.get("acceptance_required")
            if (
                not isinstance(model, str)
                or status not in {"success", "awaiting_digest_acceptance"}
                or isinstance(completed, bool)
                or not isinstance(completed, int)
                or isinstance(total, bool)
                or not isinstance(total, int)
                or total <= 0
                or completed != total
                or digest is None
                or result.get("error") is not None
                or not isinstance(digest_changed, bool)
                or not isinstance(acceptance_required, bool)
                or (result.get("previous_digest") is not None and previous_digest is None)
                or digest_changed is not bool(previous_digest and previous_digest != digest)
                or acceptance_required is not (previous_digest != digest)
                or status != ("awaiting_digest_acceptance" if acceptance_required else "success")
            ):
                return None
            try:
                _validate_pull_model_identifier(model)
            except ValueError:
                return None
            if subject is not None and model != subject.get("model"):
                return None
            return {
                "model": model,
                "status": status,
                "completed": completed,
                "total": total,
                "error": None,
                "digest": digest,
                "previous_digest": previous_digest,
                "digest_changed": digest_changed,
                "acceptance_required": acceptance_required,
            }
        if kind == "accept_model_digest":
            accepted = result.get("accepted")
            model = result.get("model")
            source_model = result.get("source_model")
            digest = result.get("digest")
            if (
                accepted is not True
                or not isinstance(model, str)
                or not isinstance(source_model, str)
                or not isinstance(digest, str)
                or len(model) > 256
                or len(source_model) > 256
                or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                or set(result) != {"accepted", "model", "source_model", "digest"}
            ):
                return None
            try:
                _validate_model_identifier(model)
                _validate_model_identifier(source_model)
            except ValueError:
                return None
            if model != _locked_model_alias(digest):
                return None
            if subject is not None and (
                digest != subject.get("digest")
                or not set(_model_aliases(source_model)).intersection(_model_aliases(subject.get("model", "")))
            ):
                return None
            return {
                "accepted": True,
                "model": model,
                "source_model": source_model,
                "digest": digest,
            }
        if kind == "reset_model_digests":
            return {"reset": True} if result.get("reset") is True else None
        if kind in {"delete_model", "prune_models"}:
            if set(result) != {"deleted", "pruned"}:
                return None
            deleted = result.get("deleted")
            pruned = result.get("pruned")
            if (
                not isinstance(deleted, list)
                or not isinstance(pruned, list)
                or len(deleted) > _MAX_OPERATION_RESULT_MODELS
                or len(pruned) > _MAX_OPERATION_RESULT_MODELS
                or any(not isinstance(value, str) or len(value) > 256 for value in [*deleted, *pruned])
                or len(set(deleted)) != len(deleted)
                or len(set(pruned)) != len(pruned)
            ):
                return None
            if kind == "delete_model":
                if len(deleted) != 1 or pruned:
                    return None
                try:
                    _validate_model_identifier(deleted[0])
                except ValueError:
                    return None
                if subject is not None and not set(_model_aliases(deleted[0])).intersection(
                    _model_aliases(subject.get("model", ""))
                ):
                    return None
            else:
                if deleted:
                    return None
                for alias in pruned:
                    if not alias.startswith(_LOCKED_MODEL_PREFIX) or not alias.endswith(_LOCKED_MODEL_SUFFIX):
                        return None
                    digest = alias[len(_LOCKED_MODEL_PREFIX) : -len(_LOCKED_MODEL_SUFFIX)]
                    if not _is_locked_model_alias(alias, digest):
                        return None
            return {"deleted": list(deleted), "pruned": list(pruned)}
        return None

    def _validate_operation(self, operation: Any) -> dict[str, Any]:
        if not isinstance(operation, dict):
            raise OllamaRuntimeError("managed Ollama operation state is invalid")
        operation_id = operation.get("id")
        admission_id = operation.get("admission_id")
        kind = operation.get("kind")
        state = operation.get("state")
        started_at = operation.get("started_at")
        finished_at = operation.get("finished_at")
        reconciled_at = operation.get("reconciled_at")
        raw_subject = operation.get("subject")
        error = operation.get("error")
        result = operation.get("result")
        owner_pid = operation.get("owner_pid", 0)
        owner_create_time = operation.get("owner_create_time", 0.0)
        owner_token = operation.get("owner_token", "")
        if (
            not isinstance(operation_id, str)
            or _OPERATION_ID.fullmatch(operation_id) is None
            or not isinstance(admission_id, str)
            or _ADMISSION_ID.fullmatch(admission_id) is None
            or kind not in _OPERATION_KINDS
            or state not in _OPERATION_STATES
            or isinstance(started_at, bool)
            or not isinstance(started_at, (int, float))
            or started_at <= 0
            or (
                state == "running"
                and (finished_at is not None or error is not None)
            )
            or (
                state != "running"
                and (
                    isinstance(finished_at, bool)
                    or not isinstance(finished_at, (int, float))
                    or finished_at < started_at
                )
            )
            or (
                reconciled_at is not None
                and (
                    state != "indeterminate"
                    or isinstance(reconciled_at, bool)
                    or not isinstance(reconciled_at, (int, float))
                    or reconciled_at < finished_at
                )
            )
            or (error is not None and (not isinstance(error, str) or len(error) > 500))
            or (state == "succeeded" and error is not None)
            or (state == "failed" and (not isinstance(error, str) or not error))
            or (state == "cancelled" and error is not None)
            or (state == "indeterminate" and (not isinstance(error, str) or not error))
            or (state != "succeeded" and result is not None)
            or isinstance(owner_pid, bool)
            or not isinstance(owner_pid, int)
            or owner_pid < 0
            or isinstance(owner_create_time, bool)
            or not isinstance(owner_create_time, (int, float))
            or owner_create_time < 0
            or not isinstance(owner_token, str)
            or (owner_token and _OPERATION_OWNER_TOKEN.fullmatch(owner_token) is None)
            or (state == "running" and (owner_pid <= 0 or owner_create_time <= 0 or not owner_token))
        ):
            raise OllamaRuntimeError("managed Ollama operation state is invalid")
        try:
            subject = self._normalise_operation_subject(str(kind), raw_subject)
        except ValueError as exc:
            raise OllamaRuntimeError("managed Ollama operation state is invalid") from exc
        normalised_result = self._normalise_operation_result(str(kind), result, subject)
        if result is not None and normalised_result != result:
            raise OllamaRuntimeError("managed Ollama operation state is invalid")
        if kind in _OPERATION_SUBJECT_KINDS and subject is None and state != "indeterminate":
            raise OllamaRuntimeError("managed Ollama operation state is invalid")
        if state == "succeeded" and kind in _OPERATION_RESULT_KINDS and normalised_result is None:
            raise OllamaRuntimeError("managed Ollama operation state is invalid")
        return {
            "id": operation_id,
            "admission_id": admission_id,
            "kind": kind,
            "state": state,
            "started_at": float(started_at),
            "finished_at": float(finished_at) if finished_at is not None else None,
            "reconciled_at": float(reconciled_at) if reconciled_at is not None else None,
            "subject": subject,
            "error": error,
            "result": normalised_result,
            "owner_pid": owner_pid,
            "owner_create_time": float(owner_create_time),
            "owner_token": owner_token,
        }

    def _validate_operation_state(self, payload: Any) -> tuple[list[dict[str, Any]], bytes, int]:
        if not isinstance(payload, dict):
            raise OllamaRuntimeError("managed Ollama operation state is invalid")
        schema = payload.get("schema")
        spent_filter = bytes(_OPERATION_SPENT_FILTER_BYTES)
        spent_count = 0

        def migrate_unknown(operation: dict[str, Any]) -> None:
            started_at = operation.get("started_at")
            finished_at = operation.get("finished_at")
            if (
                finished_at is None
                and not isinstance(started_at, bool)
                and isinstance(started_at, (int, float))
            ):
                finished_at = max(time.time(), float(started_at))
            operation.update(
                {
                    "state": "indeterminate",
                    "finished_at": finished_at,
                    "reconciled_at": None,
                    "error": _INDETERMINATE_OPERATION_ERROR,
                    "result": None,
                }
            )

        if schema == 1 and isinstance(payload.get("operation"), dict):
            legacy_operation = dict(payload["operation"])
            if legacy_operation.get("state") == "running" and "owner_pid" not in legacy_operation:
                legacy_operation.update(
                    {
                        "state": "indeterminate",
                        "finished_at": max(time.time(), float(legacy_operation.get("started_at") or 0.0)),
                        "error": _INDETERMINATE_OPERATION_ERROR,
                        "result": None,
                    }
                )
            raw_operations = [legacy_operation]
        elif schema == 2 and isinstance(payload.get("operations"), list):
            raw_operations = payload["operations"]
        elif schema in {3, _OPERATION_STATE_SCHEMA} and isinstance(
            payload.get("operations"), list
        ):
            raw_operations = [dict(operation) if isinstance(operation, dict) else operation for operation in payload["operations"]]
            if schema == 3:
                for operation in raw_operations:
                    if (
                        isinstance(operation, dict)
                        and operation.get("kind") == "pull_model"
                        and operation.get("state") == "succeeded"
                        and operation.get("result") is None
                    ):
                        migrate_unknown(operation)
            spent = payload.get("spent_admissions")
            if spent is not None:
                if (
                    not isinstance(spent, dict)
                    or spent.get("algorithm") != "sha256-double-hash-v1"
                    or isinstance(spent.get("count"), bool)
                    or not isinstance(spent.get("count"), int)
                    or not 0 < spent["count"] < 2**63
                    or not isinstance(spent.get("filter"), str)
                ):
                    raise OllamaRuntimeError("managed Ollama operation state is invalid")
                try:
                    spent_filter = base64.b64decode(spent["filter"], validate=True)
                except (ValueError, base64.binascii.Error) as exc:
                    raise OllamaRuntimeError("managed Ollama operation state is invalid") from exc
                if len(spent_filter) != _OPERATION_SPENT_FILTER_BYTES:
                    raise OllamaRuntimeError("managed Ollama operation state is invalid")
                spent_count = spent["count"]
        else:
            raise OllamaRuntimeError("managed Ollama operation state is invalid")
        if schema != _OPERATION_STATE_SCHEMA:
            for operation in raw_operations:
                if (
                    isinstance(operation, dict)
                    and operation.get("kind") in _OPERATION_SUBJECT_KINDS
                    and operation.get("subject") is None
                ):
                    migrate_unknown(operation)
        if not raw_operations or len(raw_operations) > _MAX_OPERATION_RECEIPTS:
            raise OllamaRuntimeError("managed Ollama operation state is invalid")
        operations = [self._validate_operation(operation) for operation in raw_operations]
        operation_ids = {operation["id"] for operation in operations}
        admission_ids = {operation["admission_id"] for operation in operations}
        running = [operation for operation in operations if operation["state"] == "running"]
        if len(operation_ids) != len(operations) or len(admission_ids) != len(operations) or len(running) > 1:
            raise OllamaRuntimeError("managed Ollama operation state is invalid")
        return operations, spent_filter, spent_count

    def _encoded_operation_state(
        self,
        operations: list[dict[str, Any]] | dict[str, Any],
        *,
        spent_filter: bytes | None = None,
        spent_count: int | None = None,
    ) -> bytes:
        selected = operations if isinstance(operations, list) else [operations]
        selected_filter = self._spent_admission_filter if spent_filter is None else spent_filter
        selected_count = self._spent_admission_count if spent_count is None else spent_count
        spent_admissions = (
            {
                "algorithm": "sha256-double-hash-v1",
                "count": selected_count,
                "filter": base64.b64encode(selected_filter).decode("ascii"),
            }
            if selected_count
            else None
        )
        payload = {
            "schema": _OPERATION_STATE_SCHEMA,
            "operations": selected,
            "spent_admissions": spent_admissions,
        }
        validated, validated_filter, validated_count = self._validate_operation_state(payload)
        return _json_bytes(
            {
                "schema": _OPERATION_STATE_SCHEMA,
                "operations": validated,
                "spent_admissions": (
                    {
                        "algorithm": "sha256-double-hash-v1",
                        "count": validated_count,
                        "filter": base64.b64encode(validated_filter).decode("ascii"),
                    }
                    if validated_count
                    else None
                ),
            }
        )

    def _mark_operation_truth_unavailable(self, message: str) -> None:
        with self._state_lock:
            if not self._operation_truth_error:
                self._operation_truth_error = message

    def _read_operation_journal_marker(self) -> bool | None:
        try:
            raw = _read_private_regular_file(
                self._operation_journal_marker_path(),
                max_bytes=_MAX_OPERATION_JOURNAL_MARKER_BYTES,
                managed_root=self.workspace_dir,
            )
        except FileNotFoundError:
            return None
        except (OSError, OllamaRuntimeError) as exc:
            raise OllamaRuntimeError("managed Ollama operation journal marker is invalid") from exc
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise OllamaRuntimeError("managed Ollama operation journal marker is invalid") from exc
        if (
            not isinstance(payload, dict)
            or set(payload) != {"schema", "journal_created"}
            or payload.get("schema") != 1
            or not isinstance(payload.get("journal_created"), bool)
        ):
            raise OllamaRuntimeError("managed Ollama operation journal marker is invalid")
        return payload["journal_created"]

    def _write_operation_journal_marker(self, *, journal_created: bool) -> None:
        root = self._ensure_managed_directory(self.workspace_dir, create=True)
        path = self._operation_journal_marker_path()
        if path.is_symlink():
            raise OllamaRuntimeError("managed Ollama operation journal marker is invalid")
        temporary = root / f".{_OPERATION_JOURNAL_MARKER_NAME}.{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            _write_private_file(
                temporary,
                _json_bytes({"schema": 1, "journal_created": journal_created}),
            )
            durable_replace(temporary, path)
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama operation journal marker could not be saved") from exc
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _write_operation_state(self, operations: list[dict[str, Any]] | dict[str, Any]) -> None:
        encoded = self._encoded_operation_state(operations)
        if len(encoded) > _MAX_OPERATION_STATE_BYTES:
            raise OllamaRuntimeError("managed Ollama operation receipt journal is full")
        if self._read_operation_journal_marker() is not True:
            self._write_operation_journal_marker(journal_created=True)
        root = self._ensure_managed_directory(self.runtime_root, create=True)
        path = self._operation_state_path()
        if path.is_symlink():
            raise OllamaRuntimeError("managed Ollama operation state is invalid")
        temporary = root / f".{_OPERATION_STATE_NAME}.{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            _write_private_file(temporary, encoded)
            durable_replace(temporary, path)
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama operation state could not be saved") from exc
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        with self._state_lock:
            self._operation_journal_observed = True

    def _read_operation_state(self, *, required: bool = False) -> tuple[list[dict[str, Any]], bool]:
        journal_was_created = self._read_operation_journal_marker()
        with self._state_lock:
            truth_error = self._operation_truth_error
            journal_observed = self._operation_journal_observed
        if truth_error:
            raise OllamaRuntimeError(truth_error)
        try:
            self._ensure_managed_directory(self.runtime_root, create=False)
            raw = _read_private_regular_file(
                self._operation_state_path(),
                max_bytes=_MAX_OPERATION_STATE_BYTES,
                managed_root=self.workspace_dir,
            )
        except FileNotFoundError:
            if required or journal_was_created is True or journal_observed:
                message = "managed Ollama operation truth is unavailable because its receipt journal is missing"
                self._mark_operation_truth_unavailable(message)
                raise OllamaRuntimeError(message)
            self._spent_admission_filter = bytes(_OPERATION_SPENT_FILTER_BYTES)
            self._spent_admission_count = 0
            return [], False
        except OllamaRuntimeError as exc:
            raise OllamaRuntimeError("managed Ollama operation state is invalid") from exc
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama operation state is invalid") from exc
        try:
            payload = json.loads(raw)
            operations, spent_filter, spent_count = self._validate_operation_state(payload)
        except (TypeError, ValueError, OllamaRuntimeError) as exc:
            raise OllamaRuntimeError("managed Ollama operation state is invalid") from exc
        self._spent_admission_filter = spent_filter
        self._spent_admission_count = spent_count
        with self._state_lock:
            self._operation_journal_observed = True
        return operations, payload.get("schema") != _OPERATION_STATE_SCHEMA

    def _spent_admission_might_exist(self, admission_id: str) -> bool:
        operation_filter = self._spent_admission_filter
        return all(
            operation_filter[position // 8] & (1 << (position % 8))
            for position in _spent_admission_positions(admission_id)
        )

    def _fit_operation_receipts(
        self,
        operations: list[dict[str, Any]],
        *,
        protected_operation_ids: set[str] | None = None,
    ) -> tuple[list[dict[str, Any]], bytes, int]:
        if _MAX_OPERATION_RECEIPTS < 1:
            raise OllamaRuntimeError("managed Ollama operation receipt limit is invalid")
        protected = protected_operation_ids or set()
        retained = list(operations)
        spent_filter = bytearray(self._spent_admission_filter)
        spent_count = self._spent_admission_count

        while True:
            over_count = max(0, len(retained) - _MAX_OPERATION_RECEIPTS)
            encoded_size = _MAX_OPERATION_STATE_BYTES + 1
            if over_count == 0:
                encoded_size = len(
                    self._encoded_operation_state(
                        retained,
                        spent_filter=bytes(spent_filter),
                        spent_count=spent_count,
                    )
                )
            if over_count == 0 and encoded_size <= _MAX_OPERATION_STATE_BYTES:
                return retained, bytes(spent_filter), spent_count

            removable = [
                operation
                for operation in retained
                if operation.get("state") != "running"
                and operation.get("state") != "indeterminate"
                and str(operation["id"]) not in protected
            ]
            if not removable:
                raise OllamaRuntimeError("managed Ollama operation receipt journal cannot be compacted safely")
            reclaim = max(1, len(retained) // 4)
            remove_count = min(len(removable), max(over_count, reclaim))
            removed = removable[:remove_count]
            removed_ids = {str(operation["id"]) for operation in removed}
            retained = [operation for operation in retained if str(operation["id"]) not in removed_ids]
            for operation in removed:
                admission_id = str(operation["admission_id"])
                for position in _spent_admission_positions(admission_id):
                    spent_filter[position // 8] |= 1 << (position % 8)
            spent_count += remove_count

    def _mark_interrupted_operations(
        self,
        operations: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], bool]:
        changed = False
        updated: list[dict[str, Any]] = []
        for operation in operations:
            candidate = dict(operation)
            if candidate["state"] == "running" and not self._operation_owner_is_alive(candidate):
                candidate.update(
                    {
                        "state": "indeterminate",
                        "finished_at": max(time.time(), float(candidate["started_at"])),
                        "error": _INDETERMINATE_OPERATION_ERROR,
                        "result": None,
                    }
                )
                changed = True
            updated.append(candidate)
        return updated, changed

    def _operation_owner_is_alive(self, operation: dict[str, Any]) -> bool:
        owner_pid = int(operation.get("owner_pid") or 0)
        owner_create_time = float(operation.get("owner_create_time") or 0.0)
        if not self._process_identity_is_alive(owner_pid, owner_create_time):
            return False

        lock_path = self.workspace_dir / _OPERATION_OWNER_LOCK_NAME
        self._prepare_operation_lock_path(lock_path, "owner")
        lease = _RuntimeFileLock(lock_path, timeout=0, mode=0o600, thread_local=False)
        try:
            lease.acquire(timeout=0)
        except FileLockTimeout:
            return True
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama operation owner lease could not be inspected") from exc
        try:
            self._validate_operation_lock_path(lock_path, "owner")
            return False
        finally:
            lease.release()

    def _load_operation_state(self) -> None:
        journal_was_created = self._read_operation_journal_marker()
        operations, legacy = self._read_operation_state(required=journal_was_created is True)
        if journal_was_created is None or (journal_was_created is False and self._operation_journal_observed):
            self._write_operation_journal_marker(journal_created=self._operation_journal_observed)
        if not operations:
            return
        operations, interrupted = self._mark_interrupted_operations(operations)
        if legacy or interrupted:
            self._write_operation_state(operations)
        self._operations = operations
        self._operation = dict(operations[-1])

    def _ensure_runtime_state_committed(self) -> None:
        """Persist an unambiguous legacy selection before staging another release."""
        path = self._runtime_state_path()
        try:
            path_stat = path.lstat()
        except FileNotFoundError:
            self._write_runtime_state(self._active_version, self._previous_version)
            return
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama runtime version state could not be inspected") from exc
        if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
            raise OllamaRuntimeError("managed Ollama runtime version state is invalid")

    def _repair_runtime_state(self, *, active_verified: bool = False) -> None:
        """Rebuild invalid version metadata from fully verified managed releases."""
        if not self._runtime_state_error:
            raise OllamaRuntimeError("managed Ollama runtime version state does not need recovery")
        active = self._active_version
        if not active_verified:
            self._verified_executable(rehash=True, version=active)
        previous = self._previous_version
        if previous is not None:
            try:
                self._verified_executable(rehash=True, version=previous)
            except OllamaRuntimeError:
                previous = None

        path = self._runtime_state_path()
        try:
            path_stat = path.lstat()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama runtime version state could not be inspected") from exc
        else:
            if stat.S_ISLNK(path_stat.st_mode):
                try:
                    self._mark_operation_mutation_started()
                    durable_unlink(path)
                except OSError as exc:
                    raise OllamaRuntimeError("managed Ollama runtime version state could not be reset") from exc
            elif not stat.S_ISREG(path_stat.st_mode):
                raise OllamaRuntimeError("managed Ollama runtime version state is not a removable file")
        self._mark_operation_mutation_started()
        self._write_runtime_state(active, previous)

    def _probe_private_endpoint(self) -> str | None:
        return _probe_ollama_server(self.base_url) if self._port else None

    def _ensure_managed_directory(self, directory: Path, *, create: bool) -> Path:
        """Validate one workspace descendant without following directory symlinks."""
        try:
            relative = directory.relative_to(self.workspace_dir)
        except ValueError as exc:
            raise OllamaRuntimeError("managed Ollama path is unsafe") from exc

        current = self.workspace_dir
        if not current.exists():
            if not create:
                raise FileNotFoundError(current)
            current.mkdir(parents=True, exist_ok=True)
        try:
            current_stat = current.lstat()
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama path is unsafe") from exc
        if (
            stat.S_ISLNK(current_stat.st_mode)
            or self._path_is_reparse(current_stat)
            or not stat.S_ISDIR(current_stat.st_mode)
        ):
            raise OllamaRuntimeError("managed Ollama path is unsafe")
        if create:
            try:
                harden_directory(current)
            except OSError as exc:
                raise OllamaRuntimeError("managed Ollama path could not be made private") from exc

        for part in relative.parts:
            current /= part
            try:
                current_stat = current.lstat()
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    current.mkdir()
                except FileExistsError:
                    pass
                except OSError as exc:
                    raise OllamaRuntimeError("managed Ollama path is unsafe") from exc
                try:
                    current_stat = current.lstat()
                except OSError as exc:
                    raise OllamaRuntimeError("managed Ollama path is unsafe") from exc
            except OSError as exc:
                raise OllamaRuntimeError("managed Ollama path is unsafe") from exc
            if (
                stat.S_ISLNK(current_stat.st_mode)
                or self._path_is_reparse(current_stat)
                or not stat.S_ISDIR(current_stat.st_mode)
            ):
                raise OllamaRuntimeError("managed Ollama path is unsafe")
            if create:
                try:
                    harden_directory(current)
                except OSError as exc:
                    raise OllamaRuntimeError("managed Ollama path could not be made private") from exc
        return current

    @staticmethod
    def _path_is_reparse(path_stat: os.stat_result) -> bool:
        reparse_mask = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        return bool(reparse_mask and getattr(path_stat, "st_file_attributes", 0) & reparse_mask)

    @staticmethod
    def _bounded_children(directory: Path) -> list[Path]:
        children: list[Path] = []
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if len(children) >= _MAX_RUNTIME_ROOT_ENTRIES:
                        raise OllamaRuntimeError("managed Ollama directory contains too many entries")
                    children.append(Path(entry.path))
        except OllamaRuntimeError:
            raise
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama directory could not be inspected") from exc
        return children

    def _measure_managed_path(self, path: Path, *, entries: list[int]) -> int:
        try:
            path_stat = path.lstat()
        except FileNotFoundError:
            return 0
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama storage could not be inspected") from exc
        if stat.S_ISLNK(path_stat.st_mode) or self._path_is_reparse(path_stat):
            repair_state = self._read_repair_state()
            owned_repair_link = (
                path.parent == self.install_dir.parent
                and re.fullmatch(r"\.repair-[0-9a-f]{32}", path.name) is not None
                and (
                    self._read_residue_marker(path, kind="repair") is not None
                    or repair_state is not None and repair_state["quarantine"] == path.name
                )
            )
            if not owned_repair_link:
                raise OllamaRuntimeError("managed Ollama storage is unsafe")
            entries[0] += 1
            return int(path_stat.st_size)
        entries[0] += 1
        if entries[0] > _MAX_MANAGED_STORAGE_ENTRIES:
            raise OllamaRuntimeError("managed Ollama storage contains too many entries")
        if stat.S_ISREG(path_stat.st_mode):
            return int(path_stat.st_size)
        if not stat.S_ISDIR(path_stat.st_mode):
            raise OllamaRuntimeError("managed Ollama storage is unsafe")

        total = 0
        try:
            with os.scandir(path) as children:
                for child in children:
                    total += self._measure_managed_path(Path(child.path), entries=entries)
        except OllamaRuntimeError:
            raise
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama storage could not be inspected") from exc
        return total

    def _managed_storage_bytes(self, *, include_logs: bool = True, enforce_limit: bool = True) -> int:
        """Measure every FlintTrade-owned Ollama path without following links."""
        entries = [0]
        total = 0
        for root in (self.install_dir.parent, self.models_dir, self.trust_dir):
            try:
                safe_root = self._ensure_managed_directory(root, create=False)
            except FileNotFoundError:
                continue
            total += self._measure_managed_path(safe_root, entries=entries)
        if include_logs:
            total += self._log_storage_bytes(entries=entries)
        if enforce_limit and total > _MAX_MANAGED_STORAGE_BYTES:
            raise OllamaRuntimeError("managed Ollama storage exceeds the size limit")
        return total

    def _log_paths(self) -> tuple[Path, ...]:
        return (
            self.log_path,
            *(self.log_path.with_name(f"{self.log_path.name}.{index}") for index in range(1, _LOG_BACKUP_COUNT + 1)),
        )

    def _log_storage_bytes(self, *, entries: list[int] | None = None) -> int:
        counter = entries if entries is not None else [0]
        try:
            log_root = self._ensure_managed_directory(self.log_path.parent, create=False)
        except FileNotFoundError:
            return 0
        base_name = re.escape(self.log_path.name)
        owned_name = re.compile(
            rf"(?:{base_name}(?:\.[0-9]+)?|\.{base_name}(?:\.[0-9]+)?\.[0-9]+\.[0-9]+\.tmp)\Z"
        )
        total = 0
        try:
            with os.scandir(log_root) as children:
                for child in children:
                    if owned_name.fullmatch(child.name):
                        total += self._measure_managed_path(Path(child.path), entries=counter)
        except OllamaRuntimeError:
            raise
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama logs could not be inspected") from exc
        return total

    def _ensure_extraction_capacity(self, next_bytes: int, *, managed_bytes: int | None = None) -> int:
        if next_bytes < 0:
            raise OllamaRuntimeError("managed Ollama extraction reported an invalid write size")
        try:
            free_bytes = int(self._disk_usage(self.workspace_dir).free)
        except (OSError, TypeError, ValueError) as exc:
            raise OllamaRuntimeError("could not verify free disk space during extraction") from exc
        if free_bytes < next_bytes + _INSTALL_DISK_RESERVE_BYTES:
            raise OllamaRuntimeError("insufficient free disk space during extraction")
        current_bytes = (
            self._managed_storage_bytes(enforce_limit=False)
            if managed_bytes is None
            else managed_bytes
        )
        if current_bytes + next_bytes > _MAX_MANAGED_STORAGE_BYTES:
            raise OllamaRuntimeError("managed Ollama extraction exceeds the managed storage size limit")
        return current_bytes + next_bytes

    def _residue_marker_path(self, path: Path, *, kind: str) -> Path:
        if kind == "install":
            return path / _RESIDUE_MARKER_NAME
        if kind == "repair":
            return path.with_name(f".{path.name}.owner.json")
        raise ValueError("unsupported managed residue kind")

    def _write_residue_marker(
        self,
        path: Path,
        *,
        kind: str,
        created_at: float | None = None,
        owner_pid: int | None = None,
        owner_create_time: float | None = None,
    ) -> Path:
        path_stat = path.lstat()
        install_path_is_safe = not stat.S_ISLNK(path_stat.st_mode) and stat.S_ISDIR(path_stat.st_mode)
        repair_path_is_safe = stat.S_ISDIR(path_stat.st_mode) or stat.S_ISREG(path_stat.st_mode) or stat.S_ISLNK(
            path_stat.st_mode
        )
        if (kind == "install" and not install_path_is_safe) or (kind == "repair" and not repair_path_is_safe):
            raise OllamaRuntimeError("managed Ollama residue path is unsafe")
        pid = os.getpid() if owner_pid is None else owner_pid
        process_created = (
            self._process_create_time(pid, strict=True)
            if owner_create_time is None
            else owner_create_time
        )
        marker = self._residue_marker_path(path, kind=kind)
        _write_private_file(
            marker,
            _json_bytes(
                {
                    "schema": 1,
                    "kind": kind,
                    "path": path.name,
                    "created_at": time.time() if created_at is None else created_at,
                    "owner_pid": pid,
                    "owner_create_time": process_created,
                    "token": secrets.token_hex(16),
                }
            ),
        )
        return marker

    def _read_residue_marker(self, path: Path, *, kind: str) -> dict[str, Any] | None:
        marker = self._residue_marker_path(path, kind=kind)
        try:
            raw = _read_private_regular_file(
                marker,
                max_bytes=2048,
                managed_root=self.workspace_dir,
            )
            payload = json.loads(raw)
        except FileNotFoundError:
            return None
        except (OSError, ValueError, TypeError, OllamaRuntimeError):
            return None
        if not isinstance(payload, dict) or payload.get("schema") != 1:
            return None
        if payload.get("kind") != kind or payload.get("path") != path.name:
            return None
        if (
            isinstance(payload.get("owner_pid"), bool)
            or not isinstance(payload.get("owner_pid"), int)
            or isinstance(payload.get("owner_create_time"), bool)
            or not isinstance(payload.get("owner_create_time"), (int, float))
            or isinstance(payload.get("created_at"), bool)
            or not isinstance(payload.get("created_at"), (int, float))
            or not isinstance(payload.get("token"), str)
            or not re.fullmatch(r"[0-9a-f]{32}", payload["token"])
        ):
            return None
        return payload

    def _remove_residue_marker(self, path: Path, *, kind: str) -> None:
        marker = self._residue_marker_path(path, kind=kind)
        try:
            durable_unlink(marker)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama residue marker could not be removed") from exc

    def _scavenge_stale_residue(self, *, now: float | None = None) -> None:
        current_time = time.time() if now is None else now
        runtime_root = self._ensure_managed_directory(self.install_dir.parent, create=True)
        staging_root = runtime_root / ".staging"
        candidates: list[tuple[Path, str]] = []
        try:
            if staging_root.exists() and not staging_root.is_symlink():
                candidates.extend(
                    (path, "install")
                    for path in self._bounded_children(staging_root)
                    if re.fullmatch(r"install-[0-9a-f]{32}", path.name)
                )
            candidates.extend(
                (path, "repair")
                for path in self._bounded_children(runtime_root)
                if re.fullmatch(r"\.repair-[0-9a-f]{32}", path.name)
            )
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama residue could not be inspected") from exc

        for path, kind in candidates:
            try:
                path_stat = path.lstat()
            except OSError:
                continue
            if kind == "install" and (stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISDIR(path_stat.st_mode)):
                continue
            if kind == "repair" and not (
                stat.S_ISDIR(path_stat.st_mode)
                or stat.S_ISREG(path_stat.st_mode)
                or stat.S_ISLNK(path_stat.st_mode)
            ):
                continue
            marker = self._read_residue_marker(path, kind=kind)
            if marker is None:
                continue
            age = current_time - float(marker["created_at"])
            if age < _STALE_RESIDUE_SECONDS or self._process_identity_is_alive(
                int(marker["owner_pid"]),
                float(marker["owner_create_time"]),
            ):
                continue
            _remove_path_without_following_root(path)
            if kind == "repair":
                self._remove_residue_marker(path, kind=kind)

    def _owned_residue_for_uninstall(self, *, remove: bool) -> list[tuple[Path, str]]:
        """Find or remove only residue carrying a valid FlintTrade ownership marker."""
        try:
            runtime_root = self._ensure_managed_directory(self.runtime_root, create=False)
        except FileNotFoundError:
            return []
        staging_root = runtime_root / ".staging"
        candidates: list[tuple[Path, str]] = []
        try:
            if staging_root.exists() and not staging_root.is_symlink():
                candidates.extend(
                    (path, "install")
                    for path in self._bounded_children(staging_root)
                    if re.fullmatch(r"install-[0-9a-f]{32}", path.name)
                )
            candidates.extend(
                (path, "repair")
                for path in self._bounded_children(runtime_root)
                if re.fullmatch(r"\.repair-[0-9a-f]{32}", path.name)
            )
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama residue could not be inspected for uninstall") from exc

        owned: list[tuple[Path, str]] = []
        for path, kind in candidates:
            marker = self._read_residue_marker(path, kind=kind)
            if marker is None:
                continue
            owner_pid = int(marker["owner_pid"])
            owner_created = float(marker["owner_create_time"])
            if self._process_identity_is_alive(owner_pid, owner_created):
                current_owner = owner_pid == os.getpid() and abs(
                    self._process_create_time(os.getpid(), strict=True) - owner_created
                ) < 0.01
                if not current_owner:
                    raise OllamaRuntimeError("another process still owns managed Ollama residue")
            owned.append((path, kind))

        if not remove:
            return owned
        for path, kind in owned:
            _remove_path_without_following_root(path)
            if kind == "repair":
                self._remove_residue_marker(path, kind=kind)
        try:
            staging_root.rmdir()
        except (FileNotFoundError, OSError):
            pass
        return owned

    def _regular_log_size(self, path: Path) -> int:
        try:
            path_stat = path.lstat()
        except FileNotFoundError:
            return 0
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama log could not be inspected") from exc
        if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
            raise OllamaRuntimeError("managed Ollama log path is unsafe")
        return int(path_stat.st_size)

    def _append_private_log(self, payload: bytes) -> None:
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.log_path, flags, 0o600)
            path_stat = os.fstat(descriptor)
            if not stat.S_ISREG(path_stat.st_mode):
                raise OllamaRuntimeError("managed Ollama log path is unsafe")
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short managed Ollama log write")
                view = view[written:]
        except OllamaRuntimeError:
            raise
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama log could not be written") from exc
        finally:
            if "descriptor" in locals():
                os.close(descriptor)
        harden(self.log_path)

    def _bound_existing_log(self, path: Path) -> None:
        size = self._regular_log_size(path)
        if size <= _MAX_LOG_FILE_BYTES:
            return
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
            with os.fdopen(descriptor, "rb") as source:
                descriptor = -1
                source.seek(-_MAX_LOG_FILE_BYTES, os.SEEK_END)
                tail = source.read(_MAX_LOG_FILE_BYTES + 1)
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama log could not be bounded") from exc
        finally:
            if "descriptor" in locals() and descriptor != -1:
                os.close(descriptor)
        if len(tail) != _MAX_LOG_FILE_BYTES:
            raise OllamaRuntimeError("managed Ollama log could not be bounded")
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            _write_private_file(temporary, tail)
            durable_replace(temporary, path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _normalise_existing_logs(self) -> None:
        log_root = self._ensure_managed_directory(self.log_path.parent, create=True)
        numbered_log = re.compile(rf"{re.escape(self.log_path.name)}\.([0-9]+)\Z")
        temporary_log = re.compile(
            rf"\.{re.escape(self.log_path.name)}(?:\.[0-9]+)?\.[0-9]+\.[0-9]+\.tmp\Z"
        )
        with self._log_lock:
            try:
                with os.scandir(log_root) as children:
                    residue = []
                    for child in children:
                        numbered_match = numbered_log.fullmatch(child.name)
                        if temporary_log.fullmatch(child.name) or (
                            numbered_match is not None
                            and not 1 <= int(numbered_match.group(1)) <= _LOG_BACKUP_COUNT
                        ):
                            residue.append(Path(child.path))
            except OSError as exc:
                raise OllamaRuntimeError("managed Ollama logs could not be inspected") from exc
            for path in residue:
                try:
                    path_stat = path.lstat()
                    if not (stat.S_ISREG(path_stat.st_mode) or stat.S_ISLNK(path_stat.st_mode)):
                        raise OllamaRuntimeError("managed Ollama log path is unsafe")
                    path.unlink()
                except FileNotFoundError:
                    continue
                except OllamaRuntimeError:
                    raise
                except OSError as exc:
                    raise OllamaRuntimeError("managed Ollama log residue could not be removed") from exc
            for path in self._log_paths():
                self._bound_existing_log(path)
            if self._log_storage_bytes() > _MAX_LOG_STORAGE_BYTES:
                raise OllamaRuntimeError("managed Ollama logs exceed the storage size limit")

    def _rotate_logs(self) -> None:
        oldest = self.log_path.with_name(f"{self.log_path.name}.{_LOG_BACKUP_COUNT}")
        if _LOG_BACKUP_COUNT > 0 and self._regular_log_size(oldest):
            _remove_path_without_following_root(oldest)
        for index in range(_LOG_BACKUP_COUNT - 1, 0, -1):
            source = self.log_path.with_name(f"{self.log_path.name}.{index}")
            destination = self.log_path.with_name(f"{self.log_path.name}.{index + 1}")
            if self._regular_log_size(source):
                durable_replace(source, destination)
        if _LOG_BACKUP_COUNT > 0 and self._regular_log_size(self.log_path):
            durable_replace(self.log_path, self.log_path.with_name(f"{self.log_path.name}.1"))

    def _append_log_chunk(self, payload: bytes) -> None:
        if not payload:
            return
        self._ensure_managed_directory(self.log_path.parent, create=True)
        with self._log_lock:
            remaining = memoryview(payload)
            while remaining:
                current_size = self._regular_log_size(self.log_path)
                if current_size >= _MAX_LOG_FILE_BYTES:
                    self._rotate_logs()
                    current_size = 0
                writable = min(len(remaining), _MAX_LOG_FILE_BYTES - current_size)
                piece = bytes(remaining[:writable])
                if self._managed_storage_bytes(enforce_limit=False) + len(piece) > _MAX_MANAGED_STORAGE_BYTES:
                    raise OllamaRuntimeError("managed Ollama logs exceed the managed storage size limit")
                self._append_private_log(piece)
                remaining = remaining[writable:]

    def _pump_logs(self, stream: Any) -> None:
        try:
            while chunk := stream.read(1024 * 1024):
                try:
                    self._append_log_chunk(chunk)
                except OllamaRuntimeError as exc:
                    with self._state_lock:
                        self._log_error = str(exc)
        except (OSError, ValueError) as exc:
            with self._state_lock:
                self._log_error = f"managed Ollama log stream failed: {type(exc).__name__}"
        finally:
            try:
                stream.close()
            except (OSError, ValueError):
                pass

    def _start_log_pump(self, process: Any) -> None:
        stream = getattr(process, "stdout", None)
        if stream is None or not hasattr(stream, "read"):
            return
        self._log_stream = stream
        self._log_thread = threading.Thread(
            target=self._pump_logs,
            args=(stream,),
            name="flinttrade-ollama-log",
            daemon=True,
        )
        self._log_thread.start()

    def _finish_log_pump(self, *, deadline: float) -> bool:
        stream = self._log_stream
        if stream is not None:
            try:
                stream.close()
            except (OSError, ValueError):
                pass
        thread = self._log_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=_remaining_teardown_time(deadline))
        finished = thread is None or not thread.is_alive()
        if finished:
            self._log_stream = None
            self._log_thread = None
        return finished

    @staticmethod
    def _owned_loopback_listener_ports(process: Any) -> set[int]:
        """Return loopback listener ports owned by the launched process tree."""
        if process is None or process.poll() is not None:
            return set()
        ports: set[int] = set()
        try:
            root = psutil.Process(int(process.pid))
        except (OSError, psutil.Error, TypeError, ValueError):
            return set()
        try:
            processes = [root, *root.children(recursive=True)]
        except (OSError, psutil.Error, TypeError, ValueError):
            processes = [root]
        for owned_process in processes:
            try:
                for connection in owned_process.net_connections(kind="tcp"):
                    if connection.status != psutil.CONN_LISTEN or not connection.laddr:
                        continue
                    host = getattr(connection.laddr, "ip", None)
                    port = getattr(connection.laddr, "port", None)
                    if host is None or port is None:
                        host, port = connection.laddr[:2]
                    if host in {"127.0.0.1", "::1"} and isinstance(port, int) and 1 <= port <= 65535:
                        ports.add(port)
            except (OSError, psutil.Error, TypeError, ValueError):
                continue
        return ports

    @classmethod
    def _listener_owned_by_process(cls, process: Any, expected_port: int = 0) -> bool:
        """Prove the loopback listener belongs to the launched process tree."""
        return expected_port > 0 and expected_port in cls._owned_loopback_listener_ports(process)

    @classmethod
    def _discover_owned_loopback_port(cls, process: Any) -> int:
        """Discover exactly one atomically allocated server listener."""
        ports = cls._owned_loopback_listener_ports(process)
        if len(ports) > 1:
            raise OllamaRuntimeError("managed Ollama exposed ambiguous loopback listeners")
        return next(iter(ports), 0)

    def _process_owner_path(self) -> Path:
        return self.install_dir.parent / _PROCESS_OWNER_STATE_NAME

    def _write_process_owner_record(self, record: dict[str, Any], *, exclusive: bool = False) -> None:
        owner_root = self._ensure_managed_directory(self.install_dir.parent, create=True)
        path = self._process_owner_path()
        if path.is_symlink():
            raise OllamaRuntimeError("managed Ollama process ownership state is invalid")
        if exclusive:
            try:
                _write_private_file(path, _json_bytes(record))
                fsync_parent_directory(path)
            except OllamaRuntimeError as exc:
                if path.exists() or path.is_symlink():
                    raise OllamaRuntimeError("managed Ollama process ownership is already claimed") from exc
                raise OllamaRuntimeError("managed Ollama process ownership could not be claimed") from exc
            return
        temporary = owner_root / f".{_PROCESS_OWNER_STATE_NAME}.{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            _write_private_file(temporary, _json_bytes(record))
            durable_replace(temporary, path)
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama process ownership state could not be saved") from exc
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _read_process_owner_record(
        self,
        *,
        deadline: float | None = None,
    ) -> dict[str, Any] | None:
        path = self._process_owner_path()
        try:
            self._ensure_managed_directory(self.install_dir.parent, create=False)
            raw = _read_private_regular_file(
                path,
                max_bytes=4096,
                deadline=deadline,
                managed_root=self.workspace_dir,
            )
        except FileNotFoundError:
            return None
        except (OSError, OllamaRuntimeError) as exc:
            raise OllamaRuntimeError("managed Ollama process ownership state is invalid") from exc
        try:
            record = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise OllamaRuntimeError("managed Ollama process ownership state is invalid") from exc
        required_types = {
            "backend_pid": int,
            "backend_create_time": (int, float),
            "child_pid": int,
            "child_create_time": (int, float),
            "port": int,
            "executable_sha256": str,
        }
        if not isinstance(record, dict) or record.get("schema") != 1:
            raise OllamaRuntimeError("managed Ollama process ownership state is invalid")
        if any(isinstance(record.get(key), bool) or not isinstance(record.get(key), kind) for key, kind in required_types.items()):
            raise OllamaRuntimeError("managed Ollama process ownership state is invalid")
        if (
            record["backend_pid"] <= 0
            or record["child_pid"] < 0
            or (record["port"] != 0 and not 1024 <= record["port"] <= 65535)
            or (
                "bind_port" in record
                and (
                    isinstance(record["bind_port"], bool)
                    or not isinstance(record["bind_port"], int)
                    or (record["bind_port"] != 0 and not 1024 <= record["bind_port"] <= 65535)
                )
            )
            or not re.fullmatch(r"[0-9a-f]{64}", record["executable_sha256"])
        ):
            raise OllamaRuntimeError("managed Ollama process ownership state is invalid")
        return record

    def _remove_process_owner_record(self) -> None:
        path = self._process_owner_path()
        try:
            path_stat = path.lstat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama process ownership state could not be removed") from exc
        if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
            raise OllamaRuntimeError("managed Ollama process ownership state is invalid")
        try:
            durable_unlink(path)
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama process ownership state could not be removed") from exc

    def _remove_process_owner_record_after_teardown(self) -> None:
        try:
            self._remove_process_owner_record()
        except OllamaRuntimeError:
            self._phase = "failed"
            self._error = "managed Ollama ownership cleanup is incomplete"
            raise

    @staticmethod
    def _process_identity_is_alive(pid: int, created_at: float) -> bool:
        if pid <= 0 or created_at <= 0:
            return False
        try:
            process = psutil.Process(pid)
            return bool(
                process.is_running()
                and process.status() != psutil.STATUS_ZOMBIE
                and abs(float(process.create_time()) - float(created_at)) < 0.01
            )
        except (psutil.NoSuchProcess, psutil.ZombieProcess, ProcessLookupError):
            return False
        except (OSError, psutil.Error, TypeError, ValueError) as exc:
            raise OllamaRuntimeError("managed Ollama process identity could not be verified") from exc

    @staticmethod
    def _process_create_time(pid: int, *, strict: bool) -> float:
        try:
            return float(psutil.Process(pid).create_time())
        except (OSError, psutil.Error, TypeError, ValueError) as exc:
            if strict:
                raise OllamaRuntimeError("managed Ollama process identity could not be recorded") from exc
            return 0.0

    def _recover_stale_owned_process(
        self,
        *,
        deadline: float | None = None,
        allow_current_backend: bool = False,
    ) -> bool:
        """Clear dead ownership records without signalling an inherited PID."""
        _raise_if_integrity_deadline_expired(deadline)
        record = self._read_process_owner_record(deadline=deadline)
        if record is None:
            return False
        backend_is_alive = self._process_identity_is_alive(
            int(record["backend_pid"]),
            float(record["backend_create_time"]),
        )
        current_backend = False
        if allow_current_backend and int(record["backend_pid"]) == os.getpid():
            current_backend = abs(
                self._process_create_time(os.getpid(), strict=True)
                - float(record["backend_create_time"])
            ) < 0.01
        if backend_is_alive and not current_backend:
            raise OllamaRuntimeError("another FlintTrade backend still owns the managed Ollama runtime")
        if int(record["child_pid"]) == 0:
            raise OllamaRuntimeError(
                "managed Ollama startup ownership is incomplete; terminate the inherited process manually"
            )
        child_is_alive = self._process_identity_is_alive(
            int(record["child_pid"]),
            float(record["child_create_time"]),
        )
        if not child_is_alive:
            _raise_if_integrity_deadline_expired(deadline)
            stale_version = (
                _probe_ollama_server(
                    f"http://127.0.0.1:{record['port']}",
                    deadline=deadline,
                )
                if int(record["port"]) != 0
                else None
            )
            _raise_if_integrity_deadline_expired(deadline)
            if stale_version is not None:
                raise OllamaRuntimeError("stale managed Ollama child identity could not be verified")
            self._remove_process_owner_record_after_teardown()
            return True
        raise OllamaRuntimeError(
            "managed Ollama survived its owning backend; terminate it manually before continuing"
        )

    def _metadata_file(self, name: str, *, version: str | None = None) -> Path:
        install_dir = self.runtime_root / (version or self._active_version)
        return install_dir / name

    def _regular_install_file(self, path: Path, *, install_dir: Path | None = None) -> bool:
        selected_install_dir = install_dir or self.install_dir
        try:
            relative = path.relative_to(selected_install_dir)
        except ValueError:
            return False
        current = selected_install_dir
        for part in relative.parts:
            try:
                current_stat = current.lstat()
            except OSError:
                return False
            if (
                stat.S_ISLNK(current_stat.st_mode)
                or self._path_is_reparse(current_stat)
                or not stat.S_ISDIR(current_stat.st_mode)
            ):
                return False
            current /= part
        try:
            final_stat = current.lstat()
        except OSError:
            return False
        return (
            stat.S_ISREG(final_stat.st_mode)
            and not stat.S_ISLNK(final_stat.st_mode)
            and not self._path_is_reparse(final_stat)
        )

    def _read_install_json(
        self,
        path: Path,
        *,
        install_dir: Path | None = None,
        deadline: float | None = None,
    ) -> tuple[dict[str, Any], bytes]:
        _raise_if_integrity_deadline_expired(deadline)
        if not self._regular_install_file(path, install_dir=install_dir):
            raise OllamaRuntimeError("managed Ollama runtime integrity verification failed")
        max_bytes = {
            _INSTALL_MANIFEST_NAME: _MAX_INSTALL_MANIFEST_BYTES,
            _INSTALL_MARKER_NAME: _MAX_INSTALL_MARKER_BYTES,
        }.get(path.name)
        if max_bytes is None:
            raise OllamaRuntimeError("managed Ollama runtime integrity verification failed")
        try:
            raw = _read_private_regular_file(
                path,
                max_bytes=max_bytes,
                deadline=deadline,
                invalid_message="managed Ollama runtime integrity verification failed",
                managed_root=self.workspace_dir,
            )
            payload = json.loads(raw)
        except (OSError, ValueError, TypeError) as exc:
            raise OllamaRuntimeError("managed Ollama runtime integrity verification failed") from exc
        _raise_if_integrity_deadline_expired(deadline)
        if not isinstance(payload, dict):
            raise OllamaRuntimeError("managed Ollama runtime integrity verification failed")
        return payload, raw

    def _verified_executable(
        self,
        *,
        rehash: bool,
        deadline: float | None = None,
        version: str | None = None,
    ) -> Path:
        _raise_if_integrity_deadline_expired(deadline)
        selected_version = version or self._active_version
        selected_assets = self._release_assets.get(selected_version)
        if selected_assets is None:
            raise OllamaRuntimeError("managed Ollama release is not trusted by this build")
        selected_asset = selected_assets[0]
        install_dir = self.runtime_root / selected_version
        try:
            self._ensure_managed_directory(install_dir, create=False)
        except FileNotFoundError as exc:
            raise OllamaRuntimeError("managed Ollama runtime is not installed") from exc
        marker, _marker_bytes = self._read_install_json(
            self._metadata_file(_INSTALL_MARKER_NAME, version=selected_version),
            install_dir=install_dir,
            deadline=deadline,
        )
        manifest, manifest_bytes = self._read_install_json(
            self._metadata_file(_INSTALL_MANIFEST_NAME, version=selected_version),
            install_dir=install_dir,
            deadline=deadline,
        )
        expected_assets = [
            {"name": asset.name, "sha256": asset.sha256}
            for asset in selected_assets
        ]
        if (
            marker.get("schema") != 3
            or marker.get("version") != selected_version
            or marker.get("assets") != expected_assets
            or marker.get("manifest_sha256") != hashlib.sha256(manifest_bytes).hexdigest()
            or manifest.get("schema") != 2
        ):
            raise OllamaRuntimeError("managed Ollama runtime integrity verification failed")

        candidate = str(manifest.get("executable") or "")
        raw_files = manifest.get("files")
        max_manifest_entries = (_MAX_EXTRACTED_MEMBERS * len(selected_assets)) + 2
        max_tree_bytes = min(
            _MAX_RUNTIME_TREE_BYTES,
            sum(asset.max_extracted_bytes for asset in selected_assets),
        )
        if (
            candidate not in selected_asset.executable_candidates
            or not isinstance(raw_files, list)
            or len(raw_files) > max_manifest_entries
        ):
            raise OllamaRuntimeError("managed Ollama runtime integrity verification failed")
        expected_files: dict[str, tuple[int, str]] = {}
        expected_total_bytes = 0
        for raw_file in raw_files:
            _raise_if_integrity_deadline_expired(deadline)
            if not isinstance(raw_file, dict):
                raise OllamaRuntimeError("managed Ollama runtime integrity verification failed")
            relative = str(raw_file.get("path") or "")
            expected_size = raw_file.get("size_bytes")
            expected_digest = str(raw_file.get("sha256") or "").lower()
            try:
                safe_relative = _safe_archive_path(relative).as_posix()
            except OllamaRuntimeError as exc:
                raise OllamaRuntimeError("managed Ollama runtime integrity verification failed") from exc
            if (
                safe_relative in expected_files
                or safe_relative in {_INSTALL_MANIFEST_NAME, _INSTALL_MARKER_NAME}
                or not isinstance(expected_size, int)
                or expected_size < 0
                or not re.fullmatch(r"[0-9a-f]{64}", expected_digest)
            ):
                raise OllamaRuntimeError("managed Ollama runtime integrity verification failed")
            expected_files[safe_relative] = (expected_size, expected_digest)
            expected_total_bytes += expected_size
            if expected_total_bytes > max_tree_bytes:
                raise OllamaRuntimeError("managed Ollama runtime integrity verification failed")
        if candidate not in expected_files or expected_files[candidate][0] < 1:
            raise OllamaRuntimeError("managed Ollama runtime integrity verification failed")

        actual_files: dict[str, Path] = {}
        actual_entries = 0
        try:
            for path in install_dir.rglob("*"):
                _raise_if_integrity_deadline_expired(deadline)
                actual_entries += 1
                if actual_entries > max_manifest_entries:
                    raise OllamaRuntimeError("managed Ollama runtime integrity verification failed")
                relative = path.relative_to(install_dir).as_posix()
                path_stat = path.lstat()
                if self._path_is_reparse(path_stat):
                    raise OllamaRuntimeError("managed Ollama path is unsafe")
                if stat.S_ISDIR(path_stat.st_mode):
                    continue
                if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
                    raise OllamaRuntimeError("managed Ollama runtime integrity verification failed")
                if relative not in {_INSTALL_MANIFEST_NAME, _INSTALL_MARKER_NAME}:
                    actual_files[relative] = path
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama runtime integrity verification failed") from exc
        if set(actual_files) != set(expected_files):
            raise OllamaRuntimeError("managed Ollama runtime integrity verification failed")
        for relative, (expected_size, expected_digest) in expected_files.items():
            _raise_if_integrity_deadline_expired(deadline)
            path = actual_files[relative]
            try:
                actual_size = path.stat().st_size
            except OSError as exc:
                raise OllamaRuntimeError("managed Ollama runtime integrity verification failed") from exc
            if actual_size != expected_size or (
                rehash and _sha256_file(path, deadline=deadline) != expected_digest
            ):
                raise OllamaRuntimeError("managed Ollama runtime integrity verification failed")

        executable = install_dir.joinpath(*PurePosixPath(candidate).parts)
        if not self._regular_install_file(executable, install_dir=install_dir):
            raise OllamaRuntimeError("managed Ollama runtime integrity verification failed")
        return executable

    def _installation_status(
        self,
        *,
        verification_deadline: float | None = None,
        version: str | None = None,
    ) -> tuple[bool, str | None]:
        selected_version = version or self._active_version
        try:
            self._verified_executable(
                rehash=False,
                deadline=verification_deadline,
                version=selected_version,
            )
        except OllamaRuntimeError as exc:
            if str(exc) in {
                "managed Ollama path is unsafe",
                "managed Ollama integrity verification timed out",
            }:
                return False, str(exc)
            try:
                install_dir = self.runtime_root / selected_version
                installed_path_exists = install_dir.exists() or install_dir.is_symlink()
            except OSError:
                installed_path_exists = True
            if installed_path_exists:
                return False, str(exc)
            return False, None
        return True, None

    @staticmethod
    def _public_operation(operation: dict[str, Any] | None) -> dict[str, Any] | None:
        if operation is None:
            return None
        return {
            key: operation.get(key)
            for key in (
                "id",
                "admission_id",
                "kind",
                "state",
                "started_at",
                "finished_at",
                "reconciled_at",
                "error",
                "result",
            )
        }

    def _status_snapshot(
        self,
        *,
        probe_server: bool = False,
        verification_deadline: float | None = None,
    ) -> dict[str, Any]:
        installed, installation_integrity_error = self._installation_status(
            verification_deadline=verification_deadline
        )
        with self._deadline_lock(
            self._process_lock,
            deadline=verification_deadline,
            operation="status snapshot",
        ):
            process = self._process
            server_version = self._probe() if probe_server else None
            managed = bool(process is not None and process.poll() is None)
            listener_owned = bool(managed and self._listener_is_owned(process))
            ready = bool(server_version == self.server_version and listener_owned)
            external = bool(server_version and not listener_owned)
            with self._deadline_lock(
                self._state_lock,
                deadline=verification_deadline,
                operation="status snapshot",
            ):
                operation_truth_error = self._operation_truth_error
                integrity_error = (
                    operation_truth_error
                    or self._runtime_state_error
                    or installation_integrity_error
                )
                phase = self._phase
                operation = self._public_operation(self._operation)
                unresolved_operation = self._public_operation(
                    next(
                        (
                            candidate
                            for candidate in self._operations
                            if candidate.get("state") == "indeterminate"
                            and candidate.get("reconciled_at") is None
                        ),
                        None,
                    )
                )
                model_pull = dict(self._model_pull) if self._model_pull is not None else None
                error = self._error or None
                downloaded_bytes = self._downloaded_bytes
                download_total_bytes = self._download_total_bytes
                model_digest_drift = {
                    model: dict(digests) for model, digests in self._model_digest_drift.items()
                }
                teardown = dict(self._teardown)
                inference_processor = self._inference_processor
                log_error = self._log_error or None
                if phase == "ready" and not ready:
                    phase = "failed"
                    error = error or "managed Ollama server stopped unexpectedly"
                    self._phase = phase
                    self._error = error
                    _clear_managed_ollama_owner(self)
        if integrity_error is None and error == "managed Ollama runtime integrity verification failed":
            integrity_error = error

        repair_needed = bool(
            self._runtime_state_error
            or installation_integrity_error
            or error == "managed Ollama runtime integrity verification failed"
        )
        repair_blocked_reason: str | None = None
        if operation_truth_error:
            repair_blocked_reason = (
                "Durable operation receipt truth is unavailable; runtime-file repair cannot recover it."
            )
        elif unresolved_operation is not None:
            repair_blocked_reason = "A previous Ollama operation outcome must be acknowledged first."
        elif managed or external or ready:
            repair_blocked_reason = "Stop every Ollama listener before runtime repair."
        elif operation is not None and operation.get("state") == "running":
            repair_blocked_reason = "Wait for the active Ollama operation to finish."
        elif not repair_needed:
            repair_blocked_reason = "Runtime repair is not required."
        repair_allowed = repair_blocked_reason is None

        if phase == "failed":
            state = "failed"
        elif external:
            state = "conflict"
        elif ready:
            state = "ready"
        elif phase in {"downloading", "extracting", "starting"}:
            state = phase
        elif installed:
            state = "installed"
        else:
            state = "not_installed"
        previous_dir = self.runtime_root / self._previous_version if self._previous_version else None
        rollback_available = bool(
            self._previous_version
            and self._previous_version in self._release_assets
            and previous_dir is not None
            and (previous_dir.exists() or previous_dir.is_symlink())
        )
        rollback_blocked_reason: str | None = None
        if not rollback_available:
            rollback_blocked_reason = "No retained rollback release is available."
        elif self._runtime_state_error:
            rollback_blocked_reason = "Runtime version state must be repaired before rollback."
        elif managed or external:
            rollback_blocked_reason = "Stop the Ollama runtime before rollback."
        elif operation is not None and operation.get("state") == "running":
            rollback_blocked_reason = "Wait for the active Ollama operation to finish."
        else:
            previous_installed, previous_integrity_error = self._installation_status(
                verification_deadline=verification_deadline,
                version=self._previous_version,
            )
            if not previous_installed:
                rollback_blocked_reason = previous_integrity_error or "The retained rollback release is unavailable."
        rollback_allowed = rollback_blocked_reason is None
        target_assets = self._release_assets[self.target_version]
        return {
            "version": self.target_version,
            "active_version": self._active_version,
            "target_version": self.target_version,
            "previous_version": self._previous_version,
            "update_available": self._active_version != self.target_version,
            "rollback_available": rollback_available,
            "rollback_allowed": rollback_allowed,
            "rollback_blocked_reason": rollback_blocked_reason,
            "repair_allowed": repair_allowed,
            "repair_blocked_reason": repair_blocked_reason,
            "supported": True,
            "installed": installed,
            "state": state,
            "ready": ready,
            "managed_process": managed,
            "external_process": external,
            "server_version": server_version,
            "downloaded_bytes": downloaded_bytes,
            "download_total_bytes": download_total_bytes,
            "install_required_bytes": _install_assets_required_bytes(target_assets),
            "package_variant": self.package_variant or None,
            "inference_processor": inference_processor,
            "model_pull": model_pull,
            "model_digest_drift": model_digest_drift,
            "operation": operation,
            "unresolved_operation": unresolved_operation,
            "teardown": teardown,
            "error": error,
            "log_error": log_error,
            "integrity_error": integrity_error,
        }

    def _prepare_direct_operation(self) -> None:
        with self._state_lock:
            worker = self._worker
            if worker is not None and worker.is_alive() and worker is not threading.current_thread():
                raise OllamaRuntimeError("another Ollama operation is already running")
            if worker is not threading.current_thread():
                self._cancel_event.clear()

    def _current_worker_is_cancelled(self, *, deadline: float | None = None) -> bool:
        with self._deadline_lock(
            self._state_lock,
            deadline=deadline,
            operation="lifecycle transition",
        ):
            return self._worker is threading.current_thread() and self._cancel_event.is_set()

    @contextmanager
    def _deadline_lock(
        self,
        lock: Any,
        *,
        deadline: float | None,
        operation: str,
    ) -> Iterator[None]:
        acquired = (
            lock.acquire()
            if deadline is None
            else lock.acquire(timeout=max(0.0, deadline - time.monotonic()))
        )
        if not acquired:
            raise OllamaRuntimeError(f"managed Ollama {operation} timed out")
        try:
            yield
        finally:
            lock.release()

    @contextmanager
    def _bounded_state_lock(self, *, deadline: float, operation: str) -> Iterator[None]:
        with self._deadline_lock(self._state_lock, deadline=deadline, operation=operation):
            yield

    @contextmanager
    def _workspace_lifecycle_lease(self, *, deadline: float | None = None) -> Iterator[None]:
        """Hold one OS-backed lease for every workspace lifecycle mutation."""
        try:
            self.workspace_dir.mkdir(parents=True, exist_ok=True)
            workspace_stat = self.workspace_dir.lstat()
            if (
                stat.S_ISLNK(workspace_stat.st_mode)
                or self._path_is_reparse(workspace_stat)
                or not stat.S_ISDIR(workspace_stat.st_mode)
            ):
                raise OllamaRuntimeError("managed Ollama workspace path is unsafe")
            harden_directory(self.workspace_dir)
        except OllamaRuntimeError:
            raise
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama lifecycle lease could not be prepared") from exc

        lock_path = self.workspace_dir / _LIFECYCLE_LOCK_NAME
        self._prepare_operation_lock_path(lock_path, "lifecycle")
        lease = _RuntimeFileLock(lock_path, timeout=0, mode=0o600, thread_local=False)
        while True:
            if self._current_worker_is_cancelled(deadline=deadline):
                raise _OllamaOperationCancelled("Ollama operation cancelled")
            wait_seconds = 0.25
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise OllamaRuntimeError("managed Ollama lifecycle transition timed out")
                wait_seconds = min(wait_seconds, remaining)
            try:
                lease.acquire(timeout=wait_seconds)
                break
            except FileLockTimeout:
                continue

        try:
            self._validate_operation_lock_path(lock_path, "lifecycle")
            yield
        finally:
            lease.release()

    @contextmanager
    def _exclusive_lifecycle(self, *, deadline: float | None = None) -> Iterator[None]:
        """Serialise mutations locally and across workspace-sharing processes."""
        with self._deadline_lock(
            self._lifecycle_condition,
            deadline=deadline,
            operation="lifecycle transition",
        ):
            while self._lifecycle_transition or self._lifecycle_interrupt:
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise OllamaRuntimeError("managed Ollama lifecycle transition timed out")
                    self._lifecycle_condition.wait(timeout=remaining)
                else:
                    self._lifecycle_condition.wait()
            self._lifecycle_transition = True
            try:
                while self._active_inferences:
                    if deadline is not None:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise OllamaRuntimeError("managed Ollama inference did not finish before shutdown")
                        self._lifecycle_condition.wait(timeout=remaining)
                    else:
                        self._lifecycle_condition.wait()
                if self._lifecycle_interrupt:
                    raise _OllamaOperationCancelled("Ollama operation cancelled")
            except Exception:
                self._lifecycle_transition = False
                self._lifecycle_condition.notify_all()
                raise
        try:
            with self._workspace_lifecycle_lease(deadline=deadline):
                with self._deadline_lock(
                    self._model_trust_lock,
                    deadline=deadline,
                    operation="lifecycle transition",
                ):
                    yield
        finally:
            try:
                with self._deadline_lock(
                    self._lifecycle_condition,
                    deadline=deadline,
                    operation="lifecycle transition",
                ):
                    self._lifecycle_transition = False
                    self._lifecycle_condition.notify_all()
            except OllamaRuntimeError as exc:
                cleanup = threading.Thread(
                    target=self._clear_lifecycle_transition_when_available,
                    name="flinttrade-ollama-lifecycle-cleanup",
                    daemon=True,
                )
                cleanup.start()
                raise _OllamaLifecycleCleanupTimedOut(
                    "managed Ollama lifecycle transition timed out"
                ) from exc

    def _clear_lifecycle_transition_when_available(self) -> None:
        """Release a timed-out transition only after condition ownership is recovered."""
        with self._lifecycle_condition:
            self._lifecycle_transition = False
            self._lifecycle_condition.notify_all()

    @contextmanager
    def _interrupt_lifecycle(self, *, deadline: float | None = None) -> Iterator[None]:
        """Block new inference while stop interrupts an outstanding operation."""
        with self._lifecycle_condition:
            while self._lifecycle_interrupt:
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise OllamaRuntimeError("managed Ollama stop transition timed out")
                    self._lifecycle_condition.wait(timeout=remaining)
                else:
                    self._lifecycle_condition.wait()
            self._lifecycle_interrupt = True
            try:
                while self._active_inferences:
                    if deadline is not None:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise OllamaRuntimeError("managed Ollama inference did not finish before shutdown")
                        self._lifecycle_condition.wait(timeout=remaining)
                    else:
                        self._lifecycle_condition.wait()
            except Exception:
                self._lifecycle_interrupt = False
                self._lifecycle_condition.notify_all()
                raise
        try:
            yield
        finally:
            with self._lifecycle_condition:
                self._lifecycle_interrupt = False
                self._lifecycle_condition.notify_all()

    @contextmanager
    def _stop_admission(
        self,
        *,
        grace_deadline: float,
        stop_deadline: float,
    ) -> Iterator[tuple[bool, int]]:
        """Block new admission and bound the wait for existing inference."""
        acquired = self._lifecycle_condition.acquire(
            timeout=max(0.0, stop_deadline - time.monotonic()),
        )
        if not acquired:
            raise OllamaRuntimeError("managed Ollama stop transition timed out")
        admitted = False
        try:
            while self._lifecycle_interrupt or self._lifecycle_transition:
                remaining = stop_deadline - time.monotonic()
                if remaining <= 0:
                    raise OllamaRuntimeError("managed Ollama stop transition timed out")
                self._lifecycle_condition.wait(timeout=remaining)
            self._lifecycle_interrupt = True
            admitted = True
            while self._active_inferences:
                remaining = grace_deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._lifecycle_condition.wait(timeout=remaining)
            graceful = self._active_inferences == 0
            active_inferences = self._active_inferences
            with self._workspace_lifecycle_lease(deadline=stop_deadline):
                yield graceful, active_inferences
        finally:
            if admitted:
                self._lifecycle_interrupt = False
                self._lifecycle_condition.notify_all()
            self._lifecycle_condition.release()

    def _raise_if_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise _OllamaOperationCancelled("Ollama operation cancelled")

    @contextmanager
    def _operation_control(self, *, deadline: float | None = None) -> Iterator[None]:
        if deadline is None:
            self._operation_control_lock.acquire()
            acquired = True
        else:
            acquired = self._operation_control_lock.acquire(
                timeout=max(0.0, deadline - time.monotonic()),
            )
        if not acquired:
            raise OllamaRuntimeError("managed Ollama operation admission timed out")
        try:
            yield
        finally:
            self._operation_control_lock.release()

    @contextmanager
    def _operation_state_lease(self, *, deadline: float | None = None) -> Iterator[None]:
        """Serialise durable admission receipts without waiting for lifecycle work."""
        depth = int(getattr(self._operation_state_lease_context, "depth", 0))
        if depth > 0:
            self._operation_state_lease_context.depth = depth + 1
            try:
                yield
            finally:
                self._operation_state_lease_context.depth = depth
            return
        try:
            self.workspace_dir.mkdir(parents=True, exist_ok=True)
            workspace_stat = self.workspace_dir.lstat()
            if (
                stat.S_ISLNK(workspace_stat.st_mode)
                or self._path_is_reparse(workspace_stat)
                or not stat.S_ISDIR(workspace_stat.st_mode)
            ):
                raise OllamaRuntimeError("managed Ollama workspace path is unsafe")
            harden_directory(self.workspace_dir)
        except OllamaRuntimeError:
            raise
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama operation lease could not be prepared") from exc

        lock_path = self.workspace_dir / _OPERATION_LOCK_NAME
        self._prepare_operation_lock_path(lock_path, "state")
        lease = _RuntimeFileLock(lock_path, timeout=0, mode=0o600, thread_local=False)
        while True:
            wait_seconds = 0.25
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise OllamaRuntimeError("managed Ollama operation admission timed out")
                wait_seconds = min(wait_seconds, remaining)
            try:
                lease.acquire(timeout=wait_seconds)
                break
            except FileLockTimeout:
                continue
        try:
            self._validate_operation_lock_path(lock_path, "state")
            self._operation_state_lease_context.depth = 1
            try:
                yield
            finally:
                self._operation_state_lease_context.depth = 0
        finally:
            lease.release()

    @contextmanager
    def provider_transition_guard(self, *, timeout_seconds: float = _SYNC_LIFECYCLE_WAIT_SECONDS) -> Iterator[str]:
        """Own a durable receipt across one provider configuration transition."""
        if timeout_seconds < 0:
            raise ValueError("timeout_seconds must be non-negative")
        deadline = time.monotonic() + timeout_seconds
        with self._operation_control(deadline=deadline):
            with self._operation_state_lease(deadline=deadline):
                try:
                    operation, admitted = self._begin_operation("provider_transition", None)
                except OllamaRuntimeError as exc:
                    with self._state_lock:
                        unresolved = any(
                            operation.get("state") == "indeterminate"
                            and operation.get("reconciled_at") is None
                            for operation in self._operations
                        )
                    if unresolved and "operation truth is unavailable" not in str(exc):
                        raise OllamaRuntimeError(
                            "an indeterminate managed Ollama operation requires acknowledgement"
                        ) from exc
                    raise
                if not admitted:
                    raise OllamaRuntimeError("managed Ollama provider transition admission could not be proven")
                operation_id = str(operation["id"])
                operation_context = self._enter_operation_context(operation_id)
                try:
                    try:
                        yield operation_id
                    except Exception as exc:
                        indeterminate = self._operation_mutation_started()
                        message = (
                            _INDETERMINATE_OPERATION_ERROR
                            if indeterminate
                            else (
                                str(exc).strip()[:500] or type(exc).__name__
                                if isinstance(exc, (OllamaRuntimeError, ValueError))
                                else "Managed Ollama provider transition failed"
                            )
                        )
                        self._finish_operation(
                            operation_id,
                            state="indeterminate" if indeterminate else "failed",
                            error=message,
                        )
                        raise
                    else:
                        self._finish_operation(
                            operation_id,
                            state="succeeded",
                            error=None,
                        )
                finally:
                    self._leave_operation_context(operation_context)

    def mark_provider_transition_config_mutation_started(self) -> None:
        """Mark a provider-config write as part of the admitted transition."""
        context = getattr(self._operation_context, "current", None)
        if not isinstance(context, dict):
            raise OllamaRuntimeError("managed Ollama provider transition ownership was lost")
        self._mark_operation_mutation_started()

    def mark_provider_transition_mutation_resolved(self) -> None:
        """Record that every provider-transition mutation was rolled back."""
        context = getattr(self._operation_context, "current", None)
        if not isinstance(context, dict):
            raise OllamaRuntimeError("managed Ollama provider transition ownership was lost")
        self._mark_operation_mutation_resolved()

    def _refresh_operation_status(self, *, deadline: float) -> None:
        """Publish current durable receipts before returning worker-local status."""
        with self._state_lock:
            if self._operation_truth_error:
                return
        try:
            with self._operation_state_lease(deadline=deadline):
                operations, legacy = self._read_operation_state()
                operations, interrupted = self._mark_interrupted_operations(operations)
                with self._state_lock:
                    self._operations = operations
                    self._operation = dict(operations[-1]) if operations else None
                if legacy or interrupted:
                    self._write_operation_state(operations)
        except OllamaRuntimeError as exc:
            if "admission timed out" in str(exc):
                raise
            self._mark_operation_truth_unavailable(str(exc))

    def _validate_operation_lock_path(self, lock_path: Path, purpose: str) -> None:
        lease_name = "lifecycle" if purpose == "lifecycle" else f"operation {purpose}"
        try:
            lock_stat = lock_path.lstat()
        except OSError as exc:
            raise OllamaRuntimeError(f"managed Ollama {lease_name} lease path could not be inspected") from exc
        if (
            stat.S_ISLNK(lock_stat.st_mode)
            or self._path_is_reparse(lock_stat)
            or not stat.S_ISREG(lock_stat.st_mode)
            or lock_stat.st_nlink != 1
        ):
            raise OllamaRuntimeError(f"managed Ollama {lease_name} lease path is unsafe")
        getuid = getattr(os, "getuid", None)
        if callable(getuid) and lock_stat.st_uid != getuid():
            raise OllamaRuntimeError(f"managed Ollama {lease_name} lease path is unsafe")
        harden(lock_path)

    def _prepare_operation_lock_path(self, lock_path: Path, purpose: str) -> None:
        lease_name = "lifecycle" if purpose == "lifecycle" else f"operation {purpose}"
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        created = False
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except FileExistsError:
            pass
        except OSError as exc:
            raise OllamaRuntimeError(
                f"managed Ollama {lease_name} lease path could not be prepared"
            ) from exc
        else:
            created = True
            try:
                os.close(descriptor)
                fsync_parent_directory(lock_path)
            except OSError as exc:
                try:
                    durable_unlink(lock_path)
                except OSError:
                    pass
                raise OllamaRuntimeError(
                    f"managed Ollama {lease_name} lease path could not be prepared"
                ) from exc
        try:
            self._validate_operation_lock_path(lock_path, purpose)
        except Exception:
            if created:
                try:
                    durable_unlink(lock_path)
                except OSError:
                    pass
            raise

    def _acquire_operation_owner_lease(self, *, deadline: float) -> BaseFileLock:
        lock_path = self.workspace_dir / _OPERATION_OWNER_LOCK_NAME
        self._prepare_operation_lock_path(lock_path, "owner")
        lease = _RuntimeFileLock(lock_path, timeout=0, mode=0o600, thread_local=False)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OllamaRuntimeError("managed Ollama operation owner admission timed out")
            try:
                lease.acquire(timeout=min(0.25, remaining))
                break
            except FileLockTimeout:
                continue
        try:
            self._validate_operation_lock_path(lock_path, "owner")
        except Exception:
            lease.release()
            raise
        return lease

    def _release_operation_owner_lease(self) -> None:
        lease = self._operation_owner_lease
        self._operation_owner_lease = None
        if lease is not None:
            lease.release()

    @staticmethod
    def _validated_admission_id(admission_id: str | None) -> str:
        selected = admission_id or f"adm_{secrets.token_hex(16)}"
        if _ADMISSION_ID.fullmatch(selected) is None:
            raise ValueError("admission_id is invalid")
        return selected

    def _enter_operation_context(self, operation_id: str) -> dict[str, Any]:
        context = {"operation_id": operation_id, "mutation_started": False}
        self._operation_context.current = context
        return context

    def _leave_operation_context(self, context: dict[str, Any]) -> None:
        if getattr(self._operation_context, "current", None) is context:
            del self._operation_context.current

    def _mark_operation_mutation_started(self) -> None:
        context = getattr(self._operation_context, "current", None)
        if isinstance(context, dict):
            context["mutation_started"] = True

    def _mark_operation_mutation_resolved(self) -> None:
        """Record that a failed mutation was conclusively rolled back."""
        context = getattr(self._operation_context, "current", None)
        if isinstance(context, dict):
            context["mutation_started"] = False

    def _operation_mutation_started(self) -> bool:
        context = getattr(self._operation_context, "current", None)
        return isinstance(context, dict) and context.get("mutation_started") is True

    def _begin_operation(
        self,
        kind: str,
        admission_id: str | None,
        *,
        operation_subject: dict[str, str] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        if kind not in _OPERATION_KINDS:
            raise ValueError("managed Ollama operation kind is invalid")
        subject = self._normalise_operation_subject(kind, operation_subject)
        if kind in _OPERATION_SUBJECT_KINDS and subject is None:
            raise ValueError("managed Ollama operation target is required")
        selected_admission_id = self._validated_admission_id(admission_id)
        deadline = time.monotonic() + _SYNC_LIFECYCLE_WAIT_SECONDS
        with self._operation_state_lease(deadline=deadline):
            operations, legacy = self._read_operation_state()
            operations, interrupted = self._mark_interrupted_operations(operations)
            if legacy or interrupted:
                self._write_operation_state(operations)
            with self._state_lock:
                self._operations = operations
                self._operation = dict(operations[-1]) if operations else None
            existing = next(
                (
                    operation
                    for operation in operations
                    if operation.get("admission_id") == selected_admission_id
                ),
                None,
            )
            if existing is not None:
                if existing.get("kind") != kind:
                    raise OllamaRuntimeError("admission ID is already bound to another Ollama operation")
                if existing.get("subject") != subject:
                    raise OllamaRuntimeError("admission ID is already bound to another Ollama operation target")
                return dict(existing), False
            indeterminate = next(
                (
                    operation
                    for operation in operations
                    if operation.get("state") == "indeterminate"
                    and operation.get("reconciled_at") is None
                ),
                None,
            )
            if indeterminate is not None:
                raise OllamaRuntimeError(str(indeterminate.get("error") or _INDETERMINATE_OPERATION_ERROR))
            if self._spent_admission_might_exist(selected_admission_id):
                raise OllamaRuntimeError(
                    "admission ID was already consumed and its detailed Ollama receipt has expired"
                )
            running = next((operation for operation in operations if operation.get("state") == "running"), None)
            with self._state_lock:
                local_worker_running = self._worker is not None and self._worker.is_alive()
            if local_worker_running or running is not None:
                raise OllamaRuntimeError("another Ollama operation is already running")
            owner_lease = self._acquire_operation_owner_lease(deadline=deadline)
            operation = {
                "id": f"op_{secrets.token_hex(16)}",
                "admission_id": selected_admission_id,
                "kind": kind,
                "state": "running",
                "started_at": time.time(),
                "finished_at": None,
                "reconciled_at": None,
                "subject": subject,
                "error": None,
                "result": None,
                "owner_pid": os.getpid(),
                "owner_create_time": self._process_create_time(os.getpid(), strict=True),
                "owner_token": secrets.token_hex(16),
            }
            updated_operations = [*operations, operation]
            previous_filter = self._spent_admission_filter
            previous_count = self._spent_admission_count
            try:
                updated_operations, spent_filter, spent_count = self._fit_operation_receipts(
                    updated_operations,
                    protected_operation_ids={str(operation["id"])},
                )
                self._spent_admission_filter = spent_filter
                self._spent_admission_count = spent_count
                self._write_operation_state(updated_operations)
            except Exception:
                self._spent_admission_filter = previous_filter
                self._spent_admission_count = previous_count
                owner_lease.release()
                raise
            self._operation_owner_lease = owner_lease
            with self._state_lock:
                self._operations = updated_operations
                self._operation = dict(operation)
                self._cancel_event.clear()
            return dict(operation), True

    def reconcile_indeterminate_operation(
        self,
        operation_id: str,
        admission_id: str,
    ) -> dict[str, Any]:
        """Acknowledge one exact unknown outcome without replaying the mutation."""
        if _OPERATION_ID.fullmatch(operation_id) is None:
            raise ValueError("operation_id is invalid")
        if _ADMISSION_ID.fullmatch(admission_id) is None:
            raise ValueError("admission_id is invalid")
        deadline = time.monotonic() + _SYNC_LIFECYCLE_WAIT_SECONDS
        with self._operation_control(deadline=deadline):
            with self._operation_state_lease(deadline=deadline):
                operations, legacy = self._read_operation_state()
                operations, interrupted = self._mark_interrupted_operations(operations)
                operation_index = next(
                    (
                        index
                        for index, operation in enumerate(operations)
                        if operation.get("id") == operation_id
                        and operation.get("admission_id") == admission_id
                    ),
                    None,
                )
                if operation_index is None or operations[operation_index].get("state") != "indeterminate":
                    raise OllamaRuntimeError(
                        "operation and admission IDs do not identify an indeterminate Ollama receipt"
                    )
                operation = operations[operation_index]
                if operation.get("reconciled_at") is None:
                    reconciled = dict(operation)
                    reconciled["reconciled_at"] = max(
                        time.time(),
                        float(operation["finished_at"]),
                    )
                    operations[operation_index] = reconciled
                    self._write_operation_state(operations)
                elif legacy or interrupted:
                    self._write_operation_state(operations)
                with self._state_lock:
                    self._operations = operations
                    self._operation = dict(operations[-1])
        return self.status()

    def _finish_operation(
        self,
        operation_id: str,
        *,
        state: str,
        error: str | None,
        result: Any = None,
    ) -> None:
        deadline = time.monotonic() + _SYNC_LIFECYCLE_WAIT_SECONDS
        try:
            with self._operation_state_lease(deadline=deadline):
                operations, legacy = self._read_operation_state()
                if legacy:
                    self._write_operation_state(operations)
                operation_index = next(
                    (
                        index
                        for index, operation in enumerate(operations)
                        if operation.get("id") == operation_id
                    ),
                    None,
                )
                if operation_index is None:
                    raise OllamaRuntimeError("managed Ollama operation ownership was lost")
                operation = operations[operation_index]
                if operation.get("state") != "running":
                    raise OllamaRuntimeError("managed Ollama operation ownership was lost")
                normalised_result = self._normalise_operation_result(
                    str(operation["kind"]),
                    result,
                    operation.get("subject"),
                )
                invalid_result = (
                    state == "succeeded"
                    and operation["kind"] in _OPERATION_RESULT_KINDS
                    and normalised_result is None
                )
                terminal = dict(operation)
                terminal.update(
                    {
                        "state": "indeterminate" if invalid_result else state,
                        "finished_at": max(time.time(), float(operation["started_at"])),
                        "error": "Managed Ollama operation returned an invalid result" if invalid_result else error,
                        "result": None if invalid_result else normalised_result,
                    }
                )
                updated_operations = list(operations)
                updated_operations[operation_index] = terminal
                previous_filter = self._spent_admission_filter
                previous_count = self._spent_admission_count
                try:
                    updated_operations, spent_filter, spent_count = self._fit_operation_receipts(
                        updated_operations,
                        protected_operation_ids={operation_id},
                    )
                    self._spent_admission_filter = spent_filter
                    self._spent_admission_count = spent_count
                    self._write_operation_state(updated_operations)
                except Exception:
                    self._spent_admission_filter = previous_filter
                    self._spent_admission_count = previous_count
                    indeterminate = dict(operation)
                    indeterminate.update(
                        {
                            "state": "indeterminate",
                            "finished_at": max(time.time(), float(operation["started_at"])),
                            "error": _INDETERMINATE_OPERATION_ERROR,
                            "result": None,
                        }
                    )
                    updated_operations[operation_index] = indeterminate
                    with self._state_lock:
                        self._operations = updated_operations
                        self._operation = dict(updated_operations[-1])
                    raise
                with self._state_lock:
                    self._operations = updated_operations
                    self._operation = dict(updated_operations[-1])
                if invalid_result:
                    raise OllamaRuntimeError("managed Ollama operation returned an invalid result")
        finally:
            self._release_operation_owner_lease()

    def _finish_background_operation(
        self,
        operation_id: str,
        *,
        state: str,
        error: str | None,
        result: Any = None,
    ) -> bool:
        try:
            self._finish_operation(
                operation_id,
                state=state,
                error=error,
                result=result,
            )
        except OllamaRuntimeError:
            receipt_error = "Managed Ollama operation receipt could not be committed"
            with self._state_lock:
                self._error = receipt_error
                if self._phase not in {"ready", "installed"}:
                    self._phase = "failed"
            return False
        return True

    def _replay_operation(self, operation: dict[str, Any]) -> tuple[dict[str, Any], int]:
        state = operation.get("state")
        if state == "running":
            return self._status_for_operation(operation), 202
        if state == "succeeded":
            result = operation.get("result")
            return (dict(result) if isinstance(result, dict) else self._status_for_operation(operation)), 200
        message = str(operation.get("error") or "managed Ollama operation did not complete")
        raise OllamaRuntimeError(message)

    def _status_for_operation(self, operation: dict[str, Any]) -> dict[str, Any]:
        status = self.status()
        status["operation"] = self._public_operation(operation)
        return status

    def _start_background(
        self,
        kind: str,
        callback: Callable[[], Any],
        *,
        admission_id: str | None = None,
        operation_subject: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + _SYNC_LIFECYCLE_WAIT_SECONDS
        with self._operation_control(deadline=deadline):
            operation, admitted = self._begin_operation(
                kind,
                admission_id,
                operation_subject=operation_subject,
            )
            if not admitted:
                return self._status_for_operation(operation)
            worker = threading.Thread(
                target=self._run_background,
                args=(callback, str(operation["id"])),
                name=f"flinttrade-ollama-{kind}",
                daemon=True,
            )
            with self._state_lock:
                self._worker = worker
            try:
                worker.start()
            except Exception as exc:
                with self._state_lock:
                    if self._worker is worker:
                        self._worker = None
                self._finish_operation(
                    str(operation["id"]),
                    state="failed",
                    error="Managed Ollama operation could not start",
                )
                raise OllamaRuntimeError("managed Ollama operation could not start") from exc
        return self.status()

    def run_synchronous_operation(
        self,
        kind: str,
        admission_id: str,
        callback: Callable[[], dict[str, Any]],
        *,
        operation_subject: dict[str, str] | None = None,
    ) -> tuple[dict[str, Any], int]:
        """Execute one idempotent request-thread mutation with a durable receipt."""
        deadline = time.monotonic() + _SYNC_LIFECYCLE_WAIT_SECONDS
        current_thread = threading.current_thread()
        with self._operation_control(deadline=deadline):
            operation, admitted = self._begin_operation(
                kind,
                admission_id,
                operation_subject=operation_subject,
            )
            if not admitted:
                return self._replay_operation(operation)
            with self._state_lock:
                self._worker = current_thread
        operation_context = self._enter_operation_context(str(operation["id"]))
        try:
            result = callback()
        except Exception as exc:
            cancelled = isinstance(exc, _OllamaOperationCancelled)
            indeterminate = isinstance(exc, _OllamaLifecycleCleanupTimedOut) or self._operation_mutation_started()
            message = (
                _INDETERMINATE_OPERATION_ERROR
                if indeterminate
                else (
                    str(exc).strip()[:500] or type(exc).__name__
                    if isinstance(exc, (OllamaRuntimeError, ValueError))
                    else "Managed Ollama operation failed"
                )
            )
            self._finish_operation(
                str(operation["id"]),
                state="indeterminate" if indeterminate else "cancelled" if cancelled else "failed",
                error=message if indeterminate or not cancelled else None,
            )
            raise
        else:
            self._finish_operation(
                str(operation["id"]),
                state="succeeded",
                error=None,
                result=result,
            )
            published_result = self._normalise_operation_result(kind, result, operation.get("subject"))
            return (published_result if published_result is not None else self.status()), 200
        finally:
            self._leave_operation_context(operation_context)
            with self._state_lock:
                if self._worker is current_thread:
                    self._worker = None

    def _run_background(self, callback: Callable[[], Any], operation_id: str) -> None:
        operation_context = self._enter_operation_context(operation_id)
        try:
            try:
                result = callback()
            except Exception as exc:  # noqa: BLE001 - surfaced through the status endpoint
                cancelled = isinstance(exc, _OllamaOperationCancelled)
                indeterminate = self._operation_mutation_started()
                message = (
                    _INDETERMINATE_OPERATION_ERROR
                    if indeterminate
                    else (
                        str(exc).strip()[:500] or type(exc).__name__
                        if isinstance(exc, (OllamaRuntimeError, ValueError))
                        else "Managed Ollama operation failed"
                    )
                )
                if not self._finish_background_operation(
                    operation_id,
                    state="indeterminate" if indeterminate else "cancelled" if cancelled else "failed",
                    error=message if indeterminate or not cancelled else None,
                ):
                    return
                with self._state_lock:
                    self._error = "" if cancelled and not indeterminate else message
                    if cancelled and not indeterminate:
                        installed, _integrity_error = self._installation_status()
                        self._phase = "installed" if installed else "stopped"
                    elif self._phase not in {"ready", "installed"}:
                        self._phase = "failed"
            else:
                if not self._finish_background_operation(
                    operation_id,
                    state="succeeded",
                    error=None,
                    result=result,
                ):
                    return
                with self._state_lock:
                    self._error = ""
        finally:
            self._leave_operation_context(operation_context)

    def install_async(self, *, admission_id: str | None = None) -> dict[str, Any]:
        """Start a verified runtime install without blocking the caller."""
        return self._start_background("install", self.install, admission_id=admission_id)

    def update_async(self, *, admission_id: str | None = None) -> dict[str, Any]:
        """Stage and activate the preferred release without blocking the caller."""
        return self._start_background("update", self.update, admission_id=admission_id)

    def repair_async(self, *, admission_id: str | None = None) -> dict[str, Any]:
        """Replace one corrupt managed runtime without blocking the caller."""
        return self._start_background("repair", self.repair, admission_id=admission_id)

    def start_async(
        self,
        *,
        timeout_seconds: float = 30.0,
        admission_id: str | None = None,
    ) -> dict[str, Any]:
        """Start the managed server without blocking the caller."""
        return self._start_background(
            "start",
            lambda: self.start(timeout_seconds=timeout_seconds),
            admission_id=admission_id,
        )

    def pull_model_async(self, model: str, *, admission_id: str | None = None) -> dict[str, Any]:
        """Start one model pull without blocking the caller."""
        _validate_pull_model_identifier(model)
        return self._start_background(
            "pull_model",
            lambda: self.pull_model(model),
            admission_id=admission_id,
            operation_subject={"model": model},
        )

    def wait_for_operation(self, *, timeout: float) -> bool:
        """Wait for the current background operation within a bounded timeout."""
        if timeout < 0:
            raise ValueError("timeout must be non-negative")
        deadline = time.monotonic() + timeout
        try:
            with self._bounded_state_lock(deadline=deadline, operation="operation wait"):
                worker = self._worker
        except OllamaRuntimeError:
            return False
        if worker is None:
            return True
        if worker is threading.current_thread():
            return False
        worker.join(timeout=max(0.0, deadline - time.monotonic()))
        return not worker.is_alive()

    def install(self) -> dict[str, Any]:
        with self._exclusive_lifecycle():
            return self._install_locked()

    def _install_locked(
        self,
        *,
        version: str | None = None,
        activate: bool = True,
    ) -> dict[str, Any]:
        self._prepare_direct_operation()
        selected_version = version or self._active_version
        selected_assets = self._release_assets.get(selected_version)
        if selected_assets is None:
            raise OllamaRuntimeError("managed Ollama release is not trusted by this build")
        selected_asset = selected_assets[0]
        runtime_root = self.runtime_root
        install_dir = runtime_root / selected_version
        self._ensure_managed_directory(runtime_root, create=True)
        self._scavenge_stale_residue()
        if install_dir.exists() or install_dir.is_symlink():
            try:
                self._verified_executable(rehash=True, version=selected_version)
            except OllamaRuntimeError as exc:
                self._phase = "failed"
                self._error = "managed Ollama runtime destination already exists but is incomplete"
                raise OllamaRuntimeError(self._error) from exc
            live_status = self._status_snapshot(probe_server=True)
            if live_status["managed_process"] or live_status["external_process"]:
                return live_status
            self._phase = "installed"
            self._error = ""
            if activate:
                self._mark_operation_mutation_started()
                self._write_runtime_state(selected_version, self._previous_version)
            return self._status_snapshot(probe_server=True)
        required_bytes = _install_assets_required_bytes(selected_assets)
        if self._managed_storage_bytes(enforce_limit=False) + required_bytes > _MAX_MANAGED_STORAGE_BYTES:
            self._phase = "failed"
            self._error = "managed Ollama installation exceeds the managed storage size limit"
            raise OllamaRuntimeError(self._error)
        if self._disk_usage(runtime_root).free < required_bytes:
            self._phase = "failed"
            self._error = "insufficient free disk space for the managed Ollama runtime"
            raise OllamaRuntimeError(self._error)
        staging_root = runtime_root / ".staging"
        self._ensure_managed_directory(staging_root, create=True)
        work_dir = Path(tempfile.mkdtemp(prefix="install-", dir=staging_root))
        self._write_residue_marker(work_dir, kind="install")
        extracted = work_dir / "extracted"
        self._phase = "downloading"
        self._error = ""

        try:
            self._raise_if_cancelled()
            archive_paths: list[tuple[OllamaAsset, Path]] = []
            completed_assets = 0
            total_download_bytes = sum(max(0, int(asset.size_bytes)) for asset in selected_assets)
            self._download_total_bytes = total_download_bytes
            for download_asset in selected_assets:
                archive_path = work_dir / download_asset.name

                def progress(completed: int, total: int, *, offset: int = completed_assets) -> None:
                    self._raise_if_cancelled()
                    self._downloaded_bytes = offset + max(0, int(completed))
                    if total_download_bytes <= 0:
                        self._download_total_bytes = offset + max(0, int(total))
                    self._managed_storage_bytes()

                self._download(download_asset, archive_path, progress)
                self._raise_if_cancelled()
                if _sha256_file(archive_path, check_cancelled=self._raise_if_cancelled) != download_asset.sha256:
                    raise OllamaRuntimeError("Ollama runtime hash verification failed")
                archive_paths.append((download_asset, archive_path))
                completed_assets += max(0, int(download_asset.size_bytes))
                self._downloaded_bytes = completed_assets

            self._phase = "extracting"
            for index, (extraction_asset, archive_path) in enumerate(archive_paths):
                if self._disk_usage(runtime_root).free < _extraction_required_bytes(extraction_asset):
                    raise OllamaRuntimeError("insufficient free disk space for managed Ollama extraction")
                destination = extracted if index == 0 else work_dir / f"overlay-{index}"
                accounted_managed_bytes = self._managed_storage_bytes(enforce_limit=False)

                def ensure_extraction_capacity(next_bytes: int) -> None:
                    nonlocal accounted_managed_bytes
                    accounted_managed_bytes = self._ensure_extraction_capacity(
                        next_bytes,
                        managed_bytes=accounted_managed_bytes,
                    )

                _extract_archive(
                    archive_path,
                    destination,
                    max_extracted_bytes=extraction_asset.max_extracted_bytes,
                    ensure_capacity=ensure_extraction_capacity,
                    check_cancelled=self._raise_if_cancelled,
                )
                if index:
                    _merge_extracted_overlay(destination, extracted)
                self._managed_storage_bytes()
                self._raise_if_cancelled()
            self._raise_if_cancelled()
            executable = next(
                (
                    extracted.joinpath(*PurePosixPath(candidate).parts)
                    for candidate in selected_asset.executable_candidates
                    if extracted.joinpath(*PurePosixPath(candidate).parts).is_file()
                ),
                None,
            )
            if executable is None:
                raise OllamaRuntimeError("verified Ollama archive did not contain the server executable")
            if executable.is_symlink():
                raise OllamaRuntimeError("verified Ollama archive contained a linked server executable")
            if os.name != "nt":
                executable.chmod(executable.stat().st_mode | 0o700)
            executable_relative = executable.relative_to(extracted).as_posix()
            runtime_files: list[dict[str, Any]] = []
            for path in sorted(extracted.rglob("*"), key=lambda candidate: candidate.as_posix()):
                self._raise_if_cancelled()
                path_stat = path.lstat()
                if stat.S_ISDIR(path_stat.st_mode):
                    continue
                if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
                    raise OllamaRuntimeError("verified Ollama archive contained an unsafe runtime file")
                runtime_files.append(
                    {
                        "path": path.relative_to(extracted).as_posix(),
                        "sha256": _sha256_file(path, check_cancelled=self._raise_if_cancelled),
                        "size_bytes": path_stat.st_size,
                    }
                )
            self._raise_if_cancelled()
            manifest_bytes = _json_bytes(
                {
                    "schema": 2,
                    "executable": executable_relative,
                    "files": runtime_files,
                }
            )
            if len(manifest_bytes) > _MAX_INSTALL_MANIFEST_BYTES:
                raise OllamaRuntimeError("verified Ollama archive manifest exceeds the size limit")
            marker_bytes = _json_bytes(
                {
                    "schema": 3,
                    "version": selected_version,
                    "assets": [{"name": asset.name, "sha256": asset.sha256} for asset in selected_assets],
                    "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                }
            )
            if len(marker_bytes) > _MAX_INSTALL_MARKER_BYTES:
                raise OllamaRuntimeError("verified Ollama install marker exceeds the size limit")
            self._raise_if_cancelled()
            _write_private_file(extracted / _INSTALL_MANIFEST_NAME, manifest_bytes)
            _write_private_file(extracted / _INSTALL_MARKER_NAME, marker_bytes)
            self._raise_if_cancelled()
            if install_dir.exists():
                raise OllamaRuntimeError("managed Ollama runtime destination already exists but is incomplete")
            with self._state_lock:
                self._raise_if_cancelled()
                self._mark_operation_mutation_started()
                durable_replace(extracted, install_dir)
                if activate:
                    self._mark_operation_mutation_started()
                    self._write_runtime_state(selected_version, self._previous_version)
            self._phase = "installed"
            return self._status_snapshot()
        except Exception as exc:
            cancelled = isinstance(exc, _OllamaOperationCancelled)
            self._phase = "stopped" if cancelled else "failed"
            self._error = "" if cancelled else (
                str(exc) if isinstance(exc, OllamaRuntimeError) else "managed Ollama installation failed"
            )
            if isinstance(exc, OllamaRuntimeError):
                raise
            raise OllamaRuntimeError("managed Ollama installation failed") from exc
        finally:
            _remove_path_without_following_root(work_dir)

    def _require_stopped_runtime_mutation(self, operation: str) -> None:
        with self._process_lock:
            owned_process = self._process
        if owned_process is not None and owned_process.poll() is None:
            raise OllamaRuntimeError(f"managed Ollama must be stopped before {operation}")
        if owned_process is not None:
            self._stop_owned_process(cancel_operation=False, probe_status=False)
        else:
            self._recover_stale_owned_process(allow_current_backend=True)
        if self._probe() is not None:
            raise OllamaRuntimeError(f"an Ollama listener is still present; stop it before {operation}")

    def update(self) -> dict[str, Any]:
        """Stage the preferred release, then atomically retain the active release for rollback."""
        with self._exclusive_lifecycle():
            self._prepare_direct_operation()
            if self._runtime_state_error:
                raise OllamaRuntimeError(self._runtime_state_error)
            if self._active_version == self.target_version:
                raise OllamaRuntimeError("managed Ollama runtime is already on the preferred release")
            self._require_stopped_runtime_mutation("runtime update")
            self._ensure_runtime_state_committed()
            previous = self._active_version
            self._install_locked(version=self.target_version, activate=False)
            self._raise_if_cancelled()
            self._verified_executable(rehash=True, version=self.target_version)
            with self._state_lock:
                self._raise_if_cancelled()
                self._mark_operation_mutation_started()
                self._write_runtime_state(self.target_version, previous)
            self._phase = "installed"
            self._error = ""
            return self._status_snapshot()

    def rollback(self) -> dict[str, Any]:
        """Switch to the one retained, fully rehashed release."""
        deadline = time.monotonic() + _SYNC_LIFECYCLE_WAIT_SECONDS
        with self._exclusive_lifecycle(deadline=deadline):
            self._prepare_direct_operation()
            if self._runtime_state_error:
                raise OllamaRuntimeError(self._runtime_state_error)
            previous = self._previous_version
            if previous is None:
                raise OllamaRuntimeError("no managed Ollama rollback release is available")
            self._require_stopped_runtime_mutation("runtime rollback")
            self._verified_executable(rehash=True, version=previous)
            current = self._active_version
            with self._state_lock:
                self._raise_if_cancelled()
                self._mark_operation_mutation_started()
                self._write_runtime_state(previous, current)
            self._phase = "installed"
            self._error = ""
            return self._status_snapshot()

    def _uninstall_release_entries(self) -> list[dict[str, str]]:
        try:
            root = self._ensure_managed_directory(self.runtime_root, create=False)
        except FileNotFoundError:
            return []
        entries: list[dict[str, str]] = []
        try:
            for path in self._bounded_children(root):
                if path.name.startswith(".uninstall-"):
                    raise OllamaRuntimeError("managed Ollama uninstall state is invalid")
                if re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", path.name) is None:
                    continue
                if path.name not in self._release_assets:
                    raise OllamaRuntimeError(
                        f"managed Ollama release {path.name} is not recognised by this build"
                    )
                path_stat = path.lstat()
                is_directory = (
                    stat.S_ISDIR(path_stat.st_mode)
                    and not stat.S_ISLNK(path_stat.st_mode)
                    and not self._path_is_reparse(path_stat)
                )
                if is_directory:
                    self._verified_executable(rehash=True, version=path.name)
                entries.append(
                    {
                        "version": path.name,
                        "quarantine": "",
                        "kind": "directory" if is_directory else "path",
                    }
                )
        except OllamaRuntimeError:
            raise
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama releases could not be inspected for uninstall") from exc
        return sorted(entries, key=lambda entry: entry["version"])

    def uninstall(self) -> dict[str, Any]:
        """Transactionally remove managed binaries while preserving models and trust metadata."""
        deadline = time.monotonic() + _SYNC_LIFECYCLE_WAIT_SECONDS
        with self._exclusive_lifecycle(deadline=deadline):
            self._prepare_direct_operation()
            self._require_stopped_runtime_mutation("runtime uninstall")
            if self._read_uninstall_state() is not None:
                self._mark_operation_mutation_started()
                self._recover_uninstall_transaction()
            self._owned_residue_for_uninstall(remove=False)
            releases = self._uninstall_release_entries()
            token = secrets.token_hex(16)
            for release in releases:
                release["quarantine"] = f".uninstall-{token}-{release['version']}"
            with self._state_lock:
                self._raise_if_cancelled()
                self._mark_operation_mutation_started()
                state = self._write_uninstall_state(
                    phase="prepared",
                    token=token,
                    releases=releases,
                )
                try:
                    for release in releases:
                        original = self.runtime_root / release["version"]
                        quarantine = self.runtime_root / release["quarantine"]
                        if quarantine.exists() or quarantine.is_symlink():
                            raise OllamaRuntimeError("managed Ollama uninstall quarantine already exists")
                        self._mark_operation_mutation_started()
                        durable_replace(original, quarantine)
                    state = self._write_uninstall_state(
                        phase="committed",
                        token=token,
                        releases=releases,
                    )
                except Exception as exc:
                    try:
                        observed = self._read_uninstall_state()
                        if observed is None:
                            raise OllamaRuntimeError("managed Ollama uninstall rollback state was lost")
                        if observed["phase"] == "committed":
                            self._finish_committed_uninstall(observed)
                        else:
                            self._rollback_prepared_uninstall(observed)
                            self._mark_operation_mutation_resolved()
                            raise OllamaRuntimeError("managed Ollama uninstall was rolled back") from exc
                    except OllamaRuntimeError as recovery_exc:
                        if str(recovery_exc) == "managed Ollama uninstall was rolled back":
                            raise
                        raise OllamaRuntimeError(
                            "managed Ollama uninstall failed and recovery could not be proven"
                        ) from recovery_exc
            self._finish_committed_uninstall(state)
            self._select_active_release(self.target_version)
            self._previous_version = None
            self._runtime_state_error = ""
            self._phase = "stopped"
            self._error = ""
            return self._status_snapshot()

    def repair(self) -> dict[str, Any]:
        """Quarantine and transactionally replace one corrupt managed install."""
        if self._operation_truth_error:
            raise OllamaRuntimeError(
                "durable operation receipt truth is unavailable; runtime-file repair is blocked"
            )
        operation_context = getattr(self._operation_context, "current", None)
        if not isinstance(operation_context, dict):
            result, _status_code = self.run_synchronous_operation(
                "repair",
                self._validated_admission_id(None),
                self.repair,
            )
            return result

        lifecycle_deadline = time.monotonic() + _SYNC_LIFECYCLE_WAIT_SECONDS
        with self._exclusive_lifecycle(deadline=lifecycle_deadline):
            operation_deadline = time.monotonic() + _SYNC_LIFECYCLE_WAIT_SECONDS
            with self._operation_state_lease(deadline=operation_deadline):
                operations, legacy = self._read_operation_state(required=True)
                if legacy:
                    self._write_operation_state(operations)
                operation_id = operation_context.get("operation_id")
                admitted = next(
                    (
                        operation
                        for operation in operations
                        if operation.get("id") == operation_id
                        and operation.get("kind") == "repair"
                        and operation.get("state") == "running"
                    ),
                    None,
                )
                unresolved = next(
                    (
                        operation
                        for operation in operations
                        if operation.get("state") == "indeterminate"
                        and operation.get("reconciled_at") is None
                    ),
                    None,
                )
                with self._state_lock:
                    self._operations = operations
                    self._operation = dict(operations[-1]) if operations else None
                if unresolved is not None:
                    raise OllamaRuntimeError(
                        "an indeterminate managed Ollama operation requires acknowledgement"
                    )
                if admitted is None:
                    raise OllamaRuntimeError("managed Ollama repair operation ownership was lost")
            return self._repair_locked()

    def _repair_locked(self) -> dict[str, Any]:
        if self._operation_truth_error:
            raise OllamaRuntimeError(
                "durable operation receipt truth is unavailable; runtime-file repair is blocked"
            )
        self._prepare_direct_operation()
        runtime_root = self.install_dir.parent
        try:
            self._ensure_managed_directory(runtime_root, create=False)
        except FileNotFoundError as exc:
            raise OllamaRuntimeError("managed Ollama runtime is not installed; use install instead") from exc
        with self._process_lock:
            owned_process = self._process
        if owned_process is not None and owned_process.poll() is None:
            raise OllamaRuntimeError("managed Ollama must be stopped before runtime repair")
        if owned_process is not None:
            self._stop_owned_process(cancel_operation=False, probe_status=False)
        else:
            self._recover_stale_owned_process(allow_current_backend=True)
        if self._probe() is not None:
            raise OllamaRuntimeError("an Ollama listener is still present; stop it before runtime repair")
        self._scavenge_stale_residue()
        if not self.install_dir.exists() and not self.install_dir.is_symlink():
            raise OllamaRuntimeError("managed Ollama runtime is not installed; use install instead")
        try:
            self._verified_executable(rehash=True)
        except OllamaRuntimeError:
            pass
        else:
            if self._runtime_state_error:
                self._repair_runtime_state(active_verified=True)
                self._phase = "installed"
                self._error = ""
                return self._status_snapshot()
            raise OllamaRuntimeError("managed Ollama runtime integrity is already valid")

        token = secrets.token_hex(16)
        quarantine = runtime_root / f".repair-{token}"
        if quarantine.exists() or quarantine.is_symlink():
            raise OllamaRuntimeError("could not reserve managed Ollama repair quarantine")
        self._write_repair_state(
            phase="prepared",
            version=self._active_version,
            token=token,
        )
        self._mark_operation_mutation_started()
        try:
            durable_replace(self.install_dir, quarantine)
        except OSError as exc:
            try:
                self._recover_repair_transaction()
            except OllamaRuntimeError as recovery_exc:
                raise OllamaRuntimeError(
                    "could not quarantine the corrupt managed Ollama runtime and rollback could not be proven"
                ) from recovery_exc
            self._mark_operation_mutation_resolved()
            raise OllamaRuntimeError("could not quarantine the corrupt managed Ollama runtime") from exc

        try:
            result = self._install_locked()
            self._verified_executable(rehash=True)
            self._write_repair_state(
                phase="committed",
                version=self._active_version,
                token=token,
            )
        except Exception as exc:
            try:
                observed = self._read_repair_state()
                if observed is None:
                    raise OllamaRuntimeError("managed Ollama repair transaction state was lost")
                committed = observed["phase"] == "committed"
                self._recover_repair_transaction()
            except OllamaRuntimeError as restore_exc:
                self._phase = "failed"
                self._error = "managed Ollama repair failed and the original install could not be restored"
                raise OllamaRuntimeError(self._error) from restore_exc
            if committed:
                self._phase = "installed"
                self._error = ""
                return result
            self._mark_operation_mutation_resolved()
            self._phase = "failed"
            self._error = "managed Ollama repair failed; the original install was restored"
            raise OllamaRuntimeError(self._error) from exc

        self._recover_repair_transaction()
        self._phase = "installed"
        self._error = ""
        return result

    def status(self) -> dict[str, Any]:
        deadline = time.monotonic() + _SYNC_LIFECYCLE_WAIT_SECONDS
        self._refresh_operation_status(deadline=deadline)
        return self._status_snapshot(probe_server=True, verification_deadline=deadline)

    def _managed_server_version(self) -> str | None:
        with self._process_lock:
            process = self._process
            if process is None or process.poll() is not None:
                return None
            if not self._listener_is_owned(process):
                return None
            server_version = self._probe()
            if server_version != self.server_version or not self._listener_is_owned(process):
                return None
            return server_version

    def _require_managed_ready(self) -> str:
        server_version = self._managed_server_version()
        if not server_version:
            raise OllamaRuntimeError("managed Ollama server is not ready")
        return server_version

    def start(self, *, timeout_seconds: float = 30.0) -> dict[str, Any]:
        with self._exclusive_lifecycle():
            return self._start_locked(timeout_seconds=timeout_seconds)

    def _start_locked(self, *, timeout_seconds: float) -> dict[str, Any]:
        self._prepare_direct_operation()
        if timeout_seconds < 0:
            raise ValueError("timeout_seconds must be non-negative")
        if self._runtime_state_error:
            self._phase = "failed"
            self._error = self._runtime_state_error
            raise OllamaRuntimeError(self._runtime_state_error)
        with self._process_lock:
            owned_process = self._process
        if owned_process is not None and owned_process.poll() is None:
            server_version = self._probe()
            if server_version is not None:
                if server_version != self.server_version:
                    raise OllamaRuntimeError("managed Ollama server version does not match the pinned runtime")
                if not self._listener_is_owned(owned_process):
                    raise OllamaRuntimeError("could not prove managed Ollama listener ownership")
                _publish_managed_ollama_owner(self)
                return self._status_snapshot(probe_server=True)
            self._phase = "starting"
            self._error = "managed Ollama owned process is already running but is not ready"
            raise OllamaRuntimeError(self._error)
        if owned_process is not None:
            self._stop_owned_process(cancel_operation=False)
        self._recover_stale_owned_process()
        self._scavenge_stale_residue()
        if not self.install_dir.exists() and not self.install_dir.is_symlink():
            self._phase = "stopped"
            self._error = "managed Ollama runtime is not installed"
            raise OllamaRuntimeError("managed Ollama runtime is not installed")
        try:
            executable = self._verified_executable(rehash=True)
        except OllamaRuntimeError as exc:
            self._phase = "failed"
            self._error = "managed Ollama runtime integrity verification failed"
            raise OllamaRuntimeError(self._error) from exc
        bind_port = self._port_allocator() if self._port_allocator is not None else 0
        if bind_port != 0 and not 1024 <= bind_port <= 65535:
            self._port = 0
            raise OllamaRuntimeError("could not allocate a private Ollama endpoint")
        self._port = bind_port
        if bind_port and self._probe():
            self._phase = "conflict"
            self._error = "managed Ollama endpoint is already occupied by an unowned process"
            self._port = 0
            raise OllamaRuntimeError(self._error)
        self._ensure_managed_directory(self.models_dir, create=True)
        self._model_store_bytes()
        self._normalise_existing_logs()
        self._managed_storage_bytes()
        if self._managed_storage_bytes(include_logs=False) + _MAX_LOG_STORAGE_BYTES > _MAX_MANAGED_STORAGE_BYTES:
            raise OllamaRuntimeError("managed Ollama storage cannot reserve bounded log space")
        environment = _managed_child_environment(os.environ)
        environment.update(
            {
                "OLLAMA_HOST": f"127.0.0.1:{bind_port}",
                "OLLAMA_MODELS": str(self.models_dir),
                "OLLAMA_NO_CLOUD": "1",
                "OLLAMA_ORIGINS": "http://flinttrade.invalid",
                "OLLAMA_MAX_QUEUE": "1",
                "OLLAMA_NUM_PARALLEL": "1",
                "OLLAMA_MAX_LOADED_MODELS": "1",
            }
        )
        executable_dir = str(executable.parent)
        environment["PATH"] = os.pathsep.join(filter(None, (executable_dir, environment.get("PATH", ""))))
        self._phase = "starting"
        self._error = ""
        self._log_error = ""
        with self._state_lock:
            self._inference_processor = None
        owner_record = {
            "schema": 1,
            "backend_pid": os.getpid(),
            "backend_create_time": self._process_create_time(os.getpid(), strict=True),
            "child_pid": 0,
            "child_create_time": 0.0,
            "port": bind_port,
            "bind_port": bind_port,
            "executable_sha256": _sha256_file(executable),
        }
        owner_record_written = False
        try:
            self._mark_operation_mutation_started()
            self._write_process_owner_record(owner_record, exclusive=True)
            owner_record_written = True
            with self._process_lock:
                self._raise_if_cancelled()
                self._process = self._process_factory(
                    [str(executable), "serve"],
                    cwd=str(self.install_dir),
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    **_managed_process_options(),
                )
                if os.name == "nt" and self._process_factory is subprocess.Popen:
                    self._windows_job = _contain_suspended_windows_process(
                        self._process,
                        deadline=time.monotonic() + _PROCESS_TREE_STOP_TIMEOUT_SECONDS,
                    )
                self._start_log_pump(self._process)
            owner_record.update(
                {
                    "child_pid": int(self._process.pid),
                    "child_create_time": self._process_create_time(
                        int(self._process.pid),
                        strict=self._process_factory is subprocess.Popen,
                    ),
                }
            )
            self._write_process_owner_record(owner_record)
            deadline = time.monotonic() + timeout_seconds
            while True:
                self._raise_if_cancelled()
                if self._process.poll() is not None:
                    raise OllamaRuntimeError("managed Ollama server exited before becoming ready")
                if self._port == 0:
                    discovered_port = self._port_discoverer(self._process)
                    if discovered_port:
                        if not 1024 <= discovered_port <= 65535:
                            raise OllamaRuntimeError("could not discover the managed Ollama endpoint")
                        self._port = discovered_port
                        owner_record["port"] = discovered_port
                        self._write_process_owner_record(owner_record)
                server_version = self._probe() if self._port else None
                if server_version:
                    if server_version != self.server_version:
                        raise OllamaRuntimeError("managed Ollama server version does not match the pinned runtime")
                    if not self._listener_is_owned(self._process):
                        raise OllamaRuntimeError("could not prove managed Ollama listener ownership")
                    self._phase = "ready"
                    _publish_managed_ollama_owner(self)
                    return self._status_snapshot(probe_server=True)
                if time.monotonic() >= deadline:
                    raise OllamaRuntimeError("managed Ollama server did not become ready before timeout")
                self._sleep(0.1)
        except Exception as exc:
            cleanup_proven = False
            if self._process is not None:
                try:
                    self._stop_owned_process(cancel_operation=False)
                except OllamaRuntimeError:
                    raise
                cleanup_proven = True
            elif owner_record_written:
                self._remove_process_owner_record()
                cleanup_proven = True
            if cleanup_proven:
                self._mark_operation_mutation_resolved()
            if isinstance(exc, _OllamaOperationCancelled):
                self._phase = "installed"
                self._error = ""
                raise
            message = str(exc) if isinstance(exc, OllamaRuntimeError) else "managed Ollama server could not start"
            self._phase = "failed"
            self._error = message
            if isinstance(exc, (OllamaRuntimeError, ValueError)):
                raise
            raise OllamaRuntimeError("managed Ollama server could not start") from exc

    def stop(
        self,
        *,
        timeout_seconds: float = _PROCESS_TREE_STOP_TIMEOUT_SECONDS,
        inference_grace_seconds: float = _INFERENCE_STOP_GRACE_SECONDS,
        expected_operation_id: str | None = None,
    ) -> dict[str, Any]:
        """Bound graceful inference drain, then stop only the exact owned child."""
        if timeout_seconds < 0 or inference_grace_seconds < 0:
            raise ValueError("managed Ollama stop timeouts must be non-negative")
        stop_deadline = time.monotonic() + timeout_seconds
        grace_deadline = min(stop_deadline, time.monotonic() + inference_grace_seconds)
        if expected_operation_id is not None and _OPERATION_ID.fullmatch(expected_operation_id) is None:
            raise ValueError("expected_operation_id is invalid")
        with self._operation_control(deadline=stop_deadline):
            with self._bounded_state_lock(deadline=stop_deadline, operation="stop transition"):
                operation = self._operation
                current_operation_id = str(operation.get("id")) if operation is not None else None
                running_operation_id = (
                    current_operation_id
                    if operation is not None and operation.get("state") == "running"
                    else None
                )
                if running_operation_id is not None and expected_operation_id is None:
                    raise OllamaRuntimeError("operation ID is required to cancel an active Ollama operation")
                if expected_operation_id is not None and running_operation_id != expected_operation_id:
                    raise OllamaRuntimeError("the requested Ollama operation is no longer running")
                self._cancel_event.set()
                worker = self._worker
                self._teardown = {
                    "state": "waiting",
                    "mode": None,
                    "active_inferences": self._active_inferences,
                }
            if worker is not None and worker is not threading.current_thread() and worker.is_alive():
                remaining = max(0.0, stop_deadline - time.monotonic())
                worker.join(timeout=remaining)
                if worker.is_alive():
                    raise OllamaRuntimeError("managed Ollama operation did not stop before shutdown")
            try:
                with self._stop_admission(
                    grace_deadline=grace_deadline,
                    stop_deadline=stop_deadline,
                ) as (graceful, active_inferences):
                    mode = "graceful" if graceful else "forced"
                    with self._bounded_state_lock(deadline=stop_deadline, operation="stop transition"):
                        self._teardown = {
                            "state": "stopping",
                            "mode": mode,
                            "active_inferences": active_inferences,
                        }
                    self._stop_owned_process(
                        cancel_operation=False,
                        deadline=stop_deadline,
                        probe_status=False,
                    )
                    with self._bounded_state_lock(deadline=stop_deadline, operation="stop transition"):
                        self._teardown = {
                            "state": "stopped",
                            "mode": mode,
                            "active_inferences": active_inferences,
                        }
                    return self._status_snapshot(verification_deadline=stop_deadline)
            except Exception:
                acquired = self._state_lock.acquire(timeout=max(0.0, stop_deadline - time.monotonic()))
                if acquired:
                    try:
                        self._teardown = {
                            "state": "failed",
                            "mode": self._teardown.get("mode"),
                            "active_inferences": self._active_inferences,
                        }
                    finally:
                        self._state_lock.release()
                raise

    def _stop_owned_process(
        self,
        *,
        cancel_operation: bool,
        deadline: float | None = None,
        probe_status: bool = True,
    ) -> dict[str, Any]:
        if cancel_operation:
            self._cancel_event.set()
        _clear_managed_ollama_owner(self)
        stop_deadline = _teardown_deadline(deadline)
        with self._deadline_lock(
            self._process_lock,
            deadline=stop_deadline,
            operation="process teardown",
        ):
            process = self._process
        if process is None:
            try:
                self._recover_stale_owned_process(
                    deadline=stop_deadline,
                    allow_current_backend=True,
                )
            except Exception as exc:
                self._phase = "failed"
                self._error = "could not prove managed Ollama teardown"
                if isinstance(exc, OllamaRuntimeError):
                    raise
                raise OllamaRuntimeError(self._error) from exc
            with self._deadline_lock(
                self._process_lock,
                deadline=stop_deadline,
                operation="process teardown",
            ):
                with self._deadline_lock(
                    self._state_lock,
                    deadline=stop_deadline,
                    operation="process teardown",
                ):
                    if self._process is not None:
                        raise OllamaRuntimeError("could not prove managed Ollama teardown")
                    self._port = 0
                    self._phase = "stopped"
                    self._error = ""
        else:
            with self._deadline_lock(
                self._process_lock,
                deadline=stop_deadline,
                operation="process teardown",
            ):
                try:
                    if process.poll() is None or self._windows_job is not None:
                        if (
                            os.name == "nt"
                            and self._windows_job is None
                            and self._process_factory is not subprocess.Popen
                        ):
                            _terminate_injected_windows_process(process, deadline=stop_deadline)
                        else:
                            _terminate_process_tree(
                                process,
                                deadline=stop_deadline,
                                windows_job=self._windows_job,
                            )
                        self._windows_job = None
                    elif os.name != "nt":
                        while _posix_process_group_exists(int(process.pid)):
                            remaining = _remaining_teardown_time(stop_deadline)
                            if remaining <= 0:
                                raise OllamaRuntimeError("could not prove managed Ollama teardown")
                            time.sleep(min(0.05, remaining))
                except Exception as exc:
                    self._phase = "failed"
                    self._error = "could not prove managed Ollama teardown"
                    if isinstance(exc, OllamaRuntimeError):
                        raise
                    raise OllamaRuntimeError(self._error) from exc
                self._remove_process_owner_record_after_teardown()
                if self._process is process:
                    with self._deadline_lock(
                        self._state_lock,
                        deadline=stop_deadline,
                        operation="process teardown",
                    ):
                        self._process = None
                        self._port = 0
                        self._phase = "stopped"
                        self._error = ""
        if not self._finish_log_pump(deadline=stop_deadline):
            with self._bounded_state_lock(deadline=stop_deadline, operation="process teardown"):
                self._log_error = "managed Ollama log drain did not stop before teardown deadline"
        with self._bounded_state_lock(deadline=stop_deadline, operation="process teardown"):
            self._inference_processor = None
        if not probe_status:
            return {}
        return self._status_snapshot(probe_server=True, verification_deadline=stop_deadline)

    def _model_digests_path(self) -> Path:
        return self.trust_dir / _MODEL_DIGESTS_NAME

    def _read_model_trust_state(self) -> tuple[dict[str, str], dict[str, str]]:
        try:
            self._ensure_managed_directory(self.trust_dir, create=False)
        except FileNotFoundError:
            return {}, {}
        path = self._model_digests_path()
        try:
            raw = _read_private_regular_file(
                path,
                max_bytes=64 * 1024,
                managed_root=self.workspace_dir,
            )
        except FileNotFoundError:
            return {}, {}
        except (OSError, OllamaRuntimeError) as exc:
            raise OllamaRuntimeError("managed Ollama model digest state is invalid") from exc
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise OllamaRuntimeError("managed Ollama model digest state is invalid") from exc
        schema = payload.get("schema") if isinstance(payload, dict) else None
        models = payload.get("models") if schema in {1, 2} else None
        if not isinstance(models, dict):
            raise OllamaRuntimeError("managed Ollama model digest state is invalid")
        accepted: dict[str, str] = {}
        for model, digest in models.items():
            if not isinstance(model, str) or not isinstance(digest, str):
                raise OllamaRuntimeError("managed Ollama model digest state is invalid")
            try:
                _validate_model_identifier(model)
            except ValueError as exc:
                raise OllamaRuntimeError("managed Ollama model digest state is invalid") from exc
            normalised = _normalise_model_digest(digest)
            if normalised is None:
                raise OllamaRuntimeError("managed Ollama model digest state is invalid")
            accepted[model] = normalised
        if schema == 1:
            return accepted, {}

        raw_sources = payload.get("sources")
        if not isinstance(raw_sources, dict):
            raise OllamaRuntimeError("managed Ollama model digest state is invalid")
        sources: dict[str, str] = {}
        for source, alias in raw_sources.items():
            if not isinstance(source, str) or not isinstance(alias, str):
                raise OllamaRuntimeError("managed Ollama model digest state is invalid")
            try:
                _validate_model_identifier(source)
                _validate_model_identifier(alias)
            except ValueError as exc:
                raise OllamaRuntimeError("managed Ollama model digest state is invalid") from exc
            digest = accepted.get(alias)
            if digest is None or not _is_locked_model_alias(alias, digest):
                raise OllamaRuntimeError("managed Ollama model digest state is invalid")
            sources[source] = alias
        if any(not _is_locked_model_alias(alias, digest) for alias, digest in accepted.items()):
            raise OllamaRuntimeError("managed Ollama model digest state is invalid")
        return accepted, sources

    def _read_accepted_model_digests(self) -> dict[str, str]:
        accepted, _sources = self._read_model_trust_state()
        return accepted

    def _write_model_trust_payload(self, payload: dict[str, Any]) -> None:
        self._ensure_managed_directory(self.trust_dir, create=True)
        path = self._model_digests_path()
        if path.is_symlink():
            raise OllamaRuntimeError("managed Ollama model digest state is invalid")
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            _write_private_file(temporary, _json_bytes(payload))
            durable_replace(temporary, path)
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama model digest state could not be saved") from exc
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _write_accepted_model_digests(self, accepted: dict[str, str]) -> None:
        """Write the legacy schema for compatibility and corruption-recovery tests."""
        self._write_model_trust_payload({"schema": 1, "models": accepted})

    def _write_model_trust_state(self, accepted: dict[str, str], sources: dict[str, str]) -> None:
        for alias, digest in accepted.items():
            _validate_model_identifier(alias)
            if not _is_locked_model_alias(alias, digest):
                raise OllamaRuntimeError("managed Ollama model digest state is invalid")
        for source, alias in sources.items():
            _validate_model_identifier(source)
            if alias not in accepted:
                raise OllamaRuntimeError("managed Ollama model digest state is invalid")
        self._write_model_trust_payload({"schema": 2, "models": accepted, "sources": sources})

    def reset_model_digest_state(self) -> dict[str, bool]:
        """Remove only invalid FlintTrade model trust metadata."""
        deadline = time.monotonic() + _SYNC_LIFECYCLE_WAIT_SECONDS
        with self._exclusive_lifecycle(deadline=deadline):
            return self._reset_model_digest_state_locked()

    def _reset_model_digest_state_locked(self) -> dict[str, bool]:
        self._prepare_direct_operation()
        try:
            self._ensure_managed_directory(self.trust_dir, create=False)
        except FileNotFoundError as exc:
            raise OllamaRuntimeError("managed Ollama model digest state does not need recovery") from exc
        path = self._model_digests_path()
        try:
            path_stat = path.lstat()
        except FileNotFoundError as exc:
            raise OllamaRuntimeError("managed Ollama model digest state does not need recovery") from exc
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama model digest state could not be inspected") from exc

        if stat.S_ISREG(path_stat.st_mode) and not stat.S_ISLNK(path_stat.st_mode):
            try:
                self._read_accepted_model_digests()
            except OllamaRuntimeError:
                pass
            else:
                raise OllamaRuntimeError("managed Ollama model digest state is already valid")
        elif not stat.S_ISLNK(path_stat.st_mode):
            raise OllamaRuntimeError("managed Ollama model digest state is not a removable file")

        with self._state_lock:
            self._raise_if_cancelled()
            try:
                self._mark_operation_mutation_started()
                durable_unlink(path)
            except OSError as exc:
                raise OllamaRuntimeError("managed Ollama model digest state could not be reset") from exc
            self._model_digest_drift.clear()
        return {"reset": True}

    def _raw_models(self) -> list[dict[str, Any]]:
        payload = self._request_json("GET", "/api/tags", None)
        raw_models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(raw_models, list):
            raise OllamaRuntimeError("Ollama returned an invalid model list")
        if len(raw_models) > 500:
            raise OllamaRuntimeError("Ollama returned too many models for authoritative reconciliation")
        return [model for model in raw_models if isinstance(model, dict)]

    def _model_store_bytes(self) -> int:
        """Measure the managed model store without following links or reparse points."""
        try:
            root = self._ensure_managed_directory(self.models_dir, create=False)
        except FileNotFoundError:
            return 0
        total = 0
        entries = 0
        stack = [root]
        try:
            while stack:
                current = stack.pop()
                with os.scandir(current) as children:
                    for child in children:
                        entries += 1
                        if entries > _MAX_MODEL_STORE_ENTRIES:
                            raise OllamaRuntimeError("managed Ollama model store contains too many entries")
                        child_stat = child.stat(follow_symlinks=False)
                        reparse_mask = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                        is_reparse = bool(
                            reparse_mask
                            and getattr(child_stat, "st_file_attributes", 0) & reparse_mask
                        )
                        if child.is_symlink() or stat.S_ISLNK(child_stat.st_mode) or is_reparse:
                            raise OllamaRuntimeError("managed Ollama model store is unsafe")
                        if stat.S_ISDIR(child_stat.st_mode):
                            stack.append(Path(child.path))
                        elif stat.S_ISREG(child_stat.st_mode):
                            total += child_stat.st_size
                        else:
                            raise OllamaRuntimeError("managed Ollama model store is unsafe")
                        if total > _MAX_MODEL_STORE_BYTES:
                            raise OllamaRuntimeError("managed Ollama model store exceeds the size limit")
        except OllamaRuntimeError:
            raise
        except OSError as exc:
            raise OllamaRuntimeError("managed Ollama model store could not be inspected") from exc
        return total

    def list_models(self) -> list[dict[str, Any]]:
        """Return the live server's installed models without internal fields."""
        with self._model_trust_lock:
            return self._list_models_locked()

    def _list_models_locked(self) -> list[dict[str, Any]]:
        self._require_managed_ready()
        raw_models = self._raw_models()
        self._reconcile_model_trust_state(raw_models)
        accepted, sources = self._read_model_trust_state()
        allowed = ("name", "model", "size", "digest", "modified_at", "details")
        models: list[dict[str, Any]] = []
        drift: dict[str, dict[str, str]] = {}
        for raw_model in raw_models:
            model = {key: raw_model[key] for key in allowed if key in raw_model}
            if "digest" in model:
                digest = _normalise_model_digest(model["digest"])
                if digest is None:
                    raise OllamaRuntimeError("Ollama returned an invalid model digest")
                model["digest"] = digest
            model_name = str(model.get("name") or model.get("model") or "")
            model_aliases = set(_model_aliases(model_name))
            accepted_name = next(
                (
                    alias
                    for alias in model_aliases
                    if alias in accepted and _is_locked_model_alias(alias, accepted[alias])
                ),
                "",
            )
            source_name = next((source for source in model_aliases if source in sources), "")
            if not accepted_name and source_name:
                accepted_name = sources[source_name]
                model["inference_model"] = accepted_name
            accepted_digest = accepted.get(accepted_name)
            current_digest = model.get("digest")
            if accepted_digest and isinstance(current_digest, str):
                changed = accepted_digest != current_digest
                model["accepted_digest"] = accepted_digest
                model["digest_drift"] = changed
                if changed:
                    drift[source_name or accepted_name or model_name] = {
                        "accepted": accepted_digest,
                        "current": current_digest,
                    }
            if accepted_name and _is_locked_model_alias(model_name, str(current_digest or "")):
                model["locked_alias"] = True
            models.append(model)
        with self._state_lock:
            self._model_digest_drift = drift
        return models

    @staticmethod
    def _raw_model_names(raw_models: list[dict[str, Any]]) -> set[str]:
        names: set[str] = set()
        for raw_model in raw_models:
            for value in (raw_model.get("name"), raw_model.get("model")):
                if not isinstance(value, str) or value in names:
                    continue
                try:
                    _validate_model_identifier(value)
                except ValueError as exc:
                    raise OllamaRuntimeError("Ollama returned an invalid model name") from exc
                names.add(value)
        return names

    def _reconcile_model_trust_state(self, raw_models: list[dict[str, Any]]) -> None:
        accepted, sources = self._read_model_trust_state()
        if not accepted and not sources:
            return
        live_digests: dict[str, str] = {}
        for raw_model in raw_models:
            digest = _normalise_model_digest(raw_model.get("digest"))
            if digest is None:
                continue
            for value in (raw_model.get("name"), raw_model.get("model")):
                if isinstance(value, str):
                    live_digests[value] = digest
        reconciled_accepted = {
            alias: digest
            for alias, digest in accepted.items()
            if live_digests.get(alias) == digest
        }
        reconciled_sources = {
            source: alias
            for source, alias in sources.items()
            if source in live_digests and alias in reconciled_accepted
        }
        if reconciled_accepted != accepted or reconciled_sources != sources:
            self._write_model_trust_state(reconciled_accepted, reconciled_sources)
        with self._state_lock:
            retained = set(reconciled_accepted) | set(reconciled_sources)
            self._model_digest_drift = {
                model: digests
                for model, digests in self._model_digest_drift.items()
                if model in retained
            }

    def _best_effort_reconcile_model_trust(self) -> None:
        try:
            self._reconcile_model_trust_state(self._raw_models())
        except OllamaRuntimeError:
            pass

    @staticmethod
    def _protected_model_aliases(protected_models: tuple[str, ...]) -> set[str]:
        aliases: set[str] = set()
        for model in protected_models:
            _validate_model_identifier(model)
            aliases.update(_model_aliases(model))
        return aliases

    def delete_model(
        self,
        model: str,
        *,
        protected_models: tuple[str, ...] = (),
    ) -> dict[str, list[str]]:
        """Delete exactly one installed alias and reconcile FlintTrade trust metadata."""
        deadline = time.monotonic() + _SYNC_LIFECYCLE_WAIT_SECONDS
        with self._exclusive_lifecycle(deadline=deadline):
            self._prepare_direct_operation()
            _validate_model_identifier(model)
            protected = self._protected_model_aliases(protected_models)
            if set(_model_aliases(model)).intersection(protected):
                raise OllamaRuntimeError("the selected model must be changed before deletion")
            self._require_managed_ready()
            self._model_store_bytes()
            before = self._raw_models()
            names = self._raw_model_names(before)
            matches = sorted(name for name in names if set(_model_aliases(name)).intersection(_model_aliases(model)))
            if len(matches) != 1:
                if not matches:
                    raise OllamaRuntimeError("model is not installed")
                raise OllamaRuntimeError("model name resolves to more than one installed alias")
            selected = matches[0]
            if set(_model_aliases(selected)).intersection(protected):
                raise OllamaRuntimeError("the selected model must be changed before deletion")
            with self._state_lock:
                try:
                    self._raise_if_cancelled()
                    self._mark_operation_mutation_started()
                    self._request_json("DELETE", "/api/delete", {"model": selected})
                    after = self._raw_models()
                except OllamaRuntimeError:
                    self._best_effort_reconcile_model_trust()
                    raise
                if selected in self._raw_model_names(after):
                    raise OllamaRuntimeError("Ollama did not delete the requested model alias")
                self._reconcile_model_trust_state(after)
                self._model_store_bytes()
                return {"deleted": [selected], "pruned": []}

    def prune_models(
        self,
        *,
        protected_models: tuple[str, ...] = (),
    ) -> dict[str, list[str]]:
        """Delete only unreferenced digest aliases that FlintTrade created."""
        deadline = time.monotonic() + _SYNC_LIFECYCLE_WAIT_SECONDS
        with self._exclusive_lifecycle(deadline=deadline):
            self._prepare_direct_operation()
            protected = self._protected_model_aliases(protected_models)
            self._require_managed_ready()
            self._model_store_bytes()
            accepted, sources = self._read_model_trust_state()
            referenced = set(sources.values())
            raw_models = self._raw_models()
            live_names = self._raw_model_names(raw_models)
            orphaned_locked_aliases: set[str] = set()
            for raw_model in raw_models:
                digest = _normalise_model_digest(raw_model.get("digest"))
                if digest is None:
                    continue
                for raw_name in (raw_model.get("name"), raw_model.get("model")):
                    if (
                        isinstance(raw_name, str)
                        and _is_locked_model_alias(raw_name, digest)
                        and raw_name not in accepted
                    ):
                        orphaned_locked_aliases.add(raw_name)
            candidates = sorted(
                {
                    alias
                    for alias, digest in accepted.items()
                    if alias not in referenced
                    and alias not in protected
                    and _is_locked_model_alias(alias, digest)
                    and alias in live_names
                }
                | {alias for alias in orphaned_locked_aliases if alias not in protected}
            )
            pruned: list[str] = []
            with self._state_lock:
                try:
                    self._raise_if_cancelled()
                    for alias in candidates:
                        self._mark_operation_mutation_started()
                        self._request_json("DELETE", "/api/delete", {"model": alias})
                        pruned.append(alias)
                    after = self._raw_models()
                except OllamaRuntimeError:
                    self._best_effort_reconcile_model_trust()
                    raise
                remaining = self._raw_model_names(after)
                if any(alias in remaining for alias in pruned):
                    raise OllamaRuntimeError("Ollama did not prune a managed model alias")
                self._reconcile_model_trust_state(after)
                self._model_store_bytes()
                return {"deleted": [], "pruned": pruned}

    def _accepted_model_identity(self, model: str) -> tuple[str, str] | None:
        """Return the accepted name and digest only while the live tag matches."""
        _validate_model_identifier(model)
        self._model_store_bytes()
        if self._managed_server_version() is None:
            return None
        accepted, _sources = self._read_model_trust_state()
        accepted_name = next((alias for alias in _model_aliases(model) if alias in accepted), "")
        if not accepted_name:
            return None
        expected_digest = accepted[accepted_name]
        if not _is_locked_model_alias(accepted_name, expected_digest) or model != accepted_name:
            return None
        requested_aliases = set(_model_aliases(model))
        for raw_model in self._raw_models():
            names = [raw_model.get("name"), raw_model.get("model")]
            if not any(
                requested_aliases.intersection(_model_aliases(name))
                for name in names
                if isinstance(name, str)
            ):
                continue
            current_digest = _normalise_model_digest(raw_model.get("digest"))
            if current_digest == expected_digest:
                return accepted_name, expected_digest
            if current_digest is not None:
                with self._state_lock:
                    self._model_digest_drift[accepted_name] = {
                        "accepted": expected_digest,
                        "current": current_digest,
                    }
            return None
        return None

    def _loaded_model_matches(self, model: str, expected_digest: str) -> bool:
        with self._state_lock:
            self._inference_processor = None
        payload = self._request_json("GET", "/api/ps", None)
        raw_models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(raw_models, list):
            return False
        requested_aliases = set(_model_aliases(model))
        for raw_model in raw_models[:100]:
            if not isinstance(raw_model, dict):
                continue
            names = [raw_model.get("name"), raw_model.get("model")]
            if not any(
                requested_aliases.intersection(_model_aliases(name))
                for name in names
                if isinstance(name, str)
            ):
                continue
            matches = _normalise_model_digest(raw_model.get("digest")) == expected_digest
            if matches:
                size = raw_model.get("size")
                size_vram = raw_model.get("size_vram")
                processor: str | None = None
                if (
                    isinstance(size, int)
                    and not isinstance(size, bool)
                    and isinstance(size_vram, int)
                    and not isinstance(size_vram, bool)
                    and size >= 0
                    and size_vram >= 0
                ):
                    if size_vram == 0:
                        processor = "100% CPU"
                    elif size > 0 and size_vram == size:
                        processor = "100% GPU"
                    elif size > 0 and size_vram < size:
                        cpu_percent = int(((size - size_vram) / size * 100) + 0.5)
                        processor = f"{cpu_percent}%/{100 - cpu_percent}% CPU/GPU"
                with self._state_lock:
                    self._inference_processor = processor
            return matches
        return False

    def model_is_accepted(self, model: str) -> bool:
        """Recheck that a model tag still resolves to its explicitly accepted digest."""
        with self._lifecycle_condition:
            if self._lifecycle_transition or self._lifecycle_interrupt:
                return False
        return self._accepted_model_identity(model) is not None

    def accept_model_digest(self, model: str, digest: str) -> dict[str, Any]:
        """Accept one exact, currently installed model digest after operator review."""
        deadline = time.monotonic() + _SYNC_LIFECYCLE_WAIT_SECONDS
        with self._exclusive_lifecycle(deadline=deadline):
            self._prepare_direct_operation()
            _validate_model_identifier(model)
            expected_digest = _normalise_model_digest(digest)
            if expected_digest is None:
                raise ValueError("digest must be a SHA-256 model digest")
            self._require_managed_ready()

            requested_aliases = set(_model_aliases(model))
            installed_name = ""
            for raw_model in self._raw_models():
                candidate_names = [raw_model.get("name"), raw_model.get("model")]
                matching_name = next(
                    (
                        candidate
                        for candidate in candidate_names
                        if isinstance(candidate, str)
                        and requested_aliases.intersection(_model_aliases(candidate))
                    ),
                    "",
                )
                if not matching_name:
                    continue
                if _normalise_model_digest(raw_model.get("digest")) != expected_digest:
                    raise OllamaRuntimeError("accepted digest does not match the installed model")
                installed_name = matching_name
                break
            if not installed_name:
                raise OllamaRuntimeError("model is not installed")

            _validate_model_identifier(installed_name)
            locked_alias = _locked_model_alias(expected_digest)
            with self._state_lock:
                self._raise_if_cancelled()
                if installed_name != locked_alias:
                    self._mark_operation_mutation_started()
                    self._request_json(
                        "POST",
                        "/api/copy",
                        {"source": installed_name, "destination": locked_alias},
                    )
                alias_verified = any(
                    locked_alias
                    in {
                        candidate
                        for candidate in (raw_model.get("name"), raw_model.get("model"))
                        if isinstance(candidate, str)
                    }
                    and _normalise_model_digest(raw_model.get("digest")) == expected_digest
                    for raw_model in self._raw_models()
                )
                if not alias_verified:
                    raise OllamaRuntimeError("digest-locked model alias could not be verified")
                self._model_store_bytes()
                self._managed_storage_bytes()

                accepted, sources = self._read_model_trust_state()
                replaced_aliases: set[str] = set()
                for source_name in list(sources):
                    if requested_aliases.intersection(_model_aliases(source_name)):
                        replaced_aliases.add(sources.pop(source_name))
                for accepted_name in list(accepted):
                    if requested_aliases.intersection(_model_aliases(accepted_name)):
                        accepted.pop(accepted_name, None)
                accepted[locked_alias] = expected_digest
                sources[installed_name] = locked_alias
                for replaced_alias in replaced_aliases:
                    if replaced_alias != locked_alias and replaced_alias not in sources.values():
                        accepted.pop(replaced_alias, None)
                self._mark_operation_mutation_started()
                self._write_model_trust_state(accepted, sources)
                if self._model_pull is not None:
                    pull_model = str(self._model_pull.get("model") or "")
                    pull_digest = _normalise_model_digest(self._model_pull.get("digest"))
                    if (
                        pull_digest == expected_digest
                        and requested_aliases.intersection(_model_aliases(pull_model))
                    ):
                        self._model_pull.update(
                            {
                                "status": "accepted",
                                "acceptance_required": False,
                                "error": None,
                            }
                        )
                for drift_name in list(self._model_digest_drift):
                    if requested_aliases.intersection(_model_aliases(drift_name)):
                        self._model_digest_drift.pop(drift_name, None)
            return {
                "accepted": True,
                "source_model": installed_name,
                "model": locked_alias,
                "digest": expected_digest,
            }

    @contextmanager
    def inference_session(self, model: str) -> Iterator[ManagedOllamaAdmission]:
        """Admit one model, then recheck its tag and loaded digest before release."""
        _validate_model_identifier(model)
        admitted = False
        accepted_name = ""
        accepted_digest = ""
        with self._lifecycle_condition:
            if self._lifecycle_transition or self._lifecycle_interrupt:
                raise OllamaRuntimeError("managed Ollama runtime is changing state")
            self._active_inferences += 1
        try:
            identity = self._accepted_model_identity(model)
            if identity is None or not self.base_url:
                raise OllamaRuntimeError("managed Ollama model is not accepted")
            accepted_name, accepted_digest = identity
            admission = ManagedOllamaAdmission(
                base_url=self.base_url,
                model=accepted_name,
                digest=accepted_digest,
            )
            admitted = True
            yield admission
        finally:
            verification_error: Exception | None = None
            if admitted:
                try:
                    current = self._accepted_model_identity(accepted_name)
                    if current is None or current[1] != accepted_digest:
                        raise OllamaRuntimeError("managed Ollama model digest changed during inference")
                    if not self._loaded_model_matches(accepted_name, accepted_digest):
                        raise OllamaRuntimeError("managed Ollama loaded model digest could not be verified")
                except Exception as exc:  # noqa: BLE001 - re-raised after releasing admission
                    verification_error = exc
            with self._lifecycle_condition:
                self._active_inferences -= 1
                self._lifecycle_condition.notify_all()
            if verification_error is not None:
                raise verification_error

    def pull_model(
        self,
        model: str,
        *,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> dict[str, Any]:
        """Pull one canonical model name through Ollama's streaming API."""
        with self._exclusive_lifecycle():
            return self._pull_model_locked(model, on_progress=on_progress)

    def _pull_model_locked(
        self,
        model: str,
        *,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> dict[str, Any]:
        self._prepare_direct_operation()
        _validate_pull_model_identifier(model)
        self._require_managed_ready()
        initial_store_bytes = self._model_store_bytes()
        initial_managed_bytes = self._managed_storage_bytes()
        initial_non_log_bytes = self._managed_storage_bytes(include_logs=False)
        accepted, sources = self._read_model_trust_state()
        requested_aliases = set(_model_aliases(model))
        previous_source = next(
            (
                source
                for source in sources
                if requested_aliases.intersection(_model_aliases(source))
            ),
            "",
        )
        previous_alias = sources.get(previous_source, "")
        previous_digest = accepted.get(previous_alias)
        self._model_pull = {
            "model": model,
            "status": "starting",
            "completed": 0,
            "total": 0,
            "error": None,
            "digest": None,
            "previous_digest": previous_digest,
            "digest_changed": False,
            "acceptance_required": False,
        }
        layer_progress: dict[str, tuple[int, int]] = {}
        progress_mode: str | None = None

        def progress(
            completed: Any,
            total: Any,
            status: str,
            digest: str | None = None,
        ) -> None:
            nonlocal progress_mode
            self._mark_operation_mutation_started()
            self._raise_if_cancelled()
            assert self._model_pull is not None
            if (
                isinstance(completed, bool)
                or not isinstance(completed, int)
                or isinstance(total, bool)
                or not isinstance(total, int)
                or completed < 0
                or total < 0
                or completed > total
            ):
                raise OllamaRuntimeError("Ollama reported invalid model pull progress")
            completed_bytes = completed
            total_bytes = total

            progress_key: str | None = None
            if digest is not None:
                digest_value = digest.strip().lower()
                event_mode = "aggregate" if digest_value == "sha256:model" else "layers"
                if event_mode == "layers" and not re.fullmatch(r"sha256:[0-9a-f]{64}", digest_value):
                    raise OllamaRuntimeError("Ollama reported an invalid model layer digest")
                if progress_mode is not None and progress_mode != event_mode:
                    raise OllamaRuntimeError("Ollama reported mixed model pull progress modes")
                progress_mode = event_mode
                progress_key = digest_value
            elif completed_bytes or total_bytes:
                raise OllamaRuntimeError("Ollama model byte progress requires a layer digest")

            if progress_key is not None and total_bytes:
                previous = layer_progress.get(progress_key)
                if previous is not None and previous[0] != total_bytes:
                    raise OllamaRuntimeError("Ollama reported a changed model layer total")
                previous_completed = previous[1] if previous is not None else 0
                layer_progress[progress_key] = (total_bytes, max(previous_completed, completed_bytes))

            aggregate_total = sum(layer[0] for layer in layer_progress.values())
            aggregate_completed = sum(layer[1] for layer in layer_progress.values())
            if aggregate_completed > _MAX_MODEL_PULL_BYTES or aggregate_total > _MAX_MODEL_PULL_BYTES:
                raise OllamaRuntimeError("Ollama model pull exceeds the size limit")
            if aggregate_total:
                self._model_store_bytes()
                projected_store_bytes = initial_store_bytes + aggregate_total
                if projected_store_bytes > _MAX_MODEL_STORE_BYTES:
                    raise OllamaRuntimeError("Ollama model pull exceeds the model store size limit")
                projected_managed_bytes = max(
                    initial_managed_bytes,
                    initial_non_log_bytes + _MAX_LOG_STORAGE_BYTES,
                ) + aggregate_total
                if projected_managed_bytes > _MAX_MANAGED_STORAGE_BYTES:
                    raise OllamaRuntimeError("Ollama model pull exceeds the managed storage size limit")
                try:
                    free_bytes = int(self._disk_usage(self.workspace_dir).free)
                except (OSError, TypeError, ValueError) as exc:
                    raise OllamaRuntimeError("could not verify free disk space for the Ollama model") from exc
                required_bytes = aggregate_total - aggregate_completed + _MODEL_PULL_DISK_RESERVE_BYTES
                if free_bytes < required_bytes:
                    raise OllamaRuntimeError("insufficient free disk space for the Ollama model")
            self._model_pull.update(
                {
                    "completed": aggregate_completed,
                    "total": aggregate_total,
                    "status": str(status or "pulling"),
                }
            )
            if on_progress is not None:
                on_progress(aggregate_completed, aggregate_total, status)

        try:
            self._mark_operation_mutation_started()
            self._puller(model, progress)
            self._raise_if_cancelled()
            if not layer_progress or sum(layer[0] for layer in layer_progress.values()) <= 0:
                raise OllamaRuntimeError("Ollama model pull completed without accounted byte progress")
            pulled_models = self.list_models()
            pulled = next(
                (
                    candidate
                    for candidate in pulled_models
                    if any(
                        requested_aliases.intersection(_model_aliases(candidate_name))
                        for candidate_name in (candidate.get("name"), candidate.get("model"))
                        if isinstance(candidate_name, str)
                    )
                ),
                None,
            )
            digest = pulled.get("digest") if isinstance(pulled, dict) else None
            if not isinstance(digest, str):
                raise OllamaRuntimeError("Ollama did not report the pulled model digest")
            changed = bool(previous_digest and previous_digest != digest)
            acceptance_required = previous_digest != digest
            self._model_store_bytes()
            self._managed_storage_bytes()
            assert self._model_pull is not None
            self._model_pull.update(
                {
                    "status": "awaiting_digest_acceptance" if acceptance_required else "success",
                    "digest": digest,
                    "previous_digest": previous_digest,
                    "digest_changed": changed,
                    "acceptance_required": acceptance_required,
                    "error": None,
                }
            )
            with self._state_lock:
                if changed:
                    self._model_digest_drift[previous_source or model] = {
                        "accepted": str(previous_digest),
                        "current": digest,
                    }
                elif not acceptance_required:
                    self._model_digest_drift.pop(model, None)
        except Exception as exc:
            assert self._model_pull is not None
            cancelled = isinstance(exc, _OllamaOperationCancelled)
            self._model_pull.update(
                {
                    "status": "cancelled" if cancelled else "failed",
                    "error": None if cancelled else type(exc).__name__,
                }
            )
            if isinstance(exc, OllamaRuntimeError):
                raise
            raise OllamaRuntimeError("Ollama model pull failed") from exc
        return dict(self._model_pull)

    def shutdown(self, *, timeout: float = 5.0) -> bool:
        """Stop the owned server and bound any outstanding worker wait."""
        if timeout < 0:
            raise ValueError("timeout must be non-negative")
        deadline = time.monotonic() + timeout
        try:
            operation_control = self._operation_control(deadline=deadline)
            operation_control.__enter__()
        except OllamaRuntimeError:
            return False
        try:
            with self._bounded_state_lock(deadline=deadline, operation="shutdown transition"):
                operation = self._operation
                expected_operation_id = (
                    str(operation.get("id"))
                    if operation is not None and operation.get("state") == "running"
                    else None
                )
            remaining = _remaining_teardown_time(deadline)
            self.stop(
                timeout_seconds=remaining,
                inference_grace_seconds=min(_INFERENCE_STOP_GRACE_SECONDS, remaining / 2),
                expected_operation_id=expected_operation_id,
            )
        except OllamaRuntimeError:
            return False
        finally:
            operation_control.__exit__(None, None, None)
        return self.wait_for_operation(timeout=_remaining_teardown_time(deadline))


def _normalise_model_digest(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = _MODEL_DIGEST.fullmatch(value.strip())
    return match.group(1).lower() if match else None


def _model_aliases(model: str) -> tuple[str, ...]:
    tail = model.rsplit("/", 1)[-1]
    if ":" not in tail:
        return model, f"{model}:latest"
    if tail.endswith(":latest"):
        return model, model[: -len(":latest")]
    return (model,)


def _locked_model_alias(digest: str) -> str:
    normalised = _normalise_model_digest(digest)
    if normalised is None:
        raise ValueError("digest must be a SHA-256 model digest")
    return f"{_LOCKED_MODEL_PREFIX}{normalised}{_LOCKED_MODEL_SUFFIX}"


def _is_locked_model_alias(model: str, digest: str) -> bool:
    try:
        return model == _locked_model_alias(digest)
    except ValueError:
        return False


def _validate_model_identifier(model: str) -> None:
    if (
        not isinstance(model, str)
        or not _MODEL_IDENTIFIER.fullmatch(model)
        or model != model.strip()
        or any(part in {"", ".", ".."} for part in model.split("/"))
    ):
        raise ValueError("model must be a canonical model identifier")


def _validate_pull_model_identifier(model: str) -> None:
    _validate_model_identifier(model)
    if model.startswith(_LOCKED_MODEL_PREFIX):
        raise ValueError("digest-locked FlintTrade model aliases cannot be pulled")
