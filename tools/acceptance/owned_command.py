"""Linux command custody, independent of process groups and session changes.

Each invocation starts a fresh, single-purpose child subreaper *before* spawning
its command. Kernel adoption is the ownership authority: only that command and
its descendants can become this owner's children. The caller is never made a
subreaper. No process-name search, host census, or saved PID grants authority.

On command exit, timeout or controller EOF, kill and reap direct children, then
repeat for newly adopted generations until waitpid proves ECHILD. pidfds bind
signals to the observed generation; unreaped direct children cannot be reused.
Cleanup has a separate five-second ceiling, never extra command execution time.
The caller's absolute deadline includes owner startup. Unsupported kernels fail
before spawning the command. An unkillable child or killed owner is a failure,
not successful cleanup; the outer isolation remains the final containment layer.
"""

from __future__ import annotations

import ctypes
import json
import os
import select
import signal
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import IO, Literal, TypedDict

CLEANUP_SECONDS = 5.0

type JSONValue = None | bool | int | float | str | list[JSONValue] | dict[str, JSONValue]


class CommandRecord(TypedDict, total=False):
    """Mutable command receipt populated before return or exception propagation.

    Attributes:
        name: Caller-assigned command label, if present.
        argv: Native command arguments, if present.
        exit: Observed native status, including negative signals; None if unknown.
        outcome: Executor outcome, independent of the native status.
        timeout_seconds: Original execution budget, never cleanup time.
        elapsed_seconds: Total observed invocation duration.
        ownership: Actual generation-bound owner receipt; absent when unavailable.
        exception: Exception recorded by the public runner after propagation.
    """

    name: str
    argv: list[str]
    exit: int | None
    outcome: Literal["exception", "owner_error", "timeout", "cancelled", "exited"]
    timeout_seconds: float
    elapsed_seconds: float
    ownership: dict[str, JSONValue]
    exception: dict[str, str]


class OwnershipError(RuntimeError):
    """The owner could not establish or complete kernel custody."""


def _identity(pid):
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return {"pid": pid, "ppid": int(fields[1]), "pgid": int(fields[2]), "sid": int(fields[3]), "start": fields[19]}


def _claim(pid, expected=None):
    """Refuse foreign or stale generations, including after pidfd_open."""
    before = _identity(pid)
    if before["ppid"] != os.getpid() or (
        expected is not None and (before["pid"], before["start"]) != (expected["pid"], expected["start"])
    ):
        raise OwnershipError("Refusing foreign or stale child identity")
    fd = os.pidfd_open(pid)
    try:
        after = _identity(pid)
        if after["ppid"] != os.getpid() or after["start"] != before["start"]:
            raise OwnershipError("Child generation changed during claim")
        return fd, before
    except BaseException:
        os.close(fd)
        raise


def _write(path, receipt):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(receipt, indent=2) + "\n")
    temporary.replace(path)


