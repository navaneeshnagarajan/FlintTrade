#!/usr/bin/env python3
"""Close a release pull request whose overflow notes file is missing.

GitHub accepts 65,536 characters in a pull request body. When the release
notes are larger, Release Please stores them in ``release-notes.md`` on a
side branch and leaves only a link in the pull request. Reading that file
happens before Release Please can write it again, so a missing file fails
every later run. Closing the pull request and deleting its branches lets
the same run open a fresh release pull request.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Protocol

OVERFLOW_MESSAGE = (
    "This release is too large to preview in the pull request body. "
    "View the full release notes here:"
)
NOTES_FILE = "release-notes.md"
HEAD_PREFIX = "release-please--branches--"
_OVERFLOW_RE = re.compile(re.escape(OVERFLOW_MESSAGE) + r" (?P<url>\S+)")
_BRANCH_RE = re.compile(r"/blob/(?P<branch>.+)/release-notes\.md$")
_MAX_PULL_PAGES = 20


@dataclass(frozen=True)
class OpenPullRequest:
    number: int
    head_ref: str
    body: str


@dataclass(frozen=True)
class ClosedPullRequest:
    number: int
    head_ref: str
    notes_branch: str


@dataclass(frozen=True)
class RecoveryReport:
    closed: tuple[ClosedPullRequest, ...]
    still_has_notes: tuple[int, ...]


class GitHub(Protocol):
    def list_open_pull_requests(self) -> list[OpenPullRequest]: ...

    def notes_file_status(self, branch: str) -> int: ...

    def close_pull_request(self, number: int) -> None: ...

    def delete_branch(self, branch: str) -> None: ...


def notes_branch_for(pull: OpenPullRequest) -> str | None:
    """Return the notes branch Release Please would read, or None when this pull request is not that overflow case."""
    if not pull.head_ref.startswith(HEAD_PREFIX) or pull.head_ref.endswith("--release-notes"):
        return None
    match = _OVERFLOW_RE.search(pull.body)
    if match is None:
        return None
    path = urllib.parse.unquote(urllib.parse.urlparse(match.group("url")).path)
    found = _BRANCH_RE.search(path)
    if found is None:
        return None
    expected = f"{pull.head_ref}--release-notes"
    branch = found.group("branch")
    if branch != expected:
        raise RuntimeError(
            f"Release pull request #{pull.number} points at {branch}, not {expected}. "
            "Leaving its branches untouched."
        )
    return expected


def recover(github: GitHub) -> RecoveryReport:
    """Close overflow release pull requests whose notes file is missing and delete their branches."""
    closed: list[ClosedPullRequest] = []
    still_has_notes: list[int] = []
    for pull in github.list_open_pull_requests():
        notes_branch = notes_branch_for(pull)
        if notes_branch is None:
            continue
        status = github.notes_file_status(notes_branch)
        if status == 200:
            still_has_notes.append(pull.number)
            continue
        if status != 404:
            raise RuntimeError(
                f"Could not read {NOTES_FILE} on {notes_branch} (HTTP {status}). "
                f"Release pull request #{pull.number} was left open."
            )
        github.close_pull_request(pull.number)
        github.delete_branch(pull.head_ref)
        github.delete_branch(notes_branch)
        closed.append(
            ClosedPullRequest(number=pull.number, head_ref=pull.head_ref, notes_branch=notes_branch)
        )
    return RecoveryReport(closed=tuple(closed), still_has_notes=tuple(still_has_notes))


def describe(report: RecoveryReport) -> str:
    lines = [
        (
            f"Closed release pull request #{item.number} because {NOTES_FILE} "
            f"is missing on {item.notes_branch}. Deleted {item.head_ref} and {item.notes_branch}."
        )
        for item in report.closed
    ]
    lines.extend(
        f"Release pull request #{number} still has {NOTES_FILE}; leaving it open."
        for number in report.still_has_notes
    )
    if not lines:
        return "No release pull request is missing its notes file."
    return "\n".join(lines)


class UrllibGitHub:
    """GitHub REST client for the recovery step. A missing branch is an HTTP 404."""

    def __init__(self, token: str, owner: str, repo: str, *, api_url: str, opener=urllib.request.urlopen) -> None:
        self._token = token
        self._owner = owner
        self._repo = repo
        self._api_url = api_url.rstrip("/")
        self._opener = opener

    def list_open_pull_requests(self) -> list[OpenPullRequest]:
        pulls: list[OpenPullRequest] = []
        for page in range(1, _MAX_PULL_PAGES + 1):
            status, payload = self._request(
                "GET",
                f"/repos/{self._owner}/{self._repo}/pulls?state=open&per_page=100&page={page}",
            )
            if status != 200:
                raise RuntimeError(f"Could not list open pull requests (HTTP {status}).")
            batch = _parse_pulls(payload)
            pulls.extend(batch)
            if len(batch) < 100:
                return pulls
        raise RuntimeError(f"Open pull request list exceeded {_MAX_PULL_PAGES} pages.")

    def notes_file_status(self, branch: str) -> int:
        ref = urllib.parse.quote(branch, safe="")
        status, _payload = self._request(
            "GET",
            f"/repos/{self._owner}/{self._repo}/contents/{NOTES_FILE}?ref={ref}",
        )
        return status

    def close_pull_request(self, number: int) -> None:
        status, _payload = self._request(
            "PATCH",
            f"/repos/{self._owner}/{self._repo}/pulls/{number}",
            {"state": "closed"},
        )
        if status != 200:
            raise RuntimeError(f"Could not close pull request #{number} (HTTP {status}).")

    def delete_branch(self, branch: str) -> None:
        ref = urllib.parse.quote(branch, safe="")
        status, _payload = self._request("DELETE", f"/repos/{self._owner}/{self._repo}/git/refs/heads/{ref}")
        if status not in (204, 404):
            raise RuntimeError(f"Could not delete branch {branch} (HTTP {status}).")

    def _request(self, method: str, path: str, body: dict | None = None) -> tuple[int, object]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "User-Agent": "flinttrade-release-notes-recovery",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self._api_url}{path}",
            data=data,
            method=method,
            headers=headers,
        )
        try:
            with self._opener(request, timeout=30) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as error:
            raw = error.read()
            status = error.code
        except urllib.error.URLError as error:
            raise RuntimeError(f"GitHub API request failed: {error.reason}") from error
        if not raw:
            return status, None
        try:
            return status, json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return status, None


def _parse_pulls(payload: object) -> list[OpenPullRequest]:
    if not isinstance(payload, list):
        raise RuntimeError("GitHub pull request list was not a list.")
    pulls: list[OpenPullRequest] = []
    for item in payload:
        if not isinstance(item, dict):
            raise RuntimeError("GitHub pull request list contained a non-object.")
        head = item.get("head")
        if not isinstance(head, dict) or not isinstance(head.get("ref"), str):
            raise RuntimeError(f"Pull request #{item.get('number')} has no head branch.")
        number = item.get("number")
        if not isinstance(number, int):
            raise RuntimeError("GitHub pull request list contained an entry with no number.")
        body = item.get("body")
        pulls.append(OpenPullRequest(number=number, head_ref=head["ref"], body=body if isinstance(body, str) else ""))
    return pulls


def _repository() -> tuple[str, str]:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    owner, separator, repo = repository.partition("/")
    if separator != "/" or not owner or not repo or "/" in repo:
        raise RuntimeError("GITHUB_REPOSITORY must be owner/name.")
    return owner, repo


def main() -> int:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GH_TOKEN is required.")
    owner, repo = _repository()
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    report = recover(UrllibGitHub(token, owner, repo, api_url=api_url))
    print(describe(report))
    return 0


def run() -> int:
    try:
        return main()
    except RuntimeError as error:
        print(f"release notes recovery failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(run())
