"""Docs gate: shell snippets in tracked Markdown must run on the OS they claim.

This guards the reported bug class rather than a single defect. Two shapes of the
same mistake keep shipping:

  1. A ``bash``/``sh``/``powershell`` fence chains commands with ``&&``. Stock
     Windows PowerShell 5.1 has no pipeline-chain operator, so every such line is
     a parse error for the Windows reader who is being told to paste it.
  2. A ``powershell`` fence prescribes ``make <target>``. ``make`` is not
     installed on Windows and the Makefile itself says its targets need WSL2 —
     that is the docs/setup/windows.md defect this file pins shut.

It also pins the canonical one-line install/uninstall contract into readme.md and
requires every per-OS setup page to tell the reader how to remove FlintTrade.

The scan walks tracked files via ``git ls-files`` (not a filesystem glob) so that
untracked scratch notes, build output and vendored trees are never scanned.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from fnmatch import fnmatch
from functools import lru_cache
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Fences whose contents are commands a reader is expected to paste into a shell.
_SHELL_LANGS = frozenset(
    {"bash", "sh", "shell", "zsh", "console", "shell-session", "powershell", "pwsh", "ps", "ps1"}
)
# The subset that claims to be Windows PowerShell.
_POWERSHELL_LANGS = frozenset({"powershell", "pwsh", "ps", "ps1"})

_FENCE_RE = re.compile(r"^(`{3,}|~{3,})(.*)$")

# `make`, `make foo`, `; make foo`, `| make foo` — i.e. make in command position.
_MAKE_COMMAND_RE = re.compile(r"(?:^|[;|&(]\s*)make(?:\s|$)")

# ---------------------------------------------------------------------------
# Allowlist: fences that are legitimately POSIX-only.
#
# Each entry is a (glob, reason) pair. Keep this list small — an entry here means
# the file's shell snippets are exempt from the `&&` rule, so only add documents
# whose audience is provably a POSIX shell.
# ---------------------------------------------------------------------------
_AMPERSAND_ALLOWLIST: tuple[tuple[str, str], ...] = (
    (
        "CLAUDE.md",
        # Agent/maintainer guidance, not a user-facing setup page. Its snippets mirror the
        # POSIX Makefile aliases run on the maintainer's macOS/Linux shell; Windows
        # contributors are pointed at `python scripts/ft.py` by docs/setup/windows.md.
        "agent-facing repo guide; mirrors POSIX-only Makefile aliases, never pasted by a Windows user",
    ),
    (
        "docs/superpowers/specs/*.md",
        # Frozen design specs describing deployment onto a Linux host (`cd /opt/flinttrade &&
        # make setup`). They are a record of a decision, not instructions anyone follows today.
        "frozen design specs describing Linux server deployment; historical record, not user instructions",
    ),
    (
        "flinttrade-design/baselines/*.md",
        # Dated rollback runbooks. They record verbatim what was executed on the Linux
        # release host on a specific day; rewriting them would falsify the record.
        "dated rollback runbooks recording verbatim Linux release-host commands; immutable by design",
    ),
)

# Intentionally empty. `make` inside a ```powershell fence is the exact reported defect;
# there is no legitimate case for it, because `make` does not exist on Windows and the
# cross-platform runner (`python scripts/ft.py` / `flinttrade <subcommand>`) covers every
# target. Add an entry here only with a written justification.
_MAKE_IN_POWERSHELL_ALLOWLIST: tuple[tuple[str, str], ...] = ()

# The canonical contract strings. These are verbatim by design — paraphrasing them is
# the failure mode this test exists to catch.
_WEB_INSTALL_POSIX = "curl -fsSL https://flinttrade.vercel.app/web-install.sh | bash"
_WEB_INSTALL_WINDOWS = "irm https://flinttrade.vercel.app/web-install.ps1 | iex"
_UNINSTALL_POSIX = "curl -fsSL https://flinttrade.vercel.app/uninstall.sh | bash"
_UNINSTALL_WINDOWS = "irm https://flinttrade.vercel.app/uninstall.ps1 | iex"


@lru_cache(maxsize=1)
def _tracked_paths() -> tuple[str, ...]:
    """Return every tracked repo-relative path, or an empty tuple when git is unusable."""
    git = shutil.which("git")
    if git is None:
        return ()
    result = subprocess.run(
        [git, "ls-files", "-z"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ()
    return tuple(entry for entry in result.stdout.split("\0") if entry)


def _tracked_markdown() -> tuple[Path, ...]:
    return tuple(
        _REPO_ROOT / rel
        for rel in _tracked_paths()
        if rel.endswith(".md") and (_REPO_ROOT / rel).is_file()
    )


def _require_git_listing() -> tuple[Path, ...]:
    docs = _tracked_markdown()
    if not docs:
        pytest.skip("git ls-files returned nothing (git unavailable or not a work tree)")
    return docs


def _normalise_lang(info: str) -> str:
    """Reduce a fence info string to a bare language tag.

    Handles ```bash, ```{bash}, ```.bash and ```bash title="x".

    Args:
        info: The raw info string that followed the opening fence marker.

    Returns:
        The lower-cased language tag, or an empty string when the fence is untagged.
    """
    token = info.strip().split()[0] if info.strip() else ""
    return token.strip("{}").lstrip(".").lower()


def _iter_fences(text: str) -> list[tuple[str, int, list[tuple[int, str]]]]:
    """Split Markdown into fenced blocks, tracking the opening marker and language.

    A fence closes only on the same marker character with at least the same run
    length and no info string, so a ``` line inside a ~~~ block stays content.

    Args:
        text: Full Markdown document text.

    Returns:
        A list of ``(language, opening_line_number, [(line_number, line), ...])``.
    """
    fences: list[tuple[str, int, list[tuple[int, str]]]] = []
    marker_char = ""
    marker_len = 0
    lang = ""
    opened_at = 0
    body: list[tuple[int, str]] = []
    inside = False

    for lineno, line in enumerate(text.splitlines(), 1):
        match = _FENCE_RE.match(line.lstrip())
        if not inside:
            if match:
                marker_char, marker_len = match.group(1)[0], len(match.group(1))
                lang = _normalise_lang(match.group(2))
                opened_at = lineno
                body = []
                inside = True
            continue
        closes = (
            match is not None
            and match.group(1)[0] == marker_char
            and len(match.group(1)) >= marker_len
            and not match.group(2).strip()
        )
        if closes:
            fences.append((lang, opened_at, body))
            inside = False
            continue
        body.append((lineno, line))

    if inside:  # unterminated fence — still worth scanning
        fences.append((lang, opened_at, body))
    return fences


def _strip_comment(line: str) -> str:
    """Drop a trailing ``#`` comment, honouring single and double quotes.

    Both POSIX shells and PowerShell comment with ``#``, so one stripper serves both.
    A ``#`` only opens a comment at the start of the line or after whitespace, which
    keeps URL fragments and ``$#`` intact.

    Args:
        line: A single line taken from a shell fence.

    Returns:
        The line with any comment tail removed.
    """
    single = double = False
    for index, char in enumerate(line):
        if char == "'" and not double:
            single = not single
        elif char == '"' and not single:
            double = not double
        elif char == "#" and not single and not double:
            if index == 0 or line[index - 1].isspace():
                return line[:index]
    return line


def _allowlisted(rel_path: str, allowlist: tuple[tuple[str, str], ...]) -> bool:
    return any(fnmatch(rel_path, pattern) for pattern, _ in allowlist)


@pytest.mark.unit
def test_shell_fences_never_chain_with_ampersand() -> None:
    """`&&` in a shell fence is a parse error for every Windows PowerShell 5.1 reader."""
    docs = _require_git_listing()
    violations: list[str] = []
    for path in docs:
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if _allowlisted(rel, _AMPERSAND_ALLOWLIST):
            continue
        for lang, _opened_at, body in _iter_fences(path.read_text(encoding="utf-8")):
            if lang not in _SHELL_LANGS:
                continue
            for lineno, line in body:
                if "&&" in _strip_comment(line):
                    violations.append(f"{rel}:{lineno}: ```{lang} fence chains with '&&' → {line.strip()}")

    assert not violations, (
        "Shell fences must not chain commands with '&&' (Windows PowerShell 5.1 has no "
        "chain operator — put each command on its own line, or separate with ';'):\n"
        + "\n".join(violations)
    )


