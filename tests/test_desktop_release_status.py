"""Offline execution guards for preserving the existing release channel."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "desktop-release.yml"
SOURCE_SHA = "a" * 40


def _steps() -> list[dict]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["publish"]["steps"]


def _run_guard(
    tmp_path: Path,
    metadata: object,
    *,
    tag: str = "v0.0.1",
    api_status: int = 0,
    channel_api_status: int = 0,
    channel_json: str | None = None,
    git_status: int = 0,
    tag_sha: str = SOURCE_SHA,
    empty_response: bool = False,
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Run the real workflow shell with only the Git/GitHub boundaries faked.

    The fake gh runs the workflow's actual filter through jq; it cannot contact
    GitHub or mutate a release. No project dependencies are installed.
    """
    jq = shutil.which("jq")
    bash = shutil.which("bash")
    if jq is None or bash is None:
        pytest.skip("offline workflow execution requires bash and jq")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    git = bin_dir / "git"
    git.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "args = sys.argv[1:]\n"
        "if args == ['fetch', '--force', '--no-tags', 'origin', "
        "f\"refs/tags/{os.environ['RELEASE_TAG']}:refs/flinttrade-release-publish/tag\"]:\n"
        "    sys.exit(int(os.environ['FAKE_GIT_STATUS']))\n"
        "assert args == ['rev-parse', '--verify', 'refs/flinttrade-release-publish/tag^{commit}']\n"
        "print(os.environ['FAKE_TAG_SHA'])\n",
        encoding="utf-8",
    )
    gh = bin_dir / "gh"
    gh.write_text(
        f"#!{sys.executable}\n"
        "import os, subprocess, sys\n"
        "args = sys.argv[1:]\n"
        "assert args[:3] == ['api', "
        "f\"repos/{os.environ['GITHUB_REPOSITORY']}/releases/tags/{os.environ['RELEASE_TAG']}\", '--jq']\n"
        "assert len(args) == 4\n"
        "status = int(os.environ['FAKE_API_STATUS'])\n"
        "payload = os.environ['FAKE_RELEASE']\n"
        "if '.prerelease' in args[3]:\n"
        "    status = int(os.environ['FAKE_CHANNEL_API_STATUS'])\n"
        "    if os.environ['FAKE_CHANNEL_JSON_OVERRIDE'] == 'true':\n"
        "        payload = os.environ['FAKE_CHANNEL_JSON']\n"
        "if status:\n"
        "    sys.exit(status)\n"
        "if os.environ['FAKE_EMPTY_RESPONSE'] == 'true':\n"
        "    sys.exit(0)\n"
        "result = subprocess.run([os.environ['REAL_JQ'], '-r', args[3]], "
        "input=payload, text=True, check=False)\n"
        "sys.exit(result.returncode)\n",
        encoding="utf-8",
    )
    git.chmod(0o755)
    gh.chmod(0o755)
    output = tmp_path / "output"
    guard = next(step for step in _steps() if step.get("name") == "Re-verify immutable tag and empty target release")
    result = subprocess.run(
        [bash, "--noprofile", "--norc", "-c", guard["run"]],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": str(bin_dir),
            "REAL_JQ": jq,
            "GITHUB_REPOSITORY": "example/project",
            "RELEASE_TAG": tag,
            "SOURCE_SHA": SOURCE_SHA,
            "GITHUB_OUTPUT": str(output),
            "FAKE_RELEASE": json.dumps(metadata),
            "FAKE_API_STATUS": str(api_status),
            "FAKE_CHANNEL_API_STATUS": str(channel_api_status),
            "FAKE_CHANNEL_JSON_OVERRIDE": str(channel_json is not None).lower(),
            "FAKE_CHANNEL_JSON": channel_json or "",
            "FAKE_GIT_STATUS": str(git_status),
            "FAKE_TAG_SHA": tag_sha,
            "FAKE_EMPTY_RESPONSE": str(empty_response).lower(),
        },
        text=True,
        capture_output=True,
        check=False,
    )
    return result, output.read_text(encoding="utf-8") if output.exists() else ""


