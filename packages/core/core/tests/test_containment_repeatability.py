"""Exact public containment callers under controlled process/FD scheduling."""
from __future__ import annotations

import os
import selectors
from contextlib import suppress

import pytest

from packages.core.core.tests import test_backend_guardian_high_fds as guardian_controls
from packages.core.core.tests import test_broker_account_lifecycle as lifecycle_controls

# Reuse the existing real resource owners rather than introduce a test model.
high_descriptor_owner = guardian_controls.high_descriptor_owner
lifecycle_api = lifecycle_controls.lifecycle_api
owner_factory = lifecycle_controls.owner_factory


@pytest.mark.skipif(not hasattr(os, "fork"), reason="real POSIX inherited proof refusal")
def test_inherited_local_proof_refusal_needs_no_handoff_after_child_exit(tmp_path, monkeypatch):
    """Let the real rejecting child exit before the caller can publish anything."""
    from flinttrade_core import backend_instance as module
    from packages.core.core.tests.test_backend_instance import (
        test_guardian_rejects_substituted_handoff_and_forked_local_proof as original_caller,
    )

    exited_read, exited_write = os.pipe()
    real_fork = os.fork
    real_prepare = module.prepare_backend_lease_handoff
    real_publish = module.BackendLeaseHandoff.publish
    children = []
    public_calls = []
    observed_exits = []

    def prepare(lease):
        public_calls.append("prepare")
        return real_prepare(lease)

    def publish(handoff, child):
        public_calls.append("publish")
        return real_publish(handoff, child)

    def fork_after_child_exit():
        child = real_fork()
        if child == 0:
            os.close(exited_read)
            return child
        children.append(child)
        os.close(exited_write)
        # The child retains this write end until real OS exit. No sleep, fake
        # proof, lowered FD or successful substitute for a public call is used.
        with selectors.DefaultSelector() as readiness:
            readiness.register(exited_read, selectors.EVENT_READ)
            assert readiness.select(5), "rejecting child did not exit"
        assert os.read(exited_read, 1) == b""
        status = os.waitid(os.P_PID, child, os.WEXITED | os.WNOWAIT)
        assert status is not None
        assert status.si_pid == child
        assert status.si_code == os.CLD_EXITED
        assert status.si_status == 0
        observed_exits.append(status.si_status)
        print("CONTAINMENT_CONTROL: rejecting child exited 0 before the parent resumed")
        return child

    monkeypatch.setattr(os, "fork", fork_after_child_exit)
    monkeypatch.setattr(module, "prepare_backend_lease_handoff", prepare)
    monkeypatch.setattr(module.BackendLeaseHandoff, "publish", publish)
    try:
        original_caller(tmp_path, monkeypatch, "inherited_local_proof")
        assert observed_exits == [0]
        assert public_calls == [], "fork-local proof rejection must not depend on a guardian handshake"
    finally:
        for child in children:
            with suppress(ChildProcessError):
                os.waitpid(child, 0)
        os.close(exited_read)
        if not children:
            os.close(exited_write)


@pytest.mark.skipif(os.name != "posix" or not hasattr(os, "fork"), reason="real POSIX high-FD fork refusal")
def test_real_fork_lifecycle_refuses_before_locks_with_high_fds(owner_factory, high_descriptor_owner, monkeypatch):
    """Replay the complete caller while another pipe owner retains FD pressure."""
    from packages.core.core.tests.test_broker_account_lifecycle import (
        test_reconstructed_real_fork_refuses_before_inherited_locks as original_caller,
    )

    real_pipe = os.pipe
    result_descriptors = []

    def pipe():
        read_fd, write_fd = real_pipe()
        result_descriptors.append((read_fd, write_fd))
        assert read_fd >= 1024
        assert write_fd >= 1024
        assert os.fstat(read_fd).st_ino == os.fstat(write_fd).st_ino
        print("CONTAINMENT_CONTROL: lifecycle's real result pipe exceeds the select FD ceiling")
        return read_fd, write_fd

    monkeypatch.setattr(os, "pipe", pipe)
    original_caller(owner_factory)
    assert len(result_descriptors) == 1
    # The reused owner fixture verifies every retained inode and real read/write
    # usability after lifecycle cleanup, then closes only its own duplicates.
    assert len(high_descriptor_owner) >= 2
