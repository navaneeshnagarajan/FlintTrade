"""CI guard: the public site domain has exactly one authority.

The maintainer moves the public domain from time to time. The literal URL cannot
be abstracted away — a reader runs ``curl … | bash`` from readme.md *before*
cloning, so the domain has to be spelled out — which is why it ended up
hardcoded in more than twenty tracked files.

The contract this file pins is therefore not "no literals" but "one authority,
one scripted rewrite, one guard":

  * ``flint.toml``'s ``[project] site_url`` is the authority;
  * ``scripts/apply-site-url.py`` rewrites every tracked mention;
  * ``scripts/check-site-url-consistency.py`` fails when any of them disagrees.

Without this test the guard would only run when someone remembered to invoke it,
which is exactly the failure mode a domain move produces: a stale URL left
behind in the one file nobody grepped.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check-site-url-consistency.py"
APPLIER = ROOT / "scripts" / "apply-site-url.py"


def _load(path: Path, name: str) -> ModuleType:
    """Import a hyphenated repo script as a module.

    Args:
        path: Absolute path to the script.
        name: Module name to register it under.

    Returns:
        The executed module object.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    """The site-URL consistency checker, imported as a module."""
    return _load(CHECKER, "check_site_url_consistency")


@pytest.mark.unit
def test_flint_toml_is_the_single_site_url_authority(checker: ModuleType) -> None:
    """The domain lives in flint.toml as a bare https origin, next to the version."""
    site_url = checker.read_site_url(ROOT)

    assert checker.SITE_URL_PATTERN.match(site_url), site_url
    assert not site_url.endswith("/"), "site_url is an origin, not a URL with a path"
    assert f'site_url = "{site_url}"' in (ROOT / "flint.toml").read_text(encoding="utf-8")


@pytest.mark.unit
def test_every_tracked_surface_agrees_with_flint_toml(checker: ModuleType) -> None:
    """No tracked file may name a domain other than flint.toml's site_url."""
    failures = checker.collect_failures(ROOT)

    assert failures == [], (
        "Tracked sources disagree with flint.toml's [project] site_url. Do not edit the "
        "domain by hand — run: python scripts/apply-site-url.py <new-url>\n"
        + "\n".join(f"  - {failure}" for failure in failures)
    )