def _worker(control):
    payload = b""
    while b"\n" not in payload:
        chunk = control.recv(65536)
        if not chunk:
            return 1  # Controller disappeared before there was a command.
        payload += chunk
    request = json.loads(payload)
    path = Path(request["receipt_path"])
    receipt = {
        "generation": request["generation"],
        "owner": _identity(os.getpid()),
        "controller_fd": control.fileno(),
        "deadline_monotonic": request["deadline"],
        "timeout_seconds": request["timeout"],
        "outcome": "owner_error",
        "exit": None,
        "children": [],
        "reaped": [],
        "signals": [],
        "cleanup_complete": False,
        "cleanup_budget_seconds": CLEANUP_SECONDS,
        "cleanup_time_is_execution_extension": False,
    }
    child = None
    identities = {}
    cancelled = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda number, frame: cancelled.append(number))
    try:
        if sys.platform != "linux" or not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
            raise OwnershipError("Linux subreaper and pidfds required")
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
            raise OSError(ctypes.get_errno(), "PR_SET_CHILD_SUBREAPER")
        configured = ctypes.c_int()
        if libc.prctl(37, ctypes.byref(configured), 0, 0, 0) != 0 or configured.value != 1:
            raise OwnershipError("Subreaper configuration was not retained")
        # Probe required kernel functionality before creating the command.
        probe = os.pidfd_open(os.getpid())
        os.close(probe)
        if time.monotonic() >= request["deadline"]:
            receipt["outcome"] = "timeout"
        else:
            child = subprocess.Popen(
                request["argv"], cwd=request["cwd"], env=request["env"], close_fds=True, start_new_session=True
            )
            root = _identity(child.pid)
            identities[child.pid] = root
            receipt["root"] = root
            receipt["children"].append(root)
            _write(path, receipt)
            poller = select.poll()
            poller.register(control, select.POLLIN)
            while True:
                code = child.poll()
                if code is not None:
                    receipt["exit"] = code
                    receipt["outcome"] = "exited"
                    receipt["reaped"].append({**root, "exit": code})
                    break
                if cancelled:
                    receipt["outcome"] = "cancelled"
                    receipt["owner_signal"] = cancelled[0]
                    break
                remaining = request["deadline"] - time.monotonic()
                if remaining <= 0:
                    receipt["outcome"] = "timeout"
                    break
                if poller.poll(min(20, remaining * 1000)):
                    reason = control.recv(1024)
                    receipt["outcome"] = "cancelled"
                    receipt["cancellation"] = reason.decode(errors="replace") if reason else "controller_eof"
                    break
    except BaseException as exc:
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        cleanup_start = time.monotonic()
        receipt["execution_seconds"] = cleanup_start - request["started"]
        deadline = cleanup_start + CLEANUP_SECONDS
        receipt["cleanup_started_monotonic"] = cleanup_start
        receipt["cleanup_deadline_monotonic"] = deadline
        try:
            while True:
                # Only kernel-declared children of this single-purpose owner.
                children = Path(f"/proc/self/task/{os.getpid()}/children").read_text().split()
                for value in children:
                    pid = int(value)
                    try:
                        fd, row = _claim(pid, identities.get(pid))
                    except ProcessLookupError:
                        continue
                    try:
                        if pid not in identities:
                            identities[pid] = row
                            receipt["children"].append(row)
                        signal.pidfd_send_signal(fd, signal.SIGKILL)
                        receipt["signals"].append({**row, "signal": int(signal.SIGKILL)})
                    finally:
                        os.close(fd)
                while True:
                    try:
                        pid, status = os.waitpid(-1, os.WNOHANG)
                    except ChildProcessError:
                        receipt["cleanup_complete"] = True
                        break
                    if pid == 0:
                        break
                    code = os.waitstatus_to_exitcode(status)
                    receipt["reaped"].append({**identities.get(pid, {"pid": pid}), "exit": code})
                    if child is not None and pid == child.pid:
                        child.returncode = code
                        receipt["exit"] = code
                if receipt["cleanup_complete"]:
                    break
                if time.monotonic() >= deadline:
                    raise OwnershipError("Owned children did not reap within cleanup ceiling")
                time.sleep(0.005)
        except BaseException as exc:
            receipt["cleanup_error"] = {"type": type(exc).__name__, "message": str(exc)}
        receipt["cleanup_seconds"] = time.monotonic() - cleanup_start
        receipt["total_seconds"] = time.monotonic() - request["started"]
        _write(path, receipt)
    return 0 if receipt["cleanup_complete"] and "error" not in receipt else 1