@pytest.mark.unit
def test_powershell_fences_never_prescribe_make() -> None:
    """`make` does not exist on Windows; PowerShell blocks must use the runner instead."""
    docs = _require_git_listing()
    violations: list[str] = []
    for path in docs:
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if _allowlisted(rel, _MAKE_IN_POWERSHELL_ALLOWLIST):
            continue
        for lang, _opened_at, body in _iter_fences(path.read_text(encoding="utf-8")):
            if lang not in _POWERSHELL_LANGS:
                continue
            for lineno, line in body:
                command = _strip_comment(line).strip()
                if command and _MAKE_COMMAND_RE.search(command):
                    violations.append(f"{rel}:{lineno}: ```{lang} fence runs make → {command}")

    assert not violations, (
        "PowerShell fences must not prescribe `make` targets. Use the cross-platform runner:\n"
        "  python scripts/ft.py <start|stop|restart|status|dev|setup|test|lint|clean|version|help"
        "|desktop-test|desktop-build|desktop-package|desktop-dev>\n"
        "(after install the shim exposes the same subcommands as `flinttrade <subcommand>`).\n"
        + "\n".join(violations)
    )


@pytest.mark.unit
def test_allowlist_globs_still_match_tracked_files() -> None:
    """A typo'd or renamed-away allowlist entry is a silent hole — surface it."""
    tracked = _tracked_paths()
    if not tracked:
        pytest.skip("git ls-files returned nothing (git unavailable or not a work tree)")

    dead = [
        f"{pattern}: matches no tracked file ({reason})"
        for allowlist in (_AMPERSAND_ALLOWLIST, _MAKE_IN_POWERSHELL_ALLOWLIST)
        for pattern, reason in allowlist
        if not any(fnmatch(rel, pattern) for rel in tracked)
    ]

    assert not dead, "Allowlist entries that match nothing — fix or remove them:\n" + "\n".join(dead)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("label", "command"),
    [
        ("one-line install (macOS / Linux)", _WEB_INSTALL_POSIX),
        ("one-line install (Windows 10/11)", _WEB_INSTALL_WINDOWS),
        ("one-line uninstall (macOS / Linux)", _UNINSTALL_POSIX),
        ("one-line uninstall (Windows 10/11)", _UNINSTALL_WINDOWS),
    ],
)
def test_readme_carries_the_canonical_one_line_commands(label: str, command: str) -> None:
    readme = _REPO_ROOT / "readme.md"
    assert readme.is_file(), "root docs stay lowercase — readme.md must exist (never README.md)"
    text = readme.read_text(encoding="utf-8")
    assert command in text, f"readme.md is missing the verbatim {label} command: {command}"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("page", "command"),
    [
        ("docs/setup/windows.md", _UNINSTALL_WINDOWS),
        ("docs/setup/macos.md", _UNINSTALL_POSIX),
        ("docs/setup/linux.md", _UNINSTALL_POSIX),
    ],
)
def test_every_per_os_setup_page_documents_uninstall(page: str, command: str) -> None:
    path = _REPO_ROOT / page
    assert path.is_file(), f"{page} is missing"
    text = path.read_text(encoding="utf-8")
    assert command in text, (
        f"{page} must document how to remove FlintTrade with the canonical command: {command}"
    )
