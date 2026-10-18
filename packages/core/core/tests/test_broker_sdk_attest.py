"""Unit tests for broker SDK attestation."""

from __future__ import annotations

import textwrap
import json
from importlib import metadata

import pytest

from flinttrade_core.broker_sdk_attest import (
    STATUS_MISMATCH,
    STATUS_MISSING,
    STATUS_NOT_REQUIRED,
    STATUS_OK,
    STATUS_SKIPPED,
    STATUS_UNKNOWN,
    attest_all,
    attest_all_ok,
    attestations_by_pin,
    load_pins,
    required_failures,
    sdk_attestation_fields,
)

pytestmark = pytest.mark.unit

_LOCK = textwrap.dedent(
    """
    [[broker]]
    name = "dhanhq"
    version = "2.2.0"

    [[broker]]
    name = "upstox-python-sdk"
    version = "PLACEHOLDER"

    [[broker]]
    name = "kotakneoapi"
    version = "1.0.0"
    """
)


@pytest.fixture
def lock_file(tmp_path):
    path = tmp_path / "brokers.lock"
    path.write_text(_LOCK, encoding="utf-8")
    return path


def test_ok_when_installed_matches_pin(lock_file):
    res = attest_all(
        lock_file,
        version_resolver=lambda d: {"dhanhq": "2.2.0", "kotakneoapi": "1.0.0"}.get(d),
    )
    by = {r.broker: r for r in res}
    assert by["dhanhq"].status == STATUS_OK
    assert by["kotakneoapi"].status == STATUS_OK
    # Placeholder pin → not yet live → skipped (not a failure).
    assert by["upstox-python-sdk"].status == STATUS_SKIPPED
    assert attest_all_ok(res) is True


def test_mismatch_and_missing_are_failures(lock_file):
    res = attest_all(lock_file, version_resolver=lambda d: {"dhanhq": "2.1.0"}.get(d))
    by = {r.broker: r for r in res}
    assert by["dhanhq"].status == STATUS_MISMATCH
    assert by["kotakneoapi"].status == STATUS_MISSING
    assert {f.broker for f in required_failures(res)} == {"dhanhq", "kotakneoapi"}
    assert attest_all_ok(res) is False


def test_loads_the_repo_brokers_lock():
    pins = load_pins()
    names = {p.get("name") for p in pins}
    assert "dhanhq" in names  # the repo's wave-1 pin
    assert "growwapi" in names


def test_missing_lock_returns_empty(tmp_path):
    assert attest_all(tmp_path / "nope.lock", version_resolver=lambda d: None) == []


def test_catalogue_sdk_fields_are_serialisable(lock_file):
    rows = attestations_by_pin(
        lock_file,
        version_resolver=lambda d: {"dhanhq": "2.2.0"}.get(d),
    )
    assert rows["dhanhq"] == {
        "pin": "dhanhq",
        "pinned_version": "2.2.0",
        "installed_version": "2.2.0",
        "status": STATUS_OK,
    }
    assert sdk_attestation_fields("dhanhq", attestations=rows)["sdk_attestation"]["status"] == STATUS_OK
    assert sdk_attestation_fields(None)["sdk_attestation"]["status"] == STATUS_NOT_REQUIRED
    assert sdk_attestation_fields("not-in-lock", attestations=rows)["sdk_attestation"] == {
        "pin": "not-in-lock",
        "pinned_version": None,
        "installed_version": None,
        "status": STATUS_UNKNOWN,
    }