def run_owned(
    argv: list[str],
    *,
    cwd: str | os.PathLike[str],
    env: dict[str, str],
    stdout: IO[str] | IO[bytes] | int | None,
    timeout: float,
    receipt_path: Path,
    record: CommandRecord,
) -> int:
    """Run a command in dedicated custody and preserve its native status.

    Args:
        argv: Exact native executable and arguments.
        cwd: Native command working directory.
        env: Complete native environment; no ambient fallback is added.
        stdout: Inherited output handle; stderr shares it.
        timeout: Execution budget in seconds, including owner startup.
        receipt_path: Atomic owner-receipt path in caller-owned writable storage.
        record: Mutable command record updated on success and failure. Missing
            ownership remains absent and unknown native exit remains None.

    Returns:
        The observed native exit code, including nonzero or negative signal
        codes, only after complete cleanup and an ordinary execution outcome.

    Raises:
        subprocess.TimeoutExpired: Execution or request delivery timed out.
        OwnershipError: Custody/receipt is missing, stale, incomplete or failed.
        BaseException: Caller interruption or launch failure, after bounded
            cleanup waiting. The original exception is not made successful.

    Cleanup never extends execution. Request delivery and all owner waits share
    the original absolute delivery ceiling. Closing the channel cancels without
    a write that could block behind an incomplete request. The atomic ownership
    receipt survives controller death, but is never fabricated when unavailable.
    """
    started = time.monotonic()
    generation = uuid.uuid4().hex
    request = {
        "argv": argv,
        "cwd": str(cwd),
        "env": env,
        "timeout": timeout,
        "started": started,
        "deadline": started + timeout,
        "receipt_path": str(receipt_path),
        "generation": generation,
    }
    parent, child_control = socket.socketpair()
    owner = None
    receipt = None
    failure = None
    delivery_deadline = request["deadline"] + CLEANUP_SECONDS + 1
    try:
        owner = subprocess.Popen(
            [sys.executable, "-I", "-S", str(Path(__file__).resolve()), str(child_control.fileno())],
            pass_fds=(child_control.fileno(),),
            stdout=stdout,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        child_control.close()
        # Delivery and waiting share one absolute ceiling. The owner still
        # checks the earlier execution deadline before spawning native work.
        payload = json.dumps(request).encode() + b"\n"
        parent.settimeout(max(0, delivery_deadline - time.monotonic()))
        parent.sendall(payload)
        owner.wait(timeout=max(0, delivery_deadline - time.monotonic()))
    except BaseException as exc:
        failure = subprocess.TimeoutExpired(argv, timeout) if isinstance(exc, TimeoutError) else exc
        # Cancellation is EOF, not another potentially blocking write into a
        # full request socket. Never refresh either the execution or delivery
        # deadline; early cancellation gets at most the existing cleanup bound.
        delivery_deadline = min(delivery_deadline, time.monotonic() + CLEANUP_SECONDS + 1)
    finally:
        child_control.close()
        parent.close()  # EOF is the cancellation path, including caller death.
        if owner is not None and owner.poll() is None:
            try:
                owner.wait(timeout=max(0, delivery_deadline - time.monotonic()))
            except BaseException as exc:
                if failure is None:
                    failure = exc
        record.update(
            exit=None, outcome="exception", timeout_seconds=timeout, elapsed_seconds=time.monotonic() - started
        )
        if isinstance(failure, subprocess.TimeoutExpired):
            record["outcome"] = "timeout"
        elif isinstance(failure, KeyboardInterrupt):
            record["outcome"] = "cancelled"
        try:
            receipt = json.loads(Path(receipt_path).read_text())
            if receipt.get("generation") != generation:
                raise OwnershipError("Stale ownership receipt")
            record.update(
                exit=receipt["exit"],
                outcome=receipt["outcome"],
                ownership=receipt,
                timeout_seconds=timeout,
                elapsed_seconds=time.monotonic() - started,
            )
        except (OSError, ValueError) as exc:
            if failure is None:
                failure = OwnershipError("Missing valid owned cleanup receipt: " + str(exc))
    if failure is not None:
        raise failure
    if owner is None or receipt is None or owner.returncode != 0 or not receipt["cleanup_complete"]:
        raise OwnershipError("Command ownership failed; see ownership receipt")
    if receipt["outcome"] == "timeout":
        raise subprocess.TimeoutExpired(argv, timeout)
    if receipt["outcome"] != "exited":
        raise OwnershipError("Command cancelled; see ownership receipt")
    return receipt["exit"]


if __name__ == "__main__":
    with socket.socket(fileno=int(sys.argv[1])) as channel:
        raise SystemExit(_worker(channel))
