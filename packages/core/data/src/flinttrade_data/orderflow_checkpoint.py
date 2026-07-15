"""Bounded, atomic persistence for order-flow restart checkpoints."""

from __future__ import annotations

import errno
import hashlib
import hmac
import json
import os
import stat
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from flinttrade_data.storage import TickReplayCursor

CHECKPOINT_FILENAME = "orderflow-checkpoint-v1.json"
CHECKPOINT_FORMAT = "flinttrade.orderflow-checkpoint"
CHECKPOINT_VERSION = 1
MAX_ORDERFLOW_CHECKPOINT_BYTES = 256 * 1024 * 1024
LINEAGE_EVIDENCE_FILENAME = ".orderflow-checkpoint-lineage-evidence-v1.json"
MAX_LINEAGE_EVIDENCE_BYTES = 64 * 1024
STALE_CHECKPOINT_TEMP_AGE_SECONDS = 24 * 60 * 60
_LINEAGE_EVIDENCE_FORMAT = "flinttrade.orderflow-lineage-evidence"
_LINEAGE_EVIDENCE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
_LINEAGE_EVIDENCE_MAX_RECORDS = 16
_MAX_PUBLICATION_GENERATION = 2**63 - 1
_MAX_STALE_TEMP_CANDIDATES = 1_000
_PUBLICATION_LOCK_TIMEOUT_SECONDS = 0.25
_PUBLICATION_LOCK_RETRY_SECONDS = 0.01
_REPLACE_ATTEMPTS = 3
_REPLACE_RETRY_SECONDS = 0.05
_OWNER_READ_WRITE = stat.S_IRUSR | stat.S_IWUSR
_PROCESS_PUBLICATION_OWNER_EPOCH = str(uuid.uuid4())
_MOVEFILE_REPLACE_EXISTING = 0x1
_MOVEFILE_WRITE_THROUGH = 0x8


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


class OrderFlowCheckpointDurabilityUncertainError(OrderFlowCheckpointWriteError):
    """Raised when rename succeeded but directory durability is uncertain."""


@dataclass(frozen=True, slots=True)
class _LineageHandoffEvidenceIntent:
    """Hashed evidence inputs retained in the canonical publication."""

    from_generation: int
    from_lineage_hash: str
    prior_payload_hash: str


@dataclass(frozen=True, slots=True)
class OrderFlowCheckpoint:
    """Validated aggregator state paired with its committed tick-store cursor."""

    orderflow_state: dict[str, Any]
    cursor: TickReplayCursor
    publication_generation: int = 0
    publication_owner_epoch: str | None = None
    publication_predecessor_generation: int | None = None
    payload_checksum: str = ""
    lineage_handoff_evidence: _LineageHandoffEvidenceIntent | None = None

    def has_lineage_handoff_from(self, store_id: str) -> bool:
        """Return whether this publication proves a handoff from ``store_id``."""
        intent = self.lineage_handoff_evidence
        if intent is None:
            return False
        try:
            canonical_store_id = TickReplayCursor(store_id, 0).store_id
        except (TypeError, ValueError):
            return False
        return hmac.compare_digest(intent.from_lineage_hash, _identifier_hash(canonical_store_id))


def orderflow_checkpoint_path(workspace_dir: str | os.PathLike[str]) -> Path:
    """Return the canonical checkpoint path inside ``workspace_dir``."""
    return Path(workspace_dir) / CHECKPOINT_FILENAME


