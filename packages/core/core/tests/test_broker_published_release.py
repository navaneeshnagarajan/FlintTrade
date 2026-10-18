"""Release identity checks on temporary copies of the installed official wheel."""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

import pytest

from flinttrade_core import broker_sdk_attest as attestation

pytestmark = pytest.mark.unit


def write_pin(tmp_path: Path, pin: dict[str, Any]) -> Path:
    path = tmp_path / "brokers.lock"
    lines = ["[[broker]]"]
    for key, value in pin.items():
        if type(value) is not dict:
            lines.append(f"{key} = {json.dumps(value)}")
    for key, value in pin.items():
        if type(value) is dict:
            lines.append(f"[broker.{key}]")
            lines.extend(f"{json.dumps(k)} = {json.dumps(v)}" for k, v in value.items())
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def release_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], Path, Path]:
    pin = copy.deepcopy(next(row for row in attestation.load_pins() if row["name"] == "growwapi"))
    assert pin["source_kind"] == "published-release"
    selected = metadata.distribution("growwapi")
    for relative, digest in pin["build_files"].items():
        source = Path(str(selected.locate_file(relative)))
        assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    info = tmp_path / "growwapi-1.5.0.dist-info"
    # Registry installs need no PEP610 URL; RECORD remains installer bookkeeping.
    (info / "RECORD").write_text("".join(f"{key},,\n" for key in pin["build_files"]), encoding="utf-8")
    real_distributions = metadata.distributions
    monkeypatch.setattr(attestation.metadata, "distributions", lambda: real_distributions(path=[str(tmp_path)]))
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "growwapi", raising=False)
    return pin, info, tmp_path / "growwapi"


def test_exact_official_wheel_registry_install_without_git_attests(tmp_path, release_install):
    pin, info, _ = release_install
    assert not (info / "direct_url.json").exists()
    assert not any(key in pin for key in ("source_url", "source_commit", "source_tree"))
    result = attestation.attest_all(write_pin(tmp_path, pin))[0]
    assert result.installed_version == "1.5.0"
    assert result.status == attestation.STATUS_OK
    assert not attestation.required_failures([result])


@pytest.mark.parametrize("hash_form", ["hashes", "hash", "both"])
def test_exact_wheel_archive_url_is_optional_corroboration(tmp_path, release_install, hash_form):
    pin, info, _ = release_install
    artifact = pin["release_artifact"]
    archive = {}
    if hash_form in {"hashes", "both"}:
        archive["hashes"] = {"sha256": artifact["sha256"]}
    if hash_form in {"hash", "both"}:
        archive["hash"] = "sha256=" + artifact["sha256"]
    (info / "direct_url.json").write_text(json.dumps({"url": artifact["url"], "archive_info": archive}))
    assert attestation.attest_all(write_pin(tmp_path, pin))[0].status == attestation.STATUS_OK


@pytest.mark.parametrize("change", [
    "wrong-url", "credentials", "query", "fragment", "local", "sdist", "missing-hash",
    "wrong-hash", "inconsistent-hashes", "git", "directory", "empty", "null", "list", "duplicate-key",
])
def test_self_asserted_direct_url_never_supplies_release_authority(tmp_path, release_install, change):
    pin, info, _ = release_install
    artifact = pin["release_artifact"]
    direct = {"url": artifact["url"], "archive_info": {"hashes": {"sha256": artifact["sha256"]}}}
    if change == "wrong-url":
        direct["url"] = "https://untrusted.example/" + artifact["filename"]
    elif change == "credentials":
        direct["url"] = direct["url"].replace("https://", "https://user@")
    elif change == "query":
        direct["url"] += "?source=official"
    elif change == "fragment":
        direct["url"] += "#sha256=" + artifact["sha256"]
    elif change == "local":
        direct["url"] = "file:///synthetic/" + artifact["filename"]
    elif change == "sdist":
        direct["url"] = direct["url"].replace(artifact["filename"], "growwapi-1.5.0.tar.gz")
    elif change == "missing-hash":
        direct["archive_info"] = {}
    elif change == "wrong-hash":
        direct["archive_info"]["hashes"]["sha256"] = "0" * 64
    elif change == "inconsistent-hashes":
        direct["archive_info"]["hash"] = "sha256=" + "0" * 64
    elif change == "git":
        direct["vcs_info"] = {"vcs": "git", "commit_id": "a" * 40}
    elif change == "directory":
        direct["dir_info"] = {"editable": True}
    raw = json.dumps(direct)
    if change in {"empty", "null", "list"}:
        raw = {"empty": "", "null": "null", "list": "[]"}[change]
    elif change == "duplicate-key":
        raw = '{"url":"https://untrusted.example/sdk.whl",' + raw[1:]
    (info / "direct_url.json").write_text(raw, encoding="utf-8")
    assert attestation.attest_all(write_pin(tmp_path, pin))[0].status == attestation.STATUS_PROVENANCE_MISMATCH


