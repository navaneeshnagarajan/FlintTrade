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
# Each entry tracks: repo name, local path (.local/external/ for the
# external test-deps, or .local/reference/ for pattern-absorbed repos), what
# we absorbed, and what commit/date we last checked. The external repos
# (openalgo, openclaw) used to be git submodules under infra/; they are
# now plain reference clones under .local/external/ and only present
# locally if the user ran scripts/setup-test-deps.sh. AlgoMirror is
# absent: its mirroring patterns are fully absorbed into packages/ditto/
# and the repo is no longer pulled or tracked.

ABSORBED_REPOS: list[dict] = [
    {
        "name": "openalgo",
        "github": "marketcalls/openalgo",
        "local_path": ".local/external/openalgo",
        "type": "reference",
        "absorbed": [
            "REST API client (45+ endpoints) -> packages/core/src/openalgo_client.py",
            "WebSocket protocol -> packages/terminal/src/services/websocket.ts",
            "Broker adapter pattern -> packages/gateway/",
            "Option chain/Greeks -> packages/screener/",
            "React dashboard patterns -> packages/terminal/",
        ],
        "last_absorbed_commit": "960b2ad2",  # Updated 2026-03-31
        "missing_since": [
            "Zebu OAuth migration (TOTP -> OAuth 2.0)",
            "Flattrade V2 API endpoint migration",
            "Telegram alert service refactor (sync HTTP, no asyncio)",
        ],
    },
    {
        "name": "openclaw",
        "github": "openclaw/openclaw",
        "local_path": ".local/external/openclaw",
        "type": "reference",
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
            "54 of 54 node types -> packages/integration/src/flow_builder.py",
            "Visual canvas pattern -> /automate route FlowBuilder",
            "Draggable node palette with 8 categories",
        ],
        "last_absorbed_commit": "2026-03-31",
        "missing_since": [],
    },
    # EquiCharts entry removed 2026-04-24: reference repo deleted
    # (chart patterns were absorbed into packages/terminal/src/components/Chart.tsx;
    #  further drift checking against the upstream is no longer relevant since
    #  we standardised on Lightweight Charts v5 for the Chart widget).
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
    {
        "name": "fluxscan",
        "github": "marketcalls/fluxscan",
        "local_path": ".local/reference/repos/marketcalls-all/fluxscan",
        "type": "reference",
        "absorbed": [
            "Scanner engine pattern -> packages/screener/src/scanner.py",
            "6 built-in scanner templates",
        ],
        "last_absorbed_commit": "2026-03-31",
        "missing_since": [],
    },
    {
        "name": "pandas_signals_library",
        "github": "marketcalls/pandas_signals_library",
        "local_path": ".local/reference/repos/marketcalls-all/pandas_signals_library",
        "type": "reference",
        "absorbed": [
            "exrem/flip/valuewhen signal functions -> packages/indicators/src/signals.py",
        ],
        "last_absorbed_commit": "2026-03-31",
        "missing_since": [],
    },
    {
        "name": "raptorbt",
        "github": "marketcalls/raptorbt",
        "local_path": ".local/reference/repos/marketcalls-all/raptorbt",
        "type": "reference",
        "absorbed": [
            "StreamingMetrics (Welford) -> packages/backtest-engine/src/metrics.py",
        ],
        "last_absorbed_commit": "2026-03-31",
        "missing_since": [
            "Rust basket/options/spread backtest patterns (requires Rust expertise)",
        ],
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

    # External test-deps under .local/external/ (openalgo, openclaw) are
    # tracked specially: if a .git directory is present, we can compute
    # drift against origin/main. They no longer exist for end users — only
    # for contributors who ran scripts/setup-test-deps.sh.
    is_external_test_dep = repo["local_path"].startswith(".local/external/")
    if is_external_test_dep and (local_path / ".git").exists():
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
        "## External test-deps (.local/external/)",
        "",
        "| Repo | Local | Upstream | Behind | Missing Features |",
        "|------|-------|----------|--------|------------------|",
    ]

    for r in repos:
        if not r["local_path"].startswith(".local/external/"):
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
        # Skip .local/external/* entries — they're already covered in the
        # "External test-deps" section above.
        if r["local_path"].startswith(".local/external/"):
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