@pytest.mark.parametrize(
    ("direct_url", "include_v2", "expected"),
    [
        (
            {
                "url": "https://github.com/Kotak-Neo/kotak-neo-python.git",
                "vcs_info": {"vcs": "git", "commit_id": "5bb34fae39c4a52a0e6b59d7e2d17090cafc340c"},
            },
            False,
            "ok",
        ),
        (
            {
                "url": "https://evil.example/kotak-neo-python.git",
                "vcs_info": {"vcs": "git", "commit_id": "5bb34fae39c4a52a0e6b59d7e2d17090cafc340c"},
            },
            False,
            "provenance_mismatch",
        ),
        (
            {
                "url": "https://github.com/other/kotak-neo-python.git",
                "vcs_info": {"vcs": "git", "commit_id": "5bb34fae39c4a52a0e6b59d7e2d17090cafc340c"},
            },
            False,
            "provenance_mismatch",
        ),
        (
            {
                "url": "https://github.com/Kotak-Neo/kotak-neo-python.git",
                "vcs_info": {"vcs": "git", "commit_id": "0" * 40},
            },
            False,
            "provenance_mismatch",
        ),
        (None, False, "provenance_mismatch"),
        ({"url": "https://github.com/Kotak-Neo/kotak-neo-python.git", "vcs_info": "git"}, False, "provenance_mismatch"),
        (
            {
                "url": "https://github.com:bad/Kotak-Neo/kotak-neo-python.git",
                "vcs_info": {"vcs": "git", "commit_id": "5bb34fae39c4a52a0e6b59d7e2d17090cafc340c"},
            },
            False,
            "provenance_mismatch",
        ),
        (
            {
                "url": "https://[broken/Kotak-Neo/kotak-neo-python.git",
                "vcs_info": {"vcs": "git", "commit_id": "5bb34fae39c4a52a0e6b59d7e2d17090cafc340c"},
            },
            False,
            "provenance_mismatch",
        ),
        (
            {
                "url": "https://github.com/Kotak-Neo/kotak-neo-python.git",
                "vcs_info": {"vcs": "git", "commit_id": "5bb34fae39c4a52a0e6b59d7e2d17090cafc340c"},
            },
            True,
            "conflict",
        ),
    ],
)
def test_kotak_attestation_requires_exact_git_origin_and_exclusive_namespace(
    tmp_path,
    monkeypatch,
    direct_url,
    include_v2,
    expected,
):
    from flinttrade_core import broker_sdk_attest as attestation

    from packages.core.core.tests.test_broker_sdk_source_policy import make_source_install, write_pin

    pin, dist, _ = make_source_install(
        tmp_path, monkeypatch, "kotakneoapi", commit="5bb34fae39c4a52a0e6b59d7e2d17090cafc340c"
    )
    lock = write_pin(tmp_path, pin)
    if direct_url is not None:
        (dist / "direct_url.json").write_text(json.dumps(direct_url), encoding="utf-8")
    else:
        (dist / "direct_url.json").unlink()
    if include_v2:
        v2 = tmp_path / "neo_api_client-2.0.0.dist-info"
        v2.mkdir()
        (v2 / "METADATA").write_text("Metadata-Version: 2.3\nName: neo-api-client\nVersion: 2.0.0\n")
        (v2 / "top_level.txt").write_text("neo_api_client\n")

    result = attestation.attest_all(lock)[0]

    assert result.status == expected
    assert (result in required_failures([result])) is (expected != "ok")


@pytest.mark.parametrize(("owner_evidence", "expected"), [("record", "ok"), ("none", "conflict")])
def test_kotak_requires_positive_namespace_ownership(tmp_path, monkeypatch, owner_evidence, expected):
    from flinttrade_core import broker_sdk_attest as attestation

    import shutil
    from packages.core.core.tests.test_broker_sdk_source_policy import make_source_install, write_pin

    pin, dist, package = make_source_install(
        tmp_path, monkeypatch, "kotakneoapi", commit="5bb34fae39c4a52a0e6b59d7e2d17090cafc340c"
    )
    # Keep RECORD-only ownership positive; an absent package still conflicts
    # with the actual import origin rather than reaching a weaker legacy check.
    top_level = dist / "top_level.txt"
    del pin["build_files"][top_level.relative_to(tmp_path).as_posix()]
    top_level.unlink()
    if owner_evidence == "none":
        (dist / "RECORD").unlink()
        shutil.rmtree(package)
    lock = write_pin(tmp_path, pin)

    result = attestation.attest_all(lock)[0]

    assert result.status == expected
    assert (result in required_failures([result])) is (expected != "ok")


@pytest.mark.parametrize(("installed_version", "expected"), [("3.0.9", "ok"), ("3.0.7", "version_mismatch")])
def test_current_kotak_runtime_pin_does_not_accept_the_release_distribution(
    tmp_path, monkeypatch, installed_version, expected
):
    import shutil
    import sys
    from flinttrade_core import broker_sdk_attest as attestation

    # A matching version and a self-asserted direct URL are no longer enough:
    # retain the real selected build bytes for the positive source control.
    selected = metadata.distribution("kotakneoapi")
    pin = next(row for row in load_pins() if row["name"] == "kotakneoapi")
    for relative in pin["build_files"]:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(selected.locate_file(relative), destination)
    info = next(tmp_path.glob("kotakneoapi-*.dist-info"))
    (info / "direct_url.json").write_text(selected.read_text("direct_url.json"))
    metadata_path = info / "METADATA"
    if installed_version != "3.0.9":
        metadata_path.write_bytes(
            metadata_path.read_bytes().replace(b"Version: 3.0.9", f"Version: {installed_version}".encode("ascii"), 1)
        )
    package_files = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*") if path.is_file())
    (info / "RECORD").write_text("".join(f"{path},,\n" for path in package_files))
    real_distributions = metadata.distributions
    monkeypatch.setattr(attestation.metadata, "distributions", lambda: real_distributions(path=[str(tmp_path)]))
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "neo_api_client", raising=False)

    result = next(row for row in attestation.attest_all() if row.broker == "kotakneoapi")

    assert result.pinned_version == "3.0.9"
    assert result.status == expected
    assert (result in required_failures([result])) is (expected != "ok")
