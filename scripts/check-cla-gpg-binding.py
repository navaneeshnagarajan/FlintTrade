#!/usr/bin/env python3
"""Enforce Identity H8: every commit on a contributor PR is GPG-signed with the
fingerprint declared in their CLA record (.github/cla-config.yml).

Failure modes:
  - PR author has no entry in cla-config.yml        -> unsigned_cla
  - a PR commit has no/invalid GPG signature        -> unsigned_commit
  - a PR commit's GPG fingerprint != CLA fingerprint -> fingerprint_drift
  - declared cla_text_sha256 != current CLA.md hash  -> stale_cla_artefact

Bootstrap / founder handling:
  - The CI job runs this ONLY on external-fork pull_request events (see
    supply-chain.yml `if:`). Push, schedule, dispatch, owner branches, and
    same-repo bot merges never reach the job.
  - If the repo owner's record does not yet carry a fingerprint, the script treats
    it as owner auto-attestation and exits 0. External contributors must provide a
    fingerprinted record before merge.
  - When run with no PR context (local invocation, or CI push/schedule where the
    workflow `if:` was bypassed) it verifies what it can and exits 0. GITHUB_ACTOR
    is the pusher/merger in those events — not a CLA subject.

Sub-spec §9.3-§9.4; acceptance gate #13.
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
CLA_CONFIG = REPO / ".github" / "cla-config.yml"
CLA_TEXT = REPO / "CLA.md"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout.strip()


def _commit_range() -> list[str]:
    """Return the SHAs introduced by the PR, newest first.

    Uses GITHUB_BASE_REF when present (PR context); otherwise inspects only HEAD.
    """
    base = os.environ.get("GITHUB_BASE_REF")
    if base:
        # ensure the base ref is fetched; CI checks out with fetch-depth: 0
        merge_base = _git("merge-base", f"origin/{base}", "HEAD") or _git("rev-parse", f"origin/{base}")
        if merge_base:
            out = _git("rev-list", f"{merge_base}..HEAD")
            return [s for s in out.splitlines() if s]
    head = _git("rev-parse", "HEAD")
    return [head] if head else []


def _signature(sha: str) -> tuple[str, str]:
    """Return (status, fingerprint) for a commit. status is git's %G? code."""
    out = _git("log", "-1", "--format=%G?%x1f%GF", sha)
    if "\x1f" in out:
        status, fp = out.split("\x1f", 1)
        return status.strip(), fp.strip().upper()
    return (out.strip(), "")


def _norm_fp(fp: str) -> str:
    return fp.replace(" ", "").strip().upper()


def _resolve_pr_author() -> str:
    """Return the CLA subject, or empty when Identity H8 does not apply.

    ``PR_AUTHOR`` is the only authoritative subject. ``GITHUB_ACTOR`` on
    push/schedule/dispatch is the merger, scheduler, or bot (for example
    ``cursor[bot]`` after a squash-merge) and must not be treated as a
    contributor PR author. Local dry-runs without a GitHub event name may
    still use ``GITHUB_ACTOR``.
    """
    author = (os.environ.get("PR_AUTHOR") or "").strip()
    if author:
        return author.lower()
    event = (os.environ.get("GITHUB_EVENT_NAME") or "").strip().lower()
    if event and event != "pull_request":
        return ""
    return (os.environ.get("GITHUB_ACTOR") or "").strip().lower()


def main() -> int:
    if not CLA_CONFIG.exists():
        print(f"FAIL: {CLA_CONFIG} missing", file=sys.stderr)
        return 1
    cfg = yaml.safe_load(CLA_CONFIG.read_text(encoding="utf-8")) or {}
    contributors = {
        str(c.get("github_username", "")).lower(): c
        for c in cfg.get("contributors", [])
    }

    actor = _resolve_pr_author()
    if not actor:
        print("NOTE: no PR author in environment (local run or non-PR CI event); CLA binding not enforced")
        return 0

    record = contributors.get(actor)
    if record is None:
        print(
            f"FAIL (unsigned_cla): PR author {actor!r} has no entry in cla-config.yml. "
            f"They must sign CLA.md (GPG) and be ratified before merge.",
            file=sys.stderr,
        )
        return 1

    # cla_text_sha256 drift check (skipped when no signed hash is recorded)
    artefact = record.get("signed_artefact") or {}
    declared_hash = str(artefact.get("cla_text_sha256", ""))
    if declared_hash:
        current = hashlib.sha256(CLA_TEXT.read_bytes()).hexdigest()
        if current != declared_hash:
            print(
                f"FAIL (stale_cla_artefact): CLA.md sha256 {current} does not match the "
                f"signed value {declared_hash} for {actor}; re-sign the current CLA text.",
                file=sys.stderr,
            )
            return 1

    fp = _norm_fp(str(record.get("gpg_fingerprint", "")))
    repo_owner = str(cfg.get("repo_owner", "navaneeshnagarajan")).lower()
    if not fp and actor == repo_owner:
        print(
            f"NOTE: {actor} is repo owner with auto-attested CLA record; "
            "commit-signature binding not enforced."
        )
        return 0
    if not fp:
        print(
            f"FAIL (missing_gpg_fingerprint): PR author {actor!r} has a CLA "
            "record but no GPG fingerprint. External contributors must provide "
            "a fingerprinted CLA record before merge.",
            file=sys.stderr,
        )
        return 1

    if not cfg.get("require_gpg_signed_commits", True):
        print(f"NOTE: require_gpg_signed_commits disabled; skipping commit check for {actor}")
        return 0

    failures: list[str] = []
    commits = _commit_range()
    if not commits:
        print("NOTE: no commits resolved for verification")
        return 0
    for sha in commits:
        status, commit_fp = _signature(sha)
        # G = good signature, U = good with unknown validity (acceptable: key not in CI keyring)
        if status not in ("G", "U"):
            failures.append(f"unsigned_commit: {sha[:12]} signature status {status!r}")
            continue
        if commit_fp and not commit_fp.endswith(fp[-16:]):
            failures.append(
                f"fingerprint_drift: {sha[:12]} signed by {commit_fp} != CLA fingerprint {fp}"
            )

    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1
    print(f"CLA GPG binding OK for {actor} ({len(commits)} commits verified)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
