"""The default inventory: no-app infrastructure, Vite and installed CSP roles.

No cases are ignored or skipped. All three native inclusion lists are reconciled
against the complete default collection before any bodies or servers start.
"""

import base64
import hashlib
import json
import re
import shutil
import socket
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TERM = ROOT / "packages/apps/terminal"
OUT = Path("/run/test/artifacts")
INFRA_CASES = json.loads(Path(__file__).with_name("infra-cases.json").read_text())
INFRA_FILES = {row["file"] for row in INFRA_CASES}
# Only the original two deliberate automatic-teardown failures qualify.
NEGATIVE_CONTROLS = {
    ("infra-self-tests.spec.ts", "the auto fixture fails teardown for an unused expected handler", "chromium"): (
        "An unused handler must make automatic teardown fail",
        'unused handler or usage mismatch: "deliberately unused automatic handler" GET /api/must-be-used; expected 1 call(s), observed 0',
    ),
    ("infra-self-tests.spec.ts", "the client-error guard is automatic even when syntheticApi is not requested", "chromium"): (
        "A non-allowlisted console error must make automatic teardown fail",
        "console error: automatic guard evidence at <no source URL>",
    ),
}
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


def fixture_origin(fixture_root: Path | None = None) -> tuple[Path, list[tuple[int, int]]]:
    """Read native owner positions from the caller-owned launch source.

    Args:
        fixture_root: Trusted testDir from the launcher, never report.config.
            Omission binds this checkout's actual browser launch directory.

    Returns:
        The absolute fixture path and its three ordered native frame positions.

    Raises:
        ValueError: A required source owner anchor is missing or ambiguous.
        OSError: The launch directory cannot be resolved or its fixture source
            cannot be read, including a missing directory or source file.
    """
    root = (TERM / "e2e" if fixture_root is None else fixture_root).resolve(strict=True)
    source = root / "fixture-registry.ts"
    lines = source.read_text().splitlines()
    anchors = [("    return new Error(", "new Error("),
               ("    const assertionError = this.buildAssertionError();", "buildAssertionError("),
               ("          await registry.dispose();", "await ")]
    positions = []
    for text, token in anchors:
        matches = [(index + 1, line.index(token) + 1) for index, line in enumerate(lines) if line == text]
        if len(matches) != 1:
            raise ValueError("Fixture source owner position is missing or ambiguous")
        positions.append(matches[0])
    return source, positions


def validate_fixture_root(report: dict[str, Any], fixture_root: Path | None = None) -> Path:
    """Bind the reported root to the independently selected launch directory.

    Args:
        report: Native Playwright report whose config.rootDir is checked, not
            used to choose the trusted source directory.
        fixture_root: Caller-owned launch testDir. Omission selects this
            checkout's packages/apps/terminal/e2e directory.

    Returns:
        The resolved absolute launch directory matching the reported root.

    Raises:
        ValueError: The reported root differs from the trusted launch root.
        OSError: The trusted launch directory cannot be resolved, including
            a missing directory.
    """
    root = (TERM / "e2e" if fixture_root is None else fixture_root).resolve(strict=True)
    if report.get("config", {}).get("rootDir") != str(root):
        raise ValueError("Browser report root differs from the trusted launch context")
    return root


