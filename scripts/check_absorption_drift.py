#!/usr/bin/env python3
"""Check absorption drift — what changed in upstream repos since we last absorbed.

For each absorbed repo, compares the commit we absorbed from against
the latest upstream commit and reports new features/APIs we're missing.

Usage:
    python scripts/check_absorption_drift.py
    python scripts/check_absorption_drift.py --repo openalgo
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ─── Absorption registry ─────────────────────────────────────────────────
# Each entry tracks: repo name, local path (submodule or .local/reference/),
# what we absorbed, and what commit/date we last checked.

ABSORBED_REPOS: list[dict] = [
    {
        "name": "openalgo",
        "github": "marketcalls/openalgo",
        "local_path": "infra/openalgo",
        "type": "submodule",
        "absorbed": [
            "REST API client (45+ endpoints) -> packages/core/src/openalgo_client.py",
            "WebSocket protocol -> packages/terminal/src/services/websocket.ts",
            "Broker adapter pattern -> packages/gateway/",
            "Option chain/Greeks -> packages/screener/",
            "React dashboard patterns -> packages/terminal/",
        ],
        "last_absorbed_commit": "47a1f51e",  # v0.2.0-beta baseline
        "missing_since": [
            "GET /api/broker/capabilities — broker exchange/feature metadata",
            "GET/POST /api/broker/credentials — credential management",
            "blueprints/leverage.py — leverage settings for crypto",
            "restx_api/pnl_symbols.py — P&L symbol tracking",
            "Market Price Protection (MPP) for Zerodha/Kotak",
            "Crypto design separation (dynamic exchanges, hide product)",
            "Security dashboard hardening (auto-ban toggle, sorting)",
            "Zebu OAuth migration (TOTP -> OAuth 2.0)",
            "Flattrade V2 API endpoint migration",
            "Telegram alert service refactor (sync HTTP, no asyncio)",
        ],
    },
    {
        "name": "algomirror",
        "github": "marketcalls/algomirror",
        "local_path": "infra/algomirror",
        "type": "submodule",
        "absorbed": [
            "Multi-account mirror patterns -> packages/ditto/",
            "Trailing SL logic -> packages/engine/",
        ],
        "last_absorbed_commit": "d2c3cfda",
        "missing_since": [],
    },
    {
        "name": "openclaw",
        "github": "openclaw/openclaw",
        "local_path": "infra/openclaw",
        "type": "submodule",
        "absorbed": [
            "Agent gateway pattern -> packages/automation/src/openclaw_bridge.py",
            "Telegram/WhatsApp transport -> packages/automation/src/telegram_bot.py",
        ],
        "last_absorbed_commit": "abce6407",
        "missing_since": [
            "Plugin SDK namespaces",
            "Exec approval system",
            "WhatsApp reply quoting",
            "Device token rotation",
        ],
    },
    {
        "name": "openalgo-flow",
        "github": "marketcalls/openalgo-flow",
        "local_path": ".local/reference/repos/tier1-core/openalgo-flow",
        "type": "reference",
        "absorbed": [
            "6 of 54 node types -> packages/integration/src/flow_builder.py",
            "Visual canvas pattern -> /automate route FlowBuilder",
        ],
        "last_absorbed_commit": "unknown",
        "missing_since": [
            "48 more node types not absorbed",
        ],
    },
    {
        "name": "openalgo-chart",
        "github": "aspect-build/equicharts",
        "local_path": ".local/reference/repos/tier2-ecosystem/EquiCharts",
        "type": "reference",
        "absorbed": [
            "Chart component patterns -> packages/terminal/src/components/Chart.tsx",
            "Drawing tools -> Chart widget",
            "Replay mode -> useChartReplay hook",
        ],
        "last_absorbed_commit": "unknown",
        "missing_since": [
            "80+ components only pattern-absorbed, not component-level",
        ],
    },
    {
        "name": "TradingAgents",
        "github": "TradingAgents-AI/TradingAgents",
        "local_path": ".local/reference/repos/tier3-ai-research/TradingAgents",
        "type": "reference",
        "absorbed": [
            "Multi-agent DAG pattern -> packages/ai/src/analyst_chain.py",
            "Debate/risk judge flow -> analyst_chain.py",
        ],
        "last_absorbed_commit": "unknown",
        "missing_since": [],
    },
    {
        "name": "FinMem",
        "github": "pipiku915/FinMem-LLM-StockTrading",
        "local_path": ".local/reference/repos/tier3-ai-research/FinMem",
        "type": "reference",
        "absorbed": [
            "4-layer memory architecture -> packages/ai/src/memory.py",
            "Reflection loop -> packages/ai/src/reflection.py",
        ],
        "last_absorbed_commit": "unknown",
        "missing_since": [],
    },
    {
        "name": "AlgoTrading",
        "github": "StockSharp/AlgoTrading",
        "local_path": ".local/reference/repos/external-all/AlgoTrading",
        "type": "reference",
        "absorbed": [
            "100 strategy templates -> packages/backtest-engine/src/strategies/",
        ],
        "last_absorbed_commit": "unknown",
        "missing_since": [],
    },
]


def _run(cmd: list[str], cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=cwd)
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def check_repo(repo: dict) -> dict:
    """Check a single repo for drift."""
    local_path = ROOT / repo["local_path"]
    result = {**repo, "current_commit": "", "upstream_commit": "", "commits_behind": 0}

    if not local_path.exists():
        result["notes"] = "Directory not found"
        return result

    if repo["type"] == "submodule":
        result["current_commit"] = _run(["git", "rev-parse", "--short", "HEAD"], cwd=local_path)
        _run(["git", "fetch", "origin", "--quiet"], cwd=local_path)
        result["upstream_commit"] = _run(["git", "rev-parse", "--short", "origin/main"], cwd=local_path)
        behind = _run(["git", "rev-list", "HEAD..origin/main", "--count"], cwd=local_path)
        result["commits_behind"] = int(behind) if behind.isdigit() else 0

    return result


def format_report(repos: list[dict]) -> str:
    lines = [
        "# FlintTrade — Absorption Drift Report",
        "",
        f"> Generated: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## Submodules",
        "",
        "| Repo | Local | Upstream | Behind | Missing Features |",
        "|------|-------|----------|--------|------------------|",
    ]

    for r in repos:
        if r["type"] != "submodule":
            continue
        missing_count = len(r.get("missing_since", []))
        missing_text = f"{missing_count} items" if missing_count else "Up to date"
        behind = r.get("commits_behind", 0)
        lines.append(
            f"| {r['name']} | {r.get('current_commit', '?')} | "
            f"{r.get('upstream_commit', '?')} | {behind} | {missing_text} |"
        )

    lines.extend(["", "## Reference Repos (pattern-absorbed)", ""])
    lines.append("| Repo | What We Absorbed | Missing |")
    lines.append("|------|-----------------|---------|")

    for r in repos:
        if r["type"] != "reference":
            continue
        absorbed = "; ".join(r.get("absorbed", [])[:2])
        missing = "; ".join(r.get("missing_since", [])[:2]) or "Complete"
        lines.append(f"| {r['name']} | {absorbed} | {missing} |")

    lines.extend(["", "## Action Items", ""])
    for r in repos:
        missing = r.get("missing_since", [])
        if missing:
            lines.append(f"### {r['name']}")
            for item in missing:
                lines.append(f"- [ ] {item}")
            lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check absorption drift")
    parser.add_argument("--repo", help="Check specific repo only")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = parser.parse_args()

    repos = ABSORBED_REPOS
    if args.repo:
        repos = [r for r in repos if r["name"] == args.repo]

    results = [check_repo(r) for r in repos]

    if args.format == "json":
        print(json.dumps(results, indent=2, default=str))
    else:
        print(format_report(results))


if __name__ == "__main__":
    main()
