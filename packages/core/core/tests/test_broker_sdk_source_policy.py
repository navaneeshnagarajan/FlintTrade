"""Source-policy controls using temporary distributions, never operator files."""

from __future__ import annotations

import hashlib
import json
import sys
from importlib import metadata
from pathlib import Path, PureWindowsPath
from typing import Any

import pytest

from flinttrade_core import broker_sdk_attest as attestation

pytestmark = pytest.mark.unit

_IDENTITIES = {
    "dhanhq": ("dhanhq", "https://github.com/dhan-oss/DhanHQ-py.git"),
    "upstox-python-sdk": ("upstox_client", "https://github.com/upstox/upstox-python.git"),
    "kotakneoapi": ("neo_api_client", "https://github.com/Kotak-Neo/kotak-neo-python.git"),
    "growwapi": ("growwapi", "https://source-unresolved.example/sdk.git"),
}
_ABSENT = object()


def make_source_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    version: str = "3.0.7",
    commit: str = "a" * 40,
) -> tuple[dict[str, Any], Path, Path]:
    """Create real distribution/resource metadata with explicitly synthetic bytes."""
    module, url = _IDENTITIES[name]
    info = tmp_path / f"{name.replace('-', '_')}-{version}.dist-info"
    info.mkdir()
    package = tmp_path / module
    (package / "data").mkdir(parents=True)
    (package / "__init__.py").write_bytes(b"# Synthetic package; no SDK execution.\n")
    (package / "data" / "MiXeD.txt").write_bytes("Resource: नमस्ते\n".encode())
    (info / "METADATA").write_bytes(f"Metadata-Version: 2.3\nName: {name}\nVersion: {version}\n".encode())
    (info / "top_level.txt").write_bytes(f"{module}\n".encode())
    pin = {
        "name": name,
        "version": version,
        "source_kind": "published-rc" if name == "dhanhq" else "git",
        "source_url": url,
        "source_module": module,
        "source_commit": commit,
        "source_tree": "b" * 40,
        "build_wheel_sha256": "c" * 64,
        "build_files": {
            path.relative_to(tmp_path).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in tmp_path.rglob("*") if path.is_file()
        },
    }
    (info / "direct_url.json").write_text(json.dumps({
        "url": url, "vcs_info": {"vcs": "git", "commit_id": commit, "requested_revision": commit},
    }), encoding="utf-8")
    (info / "RECORD").write_text("".join(f"{key},,\n" for key in pin["build_files"]), encoding="utf-8")
    real_distributions = metadata.distributions
    monkeypatch.setattr(attestation.metadata, "distributions", lambda: real_distributions(path=[str(tmp_path)]))
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, module, raising=False)
    return pin, info, package