def store_orderflow_checkpoint(
    workspace_dir: str | os.PathLike[str],
    orderflow_state: Mapping[str, Any],
    cursor: TickReplayCursor,
    *,
    max_bytes: int = MAX_ORDERFLOW_CHECKPOINT_BYTES,
    handoff_from_store_id: str | None = None,
    owner_epoch: str | None = None,
    expected_generation: int | None = None,
) -> Path:
    """Atomically persist aggregator state and its committed storage cursor.

    The caller must stop or barrier ingestion and flush tick storage before
    obtaining ``cursor`` and exporting ``orderflow_state``. The previous file is
    left untouched unless the complete, fsync'd replacement is ready. A new
    store lineage must name the current lineage in ``handoff_from_store_id``.
    Production publishers also provide an owner epoch and predecessor generation
    so delayed equal-cursor writes cannot overwrite newer state.
    """
    size_limit = _validate_size_limit(max_bytes)
    if not isinstance(orderflow_state, Mapping):
        raise OrderFlowCheckpointValidationError("order-flow checkpoint state is not valid JSON")
    if not isinstance(cursor, TickReplayCursor):
        raise OrderFlowCheckpointValidationError("order-flow checkpoint cursor is invalid")
    if handoff_from_store_id is not None:
        try:
            handoff_from_store_id = TickReplayCursor(
                handoff_from_store_id,
                0,
            ).store_id
        except (TypeError, ValueError):
            raise OrderFlowCheckpointValidationError("order-flow checkpoint handoff lineage is invalid") from None
    explicit_publication_fence = owner_epoch is not None or expected_generation is not None
    if explicit_publication_fence:
        if owner_epoch is None or expected_generation is None:
            raise OrderFlowCheckpointValidationError("order-flow checkpoint publication fence is incomplete")
        owner_epoch = _validate_owner_epoch(owner_epoch)
        expected_generation = _validate_generation(
            expected_generation,
            allow_zero=True,
        )

    path = orderflow_checkpoint_path(workspace_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _checkpoint_publication_lock(path):
        return _store_orderflow_checkpoint_locked(
            path,
            orderflow_state,
            cursor,
            size_limit,
            handoff_from_store_id,
            owner_epoch,
            expected_generation,
            explicit_publication_fence,
        )


def _store_orderflow_checkpoint_locked(
    path: Path,
    orderflow_state: Mapping[str, Any],
    cursor: TickReplayCursor,
    size_limit: int,
    handoff_from_store_id: str | None,
    owner_epoch: str | None,
    expected_generation: int | None,
    explicit_publication_fence: bool,
) -> Path:
    current = load_orderflow_checkpoint(
        path.parent,
        max_bytes=MAX_ORDERFLOW_CHECKPOINT_BYTES,
    )
    if current is not None and current.lineage_handoff_evidence is not None:
        try:
            _ensure_lineage_handoff_evidence(path.parent, current, reject_expired=True)
        except OrderFlowCheckpointCorruptError:
            raise
        except (OSError, OrderFlowCheckpointError) as exc:
            raise OrderFlowCheckpointWriteError(
                "order-flow checkpoint lineage evidence could not be verified"
            ) from exc
    current_generation = 0 if current is None else current.publication_generation
    resolved_owner_epoch = owner_epoch or _PROCESS_PUBLICATION_OWNER_EPOCH
    resolved_expected_generation = current_generation if expected_generation is None else expected_generation
    desired_state = dict(orderflow_state)

    if current is not None and current.publication_generation == resolved_expected_generation + 1:
        if _is_idempotent_publication(
            current,
            desired_state,
            cursor,
            resolved_owner_epoch,
            resolved_expected_generation,
            handoff_from_store_id,
        ):
            try:
                _sync_parent_directory(path.parent)
            except (OSError, OrderFlowCheckpointError) as exc:
                raise OrderFlowCheckpointDurabilityUncertainError(
                    "order-flow checkpoint is published but its durability evidence is uncertain"
                ) from exc
            return path
        raise OrderFlowCheckpointWriteError("order-flow checkpoint publication generation changed")
    if current_generation != resolved_expected_generation:
        raise OrderFlowCheckpointWriteError("order-flow checkpoint publication generation changed")

    is_lineage_handoff = False
    if current is None:
        if handoff_from_store_id is not None:
            raise OrderFlowCheckpointWriteError("order-flow checkpoint handoff lineage is no longer current")
    elif current.cursor.store_id == cursor.store_id:
        if handoff_from_store_id not in {None, cursor.store_id}:
            raise OrderFlowCheckpointWriteError("order-flow checkpoint handoff lineage is no longer current")
        if current.cursor.ingest_seq > cursor.ingest_seq:
            if explicit_publication_fence:
                raise OrderFlowCheckpointWriteError(
                    "order-flow checkpoint cursor is older than the current publication"
                )
            return path
    else:
        if handoff_from_store_id != current.cursor.store_id:
            raise OrderFlowCheckpointWriteError("order-flow checkpoint lineage differs; explicit handoff required")
        is_lineage_handoff = True

    publication_generation = resolved_expected_generation + 1
    if publication_generation > _MAX_PUBLICATION_GENERATION:
        raise OrderFlowCheckpointWriteError("order-flow checkpoint publication generation is exhausted")
    evidence_intent = (
        _LineageHandoffEvidenceIntent(
            from_generation=current.publication_generation,
            from_lineage_hash=_identifier_hash(current.cursor.store_id),
            prior_payload_hash=current.payload_checksum,
        )
        if is_lineage_handoff and current is not None
        else None
    )
    publication: dict[str, Any] = {
        "generation": publication_generation,
        "owner_epoch": resolved_owner_epoch,
        "predecessor_generation": resolved_expected_generation,
    }
    if evidence_intent is not None:
        publication["lineage_handoff"] = {
            "from_generation": evidence_intent.from_generation,
            "from_lineage_hash": evidence_intent.from_lineage_hash,
            "prior_payload_hash": evidence_intent.prior_payload_hash,
        }
    payload = {
        "cursor": {
            "store_id": cursor.store_id,
            "ingest_seq": cursor.ingest_seq,
        },
        "orderflow_state": desired_state,
        "publication": publication,
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
        raise OrderFlowCheckpointValidationError("order-flow checkpoint state is not valid JSON") from None
    if len(document_bytes) > size_limit:
        raise OrderFlowCheckpointTooLargeError("order-flow checkpoint exceeds the configured size limit")

    fd = -1
    temp_path: Path | None = None
    canonical_replaced = False
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
        canonical_replaced = True
        _sync_parent_directory(path.parent)
        if evidence_intent is not None:
            published_checkpoint = OrderFlowCheckpoint(
                orderflow_state=desired_state,
                cursor=cursor,
                publication_generation=publication_generation,
                publication_owner_epoch=resolved_owner_epoch,
                publication_predecessor_generation=resolved_expected_generation,
                payload_checksum=document["checksum"],
                lineage_handoff_evidence=evidence_intent,
            )
            try:
                _ensure_lineage_handoff_evidence(path.parent, published_checkpoint)
            except (OSError, OrderFlowCheckpointError) as exc:
                raise OrderFlowCheckpointDurabilityUncertainError(
                    "order-flow checkpoint is published but its lineage evidence is uncertain"
                ) from exc
    except OSError as exc:
        if canonical_replaced:
            raise OrderFlowCheckpointDurabilityUncertainError(
                "order-flow checkpoint could not be written; rename succeeded but directory durability is uncertain"
            ) from exc
        raise OrderFlowCheckpointWriteError("order-flow checkpoint could not be written") from exc
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
    _cleanup_stale_checkpoint_temps(path.parent)
    checkpoint: OrderFlowCheckpoint | None = None
    try:
        checkpoint = _load_orderflow_checkpoint_file(path, size_limit)
        return checkpoint
    finally:
        preserve_generation = (
            checkpoint.publication_generation
            if checkpoint is not None and checkpoint.lineage_handoff_evidence is not None
            else None
        )
        _expire_lineage_handoff_evidence(path.parent, preserve_generation=preserve_generation)


def _load_orderflow_checkpoint_file(path: Path, size_limit: int) -> OrderFlowCheckpoint | None:
    """Load one canonical file without running auxiliary evidence maintenance."""
    try:
        raw = _read_bounded_regular_file(path, size_limit)
    except FileNotFoundError:
        return None
    except OrderFlowCheckpointError:
        raise
    except OSError as exc:
        raise OrderFlowCheckpointCorruptError("order-flow checkpoint is corrupt") from exc

    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_json,
        )
    except (RecursionError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise OrderFlowCheckpointCorruptError("order-flow checkpoint is corrupt") from None
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
        raise OrderFlowCheckpointIncompatibleError("order-flow checkpoint format is incompatible")

    payload = document.get("payload")
    checksum = document.get("checksum")
    if (
        not isinstance(payload, dict)
        or set(payload)
        not in (
            {"cursor", "orderflow_state"},
            {"cursor", "orderflow_state", "publication"},
        )
        or not isinstance(checksum, str)
        or len(checksum) != 64
        or any(character not in "0123456789abcdef" for character in checksum)
    ):
        raise OrderFlowCheckpointCorruptError("order-flow checkpoint is corrupt")
    expected_checksum = hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
    if not hmac.compare_digest(checksum, expected_checksum):
        raise OrderFlowCheckpointChecksumError("order-flow checkpoint checksum is invalid")

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
        raise OrderFlowCheckpointCorruptError("order-flow checkpoint is corrupt") from None
    publication_row = payload.get("publication")
    if publication_row is None:
        publication_generation = 0
        publication_owner_epoch = None
        publication_predecessor_generation = None
    else:
        if not isinstance(publication_row, dict) or set(publication_row) not in (
            {"generation", "owner_epoch", "predecessor_generation"},
            {"generation", "owner_epoch", "predecessor_generation", "lineage_handoff"},
        ):
            raise OrderFlowCheckpointCorruptError("order-flow checkpoint is corrupt")
        try:
            publication_generation = _validate_generation(
                publication_row.get("generation"),
                allow_zero=False,
            )
            publication_owner_epoch = _validate_owner_epoch(publication_row.get("owner_epoch"))
            publication_predecessor_generation = _validate_generation(
                publication_row.get("predecessor_generation"),
                allow_zero=True,
            )
        except OrderFlowCheckpointValidationError:
            raise OrderFlowCheckpointCorruptError("order-flow checkpoint is corrupt") from None
        if publication_generation != publication_predecessor_generation + 1:
            raise OrderFlowCheckpointCorruptError("order-flow checkpoint is corrupt")
    lineage_handoff_evidence = None
    if isinstance(publication_row, dict) and "lineage_handoff" in publication_row:
        evidence_row = publication_row["lineage_handoff"]
        if (
            not isinstance(evidence_row, dict)
            or set(evidence_row) != {"from_generation", "from_lineage_hash", "prior_payload_hash"}
            or not _is_sha256(evidence_row.get("from_lineage_hash"))
            or not _is_sha256(evidence_row.get("prior_payload_hash"))
        ):
            raise OrderFlowCheckpointCorruptError("order-flow checkpoint is corrupt")
        try:
            from_generation = _validate_generation(evidence_row.get("from_generation"), allow_zero=True)
        except OrderFlowCheckpointValidationError:
            raise OrderFlowCheckpointCorruptError("order-flow checkpoint is corrupt") from None
        lineage_handoff_evidence = _LineageHandoffEvidenceIntent(
            from_generation=from_generation,
            from_lineage_hash=evidence_row["from_lineage_hash"],
            prior_payload_hash=evidence_row["prior_payload_hash"],
        )
    checkpoint = OrderFlowCheckpoint(
        orderflow_state=orderflow_state,
        cursor=cursor,
        publication_generation=publication_generation,
        publication_owner_epoch=publication_owner_epoch,
        publication_predecessor_generation=publication_predecessor_generation,
        payload_checksum=checksum,
        lineage_handoff_evidence=lineage_handoff_evidence,
    )
    return checkpoint


def ensure_orderflow_checkpoint_lineage_evidence(
    workspace_dir: str | os.PathLike[str],
    checkpoint: OrderFlowCheckpoint,
) -> Path:
    """Strictly verify or recreate evidence for one exact canonical publication."""
    if not isinstance(checkpoint, OrderFlowCheckpoint) or checkpoint.lineage_handoff_evidence is None:
        raise OrderFlowCheckpointValidationError("order-flow checkpoint lineage evidence obligation is invalid")
    path = orderflow_checkpoint_path(workspace_dir)
    with _checkpoint_publication_lock(path):
        current = load_orderflow_checkpoint(path.parent)
        if (
            current is None
            or current.publication_generation != checkpoint.publication_generation
            or not hmac.compare_digest(current.payload_checksum, checkpoint.payload_checksum)
        ):
            raise OrderFlowCheckpointWriteError("order-flow checkpoint lineage evidence obligation is no longer canonical")
        try:
            evidence_path = _ensure_lineage_handoff_evidence(path.parent, current, reject_expired=True)
        except OrderFlowCheckpointCorruptError:
            raise
        except (OSError, OrderFlowCheckpointError) as exc:
            raise OrderFlowCheckpointWriteError(
                "order-flow checkpoint lineage evidence could not be verified"
            ) from exc
    if evidence_path is None:  # pragma: no cover - guarded by validation above
        raise OrderFlowCheckpointValidationError("order-flow checkpoint lineage evidence obligation is invalid")
    return evidence_path


def _validate_size_limit(max_bytes: int) -> int:
    if (
        isinstance(max_bytes, bool)
        or not isinstance(max_bytes, int)
        or not 0 < max_bytes <= MAX_ORDERFLOW_CHECKPOINT_BYTES
    ):
        raise ValueError(f"max_bytes must be between 1 and {MAX_ORDERFLOW_CHECKPOINT_BYTES}")
    return max_bytes


def _validate_owner_epoch(value: Any) -> str:
    if not isinstance(value, str):
        raise OrderFlowCheckpointValidationError("order-flow checkpoint owner epoch is invalid")
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, ValueError):
        raise OrderFlowCheckpointValidationError("order-flow checkpoint owner epoch is invalid") from None
    if str(parsed) != value:
        raise OrderFlowCheckpointValidationError("order-flow checkpoint owner epoch is invalid")
    return value


def _validate_generation(value: Any, *, allow_zero: bool) -> int:
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= _MAX_PUBLICATION_GENERATION:
        raise OrderFlowCheckpointValidationError("order-flow checkpoint publication generation is invalid")
    return value


def _is_idempotent_publication(
    current: OrderFlowCheckpoint,
    desired_state: Mapping[str, Any],
    cursor: TickReplayCursor,
    owner_epoch: str,
    predecessor_generation: int,
    handoff_from_store_id: str | None,
) -> bool:
    try:
        states_match = _canonical_json_bytes(current.orderflow_state) == _canonical_json_bytes(dict(desired_state))
    except (OverflowError, RecursionError, TypeError, ValueError):
        return False
    evidence = current.lineage_handoff_evidence
    handoff_matches = (
        evidence is None
        if handoff_from_store_id is None
        else evidence is not None and evidence.from_lineage_hash == _identifier_hash(handoff_from_store_id)
    )
    return (
        current.cursor == cursor
        and current.publication_owner_epoch == owner_epoch
        and current.publication_predecessor_generation == predecessor_generation
        and handoff_matches
        and states_match
    )


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
            if _uses_windows_write_through():
                _replace_windows_write_through(source, target)
            else:
                os.replace(source, target)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_RETRY_SECONDS)