@pytest.mark.unit
def test_consistency_script_exits_zero(checker: ModuleType) -> None:
    """The checker is the command a maintainer runs, so run it the same way."""
    result = subprocess.run(
        [sys.executable, str(CHECKER)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode == 0, result.stdout
    assert checker.read_site_url(ROOT) in result.stdout


@pytest.mark.unit
def test_a_stale_domain_anywhere_fails_the_check(checker: ModuleType) -> None:
    """Mutating one file's domain must be caught — by absence and by the stale literal.

    This is the guard's own regression test: it mutates readme.md's text in memory
    (never on disk) and asserts both detection paths fire, so the check cannot rot
    into one that passes whatever the tree says.
    """
    site_url = checker.read_site_url(ROOT)
    host = checker.site_host(site_url)
    mutated = (ROOT / "readme.md").read_text(encoding="utf-8").replace(host, "stale.example")

    assert site_url not in mutated, "the mutation must remove every canonical mention"

    reported = checker.foreign_site_urls(mutated, host)

    assert reported, "a canonical install route served from another host must be reported"
    assert all(line > 0 and "stale.example" in url for line, url in reported)


@pytest.mark.unit
def test_legitimate_neighbouring_hosts_are_not_flagged(checker: ModuleType) -> None:
    """Ordinary third-party links must stay quiet.

    An earlier revision flagged every host outside ``NON_SITE_HOSTS``, so adding a
    plain reference link to the readme failed the build with a misleading
    "competing site origin". Only a foreign host serving one of *our* identifying
    install routes is evidence of a stale domain.
    """
    host = checker.site_host(checker.read_site_url(ROOT))
    text = (
        "git clone https://github.com/navaneeshnagarajan/FlintTrade.git\n"
        "open http://127.0.0.1:5100\n"
        f"curl -fsSL https://{host}/web-install.sh | bash\n"
        "Further reading: https://example.com/some-article\n"
        "Someone else's page: https://news.ycombinator.com/download\n"
    )

    assert checker.foreign_site_urls(text, host) == []


@pytest.mark.unit
def test_a_foreign_host_serving_an_identifying_route_is_flagged(checker: ModuleType) -> None:
    """The narrowed probe must still catch the case it exists for."""
    host = checker.site_host(checker.read_site_url(ROOT))
    text = "curl -fsSL https://old-flinttrade.example/web-install.sh | bash\n"

    reported = checker.foreign_site_urls(text, host)

    assert [url for _line, url in reported] == ["https://old-flinttrade.example/web-install.sh"]


@pytest.mark.unit
def test_extensionless_tracked_files_are_scanned(checker: ModuleType) -> None:
    """Completeness must not depend on a suffix allowlist.

    The repository tracks extensionless text files (``notice``, ``LICENSE``); a
    suffix-only filter excused every one of them from the completeness scan that
    keeps ``SITE_URL_FILES`` honest.
    """
    scanned = set(checker.tracked_text_files(ROOT))

    assert "notice" in scanned, "extensionless tracked text files must be scanned"
    assert not any(rel.endswith(".png") for rel in scanned), "binary files must stay out"


@pytest.mark.unit
def test_apply_script_rewrites_urls_and_bare_hosts(tmp_path: Path, checker: ModuleType) -> None:
    """One rewrite pass must catch both the URL form and a bare-host mention."""
    applier = _load(APPLIER, "apply_site_url")
    host = checker.site_host(checker.read_site_url(ROOT))
    sample = tmp_path / "sample.md"
    sample.write_text(
        f"curl -fsSL https://{host}/web-install.sh | bash\n"
        f'ALLOWED = {{"{host}": "the installer\'s own one-line install URL"}}\n',
        encoding="utf-8",
    )

    replaced = applier._rewrite(sample, f"https://{host}", "https://flint.example")
    rewritten = sample.read_text(encoding="utf-8")

    assert replaced == 2
    assert host not in rewritten
    # Spelled without the route suffix on purpose: a literal foreign install-route
    # URL in a tracked file is exactly what the consistency check forbids.
    assert rewritten.startswith("curl -fsSL https://flint.example")
    assert "/web-install.sh | bash" in rewritten
    assert '"flint.example":' in rewritten


@pytest.mark.unit
def test_apply_script_rejects_a_url_that_is_not_a_bare_origin() -> None:
    """A path, a trailing slash or a plain hostname must not be accepted."""
    for argument in ("flinttrade.example", "https://flint.example/", "https://flint.example/docs", "http://x.example"):
        result = subprocess.run(
            [sys.executable, str(APPLIER), argument],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        assert result.returncode == 2, f"{argument} should have been rejected: {result.stdout}"


@pytest.mark.unit
def test_rewrite_target_list_covers_every_documented_surface(checker: ModuleType) -> None:
    """The rewrite list must still name the doc, script, site and test surfaces.

    Completeness is enforced dynamically by ``collect_failures``; this pins the
    *shape* so a future edit cannot quietly narrow the list to, say, docs only
    and leave the installers behind.
    """
    listed = set(checker.SITE_URL_FILES)

    assert len(listed) == len(checker.SITE_URL_FILES), "SITE_URL_FILES has duplicates"
    for required in (
        "readme.md",
        "docs/USER_GUIDE.md",
        "docs/DESKTOP.md",
        "docs/setup/windows.md",
        "docs/setup/macos.md",
        "docs/setup/linux.md",
        "packages/apps/site/src/app/layout.tsx",
        "packages/apps/site/src/app/download/page.tsx",
        "packages/apps/site/src/app/page.tsx",
        "scripts/install/flinttrade-web-install.sh",
        "scripts/install/flinttrade-web-install.ps1",
        "tests/test_windows_command_docs.py",
    ):
        assert required in listed, f"{required} must stay in the scripted rewrite"
    for rel in checker.SITE_URL_FILES:
        assert (ROOT / rel).is_file(), f"{rel} is listed but missing"


@pytest.mark.unit
def test_self_referential_exemption_is_narrow(checker: ModuleType) -> None:
    """The guard exempts only its own two files, and only from the host scan.

    This checker's docstring shows what a stale URL looks like, and this test
    file asserts on one, so both necessarily spell example foreign install
    routes. Exempting them is correct — exempting anything else, or exempting
    them from the "must not spell the canonical URL" rule, would blind the
    guard to the exact drift it exists to catch.
    """
    assert checker.SELF_REFERENTIAL_FILES == frozenset(
        {
            "scripts/check-site-url-consistency.py",
            "tests/test_site_url_single_source.py",
        }
    ), "widening this exemption weakens the guard — justify it here first"

    # The exemption must not overlap the curated rewrite list: a listed file is
    # rewritten by apply-site-url.py and must always name the canonical URL.
    assert not (checker.SELF_REFERENTIAL_FILES & set(checker.SITE_URL_FILES))

    # Neither exempt file may spell the canonical URL — that rule still applies.
    site_url = checker.read_site_url(ROOT)
    for rel in checker.SELF_REFERENTIAL_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert site_url not in text, (
            f"{rel} is exempt from the host scan only; it must not hardcode the site URL"
        )
