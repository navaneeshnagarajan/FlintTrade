"""Validated FlintTrade source-checkout root discovery.

The Electron runtime installs Python packages non-editably inside the managed
checkout. Module depth therefore differs between POSIX
``.venv/lib/pythonX.Y/site-packages`` and Windows
``.venv/Lib/site-packages`` layouts. Repository resources must be located by a
validated source contract, never by a fixed ``Path.parents`` index.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from pathlib import Path

SOURCE_ROOT_ENV = "FLINTTRADE_SOURCE_ROOT"

_SOURCE_ROOT_MARKERS = (
    "VERSION",
    "pyproject.toml",
    "pnpm-workspace.yaml",
    "packages/core/core/pyproject.toml",
    "packages/apps/terminal/package.json",
)


class SourceRootError(RuntimeError):
    """Raised when no validated FlintTrade source checkout can be found."""


def _candidate_directories(start: Path) -> Iterator[Path]:
    """Yield ``start`` (or its parent for a file) and every ancestor."""
    resolved = start.expanduser().resolve()
    current = resolved if resolved.is_dir() else resolved.parent
    yield current
    yield from current.parents


def _has_source_contract(candidate: Path) -> bool:
    """Return whether ``candidate`` contains the exact source-root markers."""
    return candidate.is_dir() and all((candidate / marker).is_file() for marker in _SOURCE_ROOT_MARKERS)


def _validated_explicit_root(raw: str) -> Path:
    """Resolve and validate the explicit desktop source-root contract."""
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise SourceRootError(f"{SOURCE_ROOT_ENV} must be an absolute source-checkout path")
    resolved = candidate.resolve()
    if not _has_source_contract(resolved):
        raise SourceRootError(f"{SOURCE_ROOT_ENV} does not identify a FlintTrade source checkout")
    return resolved


def discover_source_root(
    module_file: Path | str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    working_directory: Path | str | None = None,
) -> Path:
    """Return the canonical, validated FlintTrade source-checkout root.

    Resolution order is deliberate:

    1. ``FLINTTRADE_SOURCE_ROOT`` supplied by the desktop process boundary;
    2. ancestors of the importing module (source/editable and in-checkout
       non-editable virtual environments);
    3. ancestors of the process working directory (source entrypoints).

    An explicit but invalid environment contract fails closed rather than
    falling back to a different checkout.

    Args:
        module_file: Module path to search from. Defaults to this module.
        environ: Environment mapping. Defaults to :data:`os.environ`.
        working_directory: Process directory fallback. Defaults to
            :func:`Path.cwd`.

    Raises:
        SourceRootError: No validated checkout exists, or the explicit contract
            is invalid.
    """
    environment = os.environ if environ is None else environ
    explicit = (environment.get(SOURCE_ROOT_ENV) or "").strip()
    if explicit:
        return _validated_explicit_root(explicit)

    starts = (
        Path(__file__) if module_file is None else Path(module_file),
        Path.cwd() if working_directory is None else Path(working_directory),
    )
    seen: set[Path] = set()
    for start in starts:
        for candidate in _candidate_directories(start):
            if candidate in seen:
                continue
            seen.add(candidate)
            if _has_source_contract(candidate):
                return candidate

    raise SourceRootError(f"FlintTrade source checkout not found; set {SOURCE_ROOT_ENV} to its absolute path")


__all__ = ["SOURCE_ROOT_ENV", "SourceRootError", "discover_source_root"]