def _uses_windows_write_through() -> bool:
    return os.name == "nt"


def _replace_windows_write_through(
    source: Path,
    target: Path,
    *,
    move_file_ex: Callable[[str, str, int], int] | None = None,
    get_last_error: Callable[[], int] | None = None,
) -> None:
    """Atomically replace one Windows file and wait for disk publication."""
    if move_file_ex is None or get_last_error is None:
        import ctypes  # noqa: PLC0415

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        move_file_ex = kernel32.MoveFileExW
        move_file_ex.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
        move_file_ex.restype = ctypes.c_int
        get_last_error = ctypes.get_last_error
    flags = _MOVEFILE_REPLACE_EXISTING | _MOVEFILE_WRITE_THROUGH
    if move_file_ex(str(source), str(target), flags):
        return
    error_code = int(get_last_error())
    message = f"MoveFileExW write-through replacement failed with Win32 error {error_code}"
    if error_code in {5, 32, 33}:
        raise PermissionError(error_code, message, str(target))
    raise OSError(error_code, message, str(target))


@contextmanager
def _checkpoint_publication_lock(path: Path) -> Iterator[None]:
    """Serialise compare-and-publish within a finite monotonic deadline."""
    lock_path = path.parent / f".{path.name}.lock"
    fd = -1
    acquired = False
    try:
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, _OWNER_READ_WRITE)
        _set_owner_only(fd, lock_path)
        if os.fstat(fd).st_size == 0:
            while True:
                try:
                    if os.write(fd, b"\0") != 1:
                        raise OSError("checkpoint lock initialisation made no progress")
                    break
                except InterruptedError:
                    continue
        deadline = time.monotonic() + _PUBLICATION_LOCK_TIMEOUT_SECONDS
        if sys.platform == "win32":
            import msvcrt  # noqa: PLC0415

            while True:
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    acquired = True
                    break
                except OSError as exc:
                    if exc.errno not in {
                        errno.EACCES,
                        errno.EAGAIN,
                        getattr(errno, "EDEADLK", errno.EACCES),
                    }:
                        raise
                    if time.monotonic() >= deadline:
                        raise OrderFlowCheckpointWriteError("order-flow checkpoint publication lock timed out") from exc
                    time.sleep(_PUBLICATION_LOCK_RETRY_SECONDS)
        else:
            import fcntl  # noqa: PLC0415

            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                        raise
                    if time.monotonic() >= deadline:
                        raise OrderFlowCheckpointWriteError("order-flow checkpoint publication lock timed out") from exc
                    time.sleep(_PUBLICATION_LOCK_RETRY_SECONDS)
        try:
            yield
        finally:
            if acquired:
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    if sys.platform == "win32":
                        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError:
                    pass
    except OrderFlowCheckpointWriteError:
        raise
    except OSError as exc:
        raise OrderFlowCheckpointWriteError("order-flow checkpoint publication lock is unavailable") from exc
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass


