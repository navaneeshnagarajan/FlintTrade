"""Generation-bound local maintenance on the existing managed runtime owner.

The socket is an OS-owner control channel, not an HTTP trading authority. Its
only decision source is the concrete complete execution/protection census.
Runtime shutdown itself belongs to the normal application lifecycle.
"""
from __future__ import annotations

import array
import json
import os
import socket
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .backend_instance import require_backend_lease_proof
from .installation_state import InstallationState, stable_application_state_root
from .maintenance_custody import ExclusionTransfer, MaintenanceRefused, PeerProcessHandle
from .maintenance_purge import custody_path
from .secure_file import HeldOwnerDirectory


def _send(channel: socket.socket, value: dict) -> None:
    data = json.dumps(value, sort_keys=True, allow_nan=False).encode()
    if channel.send(data) != len(data):
        raise MaintenanceRefused("maintenance channel write incomplete")


def _receive(channel: socket.socket) -> dict:
    data, _ancillary, flags, _address = channel.recvmsg(65536)
    if not data or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
        raise MaintenanceRefused("maintenance channel response incomplete")
    value = json.loads(data)
    if type(value) is not dict:
        raise MaintenanceRefused("maintenance channel response malformed")
    return value


def _socket_path(directory: HeldOwnerDirectory) -> str:
    # The retained namespace also avoids AF_UNIX pathname-length limits.
    return f"/proc/self/fd/{directory._descriptor}/control.sock"