def validate_negative_error(
    primary: dict[str, Any], rendered: dict[str, Any], message: str, *, fixture_root: Path | None = None
) -> None:
    """Bind one native error to its exact frames and bounded rendered code frame.

    Args:
        primary: Playwright's structured result.error record.
        rendered: The sole result.errors entry.
        message: The exact original negative-control message.
        fixture_root: Trusted launch testDir, never obtained from the report.

    Raises:
        ValueError: Provenance or rendered/structured correspondence is invalid.
        OSError: The trusted launch directory or fixture source is unavailable
            or unreadable, as described by fixture_origin.
    """
    source, positions = fixture_origin(fixture_root)
    location = primary.get("location", {})
    file = location.get("file", "")
    line, column = location.get("line"), location.get("column")
    if (not isinstance(file, str) or not re.fullmatch(r"(?:/|[A-Za-z]:[\\/])[^\r\n]+[\\/]e2e[\\/]fixture-registry\.ts", file)
            or type(line) is not int or line < 3 or type(column) is not int or column < 1
            or file != str(source) or (line, column) != positions[0]
            or rendered.get("location") != location):
        raise ValueError("Negative control failed outside the original fixture")
    owners = ["FailClosedSyntheticFixtureRegistry.buildAssertionError",
              "FailClosedSyntheticFixtureRegistry.disposeOnce", "Object.baseTest.extend.syntheticApi.auto"]
    stack = primary.get("stack", "")
    if not isinstance(stack, str) or not stack.startswith(message + "\n"):
        raise ValueError("Negative control lost automatic teardown provenance")
    frames = stack[len(message) + 1:].split("\n")
    if len(frames) != len(owners):
        raise ValueError("Negative control lost automatic teardown provenance")
    for index, (frame, owner) in enumerate(zip(frames, owners, strict=True)):
        match = re.fullmatch(r"    at " + re.escape(owner) + r" \(" + re.escape(file) + r":([1-9][0-9]*):([1-9][0-9]*)\)", frame)
        if match is None or (int(match[1]), int(match[2])) != positions[index]:
            raise ValueError("Negative control lost automatic teardown provenance")
    snippet = primary.get("snippet", "")
    if not isinstance(snippet, str):
        raise ValueError("Negative control has no native code frame")
    snippet = re.sub(r"\x1b\[[0-9;]*m", "", snippet)
    header = f"   at fixture-registry.ts:{line}\n\n"
    code = snippet.removeprefix(header).split("\n")
    if not snippet.startswith(header) or len(code) != 7:
        raise ValueError("Negative control has an invalid native code frame")
    # Playwright renders two preceding and three following source lines, plus
    # one caret. Consume the entire bounded frame; no suffix is discarded.
    numbers = [line - 2, line - 1, line, None, line + 1, line + 2, line + 3]
    for text, number in zip(code, numbers, strict=True):
        pattern = r" *\| {" + str(column) + r"}\^" if number is None else (
            (r"> " if number == line else r"  ") + r" *" + str(number) + r" \|[^\r\n\x1b]*"
        )
        if re.fullmatch(pattern, text) is None:
            raise ValueError("Negative control has an invalid native code frame")
    expected = message + "\n\n" + snippet + "\n" + "\n".join(frames)
    if rendered.get("message") != expected or ("stack" in rendered and rendered["stack"] != stack):
        raise ValueError("Negative control rendered error differs from its structured error")


def validate_negative(
    row: dict[str, str], test: dict[str, Any], *, fixture_root: Path | None = None
) -> None:
    """Require the original failed body, cause, provenance and fixture evidence.

    Args:
        row: Literal file/title/project identity.
        test: Native Playwright test and its single executed result.
        fixture_root: Trusted launch testDir; omission uses this checkout.

    Raises:
        ValueError: The record is not an exact original negative control.
        OSError: Its trusted launch directory or fixture source is unavailable
            or unreadable, as described by fixture_origin.
    """
    identity = (row["file"], row["title"], row["project"])
    if identity not in NEGATIVE_CONTROLS:
        raise ValueError("Unknown negative browser control")
    annotation, detail = NEGATIVE_CONTROLS[identity]
    evidence = f'[fail-closed registry "{row["file"]} > {row["title"]}"] 1 failure(s):\n1. {detail}'
    results = test.get("results", [])
    if len(results) != 1:
        raise ValueError("Negative control must execute once")
    result = results[0]
    errors = result.get("errors", [])
    primary = result.get("error", {})
    if (
        test.get("expectedStatus") != "failed" or test.get("status") != "expected"
        or result.get("status") != "failed" or type(result.get("retry")) is not int or result["retry"] != 0
        or len(errors) != 1 or primary.get("message") != "Error: " + evidence
    ):
        raise ValueError("Negative control did not fail for its exact intended cause")
    validate_negative_error(primary, errors[0], "Error: " + evidence, fixture_root=fixture_root)
    for source in [test, result]:
        failures = [a for a in source.get("annotations", []) if a.get("type") == "fail"]
        if len(failures) != 1 or failures[0].get("description") != annotation:
            raise ValueError("Negative control annotation changed")
    attachments = [a for a in result.get("attachments", []) if a.get("name") == "fail-closed-fixture-evidence"]
    if (len(attachments) != 1 or attachments[0].get("contentType") != "text/plain"
            or base64.b64decode(attachments[0].get("body", ""), validate=True).decode() != evidence):
        raise ValueError("Negative control lost its exact fixture evidence")


def validate_report(
    report: dict[str, Any], expected: list[dict[str, str]], *, collection: bool = False, role: str = "application",
    fixture_root: Path | None = None,
) -> list[dict[str, str]]:
    if role not in {"application", "infra"}:
        raise ValueError("Unknown browser role")
    rows = report_rows(report)
    if not rows or report.get("errors") or identities([row for row, _ in rows]) != identities(expected):
        raise ValueError("Browser report errors or changed identities")
    if not collection:
        if role == "infra":
            fixture_root = validate_fixture_root(report, fixture_root)
        for row, test in rows:
            identity = (row["file"], row["title"], row["project"])
            if role == "infra" and identity in NEGATIVE_CONTROLS:
                validate_negative(row, test, fixture_root=fixture_root)
                continue
            results = test.get("results", [])
            if (
                test.get("expectedStatus") != "passed"
                or test.get("status") != "expected"
                or len(results) != 1
                or results[0].get("status") != "passed"
                or type(results[0].get("retry")) is not int or results[0]["retry"] != 0
                or results[0].get("errors")
                or results[0].get("error")
                or any(a.get("type") in {"fail", "skip", "fixme"} for a in test.get("annotations", []))
            ):
                raise ValueError("Each browser body must pass once, with no skips or retries")
    return [row for row, _ in rows]


