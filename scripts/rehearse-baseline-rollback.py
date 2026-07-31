#!/usr/bin/env python3
"""Safely rehearse a restructure rollback without mutating the worktree."""

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_OUTPUT_DIR = Path("/private/tmp/flinttrade-rollback-rehearsal")


@dataclass(frozen=True)
class MergeTreeSummary:
    """Conflict summary extracted from a git merge-tree report."""

    line_count: int
    conflict_indicators: int
    changed_in_both: int
    removed_in_local: int
    removed_in_remote: int
    clean: bool


@dataclass(frozen=True)
class RollbackRehearsalReport:
    """Machine-readable rollback rehearsal result for one commit."""

    commit: str
    commit_sha: str
    parent_sha: str
    base_ref: str
    base_sha: str
    merge_tree_returncode: int
    report_path: str
    line_count: int
    conflict_indicators: int
    changed_in_both: int
    removed_in_local: int
    removed_in_remote: int
    clean: bool


def summarise_merge_tree(text: str) -> MergeTreeSummary:
    """Count conflict indicators in git merge-tree output."""
    lines = text.splitlines()
    lowered = [line.lower() for line in lines]
    changed_in_both = sum("changed in both" in line for line in lowered)
    removed_in_local = sum("removed in local" in line for line in lowered)
    removed_in_remote = sum("removed in remote" in line for line in lowered)
    conflict_markers = sum("conflict" in line for line in lowered)
    conflict_indicators = changed_in_both + removed_in_local + removed_in_remote + conflict_markers

    return MergeTreeSummary(
        line_count=len(lines),
        conflict_indicators=conflict_indicators,
        changed_in_both=changed_in_both,
        removed_in_local=removed_in_local,
        removed_in_remote=removed_in_remote,
        clean=conflict_indicators == 0,
    )


def decode_git_output(output: bytes) -> str:
    """Decode git output while preserving undecodable bytes as replacement chars."""
    return output.decode("utf-8", errors="replace")


def _git(repo_root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=check,
    )


def _rev_parse(repo_root: Path, rev: str) -> str:
    return _git(repo_root, "rev-parse", rev).stdout.strip()


def _git_bytes(repo_root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        check=check,
    )


def repo_root() -> Path:
    return Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").stdout.strip())


def rehearse_commit(repo_root: Path, commit: str, base_ref: str, output_dir: Path) -> RollbackRehearsalReport:
    """Run git merge-tree for a revert-style rollback rehearsal."""
    commit_sha = _rev_parse(repo_root, commit)
    parent_sha = _rev_parse(repo_root, f"{commit_sha}^")
    base_sha = _rev_parse(repo_root, base_ref)

    result = _git_bytes(
        repo_root,
        "merge-tree",
        "--trivial-merge",
        commit_sha,
        base_sha,
        parent_sha,
        check=False,
    )
    report_text = decode_git_output(result.stdout)
    if result.stderr:
        report_text = f"{report_text}\n# stderr\n{decode_git_output(result.stderr)}"

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"flinttrade-rollback-{commit_sha[:8]}-onto-{base_sha[:8]}.merge-tree.txt"
    report_path.write_text(report_text, encoding="utf-8")

    summary = summarise_merge_tree(report_text)
    return RollbackRehearsalReport(
        commit=commit,
        commit_sha=commit_sha,
        parent_sha=parent_sha,
        base_ref=base_ref,
        base_sha=base_sha,
        merge_tree_returncode=result.returncode,
        report_path=str(report_path),
        line_count=summary.line_count,
        conflict_indicators=summary.conflict_indicators,
        changed_in_both=summary.changed_in_both,
        removed_in_local=summary.removed_in_local,
        removed_in_remote=summary.removed_in_remote,
        clean=summary.clean,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("commits", nargs="+", help="Commit SHA(s) to rehearse reverting")
    parser.add_argument("--base-ref", default="HEAD", help="Tree that would receive the rollback")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--allow-conflicts",
        action="store_true",
        help="Exit zero even if conflict indicators are found; useful for recording evidence.",
    )
    args = parser.parse_args(argv)

    root = repo_root()
    reports = [rehearse_commit(root, commit, args.base_ref, args.output_dir) for commit in args.commits]
    payload = {
        "repo_root": str(root),
        "base_ref": args.base_ref,
        "output_dir": str(args.output_dir),
        "reports": [asdict(report) for report in reports],
        "clean": all(report.clean for report in reports),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))

    if payload["clean"] or args.allow_conflicts:
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
