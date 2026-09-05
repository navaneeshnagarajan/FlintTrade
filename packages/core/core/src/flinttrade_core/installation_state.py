"""Stable, owner-only installation identity and cross-process Ditto fence."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import stat
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .owner_file_lock import OwnerSafeFileLock
from .secure_file import (
    assert_hardened,
    digest_owner_owned_regular_file,
    fsync_parent_directory,
    harden_directory,
    read_hardened_owner_owned_text,
    write_secret_text,
)

_IDENTITY_NAME = "installation_id"
_IDENTITY_BINDING_NAME = ".installation-id-binding"
_IDENTITY_LOCK_NAME = ".installation-id.lock"
DITTO_FENCE_NAME = ".ditto-legacy-source.lock"
_PROCESS_LOCK_GUARD = threading.Lock()
_PROCESS_LOCKS: dict[tuple[object, ...], threading.RLock] = {}
_PROCESS_DITTO_LOCKS: dict[tuple[object, ...], OwnerSafeFileLock] = {}


def _reset_process_lock_registries_after_fork() -> None:
    """Drop inherited thread/file-lock objects in a forked child."""
    global _PROCESS_LOCK_GUARD, _PROCESS_LOCKS, _PROCESS_DITTO_LOCKS

    _PROCESS_LOCK_GUARD = threading.Lock()
    _PROCESS_LOCKS = {}
    _PROCESS_DITTO_LOCKS = {}


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_process_lock_registries_after_fork)


class InstallationStateError(RuntimeError):
    """The stable installation identity cannot safely authorise mutation."""


def _platform_home_candidate() -> Path:
    if platform.system() == "Windows":
        configured = os.environ.get("USERPROFILE")
        if not configured:
            drive = os.environ.get("HOMEDRIVE")
            homepath = os.environ.get("HOMEPATH")
            configured = f"{drive}{homepath}" if drive and homepath else None
    else:
        configured = os.environ.get("HOME")
    if configured:
        return Path(os.path.abspath(Path(configured).expanduser()))
    return Path.home()


def stable_application_state_root() -> Path:
    """Return the non-workspace root for irreversible installation lineage."""
    override = os.environ.get("FLINTTRADE_INSTALLATION_STATE_DIR")
    if override:
        return Path(os.path.abspath(Path(override).expanduser()))
    system = platform.system()
    if system == "Darwin":
        return _platform_home_candidate() / "Library" / "Application Support" / "flinttrade-installation"
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else _platform_home_candidate() / "AppData" / "Roaming"
        return base / "flinttrade-installation"
    return _platform_home_candidate() / ".flinttrade-installation"


def _active_workspace_candidate() -> Path:
    override = os.environ.get("FLINTTRADE_WORKSPACE_DIR") or os.environ.get("FLINTTRADE_HOME")
    if override:
        return Path(os.path.abspath(Path(override).expanduser()))
    system = platform.system()
    if system == "Darwin":
        return _platform_home_candidate() / "Library" / "Application Support" / "flinttrade"
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else _platform_home_candidate() / "AppData" / "Roaming"
        return base / "flinttrade"
    return _platform_home_candidate() / ".flinttrade"


def _legacy_archive_candidate() -> Path:
    return _platform_home_candidate() / ".flinttrade" / "archive"


def _desktop_managed_root() -> Path:
    return _platform_home_candidate() / ".flinttrade"


def _backup_archive_root() -> Path:
    return _platform_home_candidate() / "flint-backups"


def _canonical_path_through_existing_ancestor(path: Path) -> str:
    """Resolve symlinks and filesystem spelling without requiring the leaf."""
    # realpath(strict=False) resolves every existing symlink component and also
    # carries a dangling link's declared target into the non-existing suffix.
    # Starting the ancestor walk from the lexical path would misclassify such a
    # dangling pivot as just another missing directory.
    candidate = Path(os.path.realpath(os.path.abspath(path), strict=False))
    missing: list[str] = []
    while True:
        try:
            candidate.stat()
        except FileNotFoundError:
            if candidate == candidate.parent:
                resolved = candidate
                break
            missing.append(candidate.name)
            candidate = candidate.parent
            continue
        except OSError:
            resolved = Path(os.path.realpath(candidate))
            break
        resolved = Path(os.path.realpath(candidate))
        break
    for component in reversed(missing):
        resolved /= component
    value = os.path.normpath(str(resolved))
    if platform.system() in {"Darwin", "Windows"}:
        value = value.casefold()
    return os.path.normcase(value)


def _paths_overlap(left: Path, right: Path) -> bool:
    left_real = _canonical_path_through_existing_ancestor(left)
    right_real = _canonical_path_through_existing_ancestor(right)
    try:
        common = os.path.commonpath((left_real, right_real))
    except ValueError:
        return False
    return common in {left_real, right_real}


def paths_resolve_same_location(left: str | Path, right: str | Path) -> bool:
    """Compare two existing or prospective paths across aliases and case policy."""
    try:
        return os.path.samefile(left, right)
    except (FileNotFoundError, OSError):
        pass
    left_real = os.path.normcase(os.path.realpath(os.path.abspath(left), strict=False))
    right_real = os.path.normcase(os.path.realpath(os.path.abspath(right), strict=False))
    if platform.system() == "Windows":
        left_real = left_real.casefold()
        right_real = right_real.casefold()
    return left_real == right_real


def assert_installation_state_disjoint(
    path: str | Path,
    *,
    label: str,
    installation_root: str | Path | None = None,
) -> None:
    """Reject a mutable archive/restore path that overlaps installation lineage."""
    selected_root = (
        Path(installation_root).expanduser()
        if installation_root is not None
        else stable_application_state_root()
    )
    root = Path(os.path.normcase(os.path.abspath(selected_root)))
    candidate = Path(os.path.normcase(os.path.abspath(Path(path).expanduser())))
    if _paths_overlap(root, candidate):
        raise InstallationStateError(f"{label} overlaps the installation state root")


def _assert_static_topology(root: Path) -> None:
    exclusions = [("active workspace", _active_workspace_candidate())]
    exclusions.extend(
        (
            ("legacy archive", _legacy_archive_candidate()),
            ("desktop managed root", _desktop_managed_root()),
            ("backup archive root", _backup_archive_root()),
        )
    )
    for label, excluded in exclusions:
        if _paths_overlap(root, excluded):
            raise InstallationStateError(f"installation state root overlaps the {label}")


def _is_reparse_point(path_stat: os.stat_result) -> bool:
    mask = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(mask and getattr(path_stat, "st_file_attributes", 0) & mask)


def _uses_posix_mode_bits() -> bool:
    return os.name != "nt"


def _assert_owned_directory(
    path: Path,
    *,
    expected: os.stat_result | None = None,
    require_hardened: bool = True,
) -> os.stat_result:
    try:
        path_stat = path.lstat()
    except OSError as exc:
        raise InstallationStateError("installation state root is unsafe") from exc
    getuid = getattr(os, "geteuid", None)
    if (
        not stat.S_ISDIR(path_stat.st_mode)
        or stat.S_ISLNK(path_stat.st_mode)
        or _is_reparse_point(path_stat)
        or (callable(getuid) and path_stat.st_uid != getuid())
        or (
            expected is not None
            and (path_stat.st_dev, path_stat.st_ino) != (expected.st_dev, expected.st_ino)
        )
    ):
        raise InstallationStateError("installation state root is unsafe")
    if os.name == "nt" and require_hardened:
        hardened, _reason = assert_hardened(path)
        if not hardened:
            raise InstallationStateError("installation state root is not owner-only")
    if require_hardened and _uses_posix_mode_bits() and path_stat.st_mode & 0o077:
        raise InstallationStateError("installation state root is not owner-only")
    return path_stat


def _barrier_and_revalidate_owned_root(
    path: Path,
    *,
    expected_root: os.stat_result,
    expected_parent: os.stat_result,
) -> os.stat_result:
    """Commit the root entry before publishing it as mutation-ready.

    Every observer performs the POSIX parent-directory barrier itself, so it
    cannot outrun the process that first called ``mkdir``.  Windows deliberately
    keeps the existing no-op directory-fsync semantics; its later child writes
    use write-through primitives.  Both platforms revalidate the pinned parent
    and root generations after the barrier.
    """
    fsync_parent_directory(path)
    _assert_parent_generation(path.parent, expected_parent)
    root_stat = _assert_owned_directory(path, expected=expected_root)
    _assert_parent_generation(path.parent, expected_parent)
    return root_stat


def _prepare_owned_root(path: Path) -> os.stat_result:
    """Create only the final component, never following or repairing an unsafe root."""
    try:
        parent_stat = path.parent.lstat()
    except OSError as exc:
        raise InstallationStateError("installation state parent is unsafe") from exc
    getuid = getattr(os, "geteuid", None)
    if (
        not stat.S_ISDIR(parent_stat.st_mode)
        or stat.S_ISLNK(parent_stat.st_mode)
        or _is_reparse_point(parent_stat)
        or (callable(getuid) and parent_stat.st_uid != getuid())
    ):
        raise InstallationStateError("installation state parent is unsafe")
    try:
        existing = path.lstat()
    except FileNotFoundError:
        try:
            os.mkdir(path, 0o700)
        except FileExistsError:
            # A different process won first creation.  Its mkdir is already
            # atomic; allow a brief interval for the winner to install the
            # exact Windows DACL before validating the shared root.
            for _attempt in range(100):
                try:
                    winner = _assert_owned_directory(path)
                    return _barrier_and_revalidate_owned_root(
                        path,
                        expected_root=winner,
                        expected_parent=parent_stat,
                    )
                except InstallationStateError:
                    time.sleep(0.01)
            raise InstallationStateError("installation state root could not be created safely")
        except Exception as exc:
            raise InstallationStateError("installation state root could not be created safely") from exc
        _assert_parent_generation(path.parent, parent_stat)
        existing = _assert_owned_directory(path, require_hardened=False)
        harden_directory(path)
        _assert_parent_generation(path.parent, parent_stat)
        hardened = _assert_owned_directory(path, expected=existing)
        return _barrier_and_revalidate_owned_root(
            path,
            expected_root=hardened,
            expected_parent=parent_stat,
        )
    except OSError as exc:
        raise InstallationStateError("installation state root is unsafe") from exc
    existing = _assert_owned_directory(path, expected=existing, require_hardened=False)
    for attempt in range(100):
        try:
            existing = _assert_owned_directory(path, expected=existing)
            break
        except InstallationStateError:
            if attempt == 99:
                raise
            time.sleep(0.01)
    hardened_mode = existing.st_mode & 0o077
    if _uses_posix_mode_bits() and hardened_mode:
        raise InstallationStateError("installation state root is not owner-only")
    return _barrier_and_revalidate_owned_root(
        path,
        expected_root=existing,
        expected_parent=parent_stat,
    )


def _assert_parent_generation(path: Path, expected: os.stat_result) -> None:
    try:
        current = path.lstat()
    except OSError as exc:
        raise InstallationStateError("installation state parent changed during creation") from exc
    getuid = getattr(os, "geteuid", None)
    if (
        not stat.S_ISDIR(current.st_mode)
        or stat.S_ISLNK(current.st_mode)
        or _is_reparse_point(current)
        or (callable(getuid) and current.st_uid != getuid())
        or (current.st_dev, current.st_ino) != (expected.st_dev, expected.st_ino)
    ):
        raise InstallationStateError("installation state parent changed during creation")


class InstallationState:
    """Pinned installation identity plus the one shared Ditto mutation fence."""

    def __init__(self, root: str | Path | None = None) -> None:
        selected_root = Path(root).expanduser() if root is not None else stable_application_state_root()
        self.root = Path(os.path.normcase(os.path.abspath(selected_root)))
        _assert_static_topology(self.root)
        self.identity_path = self.root / _IDENTITY_NAME
        self._binding_path = self.root / _IDENTITY_BINDING_NAME
        self._process_id = os.getpid()
        self._lock_key: tuple[object, ...] = (
            "path",
            _canonical_path_through_existing_ancestor(self.root),
        )
        with _PROCESS_LOCK_GUARD:
            self._thread_lock = _PROCESS_LOCKS.setdefault(self._lock_key, threading.RLock())
        try:
            with self._thread_lock:
                self._root_stat = _prepare_owned_root(self.root)
                creation_lock = OwnerSafeFileLock(
                    self.root / _IDENTITY_LOCK_NAME,
                    timeout=10,
                    mode=0o600,
                    thread_local=False,
                )
                with creation_lock:
                    _assert_owned_directory(self.root, expected=self._root_stat)
                    if _uses_posix_mode_bits() and Path(creation_lock.lock_file).lstat().st_mode & 0o077:
                        raise InstallationStateError("installation identity lock is not owner-only")
                    self._create_or_read_identity()
        except InstallationStateError:
            raise
        except Exception as exc:
            raise InstallationStateError("installation identity is not owner-safe") from exc
        self._identity_stat = self.identity_path.lstat()
        self._binding_stat = self._binding_path.lstat()
        self._bind_ditto_process_locks()

    def _bind_ditto_process_locks(self) -> None:
        """Bind this handle to this process's canonical per-root lock pair."""
        self._process_id = os.getpid()
        root_stat = _assert_owned_directory(self.root, expected=self._root_stat)
        self._lock_key = ("inode", root_stat.st_dev, root_stat.st_ino)
        with _PROCESS_LOCK_GUARD:
            self._thread_lock = _PROCESS_LOCKS.setdefault(self._lock_key, threading.RLock())
            self._ditto_lock = _PROCESS_DITTO_LOCKS.setdefault(
                self._lock_key,
                OwnerSafeFileLock(
                    self.root / DITTO_FENCE_NAME,
                    timeout=30,
                    mode=0o600,
                    thread_local=False,
                ),
            )

    @property
    def installation_id(self) -> uuid.UUID:
        """The pinned immutable identity for this state handle."""
        return self._installation_id

    def _create_or_read_identity(self) -> None:
        identity_exists = self._path_exists_no_follow(self.identity_path)
        binding_exists = self._path_exists_no_follow(self._binding_path)
        if binding_exists:
            try:
                binding_payload = json.loads(
                    read_hardened_owner_owned_text(self._binding_path, max_bytes=1024)
                )
            except Exception as exc:
                raise InstallationStateError("installation identity binding is malformed") from exc
            if binding_payload.get("phase") == "preparing":
                self._recover_preparing_identity(binding_payload)
                identity_exists = self._path_exists_no_follow(self.identity_path)
                binding_exists = self._path_exists_no_follow(self._binding_path)
        if identity_exists != binding_exists:
            raise InstallationStateError("installation identity binding is incomplete")
        if not identity_exists:
            value = str(uuid.uuid4())
            candidate_name = f".installation-id-{value}.candidate"
            candidate = self.root / candidate_name
            write_secret_text(candidate, f"{value}\n")
            identity_stat = candidate.lstat()
            preparing = {
                "phase": "preparing",
                "installation_id": value,
                "candidate_name": candidate_name,
                "identity_device": identity_stat.st_dev,
                "identity_inode": identity_stat.st_ino,
                "identity_sha256": hashlib.sha256(f"{value}\n".encode()).hexdigest(),
            }
            write_secret_text(
                self._binding_path,
                json.dumps(preparing, sort_keys=True, separators=(",", ":")) + "\n",
            )
            from .secure_file import durable_replace  # noqa: PLC0415

            durable_replace(candidate, self.identity_path)
            self._write_final_binding(value, identity_stat)
        identity = self._read_uuid(self.identity_path)
        binding, bound_file_identity = self._read_binding(self._binding_path)
        identity_stat = self.identity_path.lstat()
        if identity != binding or bound_file_identity != (identity_stat.st_dev, identity_stat.st_ino):
            raise InstallationStateError("installation identity binding mismatch")
        self._installation_id = identity

    def _recover_preparing_identity(self, payload: object) -> None:
        if self._path_exists_no_follow(self.root / "ditto-legacy-migration.json"):
            raise InstallationStateError(
                "installation identity preparation cannot coexist with a migration receipt"
            )
        if not isinstance(payload, dict) or set(payload) != {
            "phase",
            "installation_id",
            "candidate_name",
            "identity_device",
            "identity_inode",
            "identity_sha256",
        }:
            raise InstallationStateError("installation identity preparation journal is malformed")
        try:
            value = payload["installation_id"]
            parsed = uuid.UUID(value)
            expected_name = f".installation-id-{value}.candidate"
            device = payload["identity_device"]
            inode = payload["identity_inode"]
            expected_digest = payload["identity_sha256"]
            if (
                parsed.version != 4
                or str(parsed) != value
                or payload["candidate_name"] != expected_name
                or type(device) is not int
                or type(inode) is not int
                or device < 0
                or inode < 0
                or expected_digest != hashlib.sha256(f"{value}\n".encode()).hexdigest()
            ):
                raise ValueError("invalid preparation journal")
        except Exception as exc:
            raise InstallationStateError("installation identity preparation journal is malformed") from exc
        candidate = self.root / expected_name
        candidate_exists = self._path_exists_no_follow(candidate)
        identity_exists = self._path_exists_no_follow(self.identity_path)
        if candidate_exists == identity_exists:
            raise InstallationStateError("installation identity preparation is ambiguous")
        recovery_path = candidate if candidate_exists else self.identity_path
        try:
            actual_digest = digest_owner_owned_regular_file(recovery_path, require_hardened=True)
        except Exception as exc:
            raise InstallationStateError("installation identity preparation does not match its journal") from exc
        recovered = self._read_uuid(recovery_path)
        recovered_stat = recovery_path.lstat()
        if (
            recovered != parsed
            or actual_digest != expected_digest
            or (recovered_stat.st_dev, recovered_stat.st_ino) != (device, inode)
        ):
            raise InstallationStateError("installation identity preparation does not match its journal")
        if candidate_exists:
            from .secure_file import durable_replace  # noqa: PLC0415

            durable_replace(candidate, self.identity_path)
        self._write_final_binding(value, recovered_stat)

    def _write_final_binding(self, value: str, identity_stat: os.stat_result) -> None:
        write_secret_text(
            self._binding_path,
            json.dumps(
                {
                    "installation_id": value,
                    "identity_device": identity_stat.st_dev,
                    "identity_inode": identity_stat.st_ino,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
        )

    @staticmethod
    def _path_exists_no_follow(path: Path) -> bool:
        try:
            path.lstat()
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise InstallationStateError("installation identity path is unsafe") from exc

    @staticmethod
    def _read_uuid(path: Path) -> uuid.UUID:
        try:
            raw = read_hardened_owner_owned_text(path, max_bytes=128)
            if not raw.endswith("\n"):
                raise ValueError("identity lacks canonical newline")
            value = raw[:-1]
            parsed = uuid.UUID(value)
        except Exception as exc:
            raise InstallationStateError("installation identity is malformed or not owner-owned") from exc
        if parsed.version != 4 or raw != f"{parsed}\n":
            raise InstallationStateError("installation identity is malformed")
        return parsed

    @classmethod
    def _read_binding(cls, path: Path) -> tuple[uuid.UUID, tuple[int, int]]:
        try:
            payload = json.loads(read_hardened_owner_owned_text(path, max_bytes=512))
            if set(payload) != {"installation_id", "identity_device", "identity_inode"}:
                raise ValueError("unexpected binding keys")
            installation_id = uuid.UUID(payload["installation_id"])
            if str(installation_id) != payload["installation_id"] or installation_id.version != 4:
                raise ValueError("invalid binding UUID")
            device = payload["identity_device"]
            inode = payload["identity_inode"]
            if type(device) is not int or type(inode) is not int or device < 0 or inode < 0:
                raise ValueError("invalid file identity")
        except Exception as exc:
            raise InstallationStateError("installation identity binding is malformed") from exc
        return installation_id, (device, inode)

    def assert_mutation_ready(self) -> None:
        """Fail closed if the pinned identity path was replaced or changed."""
        _assert_owned_directory(self.root, expected=self._root_stat)
        try:
            current_stat = self.identity_path.lstat()
            binding_stat = self._binding_path.lstat()
        except OSError as exc:
            raise InstallationStateError("installation identity was replaced") from exc
        if (current_stat.st_dev, current_stat.st_ino) != (self._identity_stat.st_dev, self._identity_stat.st_ino):
            raise InstallationStateError("installation identity was replaced")
        if (binding_stat.st_dev, binding_stat.st_ino) != (self._binding_stat.st_dev, self._binding_stat.st_ino):
            raise InstallationStateError("installation identity binding was replaced")
        if self._read_uuid(self.identity_path) != self._installation_id:
            raise InstallationStateError("installation identity was replaced")
        bound_id, bound_file_identity = self._read_binding(self._binding_path)
        if bound_id != self._installation_id or bound_file_identity != (
            current_stat.st_dev,
            current_stat.st_ino,
        ):
            raise InstallationStateError("installation identity binding mismatch")

    @contextmanager
    def ditto_fence(self) -> Iterator[None]:
        """Hold the installation-wide legacy-source/writer fence."""
        if self._process_id != os.getpid():
            self._bind_ditto_process_locks()
        self.assert_mutation_ready()
        try:
            with self._thread_lock, self._ditto_lock:
                lock_stat = Path(self._ditto_lock.lock_file).lstat()
                if _uses_posix_mode_bits() and lock_stat.st_mode & 0o077:
                    raise InstallationStateError("Ditto fence is not owner-only")
                self.assert_mutation_ready()
                yield
                self.assert_mutation_ready()
        except InstallationStateError:
            raise
        except Exception:
            raise