@pytest.mark.parametrize("change", [
    "changed", "missing", "extra", "case", "metadata-bytes", "wheel-missing", "licence-missing",
    "build-missing", "lock-missing", "metadata-extra", "file-symlink", "package-symlink",
    "directory-symlink", "within-root-link", "dangling-link", "cache-link", "direct-link",
])
def test_physical_release_inventory_refuses_modified_missing_extra_or_linked_resources(
    tmp_path, release_install, change,
):
    pin, info, package = release_install
    lock = write_pin(tmp_path, pin)
    assert attestation.attest_all(lock)[0].status == attestation.STATUS_OK
    resource = package / "README.MD"
    if change == "changed":
        resource.write_bytes(resource.read_bytes() + b"changed")
    elif change == "missing":
        resource.unlink()
    elif change == "extra":
        (package / "unrecorded.json").write_bytes(b"{}")
    elif change == "case":
        resource.rename(package / "README.md")
    elif change == "metadata-bytes":
        p = info / "METADATA"
        p.write_bytes(p.read_bytes() + b"\nChanged metadata\n")
    elif change in {"wheel-missing", "licence-missing", "build-missing", "lock-missing"}:
        {"wheel-missing": info / "WHEEL", "licence-missing": info / "LICENSE",
         "build-missing": package / "pyproject.toml", "lock-missing": package / "poetry.lock"}[change].unlink()
    elif change == "metadata-extra":
        (info / "entry_points.txt").write_bytes(b"[console_scripts]\nforged = growwapi:main\n")
    elif change in {"file-symlink", "direct-link", "within-root-link"}:
        outside = tmp_path.parent / (tmp_path.name + "-resource")
        outside.write_bytes(resource.read_bytes() if change != "direct-link" else b"null")
        if change == "direct-link":
            (info / "direct_url.json").symlink_to(outside)
        else:
            if change == "within-root-link":
                outside = tmp_path / "same-bytes"
                outside.write_bytes(resource.read_bytes())
            resource.unlink()
            resource.symlink_to(outside)
    elif change in {"package-symlink", "directory-symlink"}:
        target = package if change == "package-symlink" else package / "groww"
        outside = tmp_path.parent / (tmp_path.name + "-outside")
        target.rename(outside)
        target.symlink_to(outside, target_is_directory=True)
    elif change == "dangling-link":
        (package / "unrecorded-link").symlink_to(tmp_path / "missing")
    elif change == "cache-link":
        (package / "__pycache__").symlink_to(tmp_path.parent, target_is_directory=True)
    result = attestation.attest_all(lock)[0]
    assert result.status in {attestation.STATUS_PROVENANCE_MISMATCH, attestation.STATUS_CONFLICT}
    assert attestation.required_failures([result]) == [result]


@pytest.mark.parametrize("record", ["missing", "empty", "forged"])
def test_registry_record_is_not_resource_hash_authority(tmp_path, release_install, record):
    pin, info, package = release_install
    path = info / "RECORD"
    if record == "missing":
        path.unlink()
    else:
        path.write_bytes(b"" if record == "empty" else b"unrelated.py,sha256=forged,1\n")
    lock = write_pin(tmp_path, pin)
    assert attestation.attest_all(lock)[0].status == attestation.STATUS_OK
    resource = package / "groww" / "client.py"
    resource.write_bytes(resource.read_bytes() + b"\n# forged installed bytes\n")
    # Even a self-consistent installed RECORD cannot re-authorise changed bytes.
    path.write_text(f"growwapi/groww/client.py,sha256={hashlib.sha256(resource.read_bytes()).hexdigest()},1\n")
    assert attestation.attest_all(lock)[0].status == attestation.STATUS_PROVENANCE_MISMATCH


@pytest.mark.parametrize("ownership", ["top-level", "record", "duplicate-distribution"])
def test_conflicting_import_owners_refuse_release(tmp_path, release_install, ownership):
    pin, _, _ = release_install
    other = tmp_path / "another-1.0.dist-info"
    other.mkdir()
    name = "growwapi" if ownership == "duplicate-distribution" else "another"
    (other / "METADATA").write_text(f"Metadata-Version: 2.3\nName: {name}\nVersion: 1.5.0\n")
    if ownership == "top-level":
        (other / "top_level.txt").write_text("growwapi\n")
    elif ownership == "record":
        (other / "RECORD").write_text("growwapi/__init__.py,,\n")
    assert attestation.attest_all(write_pin(tmp_path, pin))[0].status == attestation.STATUS_CONFLICT


