"""Contract tests for the zero-prerequisite web-app installers.

These are a *separate* pair of files from ``flinttrade-install.{sh,ps1}`` on
purpose: the desktop installers are forbidden from mentioning ``uv sync``,
``cargo`` or ``packages/apps/terminal`` (tests/test_desktop_install_scripts.py),
so the web installer could not be bolted onto them.

What is pinned here:

  * both files exist where the canonical URLs promise
    (``https://flinttrade.vercel.app/web-install.sh`` / ``.ps1``);
  * the POSIX script parses under ``bash -n`` and the PowerShell script parses
    under the real PowerShell parser;
  * the PowerShell script carries no ``&&`` and no bash-isms — it must run on
    stock Windows PowerShell 5.1, which has no pipeline-chain operator;
  * neither script escalates or reaches for a system package manager
    (``sudo``, ``apt-get``, ``brew``, ``choco``, ``winget``);
  * toolchain integrity comes from the pinned ``tool-manifest.json``, never from
    a SHA-256 copied into the installer where it silently rots;
  * every ``pnpm install`` is ``--frozen-lockfile``;
  * both delegate the build to ``flinttrade-bootstrap`` instead of duplicating it;
  * only the expected hosts are contacted, always over https;
  * the two scripts expose the same four flags under each platform's spelling.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

SH = _REPO_ROOT / "scripts" / "install" / "flinttrade-web-install.sh"
PS1 = _REPO_ROOT / "scripts" / "install" / "flinttrade-web-install.ps1"

BASH = shutil.which("bash")
NO_BASH_REASON = "bash is not available on this runner"
# The two engines diverge: pwsh (7+) accepts syntax Windows PowerShell 5.1
# rejects ('&&', ternary, '??'), and the one-liner `irm ... | iex` runs under
# whichever the operator has — so the parse gate must hold under BOTH, each
# skipping cleanly when absent rather than silently preferring pwsh.
PWSH = shutil.which("pwsh")
WINDOWS_POWERSHELL = shutil.which("powershell")
POWERSHELL = PWSH or WINDOWS_POWERSHELL
NO_POWERSHELL_REASON = "PowerShell (pwsh/powershell) is not available on this runner"

_BOOTSTRAP_SH = _REPO_ROOT / "packages/apps/desktop/resources/bootstrap/flinttrade-bootstrap.sh"
_BOOTSTRAP_PS1 = _REPO_ROOT / "packages/apps/desktop/resources/bootstrap/flinttrade-bootstrap.ps1"
_TOOL_MANIFEST = _REPO_ROOT / "packages/apps/desktop/resources/bootstrap/tool-manifest.json"

# Hosts the installers are allowed to reach. Anything else is either an exfiltration
# path or an unpinned mirror.
_ALLOWED_HOSTS = frozenset(
    {
        "codeload.github.com",
        "github.com",
        "api.github.com",
        "nodejs.org",
        "registry.npmjs.org",
    }
)

# Non-fetch hosts that legitimately appear as text. Each needs a reason.
_DOCUMENTED_NON_FETCH_HOSTS: dict[str, str] = {
    # The installer's own canonical distribution URL, echoed in the usage/--help banner
    # (`curl -fsSL https://flinttrade.vercel.app/web-install.sh | bash`).
    "flinttrade.vercel.app": "the installer's own one-line install URL, printed in help/usage text",
    # The canonical backend URL the installer tells the operator to open once FlintTrade
    # is running. Loopback, so it is deliberately http.
    "127.0.0.1": "the canonical loopback backend URL http://127.0.0.1:5100",
    "localhost": "loopback alias for the backend URL",
}

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

_URL_RE = re.compile(r"(https?)://([A-Za-z0-9._:-]+)")
_PNPM_INSTALL_RE = re.compile(r"\bpnpm\s+install\b")
_SHA256_LITERAL_RE = re.compile(r"\b[0-9a-fA-F]{64}\b")

# Package managers / privilege escalation an unprivileged per-user installer must never use.
_FORBIDDEN_TOOLS = ("sudo", "apt-get", "brew", "choco", "winget")

# Constructs that are POSIX shell, not Windows PowerShell 5.1.
_BASH_ISMS: dict[str, str] = {
    "&&": "Windows PowerShell 5.1 has no pipeline-chain operator; use separate lines or ';'",
    "||": "Windows PowerShell 5.1 has no '||' operator; use if/else or -or",
    "??": "the null-coalescing operator is PowerShell 7+, not 5.1",
    "/dev/null": "POSIX device path; use $null or Out-Null",
    "[[ ": "bash conditional expression; use if (...) / Test-Path",
    "export ": "bash environment export; use $env:NAME = 'value'",
}


def _strip_shell_comments(text: str, *, block_comments: bool = False) -> str:
    """Blank out comments so a literal scan sees only executable text.

    Both POSIX shells and PowerShell comment with ``#``, and a ``#`` only opens a
    comment at the start of a line or after whitespace. Quote tracking is per line,
    which keeps ``"a#b"`` and URL fragments intact.

    Args:
        text: Full script source.
        block_comments: Strip PowerShell ``<# ... #>`` blocks first.

    Returns:
        The source with comment text removed and line count preserved.
    """
    if block_comments:
        text = re.sub(r"<#.*?#>", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.DOTALL)

    out: list[str] = []
    for line in text.splitlines():
        single = double = False
        cut = len(line)
        for index, char in enumerate(line):
            if char == "'" and not double:
                single = not single
            elif char == '"' and not single:
                double = not double
            elif char == "#" and not single and not double and (index == 0 or line[index - 1].isspace()):
                cut = index
                break
        out.append(line[:cut])
    return "\n".join(out)


def _powershell_param_block(text: str) -> str:
    """Return the body of the script's top-level ``param(...)`` block.

    Args:
        text: Full PowerShell source.

    Returns:
        The text between the block's parentheses, or an empty string when absent.
    """
    match = re.search(r"\bparam\s*\(", text, flags=re.IGNORECASE)
    if match is None:
        return ""
    depth = 0
    start = match.end()
    for index in range(match.end() - 1, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return text[start:index]
    return ""


def _read(script: Path) -> str:
    assert script.is_file(), (
        f"{script.relative_to(_REPO_ROOT).as_posix()} is missing — it backs the canonical "
        "one-line install URL and must not be moved or renamed"
    )
    return script.read_text(encoding="utf-8")


@pytest.mark.unit
@pytest.mark.parametrize("script", [SH, PS1], ids=["web-install.sh", "web-install.ps1"])
def test_web_installers_exist_at_the_canonical_paths(script: Path) -> None:
    assert script.is_file(), f"missing {script.relative_to(_REPO_ROOT).as_posix()}"


@pytest.mark.unit
@pytest.mark.skipif(BASH is None, reason=NO_BASH_REASON)
def test_posix_web_installer_is_valid_bash() -> None:
    result = subprocess.run([BASH, "-n", str(SH)], cwd=_REPO_ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.unit
@pytest.mark.parametrize(
    "engine",
    [
        pytest.param(
            PWSH,
            id="pwsh",
            marks=pytest.mark.skipif(PWSH is None, reason="pwsh (PowerShell 7+) is not available on this runner"),
        ),
        pytest.param(
            WINDOWS_POWERSHELL,
            id="windows-powershell-5.1",
            marks=pytest.mark.skipif(
                WINDOWS_POWERSHELL is None,
                reason="powershell.exe (Windows PowerShell 5.1) is not available on this runner",
            ),
        ),
    ],
)
def test_windows_web_installer_parses(engine: str) -> None:
    script_path = str(PS1).replace("'", "''")
    result = subprocess.run(
        [
            engine,
            "-NoProfile",
            "-Command",
            "$errors = $null; "
            f"[void][System.Management.Automation.Language.Parser]::ParseFile('{script_path}', "
            "[ref]$null, [ref]$errors); "
            "if ($errors) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }",
        ],
        cwd=_REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.unit
def test_windows_web_installer_has_no_bash_isms() -> None:
    """The .ps1 must run on stock Windows PowerShell 5.1 — no POSIX constructs."""
    source = _strip_shell_comments(_read(PS1), block_comments=True)
    violations: list[str] = []
    for lineno, line in enumerate(source.splitlines(), 1):
        for token, why in _BASH_ISMS.items():
            if token in line:
                violations.append(f"{PS1.name}:{lineno}: {token!r} — {why} → {line.strip()}")

    assert not violations, "bash-isms in the Windows web installer:\n" + "\n".join(violations)


@pytest.mark.unit
@pytest.mark.parametrize("script", [SH, PS1], ids=["web-install.sh", "web-install.ps1"])
def test_web_installers_never_escalate_or_use_a_system_package_manager(script: Path) -> None:
    """The install is per-user: no admin rights, no OS package manager, no mirrors."""
    source = _strip_shell_comments(_read(script), block_comments=script.suffix == ".ps1")
    violations: list[str] = []
    for lineno, line in enumerate(source.splitlines(), 1):
        for tool in _FORBIDDEN_TOOLS:
            if re.search(rf"(?<![\w.-]){re.escape(tool)}(?![\w-])", line):
                violations.append(f"{script.name}:{lineno}: uses {tool!r} → {line.strip()}")

    assert not violations, (
        "The web installers must stay unprivileged and self-contained "
        f"(no {', '.join(_FORBIDDEN_TOOLS)}):\n" + "\n".join(violations)
    )


@pytest.mark.unit
@pytest.mark.parametrize("script", [SH, PS1], ids=["web-install.sh", "web-install.ps1"])
def test_web_installers_pin_the_toolchain_via_the_manifest(script: Path) -> None:
    """Integrity comes from tool-manifest.json, never from a hash pasted into the script."""
    source = _read(script)
    assert "tool-manifest.json" in source, (
        f"{script.name} must read the pinned packages/apps/desktop/resources/bootstrap/"
        "tool-manifest.json rather than carrying its own toolchain versions"
    )

    hardcoded = [
        f"{script.name}:{source.count(chr(10), 0, m.start()) + 1}: {m.group(0)}"
        for m in _SHA256_LITERAL_RE.finditer(source)
    ]
    assert not hardcoded, (
        f"{script.name} hardcodes SHA-256 digest(s); they rot silently when the manifest is "
        "regenerated. Read them from tool-manifest.json instead:\n" + "\n".join(hardcoded)
    )


@pytest.mark.unit
def test_pinned_tool_manifest_exists() -> None:
    assert _TOOL_MANIFEST.is_file(), (
        "the web installers reference tool-manifest.json; the pinned manifest must exist at "
        f"{_TOOL_MANIFEST.relative_to(_REPO_ROOT).as_posix()}"
    )


@pytest.mark.unit
@pytest.mark.parametrize("script", [SH, PS1], ids=["web-install.sh", "web-install.ps1"])
def test_web_installer_pnpm_installs_are_frozen(script: Path) -> None:
    source = _strip_shell_comments(_read(script), block_comments=script.suffix == ".ps1")
    violations = [
        f"{script.name}:{lineno}: {line.strip()}"
        for lineno, line in enumerate(source.splitlines(), 1)
        if _PNPM_INSTALL_RE.search(line) and "--frozen-lockfile" not in line
    ]
    assert not violations, "pnpm install without --frozen-lockfile:\n" + "\n".join(violations)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("script", "bootstrap"),
    [(SH, _BOOTSTRAP_SH), (PS1, _BOOTSTRAP_PS1)],
    ids=["web-install.sh", "web-install.ps1"],
)
def test_web_installers_delegate_the_build_to_the_bootstrap(script: Path, bootstrap: Path) -> None:
    """One build sequence, owned by flinttrade-bootstrap — the installers only call it."""
    source = _read(script)
    assert bootstrap.is_file(), f"missing {bootstrap.relative_to(_REPO_ROOT).as_posix()}"
    assert bootstrap.name in source, (
        f"{script.name} must delegate to {bootstrap.name} instead of duplicating the build sequence"
    )

    body = _strip_shell_comments(source, block_comments=script.suffix == ".ps1")
    duplicated = [
        f"{script.name}:{lineno}: {line.strip()}"
        for lineno, line in enumerate(body.splitlines(), 1)
        if re.search(r"\buv\s+sync\b|\bcargo\s+(build|run|test)\b|\belectron-builder\b|\bvite\s+build\b", line)
    ]
    assert not duplicated, (
        f"{script.name} re-implements build steps that belong to {bootstrap.name}:\n"
        + "\n".join(duplicated)
    )


@pytest.mark.unit
@pytest.mark.parametrize("script", [SH, PS1], ids=["web-install.sh", "web-install.ps1"])
def test_web_installers_only_reach_expected_hosts_over_https(script: Path) -> None:
    source = _read(script)
    bad_host: list[str] = []
    plaintext: list[str] = []
    for match in _URL_RE.finditer(source):
        scheme, authority = match.group(1), match.group(2)
        host = authority.split(":")[0].lower()
        lineno = source.count("\n", 0, match.start()) + 1
        if host not in _ALLOWED_HOSTS and host not in _DOCUMENTED_NON_FETCH_HOSTS:
            bad_host.append(f"{script.name}:{lineno}: {scheme}://{authority}")
        if scheme != "https" and host not in _LOOPBACK_HOSTS:
            plaintext.append(f"{script.name}:{lineno}: {scheme}://{authority}")

    assert not bad_host, (
        "The web installers may only contact "
        f"{', '.join(sorted(_ALLOWED_HOSTS))}:\n" + "\n".join(bad_host)
    )
    assert not plaintext, (
        "Every non-loopback URL in the web installers must be https://:\n" + "\n".join(plaintext)
    )


@pytest.mark.unit
@pytest.mark.parametrize("flag", ["--help", "--dry-run", "--yes", "--no-launch"])
def test_posix_web_installer_supports_the_shared_flags(flag: str) -> None:
    assert flag in _read(SH), f"scripts/install/flinttrade-web-install.sh does not accept {flag}"


@pytest.mark.unit
@pytest.mark.parametrize("parameter", ["Help", "DryRun", "Yes", "NoLaunch"])
def test_windows_web_installer_supports_the_shared_flags(parameter: str) -> None:
    block = _powershell_param_block(_read(PS1))
    assert block, "scripts/install/flinttrade-web-install.ps1 has no param(...) block"
    assert re.search(rf"\${parameter}\b", block), (
        f"scripts/install/flinttrade-web-install.ps1 does not declare -{parameter}; the .sh and "
        ".ps1 installers must stay at flag parity (--help/-Help, --dry-run/-DryRun, "
        "--yes/-Yes, --no-launch/-NoLaunch)"
    )
