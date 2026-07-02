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
import tomllib
from collections.abc import Iterator, Mapping

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


def _cargo_dependency_tables(doc: Mapping[str, object]) -> Iterator[tuple[str, Mapping[str, object]]]:
    """Yield TOML tables that actually describe Cargo dependency sources."""
    for key in ("dependencies", "dev-dependencies", "build-dependencies"):
        value = doc.get(key)
        if isinstance(value, Mapping):
            yield key, value

    workspace = doc.get("workspace")
    if isinstance(workspace, Mapping):
        deps = workspace.get("dependencies")
        if isinstance(deps, Mapping):
            yield "workspace.dependencies", deps

    target = doc.get("target")
    if isinstance(target, Mapping):
        for target_name, target_doc in target.items():
            if not isinstance(target_doc, Mapping):
                continue
            for key in ("dependencies", "dev-dependencies", "build-dependencies"):
                value = target_doc.get(key)
                if isinstance(value, Mapping):
                    yield f"target.{target_name}.{key}", value

    patch = doc.get("patch")
    if isinstance(patch, Mapping):
        for registry, deps in patch.items():
            if isinstance(deps, Mapping):
                yield f"patch.{registry}", deps

    replace = doc.get("replace")
    if isinstance(replace, Mapping):
        yield "replace", replace


def _path_is_inside_repo(manifest: pathlib.Path, raw_path: str) -> bool:
    resolved_repo = REPO.resolve()
    resolved_path = (manifest.parent / raw_path).resolve()
    try:
        relative = resolved_path.relative_to(resolved_repo)
    except ValueError:
        return False
    blocked_parts = {"target", "node_modules", ".local"}
    return not any(part in blocked_parts for part in relative.parts)


def check_cargo_toml() -> list[str]:
    fails: list[str] = []
    for p in REPO.rglob("Cargo.toml"):
        parts = set(p.parts)
        if "target" in parts or "node_modules" in parts or ".local" in parts:
            continue
        doc = tomllib.loads(p.read_text(encoding="utf-8"))
        for section, deps in _cargo_dependency_tables(doc):
            for dep_name, spec in deps.items():
                if not isinstance(spec, Mapping):
                    continue
                git_value = spec.get("git")
                if isinstance(git_value, str):
                    fails.append(f"{p.relative_to(REPO)}: forbidden git dep {section}.{dep_name}: {git_value!r}")
                path_value = spec.get("path")
                if isinstance(path_value, str) and not _path_is_inside_repo(p, path_value):
                    fails.append(f"{p.relative_to(REPO)}: forbidden path dep {section}.{dep_name}: {path_value!r}")
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