@pytest.mark.parametrize(
    ("tag", "prerelease"),
    [
        ("v0.0.1", True),
        ("v0.0.1", False),
        ("v1.2.3", False),
        ("v1.2.3", True),
        ("v1.2.3-rc.1", True),
        ("v1.2.3-rc.1", False),
    ],
)
def test_release_channel_comes_from_existing_release(tmp_path: Path, tag: str, prerelease: bool) -> None:
    result, output = _run_guard(tmp_path, {"assets": [], "prerelease": prerelease}, tag=tag)
    assert result.returncode == 0, result.stderr
    assert output == f"prerelease={str(prerelease).lower()}\n"


@pytest.mark.parametrize("value", [None, "true", "false", 0, 1, [], {}])
def test_unknown_release_channel_fails_closed(tmp_path: Path, value: object) -> None:
    result, output = _run_guard(tmp_path, {"assets": [], "prerelease": value})
    assert result.returncode != 0
    assert output == ""


def test_missing_release_channel_fails_closed(tmp_path: Path) -> None:
    result, output = _run_guard(tmp_path, {"assets": []})
    assert result.returncode != 0
    assert output == ""


@pytest.mark.parametrize("api_status", [1, 4, 22])
def test_release_lookup_failure_fails_closed(tmp_path: Path, api_status: int) -> None:
    result, output = _run_guard(tmp_path, {"assets": [], "prerelease": True}, api_status=api_status)
    assert result.returncode != 0
    assert output == ""


@pytest.mark.parametrize("api_status", [1, 4, 22])
def test_channel_lookup_failure_after_asset_check_fails_closed(tmp_path: Path, api_status: int) -> None:
    result, output = _run_guard(tmp_path, {"assets": [], "prerelease": True}, channel_api_status=api_status)
    assert result.returncode != 0
    assert output == ""


@pytest.mark.parametrize("payload", ["", "{", '{"prerelease": true}\n{"prerelease": false}'])
def test_unreadable_or_ambiguous_channel_response_fails_closed(tmp_path: Path, payload: str) -> None:
    result, output = _run_guard(tmp_path, {"assets": [], "prerelease": True}, channel_json=payload)
    assert result.returncode != 0
    assert output == ""


def test_empty_release_response_fails_closed(tmp_path: Path) -> None:
    result, output = _run_guard(tmp_path, {"assets": [], "prerelease": True}, empty_response=True)
    assert result.returncode != 0
    assert output == ""


@pytest.mark.parametrize("git_status", [1, 128])
def test_missing_remote_tag_still_fails_closed(tmp_path: Path, git_status: int) -> None:
    result, output = _run_guard(tmp_path, {"assets": [], "prerelease": True}, git_status=git_status)
    assert result.returncode != 0
    assert output == ""


def test_moved_remote_tag_still_fails_closed(tmp_path: Path) -> None:
    result, output = _run_guard(tmp_path, {"assets": [], "prerelease": True}, tag_sha="b" * 40)
    assert result.returncode != 0
    assert output == ""


def test_existing_assets_still_fail_closed(tmp_path: Path) -> None:
    result, output = _run_guard(tmp_path, {"assets": [{"name": "existing.dmg"}], "prerelease": True})
    assert result.returncode != 0
    assert output == ""


def test_publication_uses_only_the_validated_release_channel() -> None:
    steps = _steps()
    guard = next(step for step in steps if step.get("name") == "Re-verify immutable tag and empty target release")
    publish = next(step for step in steps if step.get("id") == "publish")
    assert guard.get("id") == "release_metadata"
    assert "continue-on-error" not in guard
    assert "if" not in guard
    assert steps.index(guard) + 1 == steps.index(publish)
    assert publish["with"]["prerelease"] == "${{ fromJSON(steps.release_metadata.outputs.prerelease) }}"
    assert "contains(inputs.tag, '-')" not in WORKFLOW.read_text(encoding="utf-8")
    assert publish["with"]["overwrite_files"] is False
    assert publish["with"]["fail_on_unmatched_files"] is True
