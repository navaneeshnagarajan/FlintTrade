"""Regression checks for support-sensitive public repository surfaces."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
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


def test_public_site_labels_demo_as_sandbox_not_live() -> None:
    """The hosted demo is sample/sandbox-oriented and should not be labelled live."""
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
    assert "Sandbox Demo" in combined


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
