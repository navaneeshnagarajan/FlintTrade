"""Real guardian contracts with another owner retaining high FD pressure.

The optional plugin flag replays unchanged original callers under the same
pressure. Ordinary collection always runs the independent public control.
"""
from __future__ import annotations

import os
import selectors
from contextlib import suppress
from pathlib import Path

import pytest


@pytest.fixture
def high_descriptor_owner():
    """Fill only unused FD slots with duplicates of our unrelated pipe."""
    import fcntl
    import resource

    floor = 1024
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    descriptors = []
    try:
        if soft != resource.RLIM_INFINITY and soft < floor + 128:
            resource.setrlimit(resource.RLIMIT_NOFILE, (floor + 128, hard))
        read_fd, write_fd = os.pipe()
        descriptors.extend((read_fd, write_fd))
        # Establish a real high descriptor without replacing any existing FD.
        descriptors.append(fcntl.fcntl(write_fd, fcntl.F_DUPFD, floor))
        while True:
            descriptor = fcntl.fcntl(write_fd, fcntl.F_DUPFD, 3)
            descriptors.append(descriptor)
            if descriptor >= floor:
                break
        identity = os.fstat(read_fd).st_dev, os.fstat(read_fd).st_ino
        yield descriptors
        # Guardian cleanup must not close another resource owner's descriptors.
        assert all((os.fstat(fd).st_dev, os.fstat(fd).st_ino) == identity for fd in descriptors)
        assert os.write(write_fd, b"still-owned") == 11
        assert os.read(read_fd, 11) == b"still-owned"
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        if resource.getrlimit(resource.RLIMIT_NOFILE) != (soft, hard):
            resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))


def pytest_addoption(parser):
    """Enable exact original-node pressure/metadata only for diagnostic replays."""
    parser.addoption("--guardian-high-fds", action="store_true", default=False)
    parser.addoption("--guardian-fd-metadata", default=None)


@pytest.fixture(autouse=True)
def _original_guardian_pressure(request, monkeypatch):
    original_cases = {
        "test_guardian_handoff_binds_child_and_revokes_on_parent_release",
        "test_guardian_rejects_substituted_handoff_and_forked_local_proof",
        "test_live_guardian_handoff_preserves_unrelated_high_descriptor_owner",
    }
    if request.node.originalname not in original_cases or not request.config.getoption(
        "--guardian-high-fds", default=False,
    ):
        yield
        return
    owner = request.getfixturevalue("high_descriptor_owner")
    metadata_directory = request.config.getoption("--guardian-fd-metadata", default=None)
    if metadata_directory is None:
        yield
        return

    import json
    import traceback

    from flinttrade_core import backend_instance as module

    destination = Path(metadata_directory)
    destination.mkdir(parents=True, exist_ok=True)
    children = []
    original_claim = module.BackendLeaseHandoff.claim
    original_prepare = module.prepare_backend_lease_handoff
    original_fork = os.fork

    def record(event, **metadata):
        # Only this test's synthetic exception type/frames and owned kernel FDs.
        target = destination / f"{request.node.name}-{os.getpid()}.jsonl"
        with target.open("a", encoding="utf-8") as output:
            output.write(json.dumps({"event": event, "pid": os.getpid(), **metadata}) + "\n")

    def prepare(lease):
        handoff = original_prepare(lease)
        descriptors = [lease._raw_lease._descriptor, handoff._read_fd, handoff._write_fd]
        assert all(descriptor >= 1024 for descriptor in descriptors)
        record("public-handoff", descriptors=descriptors,
               fifo_inode=os.fstat(handoff._read_fd).st_ino,
               resource_owner_descriptors=len(owner))
        return handoff

    def claim(handoff):
        descriptor = handoff._read_fd
        record("claim-enter", descriptor=descriptor,
               fifo_inode=os.fstat(descriptor).st_ino if descriptor is not None else None)
        try:
            return original_claim(handoff)
        except BaseException as exc:
            record("claim-exception", exception_type=type(exc).__name__,
                   frames=[{"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                           for frame in traceback.extract_tb(exc.__traceback__)],
                   context_type=type(exc.__context__).__name__ if exc.__context__ is not None else None,
                   context_frames=[{"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                                   for frame in traceback.extract_tb(exc.__context__.__traceback__)]
                   if exc.__context__ is not None else [])
            raise

    def fork():
        child = original_fork()
        if child:
            children.append(child)
        return child

    monkeypatch.setattr(module, "prepare_backend_lease_handoff", prepare)
    monkeypatch.setattr(module.BackendLeaseHandoff, "claim", claim)
    monkeypatch.setattr(os, "fork", fork)
    try:
        yield
    finally:
        # Failed original readiness waits still release the guardian in their
        # own finally block. Reap only our observed fork, never unrelated PIDs.
        for child in children:
            with suppress(ChildProcessError):
                waited, status = os.waitpid(child, 0)
                record("owned-child-reaped", child=waited, status=status)


@pytest.mark.skipif(os.name != "posix" or not hasattr(os, "fork"), reason="real POSIX guardian pipe and fork")
@pytest.mark.parametrize("termination", ["release", "revoke"])
def test_live_guardian_handoff_preserves_unrelated_high_descriptor_owner(
    tmp_path, monkeypatch, high_descriptor_owner, termination,
):
    """A genuine high pipe proves live admission, one-shot claim and EOF revoke."""
    from flinttrade_core import backend_instance as module

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    lease = module.acquire_backend_instance_lease()
    local_proof = lease.proof
    with pytest.raises(module.BackendInstanceAlreadyRunning):
        module.acquire_backend_instance_lease()
    handoff = module.prepare_backend_lease_handoff(lease)
    assert lease._raw_lease._descriptor >= 1024
    assert handoff._read_fd >= 1024
    assert handoff._write_fd >= 1024
    result_read, result_write = os.pipe()
    assert result_read >= 1024
    child = os.fork()
    if child == 0:
        os.close(result_read)
        try:
            with pytest.raises(module.BackendLeaseUnavailable):
                module.require_backend_lease_proof(local_proof)
            proof = handoff.claim()
            module.require_backend_lease_proof(proof)
            with pytest.raises(module.BackendLeaseUnavailable):
                handoff.claim()
            os.write(result_write, b"live")
            assert proof.wait_revoked(5), "EOF must revoke without another request"
            with pytest.raises(module.BackendLeaseUnavailable):
                module.require_backend_lease_proof(proof)
            os._exit(0)
        except BaseException:
            os._exit(1)
    os.close(result_write)
    reaped = False
    try:
        handoff.publish(child)
        with selectors.DefaultSelector() as readiness:
            readiness.register(result_read, selectors.EVENT_READ)
            assert readiness.select(5)
        assert os.read(result_read, 4) == b"live"
        if termination == "release":
            lease.release()
        else:
            lease.proof.revoke()
        assert os.waitpid(child, 0)[1] == 0
        reaped = True
    finally:
        lease.release()
        os.close(result_read)
        if not reaped:
            os.waitpid(child, 0)
    successor = module.acquire_backend_instance_lease()
    successor.release()
