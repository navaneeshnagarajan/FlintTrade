#!/usr/bin/env python3
"""Enforce Identity H8: every commit on a contributor PR is GPG-signed with the
fingerprint declared in their CLA record (.github/cla-config.yml).

Failure modes:
  - PR author has no entry in cla-config.yml        -> unsigned_cla
  - a PR commit has no/invalid GPG signature        -> unsigned_commit
  - a PR commit's GPG fingerprint != CLA fingerprint -> fingerprint_drift
  - declared cla_text_sha256 != current CLA.md hash  -> stale_cla_artefact

Bootstrap / founder handling:
  - The CI job runs this ONLY on external forks (see supply-chain.yml `if:`), so the
    founder's own branches never reach it.
  - If the author's record still carries a PLACEHOLDER fingerprint (founder has not yet
    published a key), the binding cannot be enforced; the script prints a NOTE and exits 0.
  - When run with no PR context (local invocation) it verifies what it can and exits 0.

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


def main() -> int:
    if not CLA_CONFIG.exists():
        print(f"FAIL: {CLA_CONFIG} missing", file=sys.stderr)
        return 1
    cfg = yaml.safe_load(CLA_CONFIG.read_text(encoding="utf-8")) or {}
    contributors = {
        str(c.get("github_username", "")).lower(): c
        for c in cfg.get("contributors", [])
    }

    actor = (os.environ.get("PR_AUTHOR") or os.environ.get("GITHUB_ACTOR") or "").lower()
    if not actor:
        print("NOTE: no PR author in environment (local run); CLA binding not enforced")
        return 0

    record = contributors.get(actor)
    if record is None:
        print(
            f"FAIL (unsigned_cla): PR author {actor!r} has no entry in cla-config.yml. "
            f"They must sign CLA.md (GPG) and be ratified before merge.",
            file=sys.stderr,
        )
        return 1

    # cla_text_sha256 drift check (skipped while PLACEHOLDER)
    artefact = record.get("signed_artefact") or {}
    declared_hash = str(artefact.get("cla_text_sha256", ""))
    if declared_hash and "PLACEHOLDER" not in declared_hash:
        current = hashlib.sha256(CLA_TEXT.read_bytes()).hexdigest()
        if current != declared_hash:
            print(
                f"FAIL (stale_cla_artefact): CLA.md sha256 {current} does not match the "
                f"signed value {declared_hash} for {actor}; re-sign the current CLA text.",
                file=sys.stderr,
            )
            return 1

    fp = _norm_fp(str(record.get("gpg_fingerprint", "")))
    if not fp or "PLACEHOLDER" in fp:
        print(
            f"NOTE: {actor} has no real GPG fingerprint on record yet "
            f"(PLACEHOLDER); commit-signature binding not enforced."
        )
        return 0

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
