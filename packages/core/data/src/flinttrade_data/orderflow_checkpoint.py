"""Bounded, atomic persistence for order-flow restart checkpoints."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flinttrade_data.storage import TickReplayCursor

CHECKPOINT_FILENAME = "orderflow-checkpoint-v1.json"
CHECKPOINT_FORMAT = "flinttrade.orderflow-checkpoint"
CHECKPOINT_VERSION = 1
MAX_ORDERFLOW_CHECKPOINT_BYTES = 256 * 1024 * 1024
_REPLACE_ATTEMPTS = 3
_REPLACE_RETRY_SECONDS = 0.05
_OWNER_READ_WRITE = stat.S_IRUSR | stat.S_IWUSR


class OrderFlowCheckpointError(Exception):
    """Base class for durable order-flow checkpoint failures."""


class OrderFlowCheckpointCorruptError(OrderFlowCheckpointError):
    """Raised when a checkpoint cannot be parsed or structurally validated."""


class OrderFlowCheckpointChecksumError(OrderFlowCheckpointCorruptError):
    """Raised when checkpoint payload integrity validation fails."""


class OrderFlowCheckpointIncompatibleError(OrderFlowCheckpointError):
    """Raised when the outer checkpoint format or version is unsupported."""


class OrderFlowCheckpointTooLargeError(OrderFlowCheckpointError):
    """Raised when a checkpoint exceeds its configured size bound."""


class OrderFlowCheckpointValidationError(OrderFlowCheckpointError):
    """Raised when state cannot be represented by the checkpoint format."""


class OrderFlowCheckpointWriteError(OrderFlowCheckpointError):
    """Raised when a new atomic checkpoint cannot be published."""


@dataclass(frozen=True, slots=True)
class OrderFlowCheckpoint:
    """Validated aggregator state paired with its committed tick-store cursor."""

    orderflow_state: dict[str, Any]
    cursor: TickReplayCursor


def orderflow_checkpoint_path(workspace_dir: str | os.PathLike[str]) -> Path:
    """Return the canonical checkpoint path inside ``workspace_dir``."""
    return Path(workspace_dir) / CHECKPOINT_FILENAME


def store_orderflow_checkpoint(
    workspace_dir: str | os.PathLike[str],
    orderflow_state: Mapping[str, Any],
    cursor: TickReplayCursor,
    *,
    max_bytes: int = MAX_ORDERFLOW_CHECKPOINT_BYTES,
) -> Path:
    """Atomically persist aggregator state and its committed storage cursor.

    The caller must stop or barrier ingestion and flush tick storage before
    obtaining ``cursor`` and exporting ``orderflow_state``. The previous file is
    left untouched unless the complete, fsync'd replacement is ready.
    """
    size_limit = _validate_size_limit(max_bytes)
    if not isinstance(orderflow_state, Mapping):
        raise OrderFlowCheckpointValidationError(
            "order-flow checkpoint state is not valid JSON"
        )
    if not isinstance(cursor, TickReplayCursor):
        raise OrderFlowCheckpointValidationError(
            "order-flow checkpoint cursor is invalid"
        )

    payload = {
        "cursor": {
            "store_id": cursor.store_id,
            "ingest_seq": cursor.ingest_seq,
        },
        "orderflow_state": dict(orderflow_state),
    }
    try:
        payload_bytes = _canonical_json_bytes(payload)
        document = {
            "format": CHECKPOINT_FORMAT,
            "version": CHECKPOINT_VERSION,
            "checksum": hashlib.sha256(payload_bytes).hexdigest(),
            "payload": payload,
        }
        document_bytes = _canonical_json_bytes(document) + b"\n"
    except (OverflowError, RecursionError, TypeError, ValueError):
        raise OrderFlowCheckpointValidationError(
            "order-flow checkpoint state is not valid JSON"
        ) from None
    if len(document_bytes) > size_limit:
        raise OrderFlowCheckpointTooLargeError(
            "order-flow checkpoint exceeds the configured size limit"
        )

    path = orderflow_checkpoint_path(workspace_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = -1
    temp_path: Path | None = None
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temp_path = Path(temp_name)
        _set_owner_only(fd, temp_path)
        _write_all(fd, document_bytes)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        _replace_with_retry(temp_path, path)
        temp_path = None
        try:
            _fsync_parent_directory(path.parent)
        except (NotImplementedError, OSError):
            pass
    except OSError as exc:
        raise OrderFlowCheckpointWriteError(
            "order-flow checkpoint could not be written"
        ) from exc
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
    return path


def load_orderflow_checkpoint(
    workspace_dir: str | os.PathLike[str],
    *,
    max_bytes: int = MAX_ORDERFLOW_CHECKPOINT_BYTES,
) -> OrderFlowCheckpoint | None:
    """Load and validate the canonical checkpoint, or return ``None`` if absent."""
    size_limit = _validate_size_limit(max_bytes)
    path = orderflow_checkpoint_path(workspace_dir)
    try:
        raw = _read_bounded_regular_file(path, size_limit)
    except FileNotFoundError:
        return None
    except OrderFlowCheckpointError:
        raise
    except OSError as exc:
        raise OrderFlowCheckpointCorruptError(
            "order-flow checkpoint is corrupt"
        ) from exc

    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_json,
        )
    except (RecursionError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise OrderFlowCheckpointCorruptError(
            "order-flow checkpoint is corrupt"
        ) from None
    if not isinstance(document, dict) or set(document) != {
        "format",
        "version",
        "checksum",
        "payload",
    }:
        raise OrderFlowCheckpointCorruptError("order-flow checkpoint is corrupt")
    if (
        document.get("format") != CHECKPOINT_FORMAT
        or type(document.get("version")) is not int
        or document.get("version") != CHECKPOINT_VERSION
    ):
        raise OrderFlowCheckpointIncompatibleError(
            "order-flow checkpoint format is incompatible"
        )

    payload = document.get("payload")
    checksum = document.get("checksum")
    if (
        not isinstance(payload, dict)
        or set(payload) != {"cursor", "orderflow_state"}
        or not isinstance(checksum, str)
        or len(checksum) != 64
        or any(character not in "0123456789abcdef" for character in checksum)
    ):
        raise OrderFlowCheckpointCorruptError("order-flow checkpoint is corrupt")
    expected_checksum = hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
    if not hmac.compare_digest(checksum, expected_checksum):
        raise OrderFlowCheckpointChecksumError(
            "order-flow checkpoint checksum is invalid"
        )

    cursor_row = payload.get("cursor")
    orderflow_state = payload.get("orderflow_state")
    if (
        not isinstance(cursor_row, dict)
        or set(cursor_row) != {"store_id", "ingest_seq"}
        or not isinstance(orderflow_state, dict)
    ):
        raise OrderFlowCheckpointCorruptError("order-flow checkpoint is corrupt")
    try:
        cursor = TickReplayCursor(
            store_id=cursor_row.get("store_id"),
            ingest_seq=cursor_row.get("ingest_seq"),
        )
    except (TypeError, ValueError):
        raise OrderFlowCheckpointCorruptError(
            "order-flow checkpoint is corrupt"
        ) from None
    return OrderFlowCheckpoint(orderflow_state=orderflow_state, cursor=cursor)


def _validate_size_limit(max_bytes: int) -> int:
    if (
        isinstance(max_bytes, bool)
        or not isinstance(max_bytes, int)
        or not 0 < max_bytes <= MAX_ORDERFLOW_CHECKPOINT_BYTES
    ):
        raise ValueError(
            f"max_bytes must be between 1 and {MAX_ORDERFLOW_CHECKPOINT_BYTES}"
        )
    return max_bytes


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _write_all(fd: int, data: bytes) -> None:
    remaining = memoryview(data)
    while remaining:
        try:
            written = os.write(fd, remaining)
        except InterruptedError:
            continue
        if written <= 0:
            raise OSError("checkpoint write made no progress")
        remaining = remaining[written:]


def _set_owner_only(fd: int, path: Path) -> None:
    fchmod = getattr(os, "fchmod", None)
    if callable(fchmod):
        try:
            fchmod(fd, _OWNER_READ_WRITE)
            return
        except NotImplementedError:
            pass
    os.chmod(path, _OWNER_READ_WRITE)


def _replace_with_retry(source: Path, target: Path) -> None:
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_RETRY_SECONDS)


def _fsync_parent_directory(parent: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_fd = os.open(parent, flags)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _read_bounded_regular_file(path: Path, max_bytes: int) -> bytes:
    if path.is_symlink():
        raise OrderFlowCheckpointCorruptError("order-flow checkpoint is corrupt")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise OrderFlowCheckpointCorruptError("order-flow checkpoint is corrupt")
        if file_stat.st_size > max_bytes:
            raise OrderFlowCheckpointTooLargeError(
                "order-flow checkpoint exceeds the configured size limit"
            )
        chunks: list[bytes] = []
        total = 0
        while total <= max_bytes:
            try:
                chunk = os.read(fd, min(1024 * 1024, max_bytes + 1 - total))
            except InterruptedError:
                continue
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total > max_bytes:
            raise OrderFlowCheckpointTooLargeError(
                "order-flow checkpoint exceeds the configured size limit"
            )
        return b"".join(chunks)
    finally:
        os.close(fd)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_non_finite_json(_value: str) -> Any:
    raise ValueError("non-finite JSON value")
