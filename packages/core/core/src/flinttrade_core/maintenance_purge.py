"""Held, explicit multi-target purge filesystem phase (never safety authority).

Only the maintenance controller's pinned, drained transaction may call this
phase. Every target is captured before the first move; failures retain a durable
receipt and any quarantined bytes. Stable sibling exclusion is never a target.
"""
from __future__ import annotations

import ctypes
import json
import os
import stat
import sys
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from uuid import uuid4

from .installation_state import InstallationState
from .maintenance_custody import MaintenanceRefused
from .secure_file import HeldOwnerDirectory


def custody_path(workspace: Path) -> Path:
    """Return stable non-purgeable transaction custody beside backend exclusion."""
    return workspace.parent / f".{workspace.name}.maintenance"


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode), info.st_size, info.st_mtime_ns


def _no_alias(path: Path) -> Path:
    path = path.absolute()
    if path != path.resolve(strict=True):
        raise MaintenanceRefused("purge path or ancestor is a symbolic alias")
    if path.stat().st_uid != os.getuid():
        raise MaintenanceRefused("purge path is not owned by this OS owner")
    return path


def _scan(parent: int, name: str) -> dict[str, tuple[int, ...]]:
    info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)):
        raise MaintenanceRefused("purge contains an unqualified filesystem object")
    result = {"": _identity(info)}
    if stat.S_ISDIR(info.st_mode):
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            if _identity(os.fstat(fd)) != _identity(info):
                raise MaintenanceRefused("purge directory changed during capture")
            for child in sorted(os.listdir(fd)):
                for relative, identity in _scan(fd, child).items():
                    result[child + ("/" + relative if relative else "")] = identity
            if _identity(os.fstat(fd)) != _identity(info):
                raise MaintenanceRefused("purge directory changed during capture")
        finally:
            os.close(fd)
    return result


def _rename(parent: int, name: str, destination: int, target: str) -> None:
    # A no-clobber move into a private namespace precedes destructive work.
    rename = ctypes.CDLL(None, use_errno=True).renameat2
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(parent, os.fsencode(name), destination, os.fsencode(target), 1):
        value = ctypes.get_errno()
        raise OSError(value, os.strerror(value))
    os.fsync(parent)
    os.fsync(destination)


def _remove(parent: int, name: str, expected: dict[str, tuple[int, ...]], prefix: str = "", *,
            guard: Callable[[], None] | None = None) -> None:
    if guard is not None:
        guard()
    info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if _identity(info) != expected[prefix]:
        raise MaintenanceRefused("quarantined purge member changed; pending bytes retained")
    if stat.S_ISDIR(info.st_mode):
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            if _identity(os.fstat(fd)) != expected[prefix]:
                raise MaintenanceRefused("quarantined directory changed")
            for child in sorted(os.listdir(fd)):
                relative = prefix + ("/" if prefix else "") + child
                if relative not in expected:
                    raise MaintenanceRefused("unexpected purge member; pending bytes retained")
                _remove(fd, child, expected, relative, guard=guard)
            # Directory metadata changes with our unlinks. Recheck its inode.
            if os.stat(name, dir_fd=parent, follow_symlinks=False).st_ino != info.st_ino:
                raise MaintenanceRefused("quarantined directory replaced")
            os.rmdir(name, dir_fd=parent)
        finally:
            os.close(fd)
    else:
        # No open/write/truncate/follow of a file or symlink occurs here.
        os.unlink(name, dir_fd=parent)
    os.fsync(parent)


