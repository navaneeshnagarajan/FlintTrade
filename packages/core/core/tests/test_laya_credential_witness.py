"""Credential-bound qualification without an unkeyed password fingerprint.

Uses the existing synthetic checkpoint, sterile child and inert HTTP fixture.
These tests do not establish model quality or permission for funded Live use.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from packages.core.core.tests.test_laya_qualification_owner import sidecar as sidecar
from packages.core.core.tests.test_native_workflow_v2 import MountedDesk
from packages.core.core.tests.test_native_workflow_v2 import mounted_desk as mounted_desk

pytestmark = pytest.mark.integration


def test_credential_witness_key_is_private_per_runtime_entropy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each constructor requests a new private key without creating storage.

    Args:
        tmp_path: Disposable workspace root supplied by pytest.
        monkeypatch: Scoped replacement of the CSPRNG call for exact accounting.
    """
    from flinttrade_core import laya_runtime

    keys = iter((b"a" * 32, b"b" * 32))
    sizes: list[int] = []

    def entropy(size: int) -> bytes:
        sizes.append(size)
        return next(keys)

    monkeypatch.setattr(laya_runtime, "secrets", SimpleNamespace(token_bytes=entropy))
    first = laya_runtime.LayaRuntime(tmp_path / "first", watch=False)
    second = laya_runtime.LayaRuntime(tmp_path / "second", watch=False)
    assert sizes == [32, 32]
    assert first._credential_witness_key == b"a" * 32
    assert second._credential_witness_key == b"b" * 32
    assert not first.runtime_root.exists() and not second.runtime_root.exists()


