"""Recovery for a Release Please pull request whose overflow notes file is missing."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import urllib.error
import urllib.parse
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
HEAD = "release-please--branches--main--components--flinttrade-monorepo"
NOTES = f"{HEAD}--release-notes"
OVERFLOW = (
    "This release is too large to preview in the pull request body. "
    "View the full release notes here: "
    f"https://github.com/navaneeshnagarajan/FlintTrade/blob/{NOTES}/release-notes.md"
)


def _load():
    path = REPO / "scripts" / "recover_release_please_overflow.py"
    spec = importlib.util.spec_from_file_location("recover_release_please_overflow", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeGitHub:
    def __init__(self, pulls, statuses):
        self.pulls = pulls
        self.statuses = statuses
        self.closed: list[int] = []
        self.deleted: list[str] = []

    def list_open_pull_requests(self):
        return list(self.pulls)

    def notes_file_status(self, branch: str) -> int:
        return self.statuses[branch]

    def close_pull_request(self, number: int) -> None:
        self.closed.append(number)

    def delete_branch(self, branch: str) -> None:
        self.deleted.append(branch)


def _pull(module, *, number=60, head=HEAD, body=OVERFLOW):
    return module.OpenPullRequest(number=number, head_ref=head, body=body)


def test_missing_notes_file_closes_the_release_pull_request_and_deletes_both_branches():
    module = _load()
    github = FakeGitHub([_pull(module)], {NOTES: 404})

    report = module.recover(github)

    assert report.closed == (module.ClosedPullRequest(number=60, head_ref=HEAD, notes_branch=NOTES),)
    assert report.still_has_notes == ()
    assert github.closed == [60]
    assert github.deleted == [HEAD, NOTES]
    assert "Closed release pull request #60" in module.describe(report)
    assert NOTES in module.describe(report)


def test_existing_notes_file_leaves_the_release_pull_request_open():
    module = _load()
    github = FakeGitHub([_pull(module)], {NOTES: 200})

    report = module.recover(github)

    assert report.closed == ()
    assert report.still_has_notes == (60,)
    assert github.closed == []
    assert github.deleted == []
    assert "still has release-notes.md" in module.describe(report)


def test_unreadable_notes_file_does_not_close_the_pull_request():
    module = _load()
    github = FakeGitHub([_pull(module)], {NOTES: 500})

    with pytest.raises(RuntimeError, match="HTTP 500"):
        module.recover(github)

    assert github.closed == []
    assert github.deleted == []


def test_ordinary_pull_requests_are_not_release_pull_requests():
    module = _load()
    pulls = [
        _pull(module, number=1, head="fix/order-ticket-rules", body=OVERFLOW),
        _pull(module, number=2, body="## 0.0.1\n\n* feat: a small change"),
        _pull(module, number=3, head=NOTES, body=OVERFLOW),
    ]
    github = FakeGitHub(pulls, {})

    report = module.recover(github)

    assert report.closed == ()
    assert github.closed == []
    assert module.describe(report) == "No release pull request is missing its notes file."


def test_overflow_link_to_a_different_branch_is_left_untouched():
    module = _load()
    body = OVERFLOW.replace(NOTES, "release-please--branches--main--components--other--release-notes")
    github = FakeGitHub([_pull(module, body=body)], {})

    with pytest.raises(RuntimeError, match="Leaving its branches untouched"):
        module.recover(github)

    assert github.closed == []
    assert github.deleted == []


def test_overflow_link_without_a_notes_branch_is_not_a_missing_file():
    module = _load()
    body = (
        "This release is too large to preview in the pull request body. "
        "View the full release notes here: https://github.com/navaneeshnagarajan/FlintTrade/releases"
    )
    github = FakeGitHub([_pull(module, body=body)], {})

    report = module.recover(github)

    assert report.closed == ()
    assert github.closed == []


def test_pull_list_accepts_a_null_body_and_rejects_a_missing_head():
    module = _load()
    pulls = module._parse_pulls([{"number": 4, "body": None, "head": {"ref": "main"}}])
    assert pulls == [module.OpenPullRequest(number=4, head_ref="main", body="")]
    with pytest.raises(RuntimeError, match="no head branch"):
        module._parse_pulls([{"number": 5, "body": "", "head": {}}])


class _Response:
    def __init__(self, status: int, body: bytes):
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _client(module, handler):
    return module.UrllibGitHub("token", "navaneeshnagarajan", "FlintTrade", api_url="https://api.github.com", opener=handler)


def test_client_paginates_open_pull_requests_and_stops_on_a_short_page():
    module = _load()

    def opener(request, timeout):
        del timeout
        page = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)["page"][0]
        if page == "1":
            payload = [{"number": index, "body": "", "head": {"ref": f"branch-{index}"}} for index in range(100)]
            return _Response(200, json.dumps(payload).encode())
        if page == "2":
            payload = [{"number": 100, "body": None, "head": {"ref": "branch-100"}}]
            return _Response(200, json.dumps(payload).encode())
        raise AssertionError(request.full_url)

    pulls = _client(module, opener).list_open_pull_requests()

    assert [pull.number for pull in pulls] == [*range(100), 100]
    assert pulls[-1].body == ""


def test_client_reads_statuses_closes_without_merging_and_ignores_a_missing_branch():
    module = _load()
    seen: list[tuple[str, str]] = []

    def opener(request, timeout):
        assert timeout == 30
        assert request.get_header("Authorization") == "Bearer token"
        seen.append((request.get_method(), request.full_url))
        if request.get_method() == "GET" and "/pulls?" in request.full_url:
            payload = [{"number": 60, "body": OVERFLOW, "head": {"ref": HEAD}}]
            return _Response(200, json.dumps(payload).encode())
        if request.get_method() == "GET" and "/contents/" in request.full_url:
            assert NOTES in urllib.parse.unquote(request.full_url)
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", hdrs=None, fp=io.BytesIO(b""))
        if request.get_method() == "PATCH":
            assert json.loads(request.data) == {"state": "closed"}
            assert request.get_header("Content-type") == "application/json"
            return _Response(200, b"{}")
        if request.get_method() == "DELETE" and request.full_url.endswith(f"/heads/{HEAD}"):
            return _Response(204, b"")
        if request.get_method() == "DELETE" and request.full_url.endswith(f"/heads/{NOTES}"):
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", hdrs=None, fp=io.BytesIO(b""))
        raise AssertionError(request.full_url)

    report = module.recover(_client(module, opener))

    assert report.closed == (module.ClosedPullRequest(number=60, head_ref=HEAD, notes_branch=NOTES),)
    assert [method for method, _url in seen] == ["GET", "GET", "PATCH", "DELETE", "DELETE"]


def test_client_refuses_to_delete_a_branch_on_a_server_error():
    module = _load()

    def opener(request, timeout):
        del timeout
        raise urllib.error.HTTPError(request.full_url, 500, "Server Error", hdrs=None, fp=io.BytesIO(b""))

    with pytest.raises(RuntimeError, match="HTTP 500"):
        _client(module, opener).delete_branch(HEAD)


def test_run_reports_a_missing_token(monkeypatch, capsys):
    module = _load()
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    assert module.run() == 1
    assert "GH_TOKEN is required" in capsys.readouterr().err


def test_run_reports_a_malformed_repository(monkeypatch, capsys):
    module = _load()
    monkeypatch.setenv("GH_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "not-a-repo")

    assert module.run() == 1
    assert "owner/name" in capsys.readouterr().err


def test_release_please_starts_at_a_full_commit_and_recovers_before_running():
    # The invariants job checks out one commit, so this test cannot ask git
    # whether the bootstrap commit is an ancestor.
    config = json.loads((REPO / "release-please-config.json").read_text(encoding="utf-8"))
    sha = config["bootstrap-sha"]
    assert len(sha) == 40 and sha == sha.lower()
    assert set(sha) <= set("0123456789abcdef")

    workflow = yaml.safe_load((REPO / ".github" / "workflows" / "release-please.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["release-please"]["steps"]
    recovery = next(step for step in steps if step.get("run") == "python3 scripts/recover_release_please_overflow.py")
    release = next(step for step in steps if str(step.get("uses", "")).startswith("googleapis/release-please-action@"))
    assert steps.index(recovery) < steps.index(release)
    assert recovery["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert recovery["env"]["GITHUB_REPOSITORY"] == "${{ github.repository }}"
