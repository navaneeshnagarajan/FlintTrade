#!/usr/bin/env python3
"""Enforce the terminal's no-``any`` / no-suppression rule, with no toolchain to install.

``packages/apps/terminal/eslint.config.mjs`` used to claim this gate. It never
ran: none of the four plugins it imported were in ``pnpm-lock.yaml``, no npm
script invoked it and no CI job called it, so ``@typescript-eslint/no-explicit-any``
was decoration. The config has been removed rather than left to imply a check
that did not exist, and this script takes over the one rule in it that ``tsc``
cannot enforce on its own.

What ``tsc --noEmit`` already covers, so this script does not:

* unused locals and parameters (``noUnusedLocals`` / ``noUnusedParameters``)
* implicit ``any`` (``strict``), fallthrough cases, casing consistency

What only a lint pass covers, and what this script therefore checks:

* an **explicit** ``any`` - a deliberate escape from the type system, which
  ``strict`` permits by design
* ``@ts-ignore`` and ``@ts-expect-error`` - suppressions the house rules allow
  only with an issue link

What neither covers, and what genuinely needs ESLint: ``react-hooks/rules-of-hooks``
and ``react-hooks/exhaustive-deps``. Those are not emulated here; a regular
expression cannot see a dependency array's closure. The terminal carries 33
``eslint-disable-next-line react-hooks/exhaustive-deps`` comments that are inert
today, which is the argument for adding the real plugin - a separate change, since
it needs four new devDependencies and a regenerated ``pnpm-lock.yaml``.

Usage::

    python scripts/check-terminal-type-safety.py
    python scripts/check-terminal-type-safety.py --root packages/apps/site
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_DEFAULT_ROOT = pathlib.Path("packages/apps/terminal/src")

# Suppression pragmas. Matched against the RAW text: they live in comments, which
# is exactly why they have to be found before comments are stripped. The house
# rule permits them only with an issue link, so a bare pragma is a finding.
_PRAGMAS = (
    (re.compile(r"@ts-ignore"), "@ts-ignore is never permitted; fix the type or narrow it"),
    (
        re.compile(r"@ts-expect-error(?![^\n]*https?://)"),
        "@ts-expect-error needs an issue link on the same line",
    ),
)

# Explicit `any` in a type position. Matched against comment-stripped text, so
# prose like \"Direct broker mode: any unified BrokerAccount\" cannot trip it.
_ANY_PATTERNS = (
    re.compile(r":\s*any\b"),
    re.compile(r"\bas\s+any\b"),
    re.compile(r"<\s*any\s*>"),
    re.compile(r"\bany\s*\[\s*\]"),
    re.compile(r"<[^<>\n]*\bany\b[^<>\n]*>"),
)

_LINE_COMMENT = re.compile(r"//[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
# String and template literals, so a message such as `throw new Error("as any")`
# cannot be read as code. Deliberately conservative: an unmatched quote leaves
# the line intact, which can only produce a false positive a human then reads.
_STRING_LITERAL = re.compile(r"'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\"|`(?:\\.|[^`\\])*`", re.DOTALL)


def _blank_out(text: str, pattern: re.Pattern[str]) -> str:
    """Replace every match with newline-preserving blanks.

    Line numbers have to survive the strip, so each match becomes spaces with its
    newlines kept.

    Args:
        text: The source text.
        pattern: What to blank out.

    Returns:
        The text with matches replaced by whitespace of the same line shape.
    """
    return pattern.sub(lambda match: re.sub(r"[^\n]", " ", match.group(0)), text)


def _code_only(source: str) -> str:
    """Strip comments and literals, preserving line numbering.

    Args:
        source: The original file text.

    Returns:
        The text with comments and string literals blanked out.
    """
    stripped = _blank_out(source, _BLOCK_COMMENT)
    stripped = _blank_out(stripped, _LINE_COMMENT)
    return _blank_out(stripped, _STRING_LITERAL)


def _findings(path: pathlib.Path, relative: str) -> list[str]:
    """Return every violation in one file.

    Args:
        path: The file to read.
        relative: The repo-relative path, for the message.

    Returns:
        One ``path:line: message`` string per violation.
    """
    source = path.read_text(encoding="utf-8")
    findings: list[str] = []

    raw_lines = source.splitlines()
    for pattern, explanation in _PRAGMAS:
        for number, line in enumerate(raw_lines, start=1):
            if pattern.search(line):
                findings.append(f"{relative}:{number}: {explanation}")

    code_lines = _code_only(source).splitlines()
    for number, line in enumerate(code_lines, start=1):
        if not line.strip():
            continue
        if any(pattern.search(line) for pattern in _ANY_PATTERNS):
            findings.append(f"{relative}:{number}: explicit `any` is banned - type it, or use `unknown` and narrow")
    return findings


def main() -> int:
    """Scan the terminal source tree.

    Returns:
        ``1`` when anything was found, otherwise ``0``.
    """
    parser = argparse.ArgumentParser(description="Fail on explicit `any` or a type-check suppression.")
    parser.add_argument(
        "--root",
        type=pathlib.Path,
        default=_DEFAULT_ROOT,
        help="Directory to scan, absolute or repo-relative (default: packages/apps/terminal/src).",
    )
    args = parser.parse_args()

    root = args.root if args.root.is_absolute() else _REPO_ROOT / args.root
    label = args.root.as_posix()
    if not root.is_dir():
        print(f"FAIL: {label} is not a directory", file=sys.stderr)
        return 1

    findings: list[str] = []
    scanned = 0
    for path in sorted(root.rglob("*")):
        if path.suffix not in {".ts", ".tsx"} or not path.is_file():
            continue
        scanned += 1
        try:
            relative = path.relative_to(_REPO_ROOT).as_posix()
        except ValueError:
            relative = path.as_posix()
        findings.extend(_findings(path, relative))

    if findings:
        print(f"FAIL: {len(findings)} type-safety violation(s) across {scanned} files:", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        return 1

    print(f"OK: {scanned} TypeScript files under {label} carry no explicit `any` and no type-check suppression.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
