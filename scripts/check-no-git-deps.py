#!/usr/bin/env python3
"""Assert no unapproved git/file/path/tarball deps in lockfiles/manifests.

Every dependency — direct or transitive — must come from an attested public registry
(PyPI / npm / crates.io). A git URL has no verifiable hash chain; the upstream commit
can be force-pushed, the URL hijacked, the tarball replaced. The only current
exception is an operator-cleared broker SDK that is unavailable on PyPI and is
cross-checked against ``brokers.lock`` by exact commit.

Failures:
  - requirements.in / requirements.lock: any `git+`, `file:`, or remote archive URL
  - uv.lock: any git source except an exact broker SDK commit listed in brokers.lock
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
from urllib.parse import ParseResult, urlparse

REPO = pathlib.Path(__file__).resolve().parents[1]

_FORBIDDEN_REQ = re.compile(r"(git\+|file:|https?://[^/]+/.+\.(tar\.gz|whl|zip))")
_ALLOWED_GIT_SCHEMES = {"https"}
_ALLOWED_GIT_HOSTS = {"github.com"}


def _parse_git_url(url: str) -> ParseResult:
    """Parse a git URL after dropping pip's optional ``git+`` prefix."""

    return urlparse(url.removeprefix("git+").strip())


def _git_source_policy_failure(url: str) -> str | None:
    """Return a failure reason when a permitted git exception uses an unsafe origin."""

    parsed = _parse_git_url(url)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if scheme not in _ALLOWED_GIT_SCHEMES:
        return f"scheme {scheme or '<none>'!r} is not allowed"
    if host not in _ALLOWED_GIT_HOSTS:
        return f"host {host or '<none>'!r} is not allowed"
    if not parsed.path.strip("/"):
        return "missing repository path"
    return None


def _normalise_git_repo(url: str) -> str:
    """Canonical ``scheme://host/owner/name`` for comparing git sources.

    Strips a ``?rev=``/query suffix, a trailing ``.git``, and a trailing slash,
    and lower-cases the result so uv.lock and brokers.lock compare regardless of
    those cosmetic differences.
    """
    parsed = _parse_git_url(url)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    return f"{scheme}://{host}{path}".lower()


def _allowed_uv_git_sources() -> dict[str, dict[str, str]]:
    """Return ``{name: {"commit": ..., "repo": ...}}`` from brokers.lock.

    ``repo`` (from the ``homepage`` field, normalised) lets the uv.lock git URL
    be validated against the RIGHT repository — not merely checked for the commit
    as a substring, which a hostile URL embedding the legitimate commit
    (``https://evil.example/x?rev=<commit>``) would otherwise satisfy.
    """
    brokers_lock = REPO / "brokers.lock"
    if not brokers_lock.exists():
        return {}
    data = tomllib.loads(brokers_lock.read_text(encoding="utf-8"))
    allowed: dict[str, dict[str, str]] = {}
    for entry in data.get("broker", []):
        if not isinstance(entry, Mapping):
            continue
        name = str(entry.get("name", ""))
        source_commit = str(entry.get("source_commit", ""))
        if name and source_commit:
            allowed[name] = {
                "commit": source_commit,
                "repo": _normalise_git_repo(str(entry.get("homepage", ""))),
            }
    return allowed


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
            if _FORBIDDEN_REQ.search(s):
                fails.append(f"{fname}:{n}: forbidden non-registry source: {s!r}")
    return fails


def check_uv_lock() -> list[str]:
    p = REPO / "uv.lock"
    if not p.exists():
        return []
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    allowed = _allowed_uv_git_sources()
    fails: list[str] = []
    for package in data.get("package", []):
        if not isinstance(package, Mapping):
            continue
        source = package.get("source")
        if not isinstance(source, Mapping):
            continue
        git_value = source.get("git")
        if not isinstance(git_value, str):
            continue
        name = str(package.get("name", ""))
        expected = allowed.get(name)
        if not expected:
            fails.append(f"uv.lock: forbidden git source for {name}: {git_value!r}")
            continue
        policy_failure = _git_source_policy_failure(git_value)
        if policy_failure:
            fails.append(f"uv.lock: unapproved git source for {name}: {git_value!r} ({policy_failure})")
            continue
        # The commit must be present AND the URL must point at the expected
        # repository (host + owner + name), so a hostile URL merely embedding the
        # legitimate commit as a query/path fragment cannot pass.
        commit_ok = expected["commit"] in git_value
        repo_ok = not expected["repo"] or _normalise_git_repo(git_value) == expected["repo"]
        if not (commit_ok and repo_ok):
            fails.append(
                f"uv.lock: git source for {name} does not match the "
                f"brokers.lock-pinned repo/commit: {git_value!r}"
            )
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
    fails = check_requirements() + check_uv_lock() + check_pnpm_lock() + check_cargo_toml()
    if fails:
        for f in fails:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1
    print("dependency provenance OK (no unapproved git/file/tarball/external-path deps)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