def _ensure_lineage_handoff_evidence(
    parent: Path,
    checkpoint: OrderFlowCheckpoint,
    *,
    reject_expired: bool = False,
) -> Path | None:
    """Persist bounded hashes proving a lineage handoff without market data."""
    intent = checkpoint.lineage_handoff_evidence
    if intent is None:
        return None
    owner_epoch = checkpoint.publication_owner_epoch
    if owner_epoch is None:
        raise OrderFlowCheckpointCorruptError("order-flow checkpoint lineage evidence intent is corrupt")
    evidence_path = parent / LINEAGE_EVIDENCE_FILENAME
    with _checkpoint_publication_lock(evidence_path):
        now = int(time.time())
        records = _load_lineage_handoff_evidence(evidence_path)
        cutoff = now - _LINEAGE_EVIDENCE_MAX_AGE_SECONDS
        record = {
            "from_generation": intent.from_generation,
            "from_lineage_hash": intent.from_lineage_hash,
            "owner_epoch_hash": _identifier_hash(owner_epoch),
            "prior_payload_hash": intent.prior_payload_hash,
            "recorded_at": now,
            "to_generation": checkpoint.publication_generation,
            "to_lineage_hash": _identifier_hash(checkpoint.cursor.store_id),
        }
        record_identity = {key: value for key, value in record.items() if key != "recorded_at"}
        for existing in records:
            existing_identity = {key: value for key, value in existing.items() if key != "recorded_at"}
            if existing["to_generation"] == checkpoint.publication_generation and existing_identity != record_identity:
                raise OrderFlowCheckpointCorruptError(
                    "order-flow lineage evidence does not match the canonical checkpoint"
                )
            if (
                reject_expired
                and existing_identity == record_identity
                and not cutoff <= existing["recorded_at"] <= now
            ):
                raise OrderFlowCheckpointCorruptError("order-flow lineage evidence for the canonical checkpoint expired")
        records = [record for record in records if cutoff <= record["recorded_at"] <= now]
        if not any(
            {key: value for key, value in existing.items() if key != "recorded_at"} == record_identity
            for existing in records
        ):
            records.append(record)
        records = records[-_LINEAGE_EVIDENCE_MAX_RECORDS:]
        _write_lineage_handoff_evidence(evidence_path, records)
    return evidence_path