class PurgePlan:
    """Capture the entire known installation scope and remove lineage last.

    This class supplies path custody only, not maintenance permission. Never
    execute it on a free lease alone or from caller-supplied approval data.
    """

    def __init__(self, workspace: Path, installation: InstallationState) -> None:
        if sys.platform != "linux":
            raise MaintenanceRefused("native purge path custody is not qualified on this platform")
        self.workspace = _no_alias(Path(workspace))
        self.installation = installation
        self.installation.assert_mutation_ready()
        home = _no_alias(Path.home())
        default_lineage = home / ".flinttrade-installation"
        if installation.root != default_lineage:
            raise MaintenanceRefused("ambient installation root is not purge authority")
        managed = home / ".flinttrade"
        from .maintenance_installation import proven_web_targets

        web_targets = proven_web_targets(home)
        for name in (
            ".local/bin/flinttrade", ".local/bin/flinttrade-web", ".local/bin/flinttrade.AppImage",
            ".local/opt/flinttrade", ".local/share/applications/flinttrade.desktop",
            ".local/share/icons/hicolor/128x128/apps/flinttrade.png", ".local/state/flinttrade",
            ".local/state/flinttrade-web",
        ):
            if os.path.lexists(home / name) and home / name not in web_targets:
                raise MaintenanceRefused("complete installation custody unproved; launcher/shell receipts retained")
        candidates = [
            self.workspace, managed, home / ".config/flinttrade-shell",
            managed / "src", managed / "tools", managed / "source-build",
            *[managed / name for name in (
                "data", "archive", "sandbox", "flows", "models", "strategies", "journal_screenshots",
                "totp_auth.duckdb", "totp_install_key", "journal.sqlite", "shortcuts.duckdb", "qty_freeze.duckdb",
                "action_center.duckdb", "watchlist.db", "presets.json", "latency_log.duckdb", "traffic_log.duckdb",
            )],
            home / ".cache/com.flinttrade.app", home / ".config/com.flinttrade.app",
            home / ".local/share/com.flinttrade.app", *web_targets, default_lineage,
        ]
        self.targets = list(dict.fromkeys(path for path in candidates if os.path.lexists(path)))
        self.stable = self.workspace.parent / f".{self.workspace.name}.backend-instance.lock"
        stable = self.stable
        self.stable_identity = _identity(stable.lstat())[:3]
        self.custody = custody_path(self.workspace)
        for path in self.targets:
            _no_alias(path)
            if not path.is_relative_to(home) or path == home:
                raise MaintenanceRefused("purge targets must be known descendants of the current home")
            if stable == path or stable.is_relative_to(path) or self.custody.is_relative_to(path):
                raise MaintenanceRefused("purge would remove an ancestor of held exclusion")
            if path != default_lineage and default_lineage.is_relative_to(path):
                raise MaintenanceRefused("purge target overlaps installation lineage")
        self.roots = [path for path in self.targets if not any(
            path != other and path.is_relative_to(other) for other in self.targets
        )]
        self.custody.mkdir(mode=0o700, exist_ok=True)
        self.home = home
        self._parents: dict[Path, tuple[int, int]] = {}
        self._trees = {}
        for path in [*self.roots, self.custody / "anchor"]:
            with self._held_parent(path, capture=True) as parent:
                if path in self.roots:
                    self._trees[path] = _scan(parent._descriptor, path.name)
        self.transaction = uuid4().hex
        self.record_name = "purge-" + self.transaction + ".json"
        self._record = {"phase": "prepared", "installation": str(installation.installation_id),
                        "targets": [str(p) for p in self.targets], "removed": [], "pending": None}
        self._save()

    @contextmanager
    def _held_parent(self, target: Path, *, capture: bool = False) -> Iterator[HeldOwnerDirectory]:
        with ExitStack() as stack:
            directory = stack.enter_context(HeldOwnerDirectory(self.home, require_hardened=False))
            paths = [self.home]
            for part in target.parent.relative_to(self.home).parts:
                paths.append(paths[-1] / part)
            for index, path in enumerate(paths):
                if index:
                    directory = stack.enter_context(HeldOwnerDirectory(
                        path, require_hardened=path == self.custody, _parent=directory,
                    ))
                info = directory.revalidate()
                identity = info.st_dev, info.st_ino
                if capture:
                    previous = self._parents.setdefault(path, identity)
                else:
                    previous = self._parents[path]
                if previous != identity:
                    raise MaintenanceRefused("purge ancestor identity changed")
            yield directory

    def _save(self) -> None:
        with self._held_parent(self.custody / self.record_name) as directory:
            directory.write_text(self.record_name, json.dumps(self._record, sort_keys=True))

    def receipt(self) -> dict:
        """Read back the durable result, including incomplete and retry state."""
        with self._held_parent(self.custody / self.record_name) as directory:
            return json.loads(directory.read_text(self.record_name))

    def _assert_stable(self) -> None:
        info = self.stable.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid()
                or _identity(info)[:3] != self.stable_identity):
            raise MaintenanceRefused("stable workspace exclusion inode changed; pending bytes retained")

    def execute(self) -> None:
        """Execute only while the caller retains the authorised continuous lease."""
        self.installation.assert_mutation_ready()
        try:
            self._assert_stable()
            # Validate the COMPLETE set; never silently drop an unsafe target.
            for path, tree in self._trees.items():
                _no_alias(path)
                with self._held_parent(path) as parent:
                    if _scan(parent._descriptor, path.name) != tree:
                        raise MaintenanceRefused("purge plan changed before execution")
            for index, path in enumerate(self.roots):
                if path == self.installation.root:
                    self.installation.assert_mutation_ready()
                    if any(os.path.lexists(other) for other in self.roots if other != path):
                        raise MaintenanceRefused("earlier data remains; installation lineage retained")
                _no_alias(path)
                with self._held_parent(path) as parent, \
                        self._held_parent(self.custody / self.record_name) as quarantine:
                    tree = self._trees[path]
                    if _scan(parent._descriptor, path.name) != tree:
                        raise MaintenanceRefused("purge target changed before quarantine")
                    name = f"{self.transaction}-{index}"
                    self._record.update(phase="quarantining", pending={"source": str(path), "member": name})
                    self._save()
                    _rename(parent._descriptor, path.name, quarantine._descriptor, name)
                    self._assert_stable()
                    if _scan(quarantine._descriptor, name) != tree:
                        raise MaintenanceRefused("purge target swapped; quarantined bytes retained")
                    self._record["phase"] = "deleting"
                    self._save()
                    _remove(quarantine._descriptor, name, tree, guard=self._assert_stable)
                    if os.path.lexists(path) or quarantine.exists(name):
                        raise MaintenanceRefused("purge absence could not be proved")
                    self._record["removed"].append(str(path))
                    self._record.update(phase="partial", pending=None)
                    self._save()
            if any(os.path.lexists(path) for path in self.targets):
                raise MaintenanceRefused("complete purge absence could not be proved")
            self._record["phase"] = "complete"
            self._save()
        except BaseException:
            self._record["phase"] = "retry_required"
            self._save()
            raise
