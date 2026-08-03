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
  * the two scripts expose the same four flags under each platform's spelling;
  * nothing the web install writes collides with the Electron desktop install —
    not the launcher, not the Start Menu entry, not the source checkout — so the
    two documented one-liners can be run on one machine in either order.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

SH = _REPO_ROOT / "scripts" / "install" / "flinttrade-web-install.sh"
PS1 = _REPO_ROOT / "scripts" / "install" / "flinttrade-web-install.ps1"
DESKTOP_SH = _REPO_ROOT / "scripts" / "install" / "flinttrade-install.sh"
DESKTOP_PS1 = _REPO_ROOT / "scripts" / "install" / "flinttrade-install.ps1"
UNINSTALL_SH = _REPO_ROOT / "scripts" / "install" / "flinttrade-uninstall.sh"
UNINSTALL_PS1 = _REPO_ROOT / "scripts" / "install" / "flinttrade-uninstall.ps1"

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
GIT = shutil.which("git")
NO_GIT_REASON = "git is not available on this runner"

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


def _staged_windows_installer(tmp_path: Path, *, elevated: bool) -> Path:
    """Stage the installer with a deterministic token state for behavioural tests."""
    staged_installer = tmp_path / PS1.name
    staged_source = _read(PS1).replace(
        "\nInvoke-FlintTradeWebInstall\n",
        (
            "\nfunction Test-FlintTradeProcessIsElevated "
            f"{{ return ${str(elevated).lower()} }}\n"
            "Invoke-FlintTradeWebInstall\n"
        ),
        1,
    )
    staged_installer.write_text(staged_source, encoding="utf-8")
    return staged_installer


def _staged_windows_installer_harness(tmp_path: Path, body: str) -> Path:
    """Stage the real installer functions with a focused test entry point."""
    staged_installer = tmp_path / "flinttrade-web-install-harness.ps1"
    source = _read(PS1)
    sentinel = "\nInvoke-FlintTradeWebInstall\n"
    assert source.count(sentinel) == 1, "the installer entry-point sentinel changed"
    staged_source = source.replace(
        sentinel,
        f"\n{body.rstrip()}\n",
        1,
    )
    staged_installer.write_text(staged_source, encoding="utf-8")
    return staged_installer


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


# ---------------------------------------------------------------------------
# Managed source identity.
#
# A git-less refresh deletes --src recursively before publishing the downloaded
# checkout, so whatever authorises that deletion decides whether an operator's
# unrelated source survives a typo. Two questions decide it, and they have
# different answers:
#
#   * IS THIS FLINTTRADE'S CODE?  Repository markers answer that — and every
#     contributor clone of this repository carries all of them, because
#     flint.toml, pyproject.toml and pnpm-workspace.yaml are checked in;
#   * DID THIS INSTALLER CREATE IT?  Only its own receipt answers that.
#
# So markers may authorise an in-place 'git fetch' + 'git reset --hard' on a
# clean checkout and nothing more; the recursive replacement needs the receipt.
# ---------------------------------------------------------------------------

_REPO_SLUG = "navaneeshnagarajan/FlintTrade"
NOT_POSIX_REASON = "the POSIX installer requires POSIX absolute paths for its --src guard"
# Linux runners ship pwsh, so a PowerShell-available check is not enough on its own:
# these cases drive -SrcDir with a Windows absolute path and rely on
# [Environment]::GetFolderPath resolving AppData under a redirected USERPROFILE,
# neither of which holds when pwsh runs on Linux.
NOT_WINDOWS_REASON = "the Windows installer's path guards need Windows path semantics"


def _posix_modes_honoured() -> bool:
    """Whether the temp filesystem stores POSIX permission bits.

    The receipt reader refuses anything that is not 0700/0600, which a Windows
    filesystem can never report, so tests that plant a receipt would fail for a
    reason that has nothing to do with the installer.

    Returns:
        ``True`` when a directory chmod-ed to 0700 reads back as 0700.
    """
    with tempfile.TemporaryDirectory() as raw:
        probe = Path(raw) / "probe"
        probe.mkdir()
        probe.chmod(0o700)
        return (probe.stat().st_mode & 0o777) == 0o700


POSIX_MODES = _posix_modes_honoured()
NO_POSIX_MODES_REASON = "the web-install receipt requires a filesystem that honours POSIX modes"


def _fake_posix_bin(tmp_path: Path) -> str:
    """Return a PATH whose ``uname`` reports a supported Linux x64 host.

    Args:
        tmp_path: Per-test temporary directory.

    Returns:
        A PATH value that puts the stub ahead of the system directories.
    """
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    uname = bin_dir / "uname"
    uname.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"-m\" ]; then printf '%s\\n' x86_64; else printf '%s\\n' Linux; fi\n",
        encoding="utf-8",
        newline="\n",
    )
    uname.chmod(0o755)
    return f"{bin_dir}{os.pathsep}/usr/bin:/bin"


def _dry_run_install(tmp_path: Path, src: Path) -> subprocess.CompletedProcess[str]:
    """Run the POSIX web installer against ``src`` without touching the network."""
    return subprocess.run(
        [BASH, str(SH)],
        cwd=_REPO_ROOT,
        env={
            "PATH": _fake_posix_bin(tmp_path),
            "HOME": str(tmp_path),
            "FLINTTRADE_WEB_SRC_DIR": str(src),
            "FLINTTRADE_DRY_RUN": "1",
            "FLINTTRADE_YES": "1",
        },
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )


def _generic_mixed_project(root: Path) -> Path:
    """Create the two-file shape any Python/JS project on the machine satisfies."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "package.json").write_text("{}", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname = 'somebody-elses-work'\n", encoding="utf-8")
    (root / "main.py").write_text("print('irreplaceable')\n", encoding="utf-8")
    return root


def _marker_only_clone(root: Path) -> Path:
    """Create what every contributor clone of this repository looks like.

    Args:
        root: Directory to populate.

    Returns:
        The populated directory.
    """
    _generic_mixed_project(root)
    (root / "flint.toml").write_text(
        f'[project]\nname = "FlintTrade"\nrepository = "https://github.com/{_REPO_SLUG}"\n',
        encoding="utf-8",
    )
    return root


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run git inside ``root``.

    Args:
        root: Working directory for the command.
        *args: Arguments after the executable.

    Returns:
        The completed process.
    """
    assert GIT is not None
    return subprocess.run([GIT, *args], cwd=str(root), text=True, capture_output=True)


def _committed_marker_clone(root: Path) -> Path:
    """Create a clean contributor clone: FlintTrade's markers, all committed.

    Args:
        root: Directory to populate.

    Returns:
        The populated Git checkout.
    """
    _marker_only_clone(root)
    _git(root, "init", "-q", "-b", "main", ".")
    _git(root, "config", "user.email", "tests@flinttrade.invalid")
    _git(root, "config", "user.name", "FlintTrade tests")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "contributor clone")
    return root