def test_import_shadow_refuses_release(tmp_path, release_install, monkeypatch):
    pin, _, _ = release_install
    shadow = tmp_path / "shadow"
    package = shadow / "growwapi"
    package.mkdir(parents=True)
    (package / "__init__.py").write_bytes(b"# Synthetic shadow.\n")
    monkeypatch.syspath_prepend(str(shadow))
    assert attestation.attest_all(write_pin(tmp_path, pin))[0].status == attestation.STATUS_CONFLICT


@pytest.mark.parametrize("key, value", [
    ("source_kind", ""), ("source_kind", "git"), ("source_kind", "published-rc"),
    ("source_kind", None), ("source_kind", []), ("source_kind", {}), ("source_kind", False),
    ("source_kind", 0), ("source_kind", "PUBLISHED-RELEASE"), ("source_module", "other"),
    ("name", "groww-sdk"), ("version", "1.5.1"), ("sha256", "0" * 64),
    ("build_wheel_sha256", "0" * 64), ("source_url", "https://github.com/Groww-OSS/trading-api.git"),
    ("source_commit", "c234f28a74a3c4a5b0b46b1779f13062a5267f21"), ("source_tree", "b" * 40),
    ("source_commit", None), ("source_tree", ""),
])
def test_release_pin_cannot_invent_git_or_relabel_identity(tmp_path, release_install, monkeypatch, key, value):
    pin, _, _ = release_install
    pin[key] = value
    if value is None:
        # TOML cannot express null; retain the same parsed-pin boundary explicitly.
        monkeypatch.setattr(attestation, "load_pins", lambda path=None: [pin])
        lock = None
    else:
        lock = write_pin(tmp_path, pin)
    result = attestation.attest_all(lock)[0]
    assert result.status in {attestation.STATUS_PROVENANCE_MISMATCH, attestation.STATUS_MISMATCH}
    assert attestation.required_failures([result]) == [result]


@pytest.mark.parametrize("key", ["source_kind", "source_module", "release_artifact", "sha256", "build_wheel_sha256", "build_files"])
def test_incomplete_release_pin_refuses(tmp_path, release_install, key):
    pin, _, _ = release_install
    del pin[key]
    assert attestation.attest_all(write_pin(tmp_path, pin))[0].status == attestation.STATUS_PROVENANCE_MISMATCH


@pytest.mark.parametrize("change", ["missing-url", "missing-name", "missing-hash", "wrong-url", "wrong-name", "wrong-hash", "empty", "null", "list", "extra"])
def test_release_artifact_record_is_exact_not_merely_well_formed(tmp_path, release_install, monkeypatch, change):
    pin, _, _ = release_install
    artifact = pin["release_artifact"]
    if change.startswith("missing-"):
        del artifact[{"missing-url": "url", "missing-name": "filename", "missing-hash": "sha256"}[change]]
    elif change == "wrong-url":
        artifact["url"] = "https://untrusted.example/" + artifact["filename"]
    elif change == "wrong-name":
        artifact["filename"] = "growwapi-1.5.0.tar.gz"
    elif change == "wrong-hash":
        artifact["sha256"] = "0" * 64
    elif change == "extra":
        artifact["approved"] = True
    else:
        pin["release_artifact"] = {"empty": {}, "null": None, "list": []}[change]
    if change == "null":
        monkeypatch.setattr(attestation, "load_pins", lambda path=None: [pin])
        lock = None
    else:
        lock = write_pin(tmp_path, pin)
    assert attestation.attest_all(lock)[0].status == attestation.STATUS_PROVENANCE_MISMATCH


@pytest.mark.parametrize("change", ["rehashed", "missing-build-metadata", "case", "traversal", "backslash", "empty", "null"])
def test_inventory_cannot_rebind_the_independent_wheel_seal(tmp_path, release_install, monkeypatch, change):
    pin, _, package = release_install
    if change == "rehashed":
        resource = package / "groww" / "client.py"
        resource.write_bytes(resource.read_bytes() + b"# self-asserted release\n")
        pin["build_files"]["growwapi/groww/client.py"] = hashlib.sha256(resource.read_bytes()).hexdigest()
    elif change == "missing-build-metadata":
        del pin["build_files"]["growwapi-1.5.0.dist-info/WHEEL"]
    elif change in {"case", "traversal", "backslash"}:
        key = {"case": "growwapi/readme.md", "traversal": "../README.MD", "backslash": "growwapi\\README.MD"}[change]
        pin["build_files"][key] = pin["build_files"].pop("growwapi/README.MD")
    else:
        pin["build_files"] = {} if change == "empty" else None
    if change == "null":
        monkeypatch.setattr(attestation, "load_pins", lambda path=None: [pin])
        lock = None
    else:
        lock = write_pin(tmp_path, pin)
    assert attestation.attest_all(lock)[0].status == attestation.STATUS_PROVENANCE_MISMATCH


