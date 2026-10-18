"""Kernel-pinned maintenance ownership; no PID/port signalling or policy grants."""
from __future__ import annotations

import os
import select
import socket
import struct
import sys


class MaintenanceRefused(RuntimeError):
    """No destructive authority; retain data and exact pending cleanup."""


class PeerProcessHandle:
    """Retain the kernel's exact connected Linux peer until exit is observed.

    SO_PEERPIDFD atomically binds the socket peer, unlike reading a PID and
    subsequently calling pidfd_open (which can pin a reused PID). Other kernels
    refuse until their native identity APIs are separately qualified.
    """

    def __init__(self, channel: socket.socket) -> None:
        self.descriptor = -1
        if sys.platform != "linux" or channel.family != socket.AF_UNIX:
            raise MaintenanceRefused("native maintenance peer handles are unsupported on this platform")
        try:
            pid, uid, _gid = struct.unpack("3i", channel.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if uid != os.getuid() or pid <= 0:
                raise MaintenanceRefused("maintenance peer is not the current OS owner")
            self.descriptor = channel.getsockopt(socket.SOL_SOCKET, getattr(socket, "SO_PEERPIDFD", 77))
            os.set_inheritable(self.descriptor, False)
            self.pid = pid
        except OSError as exc:
            self.close()
            raise MaintenanceRefused("kernel cannot pin the exact maintenance peer") from exc

    def __enter__(self) -> PeerProcessHandle:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        """Close only the retained descriptor, never signal its numeric PID."""
        if self.descriptor >= 0:
            os.close(self.descriptor)
            self.descriptor = -1

    def wait_exited(self, timeout: float) -> bool:
        """Observe exit of the pinned process; the process's parent owns reap."""
        if self.descriptor < 0:
            raise MaintenanceRefused("maintenance process handle was closed")
        poller = select.poll()
        poller.register(self.descriptor, select.POLLIN)
        events = poller.poll(max(0, timeout) * 1000)
        return any(event & select.POLLIN for _fd, event in events)


class ExclusionTransfer:
    """Transfer only kernel exclusion after the managed owner has drained.

    This is not permission or a backend proof. The controller must authenticate
    its recipient, decide safe maintenance and obtain actual runtime completion
    before committing. Closing duplicate descriptors never calls LOCK_UN: the
    cooperating receiver must keep the same open descriptions locked throughout.
    """

    def __init__(self, proof: object) -> None:
        from .backend_instance import _PosixBackendFileLease, require_backend_lease_proof

        self.proof = require_backend_lease_proof(proof)
        self.descriptors: list[int] = []
        self.committed = False
        lease = self.proof._lease
        if sys.platform != "linux" or lease is None or lease._exclusion_lease is None:
            raise MaintenanceRefused("native guardian exclusion handoff is not qualified")
        self.leases = (lease._exclusion_lease, lease)
        try:
            for owner in self.leases:
                raw = owner._raw_lease
                if not isinstance(raw, _PosixBackendFileLease) or raw._descriptor is None or not owner._is_live():
                    raise MaintenanceRefused("workspace exclusion custody is unavailable")
                self.descriptors.append(os.dup(raw._descriptor))
        except BaseException:
            self.close()
            raise

    def __enter__(self) -> ExclusionTransfer:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def commit(self) -> None:
        """Retire the original descriptors without unlocking the recipient's lease."""
        from .backend_instance import require_backend_lease_proof

        require_backend_lease_proof(self.proof)
        if self.committed or len(self.descriptors) != 2:
            raise MaintenanceRefused("workspace exclusion transfer already retired")
        for lease in self.leases:
            lease._raw_lease.detach_after_fork()
        self.committed = True

    def close(self) -> None:
        """Close duplicates only; original custody remains unless commit succeeded."""
        while self.descriptors:
            os.close(self.descriptors.pop())
