from __future__ import annotations

import hashlib
import json
import textwrap

from scripts import sync_broker_sdk_refs as syncer


def test_active_sdk_entries_ignores_placeholders_and_unknowns() -> None:
    entries = [
        {"name": "dhanhq", "version": "2.2.0"},
        {"name": "future-sdk", "version": "PLACEHOLDER"},
        {"name": "unknown-sdk", "version": "1.0.0"},
        {"name": "neo-api-client", "version": "2.0.0", "source_commit": "abc"},
    ]

    assert syncer.active_sdk_entries(entries) == [
        {"name": "dhanhq", "version": "2.2.0", "source_commit": ""},
        {"name": "neo-api-client", "version": "2.0.0", "source_commit": "abc"},
    ]


def test_select_pypi_artifact_prefers_universal_py3_wheel() -> None:
    files = [
        {"filename": "pkg-1.0.0.tar.gz", "packagetype": "sdist", "python_version": "source"},
        {"filename": "pkg-1.0.0-cp312-macosx.whl", "packagetype": "bdist_wheel", "python_version": "cp312"},
        {"filename": "pkg-1.0.0-py3-none-any.whl", "packagetype": "bdist_wheel", "python_version": "py3"},
    ]

    assert syncer.select_pypi_artifact(files)["filename"] == "pkg-1.0.0-py3-none-any.whl"


def test_download_pypi_artifact_verifies_digest(tmp_path) -> None:
    body = b"wheel-bytes"
    digest = hashlib.sha256(body).hexdigest()
    release = {
        "releases": {
            "1.0.0": [
                {
                    "filename": "pkg-1.0.0-py3-none-any.whl",
                    "packagetype": "bdist_wheel",
                    "python_version": "py3",
                    "url": "https://files.example/pkg.whl",
                    "digests": {"sha256": digest},
                }
            ]
        }
    }

    def opener(url: str) -> tuple[int, bytes]:
        if url == "https://pypi.org/pypi/pkg/json":
            return 200, json.dumps(release).encode("utf-8")
        if url == "https://files.example/pkg.whl":
            return 200, body
        raise AssertionError(url)

    result = syncer.download_pypi_artifact("pkg", "1.0.0", tmp_path, opener)

    assert result["filename"] == "pkg-1.0.0-py3-none-any.whl"
    assert result["sha256"] == digest
    assert (tmp_path / "pkg-1.0.0-py3-none-any.whl").read_bytes() == body


def test_latest_pypi_version_reads_info_version() -> None:
    def opener(url: str) -> tuple[int, bytes]:
        assert url == "https://pypi.org/pypi/pkg/json"
        return 200, json.dumps({"info": {"version": "1.2.3"}}).encode("utf-8")

    assert syncer.latest_pypi_version("pkg", opener) == "1.2.3"


def test_load_broker_lock_reads_toml_entries(tmp_path) -> None:
    lock = tmp_path / "brokers.lock"
    lock.write_text(
        textwrap.dedent(
            """
            [[broker]]
            name = "dhanhq"
            version = "2.2.0"

            [[broker]]
            name = "growwapi"
            version = "1.5.0"
            """
        ),
        encoding="utf-8",
    )

    assert [entry["name"] for entry in syncer.load_broker_lock(lock)] == ["dhanhq", "growwapi"]


def test_sync_records_pypi_drift(tmp_path, monkeypatch) -> None:
    body = b"wheel-bytes"
    digest = hashlib.sha256(body).hexdigest()
    release = {
        "info": {"version": "2.3.0"},
        "releases": {
            "2.2.0": [
                {
                    "filename": "dhanhq-2.2.0-py3-none-any.whl",
                    "packagetype": "bdist_wheel",
                    "python_version": "py3",
                    "url": "https://files.example/dhanhq.whl",
                    "digests": {"sha256": digest},
                }
            ]
        },
    }

    def opener(url: str) -> tuple[int, bytes]:
        if url == "https://pypi.org/pypi/dhanhq/json":
            return 200, json.dumps(release).encode("utf-8")
        if url == "https://files.example/dhanhq.whl":
            return 200, body
        raise AssertionError(url)

    monkeypatch.setattr(syncer, "load_broker_lock", lambda _path: [{"name": "dhanhq", "version": "2.2.0"}])
    monkeypatch.setattr(
        syncer,
        "sync_git_mirror",
        lambda _source, _audit_root: {"path": "repo", "remote": "origin", "head": "abc", "describe": "abc"},
    )

    manifest = syncer.sync(audit_root=tmp_path / "audit", check_missing=False, opener=opener)

    assert manifest["sdks"][0]["pypi_latest_version"] == "2.3.0"
    assert manifest["sdks"][0]["pypi_current"] is False
    assert manifest["drift"] == [
        {"package": "dhanhq", "source": "pypi", "locked": "2.2.0", "upstream": "2.3.0"}
    ]
