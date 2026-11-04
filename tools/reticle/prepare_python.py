"""Prepare checked-hash Python bytecode without starting the application.

Only the maintained no-egress runner may invoke this entrypoint. All source and
installed dependency inputs stay read-only; the cache is fresh, run-local state.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import py_compile
import sys
import sysconfig
import time
from collections.abc import Iterable
from importlib.machinery import PathFinder
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = Path("/run/test/cache/reticle-python")


def compile_sources(sources: Iterable[Path], cache: Path) -> list[dict[str, str]]:
    """Compile static operands once, recording source and checked-cache hashes.

    Args:
        sources: Python source paths to compile without executing them.
        cache: New bytecode directory beneath the owned ``/run/test/cache``.

    Returns:
        Records containing each source path, bytecode path and their SHA-256
        hashes, ordered by the unique source paths.

    Raises:
        ValueError: The resolved cache is outside the owned run cache.
        FileExistsError: The cache already exists.
        OSError: A source or cache file cannot be read or written.
        py_compile.PyCompileError: A source cannot be compiled.
        RuntimeError: Bytecode is missing, its header or source hash is invalid,
            or a source changes during preparation.
    """
    if not cache.resolve().is_relative_to("/run/test/cache"):
        raise ValueError("Bytecode must stay in the owned run cache")
    cache.mkdir(parents=True, exist_ok=False)
    previous = sys.pycache_prefix
    rows: list[dict[str, str]] = []
    try:
        sys.pycache_prefix = str(cache)
        for source in sorted(set(sources)):
            before = source.read_bytes()
            target = py_compile.compile(
                str(source), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH
            )
            if target is None:
                raise RuntimeError("Python did not produce bytecode: " + str(source))
            bytecode = Path(target).read_bytes()
            if source.read_bytes() != before:
                raise RuntimeError("Source changed during preparation: " + str(source))
            if bytecode[:4] != importlib.util.MAGIC_NUMBER or int.from_bytes(bytecode[4:8], "little") != 3:
                raise RuntimeError("Unchecked or foreign Python bytecode: " + target)
            if bytecode[8:16] != importlib.util.source_hash(before):
                raise RuntimeError("Bytecode source hash mismatch: " + target)
            rows.append(
                {
                    "source": str(source),
                    "source_sha256": hashlib.sha256(before).hexdigest(),
                    "bytecode": target,
                    "bytecode_sha256": hashlib.sha256(bytecode).hexdigest(),
                }
            )
    finally:
        sys.pycache_prefix = previous
    return rows


def static_roots() -> tuple[list[Path], list[dict[str, str | None]]]:
    """Resolve installed top-level operands without importing their initialisers.

    Returns:
        A pair of compilation roots and shadowed-operand records. Roots include
        the standard library, project packages, fixture harness and installed
        operands that win path resolution. Each shadowed record contains the
        excluded operand path and its winning origin, or ``None`` if unresolved.

    Raises:
        OSError: The installed package directory cannot be inspected.
    """
    site = Path(sysconfig.get_path("purelib"))
    roots = [Path(sysconfig.get_path("stdlib")), ROOT / "packages", ROOT / "tools/reticle/harness"]
    shadowed: list[dict[str, str | None]] = []
    for operand in sorted(site.iterdir()):
        name = operand.stem if operand.suffix == ".py" else operand.name
        if not name.isidentifier() or name == "__pycache__" or not (operand.is_dir() or operand.suffix == ".py"):
            continue
        found = PathFinder.find_spec(name, sys.path)
        locations = [] if found is None else list(found.submodule_search_locations or [])
        if found is not None and (str(operand) in locations or found.origin == str(operand)):
            roots.append(operand)
        else:
            # Editable packages and stdlib names resolve before site-packages.
            # Compile the real winner, not an unreachable shadow implementation.
            shadowed.append({"operand": str(operand), "resolved": None if found is None else found.origin})
    return roots, shadowed


def main() -> None:
    """Prepare immutable inputs before any normal-factory or protocol execution."""
    from setup import guard

    guard()
    if sys.version_info[:3] != (3, 14, 8):
        raise RuntimeError("The explicitly qualified Python 3.14.8 is required")
    started = time.monotonic()
    roots, shadowed = static_roots()
    sources = [source for root in roots for source in (root.rglob("*.py") if root.is_dir() else [root])]
    rows = compile_sources(sources, CACHE)
    if any(name.startswith("flinttrade_") for name in sys.modules):
        raise RuntimeError("Static preparation imported application code")
    receipt = {
        "python": sys.executable,
        "version": sys.version,
        "cache_tag": sys.implementation.cache_tag,
        "optimisation": sys.flags.optimize,
        "cache": str(CACHE),
        "invalidation": "checked-hash",
        "roots": list(map(str, roots)),
        "shadowed": shadowed,
        "files": rows,
        "seconds": time.monotonic() - started,
        "application_imports": [],
    }
    Path("/run/test/artifacts/python-bytecode-preparation.json").write_text(json.dumps(receipt, indent=2))
    print(f"Prepared {len(rows)} static Python sources; no application executed", flush=True)


if __name__ == "__main__":
    main()