def _write_lineage_handoff_evidence(path: Path, records: list[dict[str, Any]]) -> None:
    """Atomically write one validated, bounded evidence record set."""
    document = {
        "format": _LINEAGE_EVIDENCE_FORMAT,
        "records": records,
        "version": 1,
    }
    document_bytes = _canonical_json_bytes(document) + b"\n"
    if len(document_bytes) > MAX_LINEAGE_EVIDENCE_BYTES:
        raise OrderFlowCheckpointWriteError("order-flow lineage evidence exceeds its size limit")
    _atomic_write_owner_only(path, document_bytes)


def _expire_lineage_handoff_evidence(parent: Path, *, preserve_generation: int | None = None) -> None:
    """Best-effort expiry for auxiliary evidence during ordinary loads."""
    evidence_path = parent / LINEAGE_EVIDENCE_FILENAME
    try:
        with _checkpoint_publication_lock(evidence_path):
            records = _load_lineage_handoff_evidence(evidence_path)
            if not records:
                return
            now = int(time.time())
            cutoff = now - _LINEAGE_EVIDENCE_MAX_AGE_SECONDS
            retained = [
                record
                for record in records
                if cutoff <= record["recorded_at"] <= now or record["to_generation"] == preserve_generation
            ]
            if retained != records:
                _write_lineage_handoff_evidence(evidence_path, retained)
    except (OSError, OrderFlowCheckpointError):
        return


