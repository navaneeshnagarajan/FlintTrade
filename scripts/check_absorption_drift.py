#!/usr/bin/env python3
"""Check absorption drift — what changed in upstream repos since we last absorbed.

For each absorbed repo, compares the commit we absorbed from against
the latest upstream commit and reports new features/APIs we're missing.

Usage:
    python scripts/check_absorption_drift.py
    python scripts/check_absorption_drift.py --repo FinMem
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ─── Absorption registry ─────────────────────────────────────────────────
ABSORBED_REPOS: list[dict] = [
    # EquiCharts entry removed 2026-04-24: reference repo deleted
    # (chart patterns were absorbed into packages/apps/terminal/src/components/Chart.tsx;
    #  further drift checking against the upstream is no longer relevant since
    #  we standardised on Lightweight Charts v5 for the Chart widget).
    {
        "name": "TradingAgents",
        "github": "TradingAgents-AI/TradingAgents",
        "local_path": ".local/reference/repos/tier3-ai-research/TradingAgents",
        "type": "reference",
        "absorbed": [
            "Multi-agent DAG pattern -> packages/services/ai/src/analyst_chain.py",
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
            "4-layer memory architecture -> packages/services/ai/src/memory.py",
            "Reflection loop -> packages/services/ai/src/reflection.py",
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
            "100 strategy templates -> packages/services/backtest/src/strategies/",
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
            "Scanner engine pattern -> packages/services/screener/src/scanner.py",
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
            "exrem/flip/valuewhen signal functions -> packages/core/indicators/src/signals.py",
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
            "StreamingMetrics (Welford) -> packages/services/backtest/src/metrics.py",
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

    # External reference clones are
    # tracked specially: if a .git directory is present, we can compute
    # drift against origin/main. They no longer exist for end users — only
    # for contributors with local reference clones.
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