@pytest.mark.parametrize("name", ["dhanhq", "upstox-python-sdk", "kotakneoapi"])
def test_other_brokers_cannot_inherit_published_release_exception(tmp_path, monkeypatch, name):
    from packages.core.core.tests.test_broker_sdk_source_policy import make_source_install

    pin, _, _ = make_source_install(tmp_path, monkeypatch, name)
    assert attestation.attest_all(write_pin(tmp_path, pin))[0].status == attestation.STATUS_OK
    pin["source_kind"] = "published-release"
    pin["release_artifact"] = dict(attestation._GROWW_RELEASE_ARTIFACT)
    assert attestation.attest_all(write_pin(tmp_path, pin))[0].status == attestation.STATUS_PROVENANCE_MISMATCH


def test_release_kind_survives_existing_attestation_consumers(tmp_path, release_install):
    from flinttrade_core import native_account_routes
    from flinttrade_gateway import capabilities_routes
    from flinttrade_gateway.adapter import BROKER_CATALOG

    pin, _, _ = release_install
    lock = write_pin(tmp_path, pin)
    result = attestation.attest_all(lock)[0]
    assert result.to_dict()["source_kind"] == "published-release"
    rows = attestation.attestations_by_pin(lock)
    for fields in (
        attestation.sdk_attestation_fields("growwapi", attestations=rows),
        capabilities_routes._catalog_sdk_fields("groww"),
        native_account_routes._native_sdk_fields(BROKER_CATALOG["groww"]),
    ):
        row = fields["sdk_attestation"]
        assert row["status"] == attestation.STATUS_OK
        assert row["source_kind"] == "published-release"
        assert not any(key in row for key in ("source_commit", "source_tree", "source_url", "build_files"))


def test_explicit_resolver_is_version_only_not_release_provenance(tmp_path, release_install):
    pin, _, _ = release_install
    del pin["release_artifact"]
    lock = write_pin(tmp_path, pin)
    assert attestation.attest_all(lock)[0].status == attestation.STATUS_PROVENANCE_MISMATCH
    result = attestation.attest_all(lock, version_resolver=lambda _: "1.5.0")[0]
    assert result.status == attestation.STATUS_OK
    assert result.to_dict().get("source_kind") is None
    assert attestation.attestations_by_pin(lock, version_resolver=lambda _: "1.5.0")["growwapi"].get("source_kind") is None


@pytest.mark.parametrize("path_style", ["physical", "windows-relative"])
def test_release_inventory_retains_wheel_posix_case_identity(tmp_path, release_install, monkeypatch, path_style):
    from packages.core.core.tests.test_broker_sdk_source_policy import WindowsRelativePath

    pin, _, _ = release_install
    lock = write_pin(tmp_path, pin)
    if path_style == "windows-relative":
        monkeypatch.setattr(attestation, "Path", WindowsRelativePath)
    assert attestation.attest_all(lock)[0].status == attestation.STATUS_OK
    pin["build_files"]["growwapi/README.md"] = pin["build_files"].pop("growwapi/README.MD")
    assert attestation.attest_all(write_pin(tmp_path, pin))[0].status == attestation.STATUS_PROVENANCE_MISMATCH


@pytest.mark.parametrize("change, expected", [("missing", "missing"), ("name", "missing"), ("version", "version_mismatch")])
def test_actual_distribution_identity_is_not_supplied_by_pin(tmp_path, release_install, change, expected):
    pin, info, _ = release_install
    if change == "missing":
        shutil.rmtree(info)
    else:
        path = info / "METADATA"
        raw = path.read_bytes()
        old, new = (b"Name: growwapi", b"Name: other") if change == "name" else (b"Version: 1.5.0", b"Version: 1.5.1")
        path.write_bytes(raw.replace(old, new, 1))
    result = attestation.attest_all(write_pin(tmp_path, pin))[0]
    assert result.status == expected
    assert attestation.required_failures([result]) == [result]


@pytest.mark.parametrize("version", [None, "", "PLACEHOLDER"])
def test_release_claim_cannot_skip_an_incomplete_version(tmp_path, release_install, version):
    pin, _, _ = release_install
    if version is None:
        del pin["version"]
    else:
        pin["version"] = version
    result = attestation.attest_all(write_pin(tmp_path, pin))[0]
    assert attestation.required_failures([result]) == [result]
