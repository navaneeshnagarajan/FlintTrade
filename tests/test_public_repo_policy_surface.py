"""Regression checks for support-sensitive public repository surfaces."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CURRENT_ELECTRON_GUIDANCE = (
    Path("packages/apps/desktop/README.md"),
    Path("readme.md"),
    Path("docs/ARCHITECTURE.md"),
    Path("docs/DEVELOPER_GUIDE.md"),
    Path("CLAUDE.md"),
    Path("templates/agent-context/CLAUDE.md.template"),
    Path("templates/agent-context/packages/apps/desktop/CLAUDE.md.template"),
)
ELECTRON_CI_GUIDANCE = Path("docs/CI.md")
ELECTRON_RUNTIME_TEMPLATES = (
    Path("templates/agent-context/CLAUDE.md.template"),
    Path("templates/agent-context/packages/apps/desktop/AGENTS.md.template"),
    Path("templates/agent-context/packages/apps/desktop/CLAUDE.md.template"),
)
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mdx",
    ".mjs",
    ".py",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yml",
    ".yaml",
}


def _tracked_text_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    paths: list[Path] = []
    for raw in result.stdout.splitlines():
        path = ROOT / raw
        if not path.is_file():
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if "/src/generated/" in path.as_posix():
            continue
        if path.name.endswith((".lock", ".snap")):
            continue
        paths.append(path)
    return paths


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def test_no_disabled_github_discussions_links_in_tracked_public_text() -> None:
    """Discussions is disabled for this repo, so public links must not point there."""
    forbidden = "https://github.com/navaneeshnagarajan/FlintTrade/" + "discussions"
    offenders = [path.relative_to(ROOT).as_posix() for path in _tracked_text_files() if forbidden in _read(path)]

    assert offenders == []


def test_api_reference_does_not_document_direct_live_order_curl() -> None:
    """Docs may list APIs, but example order requests must use the practice path."""
    api_doc = _read(ROOT / "docs/API.md")
    direct_live_order_curl = "curl -X POST http://127.0.0.1:5000/api/v1/" + "placeorder"
    concrete_option_symbol = "NIFTY28MAY" + "24850CE"

    assert direct_live_order_curl not in api_doc
    assert concrete_option_symbol not in api_doc
    assert "This example is for a locally issued **Practice-mode** FlintTrade session JWT." in api_doc


def test_api_reference_documents_broker_mcp_as_metadata_only() -> None:
    """The broker MCP catalogue must stay public and non-executable."""
    api_doc = _read(ROOT / "docs/API.md")

    assert "`broker/mcp` (**GET**)" in api_doc
    assert "Broker-hosted MCP setup catalogue" in api_doc
    assert "Metadata only" in api_doc
    assert "does not proxy MCP tool calls" in api_doc
    assert "gate_order" in api_doc
    assert "BrokerRouter" in api_doc


def test_api_reference_documents_native_broker_surface_boundaries() -> None:
    """Native broker routes should document connect, reads, and write-default gates."""
    api_doc = _read(ROOT / "docs/API.md")

    assert "Native broker connect and reads (`/api/v1/native/*`)" in api_doc
    assert "`native/brokers` (**GET**)" in api_doc
    assert "`native/accounts` (**POST**)" in api_doc
    assert "`native/oauth/start` (**POST**)" in api_doc
    assert "`native/oauth/callback` (**GET**)" in api_doc
    assert "`native/postbacks/<adapter_id>` (**POST**)" in api_doc
    assert "`native/accounts/<adapter>/<account>/<kind>` (**GET**)" in api_doc
    assert "`native/accounts/<adapter>/<account>/set-primary` (**POST**)" in api_doc
    assert "connectable=false" in api_doc
    assert "Account and market-data reads" in api_doc
    assert "require a live native session" in api_doc
    assert "connected, non-read-only native session" in api_doc


def test_user_guide_documents_indstocks_dashboard_reset_cycle() -> None:
    """Public broker docs should match the INDstocks dashboard reset semantics."""
    guide = _read(ROOT / "docs/USER_GUIDE.md")
    stale_indstocks_phrase = "INDmoney uses a dashboard-generated " + "24-hour token"

    assert "daily 06:00 IST dashboard cycle" in guide
    assert stale_indstocks_phrase not in guide


def test_public_site_labels_demo_as_exploration_not_live() -> None:
    """The hosted demo is a no-install exploration and should not be labelled live."""
    site_sources = [
        ROOT / "packages/apps/site/src/app/page.tsx",
        ROOT / "packages/apps/site/src/app/demo/page.tsx",
        ROOT / "packages/apps/site/src/components/site-header.tsx",
    ]
    combined = "\n".join(_read(path) for path in site_sources)
    live_demo_title = "Live " + "Demo"
    live_demo_phrase = "live " + "demo"

    assert live_demo_title not in combined
    assert live_demo_phrase not in combined
    assert "Sandbox Demo" not in combined
    assert "Explore demo" in combined
    assert "Install the web app" in combined
    assert "Start exploring — no install needed" not in combined


def test_public_descriptions_preserve_trading_software_identity() -> None:
    """Policy cleanup must not erase what the project actually is."""
    surfaces = {
        "README": ROOT / "readme.md",
        "docs index": ROOT / "docs/README.md",
        "site home": ROOT / "packages/apps/site/src/app/page.tsx",
        "site metadata": ROOT / "packages/apps/site/src/app/layout.tsx",
        "desktop metadata": ROOT / "packages/apps/desktop/package.json",
        "project config": ROOT / "flint.toml",
    }
    combined = "\n".join(_read(path) for path in surfaces.values())

    assert "market workflow workspace" not in combined
    assert "market workflow software" not in combined
    assert "self-hosted trading software" in combined
    assert "manual, automated, algorithmic, and AI-assisted workflows" in _read(surfaces["README"])
    assert "manual orders, automation, and AI-assisted workflows" in _read(surfaces["site home"])


def test_current_electron_guidance_describes_the_stable_release_gate() -> None:
    """Current guidance must describe repository behaviour, not external release status."""
    # This exact current-guidance set deliberately excludes PLAN.md and AGENTS.md,
    # which are live status ledgers, and docs/releases/, which is historical.
    violations: dict[str, list[str]] = {}
    unstable_status_patterns = {
        "current publication status": re.compile(r"\bpublished yet\b", re.IGNORECASE),
        "future first-release prediction": re.compile(r"\bfirst release\b", re.IGNORECASE),
        "branch deployment prediction": re.compile(r"\bthis branch\b.{0,80}\bdeployed\b", re.IGNORECASE | re.DOTALL),
        "current deployment assertion": re.compile(r"\bcurrently deployed\b", re.IGNORECASE),
        "retired beta install reference": re.compile(r"\bbeta\.13\b", re.IGNORECASE),
    }

    for relative_path in CURRENT_ELECTRON_GUIDANCE:
        content = _read(ROOT / relative_path)
        issues = [label for label, pattern in unstable_status_patterns.items() if pattern.search(content)]
        if not re.search(r"source-built web[ -]app", content, re.IGNORECASE):
            issues.append("missing distinct source-built web-app path")
        if not re.search(r"four\s+(?:canonical\s+)?(?:Electron\s+)?installers", content, re.IGNORECASE):
            issues.append("missing four-installer gate")
        if "SHA256SUMS.txt" not in content:
            issues.append("missing checksum-set gate")
        if not re.search(
            r"Tauri(?:\s+and\s+|/)PyInstaller\s+assets?\s+(?:never|do\s+not)\s+satisfy",
            content,
            re.IGNORECASE,
        ):
            issues.append("missing retired-asset rejection")
        if issues:
            violations[relative_path.as_posix()] = issues

    ci_content = _read(ROOT / ELECTRON_CI_GUIDANCE)
    ci_issues = [label for label, pattern in unstable_status_patterns.items() if pattern.search(ci_content)]
    for required in ("manual dispatch only", "four Electron installers", "SHA256SUMS.txt", "empty release target"):
        if required not in ci_content:
            ci_issues.append(f"missing CI contract: {required}")
    if ci_issues:
        violations[ELECTRON_CI_GUIDANCE.as_posix()] = ci_issues

    assert violations == {}


def test_agent_templates_match_the_pinned_electron_runtime_major() -> None:
    """Generated agent guidance must name the Electron major pinned by desktop."""
    package = json.loads(_read(ROOT / "packages/apps/desktop/package.json"))
    electron_pin = package["devDependencies"]["electron"]
    expected_major = electron_pin.split(".", maxsplit=1)[0]
    violations = {
        path.as_posix(): f"expected Electron {expected_major} for pinned {electron_pin}"
        for path in ELECTRON_RUNTIME_TEMPLATES
        if f"Electron {expected_major}" not in _read(ROOT / path)
    }

    assert violations == {}
