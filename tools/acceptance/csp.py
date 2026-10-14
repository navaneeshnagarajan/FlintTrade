"""The default browser inventory, partitioned into Vite and installed CSP runs.

No cases are ignored or skipped. Both native positive test lists are reconciled
against the complete default collection before either server is started.
"""

import hashlib
import json
import shutil
import socket
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TERM = ROOT / "packages/apps/terminal"
OUT = Path("/run/test/artifacts")
CSP_CASES = [
    {"file": "schema-csp.spec.ts", "title": title, "project": "chromium"}
    for title in [
        "cold installed production entry and strict schemas avoid CSP eval",
        "separate eval-negative control retains CSP enforcement and fatal registry",
    ]
]


def identities(rows: list[dict[str, str]]) -> Counter[tuple[str, str, str]]:
    return Counter((row["file"], row["title"], row["project"]) for row in rows)


def report_rows(report: dict[str, Any]) -> list[tuple[dict[str, str], dict[str, Any]]]:
    rows = []

    def visit(suite, parents):
        for spec in suite.get("specs", []):
            for test in spec["tests"]:
                rows.append(
                    (
                        {
                            "file": spec["file"],
                            "title": " › ".join([*parents, spec["title"]]),
                            "project": test["projectName"],
                        },
                        test,
                    )
                )
        for child in suite.get("suites", []):
            visit(child, [*parents, child["title"]])

    for suite in report["suites"]:
        visit(suite, [])
    return rows


def validate_report(
    report: dict[str, Any], expected: list[dict[str, str]], *, collection: bool = False
) -> list[dict[str, str]]:
    rows = report_rows(report)
    if report.get("errors") or identities([row for row, _ in rows]) != identities(expected):
        raise ValueError("Browser report errors or changed identities")
    if not collection:
        for _, test in rows:
            results = test.get("results", [])
            if (
                test.get("expectedStatus") != "passed"
                or test.get("status") != "expected"
                or len(results) != 1
                or results[0].get("status") != "passed"
                or results[0].get("retry") != 0
                or results[0].get("errors")
            ):
                raise ValueError("Each browser body must pass once, with no skips or retries")
    return [row for row, _ in rows]


def partition(
    rows: list[dict[str, str]], out: Path
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    csp = [row for row in rows if row["file"] == "schema-csp.spec.ts"]
    vite = [row for row in rows if row["file"] != "schema-csp.spec.ts"]
    if identities(csp) != identities(CSP_CASES):
        raise ValueError("Original CSP identities missing, changed or duplicated")
    if not vite or any(count != 1 for count in identities(rows).values()):
        raise ValueError("Default browser identities must be distinct and nonempty")
    for label, cases in [("vite", vite), ("csp", csp)]:
        (out / (label + "-test-list.txt")).write_text(
            "".join(f"[{row['project']}] › {row['file']} › {row['title']}\n" for row in cases)
        )
    return vite, csp


def command(config: str) -> list[str | Path]:
    return [
        "node",
        TERM / "node_modules/@playwright/test/cli.js",
        "test",
        "--config=" + str(TERM / config),
        "--project=chromium",
        "--workers=1",
        "--retries=0",
    ]


def collect(
    env: dict[str, str], execute: Callable[..., int]
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    def listing(config, name, extra=()):
        target = OUT / (name + ".json")
        child = dict(env, PLAYWRIGHT_JSON_OUTPUT_FILE=str(target))
        if execute([*command(config), *extra, "--list", "--reporter=json"], name, 90, child):
            raise RuntimeError("Actual default collection failed: " + name)
        report = json.loads(target.read_text())
        if report.get("errors"):
            raise ValueError("Default collection contains errors")
        return report

    report = listing("playwright.config.ts", "default-collection")
    rows = [row for row, _ in report_rows(report)]
    vite, csp = partition(rows, OUT)
    validate_report(
        listing("playwright.config.ts", "default-vite-collection", ["--test-list=" + str(OUT / "vite-test-list.txt")]),
        vite,
        collection=True,
    )
    validate_report(
        listing(
            "playwright.csp.config.ts", "default-csp-collection", ["--test-list=" + str(OUT / "csp-test-list.txt")]
        ),
        csp,
        collection=True,
    )
    (OUT / "default-partition.json").write_text(
        json.dumps({"all": rows, "vite": vite, "csp": csp, "body_execution": False}, indent=2)
    )
    return vite, csp


def run(env: dict[str, str], execute: Callable[..., int], case: str | None = None) -> int:
    vite, csp = collect(env, execute)
    if case is None:
        report = OUT / "default-vite-results.json"
        child = dict(env, PLAYWRIGHT_JSON_OUTPUT_FILE=str(report))
        if execute(
            [
                *command("playwright.config.ts"),
                "--test-list=" + str(OUT / "vite-test-list.txt"),
                "--output=" + str(OUT / "vite/playwright"),
                "--reporter=list,json",
            ],
            "default-vite",
            1200,
            child,
        ):
            raise RuntimeError("Default Vite browser cases failed")
        validate_report(json.loads(report.read_text()), vite)
    with socket.socket() as check:
        check.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        check.bind(("127.0.0.1", 5173))
    if execute(
        [
            "node",
            TERM / "node_modules/vite/bin/vite.js",
            "build",
            TERM,
            "--configLoader",
            "runner",
            "--outDir",
            OUT / "installed-dist",
        ],
        "csp-installed-build",
        240,
    ):
        raise RuntimeError("Normal production build failed")
    dist = OUT / "installed-dist"
    before = {
        str(p.relative_to(dist)): hashlib.sha256(p.read_bytes()).hexdigest() for p in dist.rglob("*") if p.is_file()
    }
    (OUT / "csp-production-bundle.json").write_text(json.dumps(before, indent=2))
    if execute(["node", TERM / "e2e/csp/build-probe.mjs", str(OUT / "schema-companion")], "csp-probe-build", 90):
        raise RuntimeError("Parser companion build failed")
    shutil.copyfile(OUT / "schema-companion/r33-schema-probe.js", dist / "assets/r33-schema-probe.js")
    shutil.copyfile(TERM / "e2e/csp/eval-negative.js", dist / "assets/r33-eval-negative.js")
    if any(hashlib.sha256((dist / name).read_bytes()).hexdigest() != digest for name, digest in before.items()):
        raise RuntimeError("Companion altered the normal production bundle")
    code = execute(
        [*command("playwright.csp.config.ts"), "--test-list=" + str(OUT / "csp-test-list.txt")], "default-csp", 240
    )
    if code:
        raise RuntimeError("Original CSP browser cases failed")
    validate_report(json.loads((OUT / "csp-results.json").read_text()), csp)
    directories = sorted((OUT / "playwright").glob("*/normal-core"))
    if len(directories) != len(csp):
        raise RuntimeError("Missing test-scoped CSP factory evidence")
    starts = [json.loads((directory / "startup.json").read_text()) for directory in directories]
    if len({row["pid"] for row in starts}) != len(csp) or len({row["workspace"] for row in starts}) != len(csp):
        raise RuntimeError("CSP cases reused a factory or workspace")
    for directory in directories:
        stop = json.loads((directory / "shutdown.json").read_text())
        if (
            not all(
                stop.get(key) is True
                for key in ["admission_drained", "listener_stopped", "listener_closed_probe", "owners_released"]
            )
            or stop.get("remaining_threads") != []
        ):
            raise RuntimeError("CSP factory failed to drain")
    return 0