def partition(
    rows: list[dict[str, str]], out: Path,
    registration_files: dict[tuple[str, str, str], str] | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    infra = [row for row in rows if row["file"] in INFRA_FILES]
    csp = [row for row in rows if row["file"] == "schema-csp.spec.ts"]
    vite = [row for row in rows if row["file"] not in INFRA_FILES | {"schema-csp.spec.ts"}]
    if identities(csp) != identities(CSP_CASES):
        raise ValueError("Original CSP identities missing, changed or duplicated")
    if identities(infra) != identities(INFRA_CASES):
        raise ValueError("Original infrastructure identities missing, changed or duplicated")
    if not vite or any(count != 1 for count in identities(rows).values()):
        raise ValueError("Default browser identities must be distinct and nonempty")
    if identities(infra + vite + csp) != identities(rows):
        raise ValueError("Browser role union differs from the complete default inventory")
    for label, cases in [("infra", infra), ("vite", vite), ("csp", csp)]:
        selectors = []
        for row in cases:
            selectors.append(row)
            if registration_files is not None:
                owner = registration_files[(row['file'], row['title'], row['project'])]
                if owner != row['file']:
                    # Playwright uses the same list for two distinct predicates:
                    # registration-file discovery and definition-file identity.
                    selectors.append(dict(row, file=owner))
        (out / (label + "-test-list.txt")).write_text(
            "".join(f"[{row['project']}] › {row['file']} › {row['title']}\n" for row in selectors)
        )
    return infra, vite, csp


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
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
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
    # CLI selection uses the registering spec, while native identity retains the
    # definition file (which can be an imported helper). Never rename that identity.
    registration_files = {
        (row['file'], row['title'], row['project']): suite['file']
        for suite in report['suites']
        for row, _ in report_rows({'suites': [suite]})
    }
    infra, vite, csp = partition(rows, OUT, registration_files)
    validate_report(
        listing("playwright.infra.config.ts", "default-infra-collection", ["--test-list=" + str(OUT / "infra-test-list.txt")]),
        infra,
        collection=True,
    )
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
        json.dumps({"all": rows, "infra": infra, "vite": vite, "csp": csp, "body_execution": False}, indent=2)
    )
    return infra, vite, csp


def require_free_port() -> None:
    """Refuse dispatch while another role owns the exact loopback listener."""
    with socket.socket() as check:
        check.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        check.bind(("127.0.0.1", 5173))


def run_browser_roles(
    env: dict[str, str], execute: Callable[..., int],
    infra: list[dict[str, str]], vite: list[dict[str, str]],
) -> None:
    """Execute disjoint infrastructure and Vite roles within one original budget.

    Args:
        env: Explicit child environment.
        execute: Owned bounded child-process executor.
        infra: Exact infrastructure inventory admitted by collection.
        vite: Exact Vite inventory admitted by collection.

    Raises:
        RuntimeError: A child fails or the shared budget is exhausted.
        ValueError: A role report fails admission.
        OSError: The exact listener port is already owned.
    """
    # Splitting processes shares the ORIGINAL 1,200-second body budget.
    deadline = time.monotonic() + 1200
    for label, cases, config, role in [
        ("infra", infra, "playwright.infra.config.ts", "infra"),
        ("vite", vite, "playwright.config.ts", "application"),
    ]:
        require_free_port()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("Default browser body budget exhausted")
        report = OUT / ("default-" + label + "-results.json")
        child = dict(env, PLAYWRIGHT_JSON_OUTPUT_FILE=str(report))
        code = execute(
            [*command(config), "--test-list=" + str(OUT / (label + "-test-list.txt")),
             "--output=" + str(OUT / label / "playwright"), "--reporter=list,json"],
            "default-" + label, remaining, child,
        )
        require_free_port()
        if code:
            raise RuntimeError("Default " + label + " browser cases failed")
        validate_report(json.loads(report.read_text()), cases, role=role, fixture_root=TERM / "e2e")


def run(env: dict[str, str], execute: Callable[..., int], case: str | None = None) -> int:
    infra, vite, csp = collect(env, execute)
    if case is None:
        run_browser_roles(env, execute, infra, vite)
    require_free_port()
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
