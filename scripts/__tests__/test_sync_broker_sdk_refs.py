from __future__ import annotations

import hashlib
import json
import subprocess
import textwrap
from pathlib import Path

import pytest

from scripts import sync_broker_sdk_refs as syncer


def test_active_sdk_entries_ignores_placeholders_and_unknowns() -> None:
    entries = [
        {"name": "dhanhq", "version": "2.2.0"},
        {"name": "future-sdk", "version": "PLACEHOLDER"},
        {"name": "unknown-sdk", "version": "1.0.0"},
        {"name": "kotakneoapi", "version": "3.0.7", "release_version": "3.0.7"},
    ]

    assert syncer.active_sdk_entries(entries) == [
        {"name": "dhanhq", "version": "2.2.0", "source_commit": ""},
        {"name": "kotakneoapi", "version": "3.0.7", "release_version": "3.0.7", "source_commit": ""},
    ]


@pytest.mark.parametrize("release_version", [None, "", "v3.0.7", "3.0.7rc1"])
def test_kotak_reference_sync_requires_an_explicit_stable_release_version(release_version):
    entry = {"name": "kotakneoapi", "version": "3.0.8"}
    if release_version is not None:
        entry["release_version"] = release_version

    with pytest.raises(ValueError, match="release_version"):
        syncer.active_sdk_entries([entry])


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
    assert "uv run python scripts/sync_broker_sdk_refs.py" in (tmp_path / "audit" / "README.md").read_text(
        encoding="utf-8"
    )
    assert manifest["drift"] == [{"package": "dhanhq", "source": "pypi", "locked": "2.2.0", "upstream": "2.3.0"}]


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=path, check=True)
    subprocess.run(["git", "config", "tag.gpgsign", "false"], cwd=path, check=True)


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _commit_and_tag(path: Path, message: str, content: str, tag: str) -> str:
    (path / "f.txt").write_text(content, encoding="utf-8")
    _git(path, "add", "f.txt")
    _git(path, "commit", "-q", "-m", message)
    _git(path, "tag", "-a", tag, "-m", tag)
    return _git(path, "rev-parse", "HEAD")