def _plant_web_receipt(home: Path, *, source: Path) -> Path:
    """Plant the owner-private receipt a previous run of this installer wrote.

    Args:
        home: Fake ``$HOME`` for the installer run.
        source: Managed source checkout the receipt records.

    Returns:
        The receipt file that was written.
    """
    state = home / ".local" / "state" / "flinttrade-web"
    state.mkdir(parents=True, exist_ok=True)
    state.chmod(0o700)
    receipt = state / "web-install.receipt"
    receipt.write_text(
        "\n".join(
            (
                "format=flinttrade-web-install-v1",
                "platform=Linux",
                f"shim={(home / '.local' / 'bin' / 'flinttrade-web').as_posix()}",
                f"shim_sha256={'0' * 64}",
                "shortcut=",
                f"source={source.as_posix()}",
                f"tools={(home / '.flinttrade' / 'tools').as_posix()}",
            )
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    receipt.chmod(0o600)
    return receipt


@pytest.mark.unit
@pytest.mark.skipif(BASH is None, reason=NO_BASH_REASON)
@pytest.mark.skipif(os.name != "posix", reason=NOT_POSIX_REASON)
def test_posix_web_installer_refuses_a_src_that_does_not_prove_flinttrade_identity(tmp_path: Path) -> None:
    """A reused or mistyped --src holding unrelated source must never be replaced."""
    src = _generic_mixed_project(tmp_path / "someone-elses-project")
    result = _dry_run_install(tmp_path, src)

    assert result.returncode != 0, result.stdout + result.stderr
    assert "nothing there proves it is a FlintTrade checkout" in result.stderr
    assert (src / "main.py").exists(), "the installer touched an unproven source directory"


@pytest.mark.unit
@pytest.mark.skipif(BASH is None, reason=NO_BASH_REASON)
@pytest.mark.skipif(os.name != "posix", reason=NOT_POSIX_REASON)
@pytest.mark.skipif(not POSIX_MODES, reason=NO_POSIX_MODES_REASON)
def test_posix_web_installer_replaces_only_a_src_its_own_receipt_names(tmp_path: Path) -> None:
    """The receipt is the only proof that this installer created the directory."""
    src = _generic_mixed_project(tmp_path / "checkout")
    _plant_web_receipt(tmp_path, source=src)

    result = _dry_run_install(tmp_path, src)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "nothing there proves it is a FlintTrade checkout" not in result.stderr
    assert "updated in place" not in result.stdout, (
        "a receipt-proved checkout is the installer's own and may be replaced outright"
    )


@pytest.mark.unit
@pytest.mark.skipif(BASH is None, reason=NO_BASH_REASON)
@pytest.mark.skipif(os.name != "posix", reason=NOT_POSIX_REASON)
@pytest.mark.skipif(GIT is None, reason=NO_GIT_REASON)
def test_posix_web_installer_updates_a_marker_only_checkout_in_place(tmp_path: Path) -> None:
    """Markers prove the code, so the clone is refreshed with git — never deleted."""
    src = _committed_marker_clone(tmp_path / "contributor-clone")

    result = _dry_run_install(tmp_path, src)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "updated in place" in result.stdout, (
        "a clean FlintTrade clone must be refreshed with git fetch + reset, not replaced"
    )
    assert (src / "main.py").exists()


@pytest.mark.unit
@pytest.mark.skipif(BASH is None, reason=NO_BASH_REASON)
@pytest.mark.skipif(os.name != "posix", reason=NOT_POSIX_REASON)
@pytest.mark.skipif(GIT is None, reason=NO_GIT_REASON)
def test_posix_web_installer_refuses_a_marker_only_checkout_holding_uncommitted_work(
    tmp_path: Path,
) -> None:
    """'git reset --hard' would silently destroy a contributor's working tree."""
    src = _committed_marker_clone(tmp_path / "contributor-clone")
    (src / "main.py").write_text("print('a week of unpushed work')\n", encoding="utf-8")

    result = _dry_run_install(tmp_path, src)

    assert result.returncode != 0, result.stdout + result.stderr
    assert "uncommitted changes" in result.stderr
    assert "print('a week of unpushed work')" in (src / "main.py").read_text(encoding="utf-8")


@pytest.mark.unit
@pytest.mark.skipif(BASH is None, reason=NO_BASH_REASON)
@pytest.mark.skipif(os.name != "posix", reason=NOT_POSIX_REASON)
def test_posix_web_installer_refuses_a_marker_only_tree_that_git_cannot_update(tmp_path: Path) -> None:
    """Without a Git checkout the only way to 'update' is rm -rf, which markers never authorise."""
    src = _marker_only_clone(tmp_path / "unpacked-copy")

    result = _dry_run_install(tmp_path, src)

    assert result.returncode != 0, result.stdout + result.stderr
    assert "could only be replaced wholesale" in result.stderr
    assert "markers prove the CODE is this" in result.stderr, (
        "the refusal must say precisely which proof was missing"
    )
    assert (src / "main.py").exists(), "the installer touched a directory it could not prove it owns"


@pytest.mark.unit
@pytest.mark.skipif(BASH is None, reason=NO_BASH_REASON)
@pytest.mark.skipif(os.name != "posix", reason=NOT_POSIX_REASON)
@pytest.mark.parametrize("state", ["empty", "absent"])
def test_posix_web_installer_still_accepts_an_empty_or_absent_src(tmp_path: Path, state: str) -> None:
    """The guard must not widen: there is nothing to destroy in an empty directory."""
    src = tmp_path / "managed"
    if state == "empty":
        src.mkdir()
    result = _dry_run_install(tmp_path, src)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "nothing there proves it is a FlintTrade checkout" not in result.stderr


@pytest.mark.unit
def test_windows_web_installer_requires_the_same_source_identity_proof() -> None:
    """The .ps1 mirrors the .sh guard rather than trusting a generic project shape."""
    source = _read(PS1)
    for helper in ("Test-WebReceiptNamesSource", "Test-FlintTradeSourceMarkers"):
        assert helper in source, (
            f"flinttrade-web-install.ps1 must prove FlintTrade identity with {helper} before it "
            "replaces an existing source directory"
        )

    body = _strip_shell_comments(source, block_comments=True)
    guard = body[body.index("function Assert-SourceDirSafe") :]
    guard = guard[: guard.index("\nfunction ")] if "\nfunction " in guard else guard
    assert "Test-WebReceiptNamesSource" in guard and "Test-FlintTradeSourceMarkers" in guard, (
        "Assert-SourceDirSafe must consult the identity proofs, not just the directory shape"
    )
    assert 'Join-Path $script:SrcDir "package.json"' not in guard, (
        "package.json + pyproject.toml is every mixed Python/JS project; it cannot authorise "
        "deleting the operator's directory"
    )


@pytest.mark.unit
@pytest.mark.skipif(WINDOWS_POWERSHELL is None, reason="powershell.exe is not available on this runner")
def test_windows_web_installer_refuses_elevated_execution_before_source_acquisition(
    tmp_path: Path,
) -> None:
    """An Administrator shell must fail before the per-user installer writes anything."""
    source = _generic_mixed_project(tmp_path / "operator-source")
    sentinel = source / "main.py"
    profile = tmp_path / "profile"
    staged_installer = _staged_windows_installer(tmp_path, elevated=True)

    result = subprocess.run(
        [
            WINDOWS_POWERSHELL,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(staged_installer),
            "-Yes",
            "-NoLaunch",
            "-SrcDir",
            str(source),
        ],
        cwd=_REPO_ROOT,
        env=_windows_home_env(profile),
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert (
        "Close this Administrator PowerShell window and rerun the command in a normal PowerShell window."
        in combined
    ), combined
    assert sentinel.read_text(encoding="utf-8") == "print('irreplaceable')\n"
    assert not (profile / ".flinttrade").exists()


@pytest.mark.unit
@pytest.mark.skipif(WINDOWS_POWERSHELL is None, reason="powershell.exe is not available on this runner")
def test_windows_web_installer_allows_help_when_elevated(tmp_path: Path) -> None:
    """Help remains usable because it exits before any PATH-resolved command can run."""
    profile = tmp_path / "profile"
    staged_installer = _staged_windows_installer(tmp_path, elevated=True)

    command = [
        WINDOWS_POWERSHELL,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(staged_installer),
        "-Help",
    ]
    result = subprocess.run(
        command,
        cwd=_REPO_ROOT,
        env=_windows_home_env(profile),
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )

    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "Flags:" in combined, combined
    assert "Close this Administrator PowerShell window" not in combined, combined
    assert not (profile / ".flinttrade").exists()


@pytest.mark.unit
@pytest.mark.skipif(WINDOWS_POWERSHELL is None, reason="powershell.exe is not available on this runner")
def test_windows_web_installer_refuses_elevated_dry_run_before_path_probes(tmp_path: Path) -> None:
    """Dry-run must not execute user-writable PATH commands with an elevated token."""
    profile = tmp_path / "profile"
    marker = tmp_path / "path-command-ran"
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    (fake_bin / "git.cmd").write_text(
        f'@echo off\r\n> "{marker}" echo unsafe\r\necho git version 2.0\r\n',
        encoding="utf-8",
    )
    staged_installer = _staged_windows_installer(tmp_path, elevated=True)

    env = _windows_home_env(profile)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        [
            WINDOWS_POWERSHELL,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(staged_installer),
            "-DryRun",
            "-Yes",
            "-NoLaunch",
            "-SrcDir",
            str(profile / "planned-source"),
        ],
        cwd=_REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "Close this Administrator PowerShell window" in combined, combined
    assert not marker.exists(), "elevated dry-run executed a PATH-resolved command"
    assert not (profile / ".flinttrade").exists()


@pytest.mark.unit
@pytest.mark.skipif(WINDOWS_POWERSHELL is None, reason="powershell.exe is not available on this runner")
def test_windows_web_receipt_directory_hardening_is_idempotent(tmp_path: Path) -> None:
    """A reinstall must reapply and verify the owner-only DACL without a privilege warning."""
    target = tmp_path / "receipt-state"
    harness = _staged_windows_installer_harness(
        tmp_path,
        r"""
$target = $env:FLINTTRADE_ACL_TEST_PATH
[void](New-Item -ItemType Directory -Force -Path $target)
Protect-WebReceiptDirectory $target
Protect-WebReceiptDirectory $target
$acl = Get-Acl -LiteralPath $target
$rules = @($acl.Access)
$currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$ownerSid = $acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value
$ruleSid = if ($rules.Count -eq 1) {
    $rules[0].IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
} else { "" }
$expectedInheritance = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
    [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
if (-not $acl.AreAccessRulesProtected -or $ownerSid -ne $currentSid -or $rules.Count -ne 1 -or
    $rules[0].IsInherited -or $ruleSid -ne $currentSid -or
    $rules[0].FileSystemRights -ne [System.Security.AccessControl.FileSystemRights]::FullControl -or
    $rules[0].InheritanceFlags -ne $expectedInheritance -or
    $rules[0].PropagationFlags -ne [System.Security.AccessControl.PropagationFlags]::None -or
    $rules[0].AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow) {
    throw "receipt directory is not protected by one current-user FullControl rule"
}
Write-Output "ACL_OK"
""",
    )
    env = os.environ.copy()
    env["FLINTTRADE_ACL_TEST_PATH"] = str(target)

    result = subprocess.run(
        [WINDOWS_POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        cwd=_REPO_ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )

    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "ACL_OK" in combined, combined
    assert "Could not restrict" not in combined, combined
    assert "SeSecurityPrivilege" not in combined, combined


@pytest.mark.unit
@pytest.mark.skipif(WINDOWS_POWERSHELL is None, reason="powershell.exe is not available on this runner")
def test_windows_web_receipt_hardening_failure_stops_the_installer(tmp_path: Path) -> None:
    """A receipt must never be published after its owner-only DACL cannot be established."""
    target = tmp_path / "not-a-directory"
    target.write_text("ordinary file", encoding="utf-8")
    harness = _staged_windows_installer_harness(
        tmp_path,
        r"""
Protect-WebReceiptDirectory $env:FLINTTRADE_ACL_TEST_PATH
Write-Output "UNSAFE_CONTINUATION"
""",
    )
    env = os.environ.copy()
    env["FLINTTRADE_ACL_TEST_PATH"] = str(target)

    result = subprocess.run(
        [WINDOWS_POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        cwd=_REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "UNSAFE_CONTINUATION" not in combined, combined


@pytest.mark.unit
@pytest.mark.skipif(WINDOWS_POWERSHELL is None, reason="powershell.exe is not available on this runner")
def test_windows_web_installer_refuses_to_rewrite_an_existing_permissive_receipt(tmp_path: Path) -> None:
    """Hardening after reading cannot make previously writable receipt contents trustworthy."""
    receipt_dir = tmp_path / "receipt-state"
    receipt_dir.mkdir()
    receipt = receipt_dir / "web-install.receipt"
    receipt.write_text("untrusted old contents", encoding="utf-8")
    shim = tmp_path / "flinttrade-web.cmd"
    shim.write_text("@echo off\r\n", encoding="utf-8")
    source = tmp_path / "source"
    tools = tmp_path / "tools"
    source.mkdir()
    tools.mkdir()
    harness = _staged_windows_installer_harness(
        tmp_path,
        r"""
$WebReceiptDir = $env:FLINTTRADE_ACL_TEST_DIR
$WebReceiptPath = Join-Path $WebReceiptDir "web-install.receipt"
$ShimPath = $env:FLINTTRADE_ACL_TEST_SHIM
$StartMenuShortcut = Join-Path $WebReceiptDir "missing-shortcut.lnk"
$script:SrcDir = $env:FLINTTRADE_ACL_TEST_SOURCE
$ToolsRoot = $env:FLINTTRADE_ACL_TEST_TOOLS
$insecure = Get-Acl -LiteralPath $WebReceiptPath
$insecure.SetAccessRuleProtection($true, $false)
foreach ($existing in @($insecure.Access)) { [void]$insecure.RemoveAccessRule($existing) }
$everyone = New-Object System.Security.Principal.SecurityIdentifier("S-1-1-0")
$everyoneRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    $everyone,
    [System.Security.AccessControl.FileSystemRights]::FullControl,
    [System.Security.AccessControl.AccessControlType]::Allow)
$insecure.AddAccessRule($everyoneRule)
[System.IO.File]::SetAccessControl($WebReceiptPath, $insecure)
Write-WebInstallReceipt
Write-Output "UNSAFE_RECEIPT_REWRITTEN"
""",
    )
    env = os.environ.copy()
    env.update(
        {
            "FLINTTRADE_ACL_TEST_DIR": str(receipt_dir),
            "FLINTTRADE_ACL_TEST_SHIM": str(shim),
            "FLINTTRADE_ACL_TEST_SOURCE": str(source),
            "FLINTTRADE_ACL_TEST_TOOLS": str(tools),
        }
    )

    result = subprocess.run(
        [WINDOWS_POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        cwd=_REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "UNSAFE_RECEIPT_REWRITTEN" not in combined, combined
    assert "not current-user-only" in combined, combined


@pytest.mark.unit
@pytest.mark.skipif(WINDOWS_POWERSHELL is None, reason="powershell.exe is not available on this runner")
def test_windows_web_installer_publishes_a_private_receipt_idempotently(tmp_path: Path) -> None:
    """A fresh receipt and a reinstall both finish with the exact trusted ACL."""
    receipt_dir = tmp_path / "receipt-state"
    shim = tmp_path / "flinttrade-web.cmd"
    shim.write_text("@echo off\r\n", encoding="utf-8")
    source = tmp_path / "source"
    tools = tmp_path / "tools"
    source.mkdir()
    tools.mkdir()
    harness = _staged_windows_installer_harness(
        tmp_path,
        r"""
$WebReceiptDir = $env:FLINTTRADE_ACL_TEST_DIR
$WebReceiptPath = Join-Path $WebReceiptDir "web-install.receipt"
$ShimPath = $env:FLINTTRADE_ACL_TEST_SHIM
$StartMenuShortcut = Join-Path $WebReceiptDir "missing-shortcut.lnk"
$script:SrcDir = $env:FLINTTRADE_ACL_TEST_SOURCE
$ToolsRoot = $env:FLINTTRADE_ACL_TEST_TOOLS
Write-WebInstallReceipt
Write-WebInstallReceipt
if (-not (Test-TrustedWebReceiptAcl)) { throw "published receipt ACL is not trusted" }
if (@(Get-ChildItem -LiteralPath $WebReceiptDir -Filter ".receipt-acl-probe-*" -Force).Count -ne 0) {
    throw "receipt ACL preflight left a probe behind"
}
Write-Output "PRIVATE_RECEIPT_OK"
""",
    )
    env = os.environ.copy()
    env.update(
        {
            "FLINTTRADE_ACL_TEST_DIR": str(receipt_dir),
            "FLINTTRADE_ACL_TEST_SHIM": str(shim),
            "FLINTTRADE_ACL_TEST_SOURCE": str(source),
            "FLINTTRADE_ACL_TEST_TOOLS": str(tools),
        }
    )

    result = subprocess.run(
        [WINDOWS_POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        cwd=_REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )

    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "PRIVATE_RECEIPT_OK" in combined, combined


@pytest.mark.unit
@pytest.mark.skipif(WINDOWS_POWERSHELL is None, reason="powershell.exe is not available on this runner")
def test_windows_web_installer_rejects_a_permissive_receipt_before_reading_it(tmp_path: Path) -> None:
    """An Everyone-writable receipt must not authorise managed-source replacement."""
    receipt_dir = tmp_path / "receipt-state"
    source = tmp_path / "managed-source"
    harness = _staged_windows_installer_harness(
        tmp_path,
        r"""
$WebReceiptDir = $env:FLINTTRADE_ACL_TEST_DIR
$WebReceiptPath = Join-Path $WebReceiptDir "web-install.receipt"
[void](New-Item -ItemType Directory -Force -Path $WebReceiptDir)
Protect-WebReceiptDirectory $WebReceiptDir
$lines = @(
    "format=flinttrade-web-install-v1",
    "platform=Windows",
    "shim=C:\safe\flinttrade-web.cmd",
    ("shim_sha256=" + ("0" * 64)),
    "shortcut=",
    ("source=" + $env:FLINTTRADE_ACL_TEST_SOURCE),
    "tools=C:\safe\tools"
)
[System.IO.File]::WriteAllText(
    $WebReceiptPath,
    (($lines -join "`r`n") + "`r`n"),
    (New-Object System.Text.UTF8Encoding($false)))
$insecure = Get-Acl -LiteralPath $WebReceiptPath
$everyone = New-Object System.Security.Principal.SecurityIdentifier("S-1-1-0")
$everyoneRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    $everyone,
    [System.Security.AccessControl.FileSystemRights]::Modify,
    [System.Security.AccessControl.AccessControlType]::Allow)
$insecure.AddAccessRule($everyoneRule)
[System.IO.File]::SetAccessControl($WebReceiptPath, $insecure)
$recorded = Get-RecordedWebInstallField "source="
if ($recorded) { throw "trusted an Everyone-writable receipt: $recorded" }
Write-Output "UNSAFE_RECEIPT_REJECTED"
""",
    )
    env = os.environ.copy()
    env.update(
        {
            "FLINTTRADE_ACL_TEST_DIR": str(receipt_dir),
            "FLINTTRADE_ACL_TEST_SOURCE": str(source),
        }
    )

    result = subprocess.run(
        [WINDOWS_POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        cwd=_REPO_ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )

    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "UNSAFE_RECEIPT_REJECTED" in combined, combined


@pytest.mark.unit
@pytest.mark.skipif(WINDOWS_POWERSHELL is None, reason="powershell.exe is not available on this runner")
def test_windows_web_installer_accepts_a_legacy_inherited_owner_only_receipt(tmp_path: Path) -> None:
    """A safe receipt inherited from the protected directory remains upgradeable."""
    receipt_dir = tmp_path / "receipt-state"
    source = tmp_path / "用户-managed-source"
    harness = _staged_windows_installer_harness(
        tmp_path,
        r"""
$WebReceiptDir = $env:FLINTTRADE_ACL_TEST_DIR
$WebReceiptPath = Join-Path $WebReceiptDir "web-install.receipt"
[void](New-Item -ItemType Directory -Force -Path $WebReceiptDir)
Protect-WebReceiptDirectory $WebReceiptDir
$lines = @(
    "format=flinttrade-web-install-v1",
    "platform=Windows",
    "shim=C:\safe\flinttrade-web.cmd",
    ("shim_sha256=" + ("0" * 64)),
    "shortcut=",
    ("source=" + $env:FLINTTRADE_ACL_TEST_SOURCE),
    "tools=C:\safe\tools"
)
[System.IO.File]::WriteAllText(
    $WebReceiptPath,
    (($lines -join "`r`n") + "`r`n"),
    (New-Object System.Text.UTF8Encoding($false)))
$recorded = Get-RecordedWebInstallField "source="
if ($recorded -cne $env:FLINTTRADE_ACL_TEST_SOURCE) {
    throw "safe inherited receipt was not accepted: $recorded"
}
Write-Output "LEGACY_RECEIPT_ACCEPTED"
""",
    )
    env = os.environ.copy()
    env.update(
        {
            "FLINTTRADE_ACL_TEST_DIR": str(receipt_dir),
            "FLINTTRADE_ACL_TEST_SOURCE": str(source),
        }
    )

    result = subprocess.run(
        [WINDOWS_POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        cwd=_REPO_ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )

    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "LEGACY_RECEIPT_ACCEPTED" in combined, combined


@pytest.mark.unit
def test_windows_web_installer_preflights_receipt_storage_before_source_changes() -> None:
    """Receipt publication must be proved before source, launcher, or shortcut mutation."""
    source = _read(PS1)
    main = source[source.index("function Invoke-FlintTradeWebInstall") :]

    assert "Initialize-WebReceiptStorage" in source
    assert main.index("Initialize-WebReceiptStorage") < main.index("Invoke-SourceAcquisition")
    assert main.index("Initialize-WebReceiptStorage") < main.index("Install-LauncherShim")


@pytest.mark.unit
@pytest.mark.skipif(WINDOWS_POWERSHELL is None, reason="powershell.exe is not available on this runner")
def test_windows_web_installer_refuses_a_src_without_identity(tmp_path: Path) -> None:
    """The Windows installer refuses an unproven -SrcDir before deleting anything."""
    src = _generic_mixed_project(tmp_path / "someone-elses-project")
    result = subprocess.run(
        [
            WINDOWS_POWERSHELL,
            "-NoProfile",
            "-File",
            str(_staged_windows_installer(tmp_path, elevated=False)),
            "-DryRun",
            "-Yes",
            "-SrcDir",
            str(src),
        ],
        cwd=_REPO_ROOT,
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )

    combined = result.stdout + result.stderr
    assert "nothing there proves it is a FlintTrade checkout" in combined, combined
    assert (src / "main.py").exists(), "the installer touched an unproven source directory"


@pytest.mark.unit
@pytest.mark.skipif(WINDOWS_POWERSHELL is None, reason="powershell.exe is not available on this runner")
def test_windows_web_installer_refuses_a_marker_only_tree_it_cannot_update(tmp_path: Path) -> None:
    """The .ps1 mirrors the split: markers alone never authorise a recursive delete."""
    src = _marker_only_clone(tmp_path / "unpacked-copy")
    result = subprocess.run(
        [
            WINDOWS_POWERSHELL,
            "-NoProfile",
            "-File",
            str(_staged_windows_installer(tmp_path, elevated=False)),
            "-DryRun",
            "-Yes",
            "-SrcDir",
            str(src),
        ],
        cwd=_REPO_ROOT,
        env=_windows_home_env(tmp_path),
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "markers prove the CODE is this" in combined, combined
    assert "could only be replaced wholesale" in combined, combined
    assert (src / "main.py").exists(), "the installer touched a directory it could not prove it owns"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("script", "guard", "markers"),
    [
        (SH, "assert_source_dir_safe", "flinttrade_source_markers_present"),
        (PS1, "Assert-SourceDirSafe", "Test-FlintTradeSourceMarkers"),
    ],
    ids=["web-install.sh", "web-install.ps1"],
)
def test_web_installers_never_let_markers_authorise_a_destructive_replacement(
    script: Path, guard: str, markers: str
) -> None:
    """flint.toml and the workspace members are checked in, so every clone carries them."""
    body = _strip_shell_comments(_read(script), block_comments=script.suffix == ".ps1")
    start = body.index(guard + "(") if script.suffix == ".sh" else body.index("function " + guard)
    end = body.index("\n}\n", start)
    guard_body = body[start:end]

    assert markers in guard_body, f"{script.name}: the marker check left {guard}"
    assert "status --porcelain" in guard_body, (
        f"{script.name}: a marker-proved checkout must be refused while it holds uncommitted work"
    )
    assert ".git" in guard_body, (
        f"{script.name}: markers may only authorise an in-place update of an actual Git checkout"
    )
    marker_index = guard_body.index(markers)
    porcelain_index = guard_body.index("status --porcelain")
    assert marker_index < porcelain_index, (
        f"{script.name}: the uncommitted-work check must gate the marker branch, not precede it"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("script", "reader", "open_call"),
    [
        (SH, "web_receipt_field", '< "$WEB_RECEIPT_PATH"'),
        (PS1, "Get-RecordedWebInstallField", "Get-Content -LiteralPath $WebReceiptPath"),
    ],
    ids=["web-install.sh", "web-install.ps1"],
)
def test_web_installers_read_the_receipt_through_one_strict_reader(
    script: Path, reader: str, open_call: str
) -> None:
    """A second, weaker reader is simply the way round the strict one."""
    body = _strip_shell_comments(_read(script), block_comments=script.suffix == ".ps1")
    assert body.count(open_call) == 1, (
        f"{script.name} opens the web-install receipt in more than one place; every trusting read "
        f"must go through {reader}, which is the only one that checks ownership and privacy"
    )
    start = body.index(reader + "(") if script.suffix == ".sh" else body.index("function " + reader)
    end = body.index("\n}\n", start)
    reader_body = body[start:end]
    if script.suffix == ".sh":
        assert "private_mode" in reader_body and "-O " in reader_body, (
            "the POSIX reader must require an owner-local 0700/0600 receipt, exactly as "
            "flinttrade-uninstall.sh does"
        )
    else:
        assert "Test-TrustedWebReceiptAcl" in reader_body and "ReparsePoint" in reader_body, (
            "the Windows reader must require an owner-private receipt with no reparse alias in its "
            "path, exactly as flinttrade-uninstall.ps1 does"
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


@pytest.mark.unit
@pytest.mark.parametrize(
    ("script", "launcher_variable"),
    [(SH, "$SHIM_PATH"), (PS1, "$ShimPath")],
    ids=["web-install.sh", "web-install.ps1"],
)
def test_install_only_guidance_uses_the_launcher_path_when_the_alias_may_be_off_path(
    script: Path,
    launcher_variable: str,
) -> None:
    """The no-launch result must give a command that works before PATH is edited."""
    source = _read(script)

    assert "Start it later with: flinttrade-web start" not in source
    assert "(also: flinttrade-web <subcommand>)" not in source
    assert launcher_variable in source[source.index("offer_to_start" if script == SH else "Invoke-OptionalLaunch") :]


# ---------------------------------------------------------------------------
# Collisions between the web install and the Electron desktop install.
#
# The two installers are documented as independent one-liners, so a machine may
# run them in either order and at any interval. Every path one of them writes
# must therefore be a path the other never claims:
#
#   * on Windows, %LOCALAPPDATA%\Programs\FlintTrade is the electron-builder
#     per-user install directory. Assert-WindowsFreshInstallAdmission in
#     flinttrade-install.ps1 REFUSES a fresh desktop install when that directory
#     exists without exactly one proven FlintTrade uninstall-registry identity,
#     so a web launcher parked there locked the desktop installer out for good;
#   * on Linux, ~/.local/bin/flinttrade is the desktop shell's own wrapper, and
#     flinttrade-install.sh refuses to replace it unless its shell receipt
#     proves the current contents byte for byte;
#   * ~/.flinttrade/src/FlintTrade is the desktop shell's ACTIVE source, guarded
#     by a bootstrap operation lease no shell script can hold (see below).
# ---------------------------------------------------------------------------


def _bash_path(target: Path) -> str:
    """Render a filesystem path the way the bash on this runner spells it.

    Git Bash on Windows is a POSIX shell over a Windows filesystem: ``C:\\x``
    reaches it as ``/c/x``, and the installer's own ``--src must be an absolute
    path`` guard rejects the drive-letter form.

    Args:
        target: Path to render.

    Returns:
        An absolute POSIX-style path.
    """
    text = target.as_posix()
    if len(text) > 1 and text[1] == ":":
        return f"/{text[0].lower()}{text[2:]}"
    return text


def _windows_home_env(home: Path) -> dict[str, str]:
    """Return an environment that moves PowerShell's ``$HOME`` to ``home``.

    ``[Environment]::GetFolderPath`` resolves the profile's ``AppData`` folders
    relative to ``USERPROFILE`` and returns an empty string when they are absent,
    so the throwaway profile has to look like a real one.

    Args:
        home: Directory to use as the profile root; its ``AppData`` folders are
            created as a side effect.

    Returns:
        The current environment with the home-related variables replaced.
    """
    (home / "AppData" / "Local").mkdir(parents=True, exist_ok=True)
    (home / "AppData" / "Roaming").mkdir(parents=True, exist_ok=True)
    drive, _, rest = str(home).partition("\\")
    return {
        **os.environ,
        "USERPROFILE": str(home),
        "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "APPDATA": str(home / "AppData" / "Roaming"),
        "HOMEDRIVE": drive,
        "HOMEPATH": f"\\{rest}",
        "HOME": str(home),
    }


def _assignment(source: str, name: str) -> str:
    """Return the right-hand side of a single-line shell/PowerShell assignment.

    Args:
        source: Full script source.
        name: Variable name, including its ``$`` sigil for PowerShell.

    Returns:
        The assigned expression with surrounding whitespace removed.
    """
    match = re.search(rf"^{re.escape(name)}\s*=\s*(.+)$", source, flags=re.MULTILINE)
    assert match is not None, f"{name} is not assigned on a single line"
    return match.group(1).strip()


@pytest.mark.unit
def test_windows_web_launcher_never_squats_the_electron_install_directory() -> None:
    """The web shim must not create %LOCALAPPDATA%\\Programs\\FlintTrade."""
    web = _read(PS1)
    desktop = _read(DESKTOP_PS1)

    electron_dir = _assignment(desktop, "$DefaultElectronInstallDir")
    assert r'Programs\FlintTrade"' in electron_dir, (
        "the Electron per-user install directory moved; re-derive this test from "
        "flinttrade-install.ps1 rather than weakening it"
    )

    shim_dir = _assignment(web, "$ShimDir")
    assert r'Programs\FlintTradeWeb"' in shim_dir, (
        "the web launcher directory must be its own; installing it into the Electron "
        "per-user directory makes Assert-WindowsFreshInstallAdmission refuse every later "
        f"desktop install (found: {shim_dir})"
    )
    assert not re.search(r'Programs\\FlintTrade"', shim_dir), (
        f"$ShimDir still resolves to the Electron install directory: {shim_dir}"
    )
    shim_path = _assignment(web, "$ShimPath")
    assert '"flinttrade-web.cmd"' in shim_path and '"flinttrade.cmd"' not in shim_path, (
        "the web launcher must not be named flinttrade.cmd inside a FlintTrade-branded "
        f"directory; the distinct name is what keeps the two installs separable (found: {shim_path})"
    )


@pytest.mark.unit
def test_windows_web_start_menu_folder_never_collides_with_the_shell() -> None:
    """The desktop uninstaller sweeps Start Menu\\Programs\\FlintTrade and fails on residue."""
    web = _read(PS1)
    uninstall = _read(UNINSTALL_PS1)

    assert r"Start Menu\Programs\FlintTrade" in uninstall, (
        "the desktop uninstaller no longer sweeps a Start Menu folder; re-derive this test"
    )
    assert r'Start Menu\Programs"' in _assignment(web, "$StartMenuRoot"), (
        "the web installer no longer resolves the per-user Start Menu root; re-derive this test"
    )
    start_menu_dir = _assignment(web, "$StartMenuDir")
    assert '"FlintTrade Web"' in start_menu_dir and '"FlintTrade"' not in start_menu_dir, (
        "the web Start Menu folder must be its own - the desktop uninstaller reports a "
        f"non-empty Programs\\FlintTrade folder as unproven residue (found: {start_menu_dir})"
    )
    shortcut = _assignment(web, "$StartMenuShortcut")
    assert '"FlintTrade Web.lnk"' in shortcut and '"FlintTrade.lnk"' not in shortcut, (
        "the web shortcut must not be named FlintTrade.lnk; the desktop uninstaller removes "
        f"exactly that leaf name once it has proven the Electron shell (found: {shortcut})"
    )


@pytest.mark.unit
def test_posix_web_launcher_preserves_the_electron_wrapper() -> None:
    """~/.local/bin/flinttrade belongs to the desktop shell; the web app takes another name."""
    web = _read(SH)
    desktop = _read(DESKTOP_SH)

    assert 'wrapper="$HOME/.local/bin/flinttrade"' in desktop, (
        "the desktop shell's Linux wrapper moved; re-derive this test from "
        "flinttrade-install.sh rather than weakening it"
    )
    assert _assignment(web, "SHIM_PATH") == '"$SHIM_DIR/flinttrade-web"', (
        "the web launcher must not overwrite the desktop shell's ~/.local/bin/flinttrade "
        "wrapper: doing so repoints the installed desktop entry at the web runner and makes "
        "every later desktop update refuse to validate its integration file"
    )
    assert _assignment(web, "LEGACY_SHIM_PATH") == '"$SHIM_DIR/flinttrade"', (
        "the pre-collision launcher path must stay recorded so a re-run can retire a shim "
        "this installer's own receipt still proves it wrote"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("script", "marker"),
    [
        (SH, "retire_legacy_launcher_shim"),
        (PS1, "Remove-LegacyWebLauncher"),
    ],
    ids=["web-install.sh", "web-install.ps1"],
)
def test_web_installers_retire_the_old_launcher_only_on_receipt_proof(script: Path, marker: str) -> None:
    """A machine installed by an earlier revision must heal, never guess."""
    source = _read(script)
    assert marker in source, f"{script.name} has no legacy-launcher retirement step"
    body = source[source.index(marker) :]
    assert "shim_sha256" in body[:4500], (
        f"{script.name} must compare the recorded SHA-256 before removing the earlier launcher; "
        "a desktop install may have republished its own wrapper at that path since"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "uninstaller",
    [UNINSTALL_SH, UNINSTALL_PS1],
    ids=["uninstall.sh", "uninstall.ps1"],
)
def test_uninstallers_still_find_the_relocated_web_launcher(uninstaller: Path) -> None:
    """The receipt drives removal, so its allowed locations must track the installer."""
    source = _read(uninstaller)
    if uninstaller.suffix == ".sh":
        assert '"$HOME/.local/bin/flinttrade-web"' in source, (
            "flinttrade-uninstall.sh no longer accepts the web launcher's own path, so a web "
            "install would leave its launcher behind forever"
        )
        assert '"$HOME/.local/bin/flinttrade"' in source, (
            "the pre-collision launcher path must stay acceptable so machines installed by an "
            "earlier revision can still be uninstalled cleanly"
        )
    else:
        assert '"flinttrade-web.cmd"' in source, (
            "flinttrade-uninstall.ps1 no longer accepts the web launcher's own path, so a web "
            "install would leave its launcher behind forever"
        )
        assert "FlintTrade Web.lnk" in source, (
            "flinttrade-uninstall.ps1 no longer accepts the web Start Menu shortcut"
        )
        assert '"flinttrade.cmd"' in source, (
            "the pre-collision launcher path must stay acceptable so machines installed by an "
            "earlier revision can still be uninstalled cleanly"
        )


# ---------------------------------------------------------------------------
# The shared-source race.
#
# The desktop's operation lease is not a primitive an outside process can hold:
# acquireOperationLease in packages/apps/desktop/electron/bootstrap-io.ts treats
# any lease directory it finds as recoverable stale evidence, waits only for the
# process records inside it, then quarantines and deletes it. A lease written by
# a shell installer carries no process-group / supervisor record bound to a
# containment token the Electron singleton minted, so it is stolen immediately.
#
# Checking the lease once and then fetching, hard-resetting and building for
# several minutes was therefore not a guard at all. Separate trees are.
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("script", "default_source"),
    [(SH, 'SRC_DIR="$WEB_ACTIVE_SOURCE"'), (PS1, "$script:SrcDir = $WebActiveSource")],
    ids=["web-install.sh", "web-install.ps1"],
)
def test_web_installers_default_to_their_own_source_tree(script: Path, default_source: str) -> None:
    source = _strip_shell_comments(_read(script), block_comments=script.suffix == ".ps1")
    assert default_source in source, (
        f"{script.name} must default to its own managed checkout, not the desktop shell's "
        "active source at ~/.flinttrade/src/FlintTrade"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("script", "removed", "added"),
    [
        (SH, "assert_desktop_not_operating", "assert_desktop_source_not_shared"),
        (PS1, "Assert-DesktopNotOperating", "Assert-DesktopSourceNotShared"),
    ],
    ids=["web-install.sh", "web-install.ps1"],
)
def test_web_installers_refuse_the_shared_tree_instead_of_probing_the_lease(
    script: Path, removed: str, added: str
) -> None:
    source = _read(script)
    assert removed not in source, (
        f"{script.name} still probes the desktop lease and then proceeds; the fetch, the hard "
        "reset and the multi-minute build all happen afterwards, so a desktop started in that "
        "window mutates the same checkout concurrently"
    )
    assert added in source, f"{script.name} has no shared-source refusal"
    body = _strip_shell_comments(source, block_comments=script.suffix == ".ps1")
    fetch_marker = "acquire_source_with_git" if script.suffix == ".sh" else "Invoke-SourceAcquisition"
    assert body.index(added + "\n") < body.rindex(fetch_marker), (
        f"{script.name} must refuse the overlap before any source mutation"
    )


@pytest.mark.unit
@pytest.mark.skipif(BASH is None, reason=NO_BASH_REASON)
def test_posix_web_installer_refuses_the_desktop_active_source(tmp_path: Path) -> None:
    """A --src inside ~/.flinttrade/src is refused before anything is probed."""
    result = subprocess.run(
        [BASH, str(SH), "--dry-run", "--src", _bash_path(tmp_path / ".flinttrade" / "src" / "FlintTrade")],
        cwd=_REPO_ROOT,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": _bash_path(tmp_path)},
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "overlaps the FlintTrade Desktop shell's active source tree" in result.stderr
    assert "Choose a source checkout outside" in result.stderr


@pytest.mark.unit
@pytest.mark.skipif(BASH is None, reason=NO_BASH_REASON)
def test_posix_web_installer_refuses_a_parent_of_the_desktop_source(tmp_path: Path) -> None:
    """The git-less refresh removes --src recursively, so a parent is just as fatal."""
    result = subprocess.run(
        [BASH, str(SH), "--dry-run", "--src", _bash_path(tmp_path / ".flinttrade")],
        cwd=_REPO_ROOT,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": _bash_path(tmp_path)},
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "overlaps the FlintTrade Desktop shell's active source tree" in result.stderr


@pytest.mark.unit
@pytest.mark.skipif(BASH is None, reason=NO_BASH_REASON)
def test_posix_web_installer_accepts_a_source_outside_the_desktop_tree(tmp_path: Path) -> None:
    """Negative control: an unrelated --src must not trip the overlap refusal."""
    result = subprocess.run(
        [BASH, str(SH), "--dry-run", "--src", _bash_path(tmp_path / "elsewhere")],
        cwd=_REPO_ROOT,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": _bash_path(tmp_path)},
        text=True,
        capture_output=True,
    )
    assert "overlaps the FlintTrade Desktop shell's active source tree" not in (
        result.stdout + result.stderr
    )


@pytest.mark.unit
@pytest.mark.skipif(not POWERSHELL, reason=NO_POWERSHELL_REASON)
@pytest.mark.skipif(os.name != "nt", reason=NOT_WINDOWS_REASON)
def test_windows_web_installer_refuses_the_desktop_active_source(tmp_path: Path) -> None:
    """-SrcDir inside the desktop source root is refused before anything is probed."""
    shared = tmp_path / ".flinttrade" / "src" / "FlintTrade"
    result = subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(_staged_windows_installer(tmp_path, elevated=False)),
            "-DryRun",
            "-SrcDir",
            str(shared),
        ],
        cwd=_REPO_ROOT,
        env=_windows_home_env(tmp_path),
        text=True,
        capture_output=True,
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "overlaps the FlintTrade Desktop shell's active source tree" in combined


@pytest.mark.unit
@pytest.mark.skipif(BASH is None, reason=NO_BASH_REASON)
@pytest.mark.parametrize(
    "spelling",
    [".flinttrade/./src/FlintTrade", ".flinttrade/src/FlintTrade/", "nowhere/../.flinttrade/src/FlintTrade"],
    ids=["dot-component", "trailing-slash", "parent-component"],
)
def test_posix_web_installer_canonicalises_before_the_desktop_overlap_check(
    tmp_path: Path, spelling: str
) -> None:
    """A lexical compare of the raw --src string is bypassed by every other spelling."""
    result = subprocess.run(
        [BASH, str(SH), "--dry-run", "--src", f"{_bash_path(tmp_path)}/{spelling}"],
        cwd=_REPO_ROOT,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": _bash_path(tmp_path)},
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "overlaps the FlintTrade Desktop shell's active source tree" in result.stderr


@pytest.mark.unit
@pytest.mark.skipif(BASH is None, reason=NO_BASH_REASON)
@pytest.mark.skipif(os.name != "posix", reason=NOT_POSIX_REASON)
def test_posix_web_installer_resolves_a_symlinked_parent_before_the_overlap_check(tmp_path: Path) -> None:
    """A symlinked parent spells the desktop's own tree without matching it lexically."""
    managed = tmp_path / ".flinttrade"
    managed.mkdir()
    link = tmp_path / "managed-alias"
    try:
        link.symlink_to(managed, target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover - runner-dependent
        pytest.skip("this runner cannot create directory symbolic links")
    if not link.is_symlink():  # pragma: no cover - runner-dependent
        pytest.skip("this runner materialised the symbolic link as a real directory")

    result = subprocess.run(
        [BASH, str(SH), "--dry-run", "--src", f"{_bash_path(link)}/src/FlintTrade"],
        cwd=_REPO_ROOT,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": _bash_path(tmp_path)},
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "overlaps the FlintTrade Desktop shell's active source tree" in result.stderr


@pytest.mark.unit
@pytest.mark.skipif(POWERSHELL is None, reason=NO_POWERSHELL_REASON)
@pytest.mark.skipif(os.name != "nt", reason="mklink /J needs Windows")
def test_windows_web_installer_resolves_a_junctioned_parent_before_the_overlap_check(
    tmp_path: Path,
) -> None:
    """A junction spells the desktop's own tree without matching it as a string."""
    managed = tmp_path / ".flinttrade"
    managed.mkdir()
    alias = tmp_path / "alias"
    link = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(alias), str(managed)],
        text=True,
        capture_output=True,
    )
    if link.returncode != 0:  # pragma: no cover - runner-dependent
        pytest.skip("this runner cannot create directory junctions")

    result = subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-File",
            str(_staged_windows_installer(tmp_path, elevated=False)),
            "-DryRun",
            "-Yes",
            "-SrcDir",
            str(alias / "src" / "FlintTrade"),
        ],
        cwd=_REPO_ROOT,
        env=_windows_home_env(tmp_path),
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "overlaps the FlintTrade Desktop shell's active source tree" in combined, combined


@pytest.mark.unit
@pytest.mark.parametrize(
    ("script", "anchor"),
    [
        (SH, "assert_desktop_source_not_shared() {"),
        (PS1, "function Assert-DesktopSourceNotShared {"),
    ],
    ids=["web-install.sh", "web-install.ps1"],
)
def test_web_installers_canonicalise_both_sides_of_the_overlap_check(script: Path, anchor: str) -> None:
    """The guard must compare trees, not the spellings the operator happened to type."""
    body = _strip_shell_comments(_read(script), block_comments=script.suffix == ".ps1")
    start = body.index(anchor)
    guard = body[start : body.index("\n}\n", start)]
    canonicaliser = "canonical_overlap_path" if script.suffix == ".sh" else "Get-CanonicalOverlapPath"
    assert guard.count(canonicaliser) >= 2, (
        f"{script.name}: both the requested source and the desktop source root must be "
        "canonicalised before they are compared"
    )


# ---------------------------------------------------------------------------
# Machines installed by the revision that shared the desktop's source root.
#
# That revision defaulted the web source to ~/.flinttrade/src/FlintTrade — the
# desktop shell's own active source. Retiring only its launcher left the web
# checkout sitting in the desktop's tree, so the desktop and the web installer
# still fight over one directory and the machine stays locked out of the shell.
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("script", "anchor"),
    [
        (SH, "migrate_legacy_web_source_checkout() {"),
        (PS1, "function Move-LegacyWebSourceCheckout {"),
    ],
    ids=["web-install.sh", "web-install.ps1"],
)
def test_web_installers_migrate_rather_than_delete_a_legacy_desktop_root_checkout(
    script: Path, anchor: str
) -> None:
    """The tree may be moved on receipt proof; it may never be deleted."""
    body = _strip_shell_comments(_read(script), block_comments=script.suffix == ".ps1")
    start = body.index(anchor)
    migration = body[start : body.index("\n}\n", start)]

    if script.suffix == ".sh":
        assert "web_receipt_field source" in migration, (
            "the receipt is the only thing that proves this installer created the checkout"
        )
        assert "mv " in migration and "rm -rf" not in migration, (
            "an unprovable tree must never be deleted; a provable one is only ever moved"
        )
        assert "desktop_shell_appears_installed" in migration
        assert "DESKTOP_OPERATION_LEASE" in migration
    else:
        assert 'Get-RecordedWebInstallField "source="' in migration
        assert "Move-Item" in migration and "-Recurse" not in migration, (
            "an unprovable tree must never be deleted; a provable one is only ever moved"
        )
        assert "Test-DesktopShellInstalled" in migration
        assert "DesktopOperationLease" in migration


@pytest.mark.unit
@pytest.mark.skipif(BASH is None, reason=NO_BASH_REASON)
@pytest.mark.skipif(os.name != "posix", reason=NOT_POSIX_REASON)
@pytest.mark.skipif(not POSIX_MODES, reason=NO_POSIX_MODES_REASON)
def test_posix_web_installer_reports_the_legacy_checkout_it_would_migrate(tmp_path: Path) -> None:
    """The upgrade is announced from the receipt, and a dry run still moves nothing."""
    legacy = tmp_path / ".flinttrade" / "src" / "FlintTrade"
    _marker_only_clone(legacy)
    _plant_web_receipt(tmp_path, source=legacy)

    result = subprocess.run(
        [BASH, str(SH), "--dry-run"],
        cwd=_REPO_ROOT,
        env={
            "PATH": _fake_posix_bin(tmp_path),
            "HOME": str(tmp_path),
            "FLINTTRADE_YES": "1",
        },
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "would move" in result.stdout
    assert str(tmp_path / ".flinttrade" / "web-src" / "FlintTrade") in result.stdout
    assert (legacy / "flint.toml").exists(), "a dry run must move nothing"


@pytest.mark.unit
@pytest.mark.skipif(BASH is None, reason=NO_BASH_REASON)
@pytest.mark.skipif(os.name != "posix", reason=NOT_POSIX_REASON)
@pytest.mark.skipif(not POSIX_MODES, reason=NO_POSIX_MODES_REASON)
def test_posix_web_installer_leaves_the_legacy_checkout_when_the_desktop_shell_is_installed(
    tmp_path: Path,
) -> None:
    """A tree the desktop may own is never moved; the operator is told exactly what to do."""
    legacy = tmp_path / ".flinttrade" / "src" / "FlintTrade"
    _marker_only_clone(legacy)
    _plant_web_receipt(tmp_path, source=legacy)
    shell_receipt = tmp_path / ".local" / "state" / "flinttrade" / "shell-install.receipt"
    shell_receipt.parent.mkdir(parents=True)
    shell_receipt.write_text("format=flinttrade-electron-shell-v1\n", encoding="utf-8")

    result = subprocess.run(
        [BASH, str(SH), "--dry-run"],
        cwd=_REPO_ROOT,
        env={
            "PATH": _fake_posix_bin(tmp_path),
            "HOME": str(tmp_path),
            "FLINTTRADE_YES": "1",
        },
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "would move" not in result.stdout
    assert "the FlintTrade Desktop shell is installed on this machine" in result.stderr
    assert "Decide which checkout to keep" in result.stderr
    assert (legacy / "flint.toml").exists()


@pytest.mark.unit
@pytest.mark.skipif(BASH is None, reason=NO_BASH_REASON)
@pytest.mark.skipif(os.name != "posix", reason=NOT_POSIX_REASON)
@pytest.mark.skipif(not POSIX_MODES, reason=NO_POSIX_MODES_REASON)
def test_posix_web_installer_moves_the_legacy_checkout_out_of_the_desktop_tree(tmp_path: Path) -> None:
    """The real upgrade run relocates the checkout the receipt proves it created.

    The stub ``git`` fails every command, so the run stops at the fetch — after
    the migration, which is what this pins.
    """
    legacy = tmp_path / ".flinttrade" / "src" / "FlintTrade"
    _marker_only_clone(legacy)
    (legacy / ".git").mkdir()
    _plant_web_receipt(tmp_path, source=legacy)
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    stub_git = bin_dir / "git"
    stub_git.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8", newline="\n")
    stub_git.chmod(0o755)

    result = subprocess.run(
        [BASH, str(SH)],
        cwd=_REPO_ROOT,
        env={
            "PATH": _fake_posix_bin(tmp_path),
            "HOME": str(tmp_path),
            "FLINTTRADE_YES": "1",
        },
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )

    moved = tmp_path / ".flinttrade" / "web-src" / "FlintTrade"
    assert result.returncode != 0, "the stub git must stop the run at the fetch"
    assert "Could not fetch" in result.stderr, result.stdout + result.stderr
    assert not legacy.exists(), "the web checkout was left inside the desktop shell's source root"
    assert (moved / "flint.toml").exists(), "the migrated checkout is missing from the web source root"


# ---------------------------------------------------------------------------
# --ref accepts a branch, a tag AND a raw commit SHA
#
# The flag is documented as "Branch, tag or commit", and the archive fallback
# signs off with "re-run with --ref <sha> to reproduce this exact install".
# `git clone --branch` resolves its argument against the remote's branches and
# tags only, so on a fresh machine the advertised commit form failed outright —
# and the reproducibility advice pointed at a command that could not work.
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize("script", [SH, PS1], ids=["posix", "windows"])
def test_web_installers_never_select_a_ref_with_clone_branch(script: Path) -> None:
    """`git clone --branch` cannot select a commit, so no installer may use it."""
    source = script.read_text(encoding="utf-8")
    executable = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )

    assert "clone --branch" not in executable, (
        f"{script.name} selects a ref with 'git clone --branch', which rejects a commit SHA"
    )
    assert "--branch" not in executable, f"{script.name} still resolves a ref against branches/tags"


@pytest.mark.unit
@pytest.mark.parametrize("script", [SH, PS1], ids=["posix", "windows"])
def test_web_installers_fetch_the_exact_revision_into_a_fresh_checkout(script: Path) -> None:
    """A fresh install must init + fetch <ref> + check out FETCH_HEAD.

    That sequence takes a branch, a tag and a raw commit alike, so a fresh
    install and a refresh agree on which --ref forms exist.
    """
    source = script.read_text(encoding="utf-8")

    for fragment in ("init --quiet", "remote add origin", "fetch --depth 1 origin", "FETCH_HEAD"):
        assert fragment in source, f"{script.name} is missing the '{fragment}' step"
    assert "checkout --detach --force FETCH_HEAD" in source, (
        f"{script.name} never checks out the fetched revision"
    )


@pytest.mark.unit
@pytest.mark.parametrize("script", [SH, PS1], ids=["posix", "windows"])
def test_web_installers_still_advertise_a_reproducible_commit(script: Path) -> None:
    """The archive fallback's '--ref <sha>' advice must stay followable with Git."""
    source = script.read_text(encoding="utf-8")

    assert "to reproduce this exact install" in source
    assert "Branch, tag or commit" in source


@pytest.mark.unit
@pytest.mark.skipif(GIT is None, reason=NO_GIT_REASON)
def test_git_clone_branch_rejects_a_commit_but_fetch_checkout_accepts_it(tmp_path: Path) -> None:
    """Prove the premise against real Git rather than trusting the manual page.

    Guards the fix from being 'simplified' back to a clone: the two commands are
    run against one local repository, and only the installer's sequence resolves
    a raw commit SHA.
    """
    origin = tmp_path / "origin"
    origin.mkdir()

    def git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run([GIT, *args], cwd=str(cwd), text=True, capture_output=True)

    git("init", "-q", "-b", "main", ".", cwd=origin)
    git("config", "user.email", "tests@flinttrade.invalid", cwd=origin)
    git("config", "user.name", "FlintTrade tests", cwd=origin)
    (origin / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    git("add", "-A", cwd=origin)
    git("commit", "-qm", "first", cwd=origin)
    sha = git("rev-parse", "HEAD", cwd=origin).stdout.strip()
    (origin / "pyproject.toml").write_text("[project]\nname = 'later'\n", encoding="utf-8")
    git("commit", "-qam", "second", cwd=origin)

    cloned = tmp_path / "cloned"
    clone = git("clone", "--depth", "1", "--branch", sha, str(origin), str(cloned), cwd=tmp_path)
    assert clone.returncode != 0, "git clone --branch unexpectedly accepted a raw commit SHA"

    fetched = tmp_path / "fetched"
    fetched.mkdir()
    assert git("init", "--quiet", cwd=fetched).returncode == 0
    assert git("remote", "add", "origin", str(origin), cwd=fetched).returncode == 0
    assert git("fetch", "--depth", "1", "origin", sha, cwd=fetched).returncode == 0
    assert git("checkout", "--detach", "--force", "FETCH_HEAD", cwd=fetched).returncode == 0
    assert git("rev-parse", "HEAD", cwd=fetched).stdout.strip() == sha
    assert (fetched / "pyproject.toml").read_text(encoding="utf-8") == "[project]\n"