def write_pin(tmp_path: Path, pin: dict[str, Any]) -> Path:
    """Use the real TOML loader for every representable source-kind control."""
    path = tmp_path / "brokers.lock"
    scalars = "\n".join(f"{key} = {json.dumps(value)}" for key, value in pin.items() if key != "build_files")
    files = "\n".join(f"{json.dumps(key)} = {json.dumps(value)}" for key, value in pin["build_files"].items())
    path.write_text(f"[[broker]]\n{scalars}\n[broker.build_files]\n{files}\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("name", ["upstox-python-sdk", "kotakneoapi", "dhanhq", "growwapi"])
@pytest.mark.parametrize("kind", [_ABSENT, "", None, False, 0, [], {}, 123, "GIT"],
                         ids=["absent", "empty", "null", "false", "zero", "list", "mapping", "integer", "invalid-text"])
def test_normal_attestation_refuses_missing_or_invalid_source_kind(tmp_path, monkeypatch, name, kind):
    pin, _, _ = make_source_install(tmp_path, monkeypatch, name)
    if kind is _ABSENT:
        del pin["source_kind"]
    else:
        pin["source_kind"] = kind
    if kind is None:
        # TOML has no null value. Exercise the same parsed-pin boundary explicitly.
        monkeypatch.setattr(attestation, "load_pins", lambda path=None: [pin])
        lock = None
    else:
        lock = write_pin(tmp_path, pin)
    result = attestation.attest_all(lock)[0]
    assert result.status == attestation.STATUS_PROVENANCE_MISMATCH
    assert attestation.required_failures([result]) == [result]


@pytest.mark.parametrize("name", ["upstox-python-sdk", "kotakneoapi"])
@pytest.mark.parametrize("kind", [_ABSENT, "", "git"], ids=["absent", "empty", "git"])
@pytest.mark.parametrize("change", ["fork", "resource"])
def test_correct_version_wrong_source_never_attests(tmp_path, monkeypatch, name, kind, change):
    pin, info, package = make_source_install(tmp_path, monkeypatch, name)
    if kind is _ABSENT:
        del pin["source_kind"]
    else:
        pin["source_kind"] = kind
    if change == "fork":
        direct = json.loads((info / "direct_url.json").read_bytes())
        direct["url"] = "https://untrusted.example/sdk.git"
        (info / "direct_url.json").write_bytes(json.dumps(direct).encode())
    else:
        (package / "__init__.py").write_bytes(b"# Wrong source, same version and direct URL.\n")
    result = attestation.attest_all(write_pin(tmp_path, pin))[0]
    assert result.status == attestation.STATUS_PROVENANCE_MISMATCH
    assert result.installed_version == pin["version"]


@pytest.mark.parametrize("name", ["upstox-python-sdk", "kotakneoapi", "dhanhq"])
def test_complete_temporary_source_install_attests(tmp_path, monkeypatch, name):
    pin, _, _ = make_source_install(tmp_path, monkeypatch, name)
    assert attestation.attest_all(write_pin(tmp_path, pin))[0].status == attestation.STATUS_OK


def test_explicit_version_resolver_remains_a_test_seam(tmp_path, monkeypatch):
    pin, _, _ = make_source_install(tmp_path, monkeypatch, "upstox-python-sdk")
    del pin["source_kind"]
    calls = []

    def resolve(name):
        calls.append(name)
        return pin["version"]

    assert attestation.attest_all(write_pin(tmp_path, pin), version_resolver=resolve)[0].status == attestation.STATUS_OK
    assert calls == [pin["name"]]


def test_placeholder_and_sdk_free_catalogue_stay_non_blocking(tmp_path):
    lock = tmp_path / "brokers.lock"
    lock.write_text('[[broker]]\nname="upstox-python-sdk"\nversion="PLACEHOLDER"\n', encoding="utf-8")
    assert attestation.attest_all(lock)[0].status == attestation.STATUS_SKIPPED
    assert attestation.sdk_attestation_fields(None)["sdk_attestation"]["status"] == attestation.STATUS_NOT_REQUIRED


class WindowsRelativePath(type(Path())):
    """Real local I/O with Windows relative-name semantics; not a native OS run."""

    def relative_to(self, *args, **kwargs):
        relative = super().relative_to(*args, **kwargs)
        return PureWindowsPath(*relative.parts)


@pytest.mark.parametrize("name", ["upstox-python-sdk", "kotakneoapi", "dhanhq"])
@pytest.mark.parametrize("path_style", ["physical", "windows-relative"])
def test_source_inventory_uses_exact_wheel_keys(tmp_path, monkeypatch, name, path_style):
    pin, _, _ = make_source_install(tmp_path, monkeypatch, name)
    lock = write_pin(tmp_path, pin)
    if path_style == "windows-relative":
        monkeypatch.setattr(attestation, "Path", WindowsRelativePath)
        relative = WindowsRelativePath(tmp_path / pin["source_module"] / "data" / "MiXeD.txt").relative_to(tmp_path)
        assert "\\" in str(relative)
        assert relative.as_posix() == pin["source_module"] + "/data/MiXeD.txt"
    assert attestation.attest_all(lock)[0].status == attestation.STATUS_OK


@pytest.mark.parametrize("path_style", ["physical", "windows-relative"])
@pytest.mark.parametrize("change", ["extra", "missing", "case", "bytes", "symlink", "parent-symlink", "traversal"])
def test_portable_inventory_does_not_weaken_source_refusals(tmp_path, monkeypatch, path_style, change):
    pin, _, package = make_source_install(tmp_path, monkeypatch, "upstox-python-sdk")
    resource = package / "data" / "MiXeD.txt"
    original = resource.read_bytes()
    if change == "extra":
        (package / "unrecorded.txt").write_bytes(b"extra")
    elif change == "missing":
        resource.unlink()
    elif change == "case":
        key = resource.relative_to(tmp_path).as_posix()
        pin["build_files"][key.lower()] = pin["build_files"].pop(key)
    elif change == "bytes":
        resource.write_bytes(original + b"changed")
    elif change in {"symlink", "parent-symlink"}:
        outside = tmp_path.parent / (tmp_path.name + "-outside")
        outside.mkdir()
        (outside / "MiXeD.txt").write_bytes(original)
        resource.unlink()
        if change == "symlink":
            resource.symlink_to(outside / "MiXeD.txt")
        else:
            resource.parent.rmdir()
            resource.parent.symlink_to(outside, target_is_directory=True)
    elif change == "traversal":
        outside = tmp_path.parent / (tmp_path.name + "-outside.txt")
        outside.write_bytes(original)
        pin["build_files"]["../" + outside.name] = hashlib.sha256(original).hexdigest()
    lock = write_pin(tmp_path, pin)
    if path_style == "windows-relative":
        monkeypatch.setattr(attestation, "Path", WindowsRelativePath)
    result = attestation.attest_all(lock)[0]
    assert result.status == attestation.STATUS_PROVENANCE_MISMATCH
    assert attestation.required_failures([result]) == [result]


@pytest.mark.parametrize("installed_version", ["3.0.9", "3.0.7"])
@pytest.mark.parametrize("newlines", ["lf", "crlf", "mixed"])
def test_copied_metadata_preserves_unrelated_bytes(tmp_path, monkeypatch, installed_version, newlines):
    from packages.core.core.tests import test_broker_sdk_attest as original

    source = tmp_path / "source"
    source.mkdir()
    with monkeypatch.context() as setup:
        pin, info, _ = make_source_install(source, setup, "kotakneoapi", version="3.0.9")
    before = b"Metadata-Version: 2.3\nName: kotakneoapi\nVersion: 3.0.9\nSummary: caf\xc3\xa9\n\nKeep: exact\n"
    if newlines == "crlf":
        before = before.replace(b"\n", b"\r\n")
    elif newlines == "mixed":
        before = before.replace(b"Summary:", b"\r\nSummary:", 1)
    (info / "METADATA").write_bytes(before)
    pin["build_files"][(info / "METADATA").relative_to(source).as_posix()] = hashlib.sha256(before).hexdigest()
    selected = metadata.PathDistribution(info)
    real_distribution = metadata.distribution
    monkeypatch.setattr(metadata, "distribution", lambda name: selected if name == "kotakneoapi" else real_distribution(name))
    monkeypatch.setattr(original, "load_pins", lambda: [pin])
    monkeypatch.setattr(attestation, "load_pins", lambda path=None: [pin])
    copied = tmp_path / "copied"
    copied.mkdir()
    target = copied / info.name / "METADATA"
    real_write_text = Path.write_text
    text_writes = []

    def windows_text_write(path, data, encoding=None, errors=None, newline=None):
        if path == target:
            text_writes.append(path)
            # TextIO's Windows default write translation, without changing host OS.
            newline = "\r\n" if newline is None else newline
        return real_write_text(path, data, encoding=encoding, errors=errors, newline=newline)

    monkeypatch.setattr(Path, "write_text", windows_text_write)
    expected = "ok" if installed_version == "3.0.9" else "version_mismatch"
    original.test_current_kotak_runtime_pin_does_not_accept_the_release_distribution(
        copied, monkeypatch, installed_version, expected
    )
    expected_bytes = before.replace(b"Version: 3.0.9", f"Version: {installed_version}".encode("ascii"), 1)
    assert target.read_bytes() == expected_bytes
    assert text_writes == []
    assert (info / "METADATA").read_bytes() == before


def test_copied_record_uses_wheel_keys(tmp_path, monkeypatch):
    import csv
    from packages.core.core.tests import test_broker_sdk_attest as original

    copied = tmp_path / "copied"
    copied.mkdir()
    original.test_current_kotak_runtime_pin_does_not_accept_the_release_distribution(
        WindowsRelativePath(copied), monkeypatch, "3.0.9", "ok"
    )
    record = next(copied.glob("*.dist-info/RECORD"))
    keys = [row[0] for row in csv.reader(record.read_text(encoding="utf-8").splitlines())]
    expected = sorted(path.relative_to(copied).as_posix() for path in copied.rglob("*") if path.is_file() and path != record)
    assert keys == expected
    assert all("\\" not in key for key in keys)
