"""FATAL CSP gate (audit §28.7 / DS-CSP-01): no `script-src 'unsafe-inline'` anywhere.

`script-src 'unsafe-inline'` nullifies XSS containment on the order-entry surface; the
parent spec declares it FATAL. This gate greps every source file under packages/ for the
pattern so a regression (a re-added meta CSP, a copied snippet, a new app) fails CI.

`style-src 'unsafe-inline'` is permitted (founder decision §9.3 — radix + framer-motion);
only the `script-src` form is forbidden.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PACKAGES = _REPO_ROOT / "packages"

# Same shape as the audit's grep gate: a script-src directive that includes 'unsafe-inline'
# before the next ';'. Tolerates other tokens between them.
_FATAL_RE = re.compile(r"script-src[^;]*'unsafe-inline'")

_SKIP_DIRS = {"node_modules", "dist", ".next", "build", "__pycache__", ".turbo", "coverage"}
_SCAN_SUFFIXES = {".html", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py", ".css"}


def _iter_source_files():
    for path in _PACKAGES.rglob("*"):
        if not path.is_file() or path.suffix not in _SCAN_SUFFIXES:
            continue
        if _SKIP_DIRS & set(path.parts):
            continue
        yield path


def test_no_script_src_unsafe_inline_in_packages():
    offenders: list[str] = []
    for path in _iter_source_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            # Faithful mirror of the audit's `grep -rE "script-src[^;]*'unsafe-inline'"`:
            # the literal directive sequence must never appear in a source file — not in a
            # CSP directive and not in prose (prose trips the real grep gate too).
            if _FATAL_RE.search(line):
                offenders.append(f"{path.relative_to(_REPO_ROOT).as_posix()}:{n}: {line.strip()}")
    assert not offenders, (
        "FATAL: script-src 'unsafe-inline' found (audit §28.7 / DS-CSP-01):\n"
        + "\n".join(offenders)
    )