def _load_lineage_handoff_evidence(path: Path) -> list[dict[str, Any]]:
    try:
        raw = _read_bounded_regular_file(path, MAX_LINEAGE_EVIDENCE_BYTES)
    except FileNotFoundError:
        return []
    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_json,
        )
    except (RecursionError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise OrderFlowCheckpointCorruptError("order-flow lineage evidence is corrupt") from None
    if (
        not isinstance(document, dict)
        or set(document) != {"format", "records", "version"}
        or document.get("format") != _LINEAGE_EVIDENCE_FORMAT
        or document.get("version") != 1
        or not isinstance(document.get("records"), list)
        or len(document["records"]) > _LINEAGE_EVIDENCE_MAX_RECORDS
    ):
        raise OrderFlowCheckpointCorruptError("order-flow lineage evidence is corrupt")
    records: list[dict[str, Any]] = []
    expected_keys = {
        "from_generation",
        "from_lineage_hash",
        "owner_epoch_hash",
        "prior_payload_hash",
        "recorded_at",
        "to_generation",
        "to_lineage_hash",
    }
    for record in document["records"]:
        if (
            not isinstance(record, dict)
            or set(record) != expected_keys
            or any(
                not _is_sha256(record.get(key))
                for key in (
                    "from_lineage_hash",
                    "owner_epoch_hash",
                    "prior_payload_hash",
                    "to_lineage_hash",
                )
            )
            or any(
                isinstance(record.get(key), bool) or not isinstance(record.get(key), int) or record[key] < 0
                for key in (
                    "from_generation",
                    "recorded_at",
                    "to_generation",
                )
            )
        ):
            raise OrderFlowCheckpointCorruptError("order-flow lineage evidence is corrupt")
        records.append(record)
    return records


def _identifier_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _atomic_write_owner_only(path: Path, data: bytes) -> None:
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
        _write_all(fd, data)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        _replace_with_retry(temp_path, path)
        temp_path = None
        _sync_parent_directory(path.parent)
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass


def _sync_parent_directory(parent: Path) -> None:
    if _uses_windows_write_through():
        return
    try:
        _fsync_parent_directory(parent)
    except NotImplementedError as exc:
        raise OSError(errno.ENOTSUP, "directory fsync is unsupported", str(parent)) from exc


def _cleanup_stale_checkpoint_temps(parent: Path) -> None:
    """Remove bounded, old crash remnants while preserving live writer temps."""
    cutoff = time.time() - STALE_CHECKPOINT_TEMP_AGE_SECONDS
    patterns = (
        f".{CHECKPOINT_FILENAME}.*.tmp",
        f".{LINEAGE_EVIDENCE_FILENAME}.*.tmp",
    )
    scanned = 0
    try:
        for pattern in patterns:
            for candidate in parent.glob(pattern):
                if scanned >= _MAX_STALE_TEMP_CANDIDATES:
                    return
                scanned += 1
                candidate_stat = candidate.lstat()
                if not stat.S_ISREG(candidate_stat.st_mode) or candidate_stat.st_mtime >= cutoff:
                    continue
                candidate.unlink()
    except (FileNotFoundError, OSError):
        return


def _fsync_parent_directory(parent: Path) -> None:
    if os.name == "nt":
        raise NotImplementedError("directory fsync is unavailable on Windows")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        directory_fd = os.open(parent, flags)
    except OSError as exc:
        unsupported = {errno.EINVAL, errno.ENOTSUP, getattr(errno, "EOPNOTSUPP", errno.ENOTSUP)}
        if exc.errno in unsupported:
            raise NotImplementedError("directory fsync is unsupported") from None
        raise
    try:
        try:
            os.fsync(directory_fd)
        except OSError as exc:
            unsupported = {errno.EINVAL, errno.ENOTSUP, getattr(errno, "EOPNOTSUPP", errno.ENOTSUP)}
            if exc.errno in unsupported:
                raise NotImplementedError("directory fsync is unsupported") from None
            raise
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
            raise OrderFlowCheckpointTooLargeError("order-flow checkpoint exceeds the configured size limit")
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
            raise OrderFlowCheckpointTooLargeError("order-flow checkpoint exceeds the configured size limit")
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
