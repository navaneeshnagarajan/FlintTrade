"""The git-SDK drift gate must track the REMOTE head, not the clone-time HEAD.

``git fetch`` only updates remote-tracking refs — it never moves the local
checkout's HEAD — so measuring drift with ``rev-parse HEAD`` reports
``git-current`` forever after the first sync, silently defeating the gate for
the one SDK whose only distribution channel is git (Renovate cannot watch
git-pinned uv sources either).
"""

from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]


def _load_sync_module():
    spec = importlib.util.spec_from_file_location(
        "sync_broker_sdk_refs", REPO / "scripts" / "sync_broker_sdk_refs.py"
    )
    module = importlib.util.module_from_spec(spec)
    # Register before exec: the module's dataclasses use `from __future__
    # import annotations`, and dataclass field resolution looks the module up
    # in sys.modules at instantiation time.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(cwd: pathlib.Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.mark.integration
def test_git_mirror_head_tracks_moved_upstream(tmp_path, monkeypatch) -> None:
    sync = _load_sync_module()
    monkeypatch.setattr(sync, "REPO", tmp_path)

    # Build a tiny upstream repo with one commit.
    origin = tmp_path / "origin.git-src"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    _git(origin, "config", "user.email", "test@example.invalid")
    _git(origin, "config", "user.name", "Test")
    (origin / "f.txt").write_text("one\n", encoding="utf-8")
    _git(origin, "add", "f.txt")
    _git(origin, "commit", "-q", "-m", "one")

    audit_root = tmp_path / "audit"
    source = sync.BrokerSdkSource(
        package="fake-sdk", git_url=str(origin), repo_name="fake-sdk"
    )

    # First sync clones; head == upstream's only commit.
    first = sync.sync_git_mirror(source, audit_root)
    first_head = _git(origin, "rev-parse", "HEAD")
    assert first["head"] == first_head

    # Upstream moves. The re-sync must report the NEW remote head even though
    # the local mirror checkout's HEAD is still the clone-time commit.
    (origin / "f.txt").write_text("two\n", encoding="utf-8")
    _git(origin, "add", "f.txt")
    _git(origin, "commit", "-q", "-m", "two")
    moved_head = _git(origin, "rev-parse", "HEAD")
    assert moved_head != first_head

    second = sync.sync_git_mirror(source, audit_root)
    assert second["head"] == moved_head, (
        "drift gate frozen at clone-time HEAD — upstream commits invisible"
    )
