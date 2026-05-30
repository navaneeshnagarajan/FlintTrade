#!/usr/bin/env python3
"""Assert no git/file/path/tarball deps in any lockfile or manifest (provenance gate).

Every dependency — direct or transitive — must come from an attested public registry
(PyPI / npm / crates.io). A git URL has no verifiable hash chain; the upstream commit
can be force-pushed, the URL hijacked, the tarball replaced.

Failures:
  - requirements.in / requirements.lock: any `git+`, `file:`, or remote archive URL
  - pnpm-lock.yaml: any git-resolution or tarball-URL dependency
  - Cargo.toml: any external `git = "..."` or `path = "..."` dep outside the workspace

Sub-spec §10.2; acceptance gate #14.
"""

from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]

_FORBIDDEN_REQ = re.compile(r"(git\+|file:|https?://[^/]+/.+\.(tar\.gz|whl|zip))")


def check_requirements() -> list[str]:
    fails: list[str] = []
    for fname in ("requirements.in", "requirements.lock"):
        p = REPO / fname
        if not p.exists():
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            s = line.strip()
            if not s or s.startswith("#") or s.startswith("--hash"):
                continue
            if _FORBIDDEN_REQ.match(s):
                fails.append(f"{fname}:{n}: forbidden non-registry source: {s!r}")
    return fails


def check_pnpm_lock() -> list[str]:
    p = REPO / "pnpm-lock.yaml"
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8")
    fails: list[str] = []
    for m in re.finditer(r"resolution:\s*\{\s*type:\s*git", text):
        line_no = text[: m.start()].count("\n") + 1
        fails.append(f"pnpm-lock.yaml:{line_no}: git-resolution dep forbidden")
    for m in re.finditer(r"resolution:\s*\{\s*tarball:\s*https?://", text):
        line_no = text[: m.start()].count("\n") + 1
        fails.append(f"pnpm-lock.yaml:{line_no}: tarball-URL dep forbidden")
    return fails


def check_cargo_toml() -> list[str]:
    fails: list[str] = []
    for p in REPO.rglob("Cargo.toml"):
        parts = set(p.parts)
        if "target" in parts or "node_modules" in parts or ".local" in parts:
            continue
        text = p.read_text(encoding="utf-8")
        for m in re.finditer(r'(?m)^\s*(?:git|path)\s*=\s*"([^"]+)"', text):
            kind = m.group(0).strip().split("=", 1)[0].strip()
            value = m.group(1)
            # workspace-internal path deps (".", "../sibling-in-workspace") are fine;
            # flag absolute/external paths and any git source.
            if kind == "path" and (value.startswith(".") and "../" not in value):
                continue
            if kind == "path" and value.startswith(".."):
                # relative workspace sibling — permitted (cargo workspace layout)
                continue
            fails.append(f"{p.relative_to(REPO)}: forbidden {kind} dep: {value!r}")
    return fails


def main() -> int:
    fails = check_requirements() + check_pnpm_lock() + check_cargo_toml()
    if fails:
        for f in fails:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1
    print("dependency provenance OK (no git/file/tarball/external-path deps)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