def _dhan_pypi_opener(body: bytes = b"wheel-bytes"):
    digest = hashlib.sha256(body).hexdigest()
    release = {
        "info": {"version": "2.3.0"},
        "releases": {
            "2.3.0": [
                {
                    "filename": "dhanhq-2.3.0-py3-none-any.whl",
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

    return opener, digest


def test_latest_final_git_tag_skips_prereleases() -> None:
    tags = ["v2.3.0", "v2.4.0rc1", "v2.4.0a1", "v2.4.0b1", "v2.4.0.dev1"]
    assert syncer.latest_final_git_tag(tags) == "v2.3.0"
    assert syncer.latest_final_git_tag(["v2.3.0", "v2.4.0rc1", "v2.4.0"]) == "v2.4.0"
    assert syncer.latest_final_git_tag(["v2.4.0rc1", "2.3.0"]) == "2.3.0"
    assert syncer.latest_final_git_tag(["v2.4.0rc1"]) is None


def test_git_pin_stays_current_when_newest_tag_is_a_release_candidate(tmp_path, monkeypatch) -> None:
    origin = tmp_path / "origin"
    origin.mkdir()
    _init_git_repo(origin)
    final_commit = _commit_and_tag(origin, "2.3.0", "final\n", "v2.3.0")
    rc_commit = _commit_and_tag(origin, "2.4.0rc1", "rc\n", "v2.4.0rc1")
    assert rc_commit != final_commit

    opener, digest = _dhan_pypi_opener()
    monkeypatch.setattr(syncer, "REPO", tmp_path)
    monkeypatch.setitem(
        syncer.SDK_SOURCES,
        "dhanhq",
        syncer.BrokerSdkSource(
            package="dhanhq",
            repo_name="dhanhq-py",
            git_url=str(origin),
            pypi_name="dhanhq",
        ),
    )
    monkeypatch.setattr(
        syncer,
        "load_broker_lock",
        lambda _path: [{"name": "dhanhq", "version": "2.3.0", "source_commit": final_commit, "sha256": digest}],
    )

    manifest = syncer.sync(audit_root=tmp_path / "audit", check_missing=False, opener=opener)
    git = manifest["sdks"][0]["git"]

    assert git["head"] == rc_commit
    assert git["latest_final_tag"] == "v2.3.0"
    assert git["latest_final_commit"] == final_commit
    assert manifest["sdks"][0]["git_current"] is True
    assert manifest["drift"] == []
    assert "git status: current" in (tmp_path / "audit" / "README.md").read_text(encoding="utf-8")


def test_git_pin_flags_drift_when_a_newer_final_tag_exists(tmp_path, monkeypatch) -> None:
    origin = tmp_path / "origin"
    origin.mkdir()
    _init_git_repo(origin)
    locked_commit = _commit_and_tag(origin, "2.3.0", "final\n", "v2.3.0")
    newer_final = _commit_and_tag(origin, "2.4.0", "newer\n", "v2.4.0")
    rc_commit = _commit_and_tag(origin, "2.5.0rc1", "rc\n", "v2.5.0rc1")
    assert rc_commit != newer_final

    opener, digest = _dhan_pypi_opener()
    monkeypatch.setattr(syncer, "REPO", tmp_path)
    monkeypatch.setitem(
        syncer.SDK_SOURCES,
        "dhanhq",
        syncer.BrokerSdkSource(
            package="dhanhq",
            repo_name="dhanhq-py",
            git_url=str(origin),
            pypi_name="dhanhq",
        ),
    )
    monkeypatch.setattr(
        syncer,
        "load_broker_lock",
        lambda _path: [{"name": "dhanhq", "version": "2.3.0", "source_commit": locked_commit, "sha256": digest}],
    )

    manifest = syncer.sync(audit_root=tmp_path / "audit", check_missing=False, opener=opener)
    git = manifest["sdks"][0]["git"]

    assert git["head"] == rc_commit
    assert git["latest_final_tag"] == "v2.4.0"
    assert git["latest_final_commit"] == newer_final
    assert manifest["sdks"][0]["git_current"] is False
    assert manifest["drift"] == [
        {"package": "dhanhq", "source": "git", "locked": locked_commit, "upstream": newer_final}
    ]
    assert "locked behind the latest final release" in (tmp_path / "audit" / "README.md").read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize(
    ("git_change", "pypi_version", "expected_source"),
    [
        ({}, "3.0.7", None),
        ({"head": "b" * 40, "head_tree": "1" * 40}, "3.0.7", None),
        ({"latest_stable_tag": "v3.0.8"}, "3.0.8", "release-tag"),
        ({"release_commit": "c" * 40}, "3.0.7", "release-commit"),
        ({"latest_stable_tag": "v3.0.10"}, "3.0.10", "release-tag"),
    ],
)
def test_kotak_dual_track_drift_is_independent(
    tmp_path,
    monkeypatch,
    git_change: dict[str, str],
    pypi_version: str,
    expected_source: str | None,
) -> None:
    wheel = b"release wheel"
    sdist = b"release sdist"
    wheel_hash = hashlib.sha256(wheel).hexdigest()
    sdist_hash = hashlib.sha256(sdist).hexdigest()
    locked = {
        "name": "kotakneoapi",
        "version": "3.0.8",
        "release_version": "3.0.7",
        "source_commit": "a" * 40,
        "source_tree": "d" * 40,
        "release_tag": "v3.0.7",
        "release_commit": "e" * 40,
        "release_tree": "f" * 40,
        "release_wheel_sha256": wheel_hash,
        "release_sdist_sha256": sdist_hash,
        "sha256": wheel_hash,
    }
    git = {
        "path": "mirror",
        "remote": "origin",
        "head": locked["source_commit"],
        "head_tree": locked["source_tree"],
        "describe": "v3.0.7",
        "latest_stable_tag": locked["release_tag"],
        "release_commit": locked["release_commit"],
        "release_tree": locked["release_tree"],
    }
    git.update(git_change)
    monkeypatch.setattr(syncer, "load_broker_lock", lambda _path: [locked])
    monkeypatch.setattr(syncer, "sync_git_mirror", lambda _source, _root: git)

    def opener(url: str) -> tuple[int, bytes]:
        if url == "https://pypi.org/pypi/kotakneoapi/json":
            data = {
                "info": {"version": pypi_version},
                "releases": {
                    "3.0.7": [
                        {
                            "filename": "kotakneoapi-3.0.7-py3-none-any.whl",
                            "packagetype": "bdist_wheel",
                            "python_version": "py3",
                            "url": "https://files.example/wheel",
                            "digests": {"sha256": wheel_hash},
                        },
                        {
                            "filename": "kotakneoapi-3.0.7.tar.gz",
                            "packagetype": "sdist",
                            "python_version": "source",
                            "url": "https://files.example/sdist",
                            "digests": {"sha256": sdist_hash},
                        },
                    ]
                },
            }
            return 200, json.dumps(data).encode()
        if url == "https://files.example/wheel":
            return 200, wheel
        if url == "https://files.example/sdist":
            return 200, sdist
        raise AssertionError(url)

    manifest = syncer.sync(audit_root=tmp_path / "audit", check_missing=False, opener=opener)

    sdk = manifest["sdks"][0]
    if expected_source is None:
        assert manifest["drift"] == []
        assert sdk["git_current"] is True
    else:
        assert any(d["package"] == "kotakneoapi" and d["source"] == expected_source for d in manifest["drift"])
        if expected_source == "release-commit":
            assert sdk["git_current"] is False
    if "head" in git_change:
        readme = (tmp_path / "audit" / "README.md").read_text(encoding="utf-8")
        assert "locked behind upstream HEAD" not in readme
        assert "git status: current" in readme
    assert sdk["version"] == "3.0.8"
    assert manifest["sdks"][0]["release_version"] == "3.0.7"
    assert manifest["sdks"][0]["pypi"]["filename"] == "kotakneoapi-3.0.7-py3-none-any.whl"


def _release_files(*versions: str, yanked: tuple[str, ...] = ()) -> dict:
    return {version: [{"filename": f"dhanhq-{version}.tar.gz", "yanked": version in yanked}] for version in versions}


@pytest.mark.parametrize(
    ("locked", "info_version", "versions", "yanked", "expected"),
    [
        ("2.3.0", "2.3.0", ("2.3.0", "2.4.0rc1"), (), "2.3.0"),
        ("2.3.0", "2.4.0rc1", ("2.3.0", "2.4.0rc1"), (), "2.3.0"),
        ("2.3.0", "2.3.0", ("2.3.0", "2.4.0a1", "2.4.0b1", "2.4.0.dev1"), (), "2.3.0"),
        ("2.3.0", "2.4.0", ("2.3.0", "2.4.0rc1", "2.4.0"), (), "2.4.0"),
        ("2.3.0", "2.3.0", ("2.3.0", "2.4.0"), ("2.4.0",), "2.3.0"),
        ("2.4.0rc1", "2.3.0", ("2.3.0", "2.4.0rc1"), (), "2.3.0"),
    ],
)
def test_upstream_version_ignores_prereleases(locked, info_version, versions, yanked, expected) -> None:
    data = {"info": {"version": info_version}, "releases": _release_files(*versions, yanked=yanked)}
    assert syncer.upstream_pypi_version(data, locked) == expected


def test_sync_keeps_final_pin_current_when_release_candidate_exists(tmp_path, monkeypatch) -> None:
    body = b"wheel-bytes"
    digest = hashlib.sha256(body).hexdigest()
    wheel = {
        "filename": "dhanhq-2.3.0-py3-none-any.whl",
        "packagetype": "bdist_wheel",
        "python_version": "py3",
        "url": "https://files.example/dhanhq.whl",
        "digests": {"sha256": digest},
    }
    rc_wheel = {
        "filename": "dhanhq-2.4.0rc1-py3-none-any.whl",
        "packagetype": "bdist_wheel",
        "python_version": "py3",
        "url": "https://files.example/dhanhq-rc.whl",
        "digests": {"sha256": digest},
    }
    release = {
        "info": {"version": "2.4.0rc1"},
        "releases": {"2.3.0": [wheel], "2.4.0rc1": [rc_wheel]},
    }

    def opener(url: str) -> tuple[int, bytes]:
        if url == "https://pypi.org/pypi/dhanhq/json":
            return 200, json.dumps(release).encode("utf-8")
        if url == "https://files.example/dhanhq.whl":
            return 200, body
        raise AssertionError(url)

    monkeypatch.setattr(syncer, "load_broker_lock", lambda _path: [{"name": "dhanhq", "version": "2.3.0"}])
    monkeypatch.setattr(
        syncer,
        "sync_git_mirror",
        lambda _source, _audit_root: {"path": "repo", "remote": "origin", "head": "abc", "describe": "abc"},
    )

    manifest = syncer.sync(audit_root=tmp_path / "audit", check_missing=False, opener=opener)

    assert manifest["sdks"][0]["pypi_latest_version"] == "2.3.0"
    assert manifest["sdks"][0]["pypi_current"] is True
    assert manifest["drift"] == []