def test_qualification_identity_keys_even_a_short_credential(
    sidecar: tuple[Any, list[str]], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hold every other field fixed to distinguish HMAC from a raw key hash.

    Args:
        sidecar: Real runtime lifecycle with synthetic bytes and inert transport.
        monkeypatch: Scoped deterministic private key used by the expected digest.
    """
    from flinttrade_engine.laya import process_laya

    runtime, _calls = sidecar
    gate = process_laya()
    runtime._remember_key("short-test-key")
    monkeypatch.setattr(runtime, "_credential_witness_key", b"a" * 32)
    check = runtime.ensure_artifact_check()
    credential = hmac.new(b"a" * 32, b"short-test-key", hashlib.sha256).hexdigest()
    value = [id(runtime), id(gate._decision_client), runtime._generation, asdict(check),
             runtime.base_url, runtime._device, credential, runtime._watched_signature()]
    expected = hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()
    actual = runtime.qualification_identity(gate)
    assert actual == expected
    assert runtime.qualification_identity(gate) == actual
    monkeypatch.setattr(runtime, "_credential_witness_key", b"b" * 32)
    assert runtime.qualification_identity(gate) != actual


def test_credential_refresh_alone_retires_qualification(
    mounted_desk: MountedDesk, sidecar: tuple[Any, list[str]],
) -> None:
    """A changed credential invalidates evidence without relying on file contents.

    Args:
        mounted_desk: Existing normal-factory native workflow fixture.
        sidecar: Real runtime lifecycle with synthetic bytes and inert transport.
    """
    from flinttrade_engine.laya import DecisionStatus, process_laya

    runtime, calls = sidecar
    gate = process_laya()
    owner = mounted_desk.app.config["LAYA_QUALIFICATION_OWNER"]
    owner.configure(cases=(("allow", "BUY", "Reviewed limit", "allow"),
                           ("deny", "BUY", "revenge", "deny")), max_age_seconds=10.0)
    assert owner.qualify()["qualified"] is True
    captured = owner.capture()
    before = runtime.qualification_identity(gate)
    signature = runtime._watched_signature()
    client = gate._decision_client
    count = len(calls)
    runtime._remember_key(runtime._api_key)
    assert runtime.qualification_identity(gate) == before and owner.qualifies()
    # Exercise the actual client-refresh callback without a file/client change.
    runtime._remember_key("changed-short-test-key")
    assert runtime._watched_signature() == signature and gate._decision_client is client
    assert runtime.qualification_identity(gate) != before
    assert not owner.qualifies()
    with pytest.raises(ValueError, match="retired"):
        owner.revalidate(captured)
    assert gate.effective_status("live") is DecisionStatus.DOWN
    assert len(calls) == count


def test_attach_after_start_keeps_low_entropy_key_in_keyed_witness(
    mounted_desk: MountedDesk, sidecar: tuple[Any, list[str]], tmp_path: Path,
) -> None:
    """An attached key can reach qualification while the owned child is retained.

    Args:
        mounted_desk: Existing normal-factory native workflow fixture.
        sidecar: Real runtime lifecycle with synthetic bytes and inert transport.
        tmp_path: Disposable key-file location supplied by pytest.
    """
    from flinttrade_engine.laya import process_laya

    runtime, _calls = sidecar
    gate = process_laya()
    owner = mounted_desk.app.config["LAYA_QUALIFICATION_OWNER"]
    owner.configure(cases=(("allow", "BUY", "Reviewed limit", "allow"),
                           ("deny", "BUY", "revenge", "deny")), max_age_seconds=10.0)
    assert owner.qualify()["qualified"] is True
    captured = owner.capture()
    process = runtime._process
    secret = runtime._credential_witness_key
    key_path = tmp_path / "attached-test-key"
    key_path.write_text("short-test-key", encoding="utf-8")
    runtime.attach(key_path)
    assert runtime._process is process and process.poll() is None
    assert runtime._attached and runtime._start_token == ""
    assert runtime._credential_witness_key == secret
    assert runtime._api_key == "short-test-key"
    assert not owner.qualifies()
    with pytest.raises(ValueError, match="retired"):
        owner.revalidate(captured)
    identity = runtime.qualification_identity(gate)
    assert runtime.qualification_identity(gate) == identity
    assert owner.qualify()["qualified"] is True
    # Rotating the attached file retires the new binding as well.
    key_path.write_text("other-test-key", encoding="utf-8")
    assert runtime._sync_watched_key()
    assert runtime.qualification_identity(gate) != identity
    assert not owner.qualifies()


def test_qualification_report_and_runtime_files_exclude_private_witness_key(
    mounted_desk: MountedDesk, sidecar: tuple[Any, list[str]], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Returned reports and existing records never serialise the private HMAC key.

    Args:
        mounted_desk: Existing normal-factory native workflow fixture.
        sidecar: Real runtime lifecycle with synthetic bytes and inert transport.
        monkeypatch: Scoped recognisable sentinel key for disclosure assertions.
    """
    from flinttrade_engine.laya import process_laya

    runtime, _calls = sidecar
    secret = b"private-witness-key-sentinel-0000"
    monkeypatch.setattr(runtime, "_credential_witness_key", secret)
    owner = mounted_desk.app.config["LAYA_QUALIFICATION_OWNER"]
    owner.configure(cases=(("allow", "BUY", "Reviewed limit", "allow"),
                           ("deny", "BUY", "revenge", "deny")), max_age_seconds=10.0)
    report = owner.qualify()
    assert report["qualified"] is True
    assert report["runtime_revision"] == runtime.qualification_identity(process_laya())
    assert owner.qualifies()
    public = json.dumps([report, runtime.status()], sort_keys=True).encode()
    stored = [path.read_bytes() for path in runtime.runtime_root.rglob("*") if path.is_file()]
    for payload in [public, *stored]:
        assert secret not in payload and secret.hex().encode() not in payload


def test_stop_and_restart_preserve_key_scope_but_retire_runtime_identity(
    mounted_desk: MountedDesk, sidecar: tuple[Any, list[str]],
) -> None:
    """Private key lifetime is per object; a stopped or restarted run still refuses.

    Args:
        mounted_desk: Existing normal-factory native workflow fixture.
        sidecar: Real runtime lifecycle with synthetic bytes and inert transport.
    """
    from flinttrade_core.laya_runtime import LayaRuntimeError
    from flinttrade_engine.laya import DecisionStatus, process_laya

    runtime, _calls = sidecar
    gate = process_laya()
    owner = mounted_desk.app.config["LAYA_QUALIFICATION_OWNER"]
    owner.configure(cases=(("allow", "BUY", "Reviewed limit", "allow"),
                           ("deny", "BUY", "revenge", "deny")), max_age_seconds=10.0)
    assert owner.qualify()["qualified"] is True
    before = runtime.qualification_identity(gate)
    secret = runtime._credential_witness_key
    runtime.stop()
    with pytest.raises(LayaRuntimeError, match="identity unavailable"):
        runtime.qualification_identity(gate)
    assert not owner.qualifies()
    runtime.start()
    assert runtime._credential_witness_key == secret
    assert runtime.qualification_identity(gate) != before
    assert gate.effective_status("live") is DecisionStatus.DOWN