class MaintenanceControl:
    """One exact backend generation; missing policy never becomes idle."""

    def __init__(self, app: Any, workspace: Path, request_shutdown: Callable[[], None]) -> None:
        if sys.platform != "linux":
            raise MaintenanceRefused("native maintenance control is unsupported on this platform")
        self.app = app
        self.proof = require_backend_lease_proof(app.config.get("BACKEND_LEASE_PROOF"))
        self.workspace = Path(workspace).absolute()
        if self.workspace != self.proof.workspace_path:
            raise MaintenanceRefused("maintenance workspace does not match its backend generation")
        self.installation = InstallationState()
        self.request_shutdown = request_shutdown
        self._tracker = app.config.get("RUNTIME_REQUEST_TRACKER")
        self._runtime_complete = threading.Event()
        self._transfer_done = threading.Event()
        self._transfer_error: str | None = None
        self._pending: dict | None = None
        self.identity = {"workspace": str(self.workspace), "installation": str(self.installation.installation_id),
                         "generation": str(self.proof.incarnation), "pid": os.getpid()}
        path = custody_path(self.workspace)
        path.mkdir(mode=0o700, exist_ok=True)
        self.directory = HeldOwnerDirectory(path).__enter__()
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.closed = threading.Event()
        try:
            # Only the current real kernel owner can retire an earlier endpoint.
            if self.directory.exists("control.sock"):
                os.unlink("control.sock", dir_fd=self.directory._descriptor)
            self.listener.bind(_socket_path(self.directory))
            os.chmod(_socket_path(self.directory), 0o600)
            self.listener.listen(1)
            self.listener.settimeout(0.2)
            self.directory.write_text("owner.json", json.dumps(self.identity))
            self.thread = threading.Thread(target=self._serve, name="maintenance-control", daemon=True)
            self.thread.start()
        except BaseException:
            self.listener.close()
            self.directory.__exit__()
            raise

    def _safe_idle(self) -> dict:
        from .execution_sessions import ExecutionSessions
        from .protection_grants import ProtectionServices

        require_backend_lease_proof(self.proof)
        self.installation.assert_mutation_ready()
        sessions = self.app.config.get("EXECUTION_SESSIONS")
        protection = self.app.config.get("PROTECTION_SERVICES")
        if type(sessions) is not ExecutionSessions or type(protection) is not ProtectionServices:
            raise MaintenanceRefused("execution/protection census unavailable; policy unknown")
        if (sessions.app is not self.app or sessions.path != self.workspace / "execution-sessions"
                or protection.app is not self.app or protection.workspace != self.workspace):
            raise MaintenanceRefused("execution/protection owner conflict")
        with sessions.lock:
            census = sessions.maintenance_snapshot()
            from .maintenance_history import MaintenanceHistory

            coverage = MaintenanceHistory(self.installation, self.workspace).reconcile_idle(self.app, census)
            duty = protection.maintenance_snapshot()
            if duty.get("registry_complete") is not True or duty.get("disposal_authorised") is not True:
                raise MaintenanceRefused("protection duties or unknown custody retained")
        return {"execution": census, "coverage": coverage, "protection": duty}

    def _serve(self) -> None:
        while not self.closed.is_set():
            try:
                channel, _ = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with channel:
                channel.settimeout(5)
                try:
                    with PeerProcessHandle(channel):
                        self.directory.revalidate()
                        _send(channel, self.identity)
                        request = _receive(channel)
                        operation, timeout = request.get("operation"), request.get("timeout")
                        if (set(request) != {"identity", "operation", "timeout"}
                                or request["identity"] != self.identity or operation not in {"stop", "purge"}
                                or type(timeout) not in {int, float} or not 0 < timeout <= 300):
                            raise MaintenanceRefused("maintenance operation or exact generation mismatch")
                        self._perform(channel, operation, timeout)
                except Exception as exc:
                    reason = str(exc) if isinstance(exc, MaintenanceRefused) else "maintenance custody unavailable"
                    if self._pending is not None:
                        self._transfer_error = reason
                        self._pending["phase"] = "retry_required"
                        self.directory.write_text("pending.json", json.dumps(self._pending))
                        self._transfer_done.set()
                    try:
                        _send(channel, {"refused": reason})
                    except OSError:
                        pass

    def _perform(self, channel: socket.socket, operation: str, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        # Validate descriptor custody BEFORE disturbing an otherwise usable runtime.
        with ExclusionTransfer(self.proof) as transfer:
            if self._pending is None:
                self._safe_idle()
                if self._tracker is None or self.app.config.get("RUNTIME_REQUEST_TRACKER") is not self._tracker:
                    raise MaintenanceRefused("actual request drain owner unavailable")
                sessions = self.app.config["EXECUTION_SESSIONS"]
                with sessions.lock:
                    self._safe_idle()
                    self._pending = {"identity": self.identity, "operation": operation,
                                     "phase": "admission-closing", "sealed": False}
                    self.directory.write_text("pending.json", json.dumps(self._pending, sort_keys=True))
                    self.app.config["RUNTIME_ACCEPTING_REQUESTS"] = False
                    self._tracker.stop_admitting()
            elif self._pending["operation"] != operation:
                raise MaintenanceRefused("another exact maintenance transaction remains pending")
            self._transfer_done.clear()
            self._transfer_error = None
            if self._pending["sealed"] is not True:
                if not self._tracker.wait_for_idle(max(0, deadline - time.monotonic())):
                    raise MaintenanceRefused("active requests did not drain")
                # Admitted mutations may have completed while admission was closed.
                sessions = self.app.config["EXECUTION_SESSIONS"]
                with sessions.lock:
                    evidence = self._safe_idle()
                self._pending.update(phase="draining", evidence=evidence, sealed=True)
                self.directory.write_text("pending.json", json.dumps(self._pending, sort_keys=True))
                self.request_shutdown()
            if not self._runtime_complete.wait(max(0, deadline - time.monotonic())):
                raise MaintenanceRefused("managed runtime stop timed out; exact recovery retained")
            self.installation.assert_mutation_ready()
            self.directory.revalidate()
            if not self._tracker.wait_for_idle(0):
                raise MaintenanceRefused("request quiescence changed after runtime completion")
            channel.settimeout(max(0.01, deadline - time.monotonic()))
            ready = {"identity": self.identity, "phase": "runtime-drained"}
            payload = json.dumps(ready, sort_keys=True).encode()
            if channel.sendmsg([payload], [(socket.SOL_SOCKET, socket.SCM_RIGHTS,
                                            array.array("i", transfer.descriptors))]) != len(payload):
                raise MaintenanceRefused("exclusion handoff write incomplete")
            if _receive(channel) != {"accepted": self.identity}:
                raise MaintenanceRefused("exclusion handoff not acknowledged by exact recipient")
            transfer.commit()
            self._pending["phase"] = "exclusion-transferred"
            self.directory.write_text("pending.json", json.dumps(self._pending, sort_keys=True))
            _send(channel, {"identity": self.identity, "phase": "committed"})
            self._transfer_done.set()

    def runtime_stopped(self, *, timeout: float) -> None:
        """Only the real lifecycle calls this after ALL managed stop work succeeds.

        Errors propagate to that lifecycle's existing exact recovery owner; never
        release its lease or report shutdown completed after this hook fails.
        """
        if self._pending is None:
            return
        if not self._tracker.wait_for_idle(0):
            raise MaintenanceRefused("actual requests remain in flight")
        self._runtime_complete.set()
        if not self._transfer_done.wait(timeout) or self._transfer_error is not None:
            raise MaintenanceRefused("maintenance handoff remains pending; retain runtime recovery owner")

    def close(self) -> None:
        """Close the endpoint only; never dispose borrowed application owners."""
        self.closed.set()
        self.listener.close()
        self.thread.join(timeout=1)
        self.directory.__exit__()


def install_maintenance_control(app: Any, workspace: Path, *,
                                request_shutdown: Callable[[], None]) -> MaintenanceControl:
    """Bind a real managed shutdown request, not an approval/policy callback."""
    existing = app.extensions.get("flinttrade.maintenance")
    if existing is not None:
        if type(existing) is not MaintenanceControl or existing.workspace != Path(workspace).absolute():
            raise MaintenanceRefused("maintenance controller ownership conflict")
        return existing
    owner = MaintenanceControl(app, workspace, request_shutdown)
    app.extensions["flinttrade.maintenance"] = owner
    return owner


@contextmanager
def stopped_workspace(workspace: Path, *, operation: str = "stop", timeout: float = 60) -> Iterator[InstallationState]:
    """Retain continuous kernel exclusion after actual owner drain and native exit.

    Only this live, pinned control exchange supplies safety authority. Neither
    owner.json nor pending.json is accepted as an offline approval certificate.
    """
    workspace = Path(workspace).absolute()
    root = stable_application_state_root()
    if not (root / "installation_id").exists() or not (root / ".installation-id-binding").exists():
        raise MaintenanceRefused("installation custody unavailable; policy unknown")
    installation = InstallationState(root)
    with HeldOwnerDirectory(custody_path(workspace)) as directory:
        identity = json.loads(directory.read_text("owner.json"))
        if identity.get("workspace") != str(workspace) or identity.get("installation") != str(installation.installation_id):
            raise MaintenanceRefused("exact installation mismatch")
        with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as channel:
            deadline = time.monotonic() + timeout
            # Allow the owner to deliver its bounded failure receipt after its
            # own drain deadline; this does not extend native-exit authority.
            channel.settimeout(timeout + 0.25)
            channel.connect(_socket_path(directory))
            with PeerProcessHandle(channel) as process:
                if process.pid != identity.get("pid") or _receive(channel) != identity:
                    raise MaintenanceRefused("backend generation does not match pinned owner")
                installation.assert_mutation_ready()
                directory.revalidate()
                _send(channel, {"identity": identity, "operation": operation, "timeout": timeout})
                descriptors: list[int] = []
                try:
                    data, ancillary, flags, _address = channel.recvmsg(
                        65536, socket.CMSG_SPACE(8), socket.MSG_CMSG_CLOEXEC,
                    )
                    for level, kind, packed in ancillary:
                        if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                            values = array.array("i")
                            values.frombytes(packed[:len(packed) - len(packed) % values.itemsize])
                            descriptors.extend(values)
                    if not data or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
                        raise MaintenanceRefused("exclusion handoff incomplete")
                    reply = json.loads(data)
                    if type(reply) is not dict:
                        raise MaintenanceRefused("exclusion handoff malformed")
                    if "refused" in reply:
                        raise MaintenanceRefused(str(reply["refused"]))
                    if reply != {"identity": identity, "phase": "runtime-drained"} or len(descriptors) != 2:
                        raise MaintenanceRefused("runtime completion or exclusion custody missing")
                    paths = [workspace.parent / f".{workspace.name}.backend-instance.lock",
                             workspace / "backend_instance.lock"]
                    for descriptor, path in zip(descriptors, paths, strict=True):
                        opened, named = os.fstat(descriptor), path.lstat()
                        if ((opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
                                or opened.st_uid != os.getuid() or opened.st_nlink != 1):
                            raise MaintenanceRefused("workspace exclusion identity changed")
                        # fdinfo reports locks held by this exact open description;
                        # never acquire a new lock and call an intervening gap safe.
                        lines = Path(f"/proc/self/fdinfo/{descriptor}").read_text().splitlines()
                        if not any(line.startswith("lock:") and "FLOCK" in line and "WRITE" in line for line in lines):
                            raise MaintenanceRefused("transferred descriptor is not the kernel exclusion owner")
                    _send(channel, {"accepted": identity})
                    if _receive(channel) != {"identity": identity, "phase": "committed"}:
                        raise MaintenanceRefused("workspace exclusion transfer was not committed")
                    if not process.wait_exited(max(0, deadline - time.monotonic())):
                        raise MaintenanceRefused("exact backend has not exited; pending cleanup retained")
                    installation.assert_mutation_ready()
                    directory.revalidate()
                    directory.write_text("last-stopped.json", json.dumps({"identity": identity, "operation": operation}))
                    yield installation
                    directory.revalidate()
                    pending = json.loads(directory.read_text("pending.json"))
                    if pending.get("identity") != identity or pending.get("phase") != "exclusion-transferred":
                        raise MaintenanceRefused("pending cleanup custody changed")
                    os.unlink("pending.json", dir_fd=directory._descriptor)
                    os.fsync(directory._descriptor)
                finally:
                    while descriptors:
                        os.close(descriptors.pop())


def stop_workspace(workspace: Path, *, timeout: float = 60) -> None:
    """Stop only the explicitly requested generation; never signal a PID or port."""
    with stopped_workspace(workspace, timeout=timeout):
        pass
    print("Backend stopped: managed runtime drained and exact native owner exited; entries are not re-armed.")
