"""Publish only typed numeric outcomes, never raw acceptance evidence.

This is a lossy public summary, NOT an acceptance validator. Originals remain
untouched in runner-local custody; Actions artifacts are public to repo readers.
Missing/invalid evidence is unknown (null), not zero or a successful execution.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

LANES = ("e2e:maintained:contracts", "e2e:infra:typecheck", "e2e:infra:lint",
         "e2e:maintained:collect", "e2e:reticle:collect", "e2e:default",
         "e2e:public-demo", "e2e:incidents", "e2e:oauth", "e2e:reticle:controls",
         "e2e:reticle", "e2e:policy", "e2e:paper")
# Only these exact report files are read. No raw fields are ever projected.
REPORTS = (("default-infra", "e2e:default", "default-infra-results.json"),
           ("default-vite", "e2e:default", "default-vite-results.json"),
           ("default-csp", "e2e:default", "csp-results.json"),
           ("incidents", "e2e:incidents", "incidents/report.xml"),
           ("oauth", "e2e:oauth", "oauth.xml"),
           ("reticle", "e2e:reticle", "results.xml"),
           ("policy", "e2e:policy", "results.xml"))


def require(condition):
    if not condition:
        raise ValueError("Invalid evidence")


def integer(value, minimum=0):
    require(type(value) is int and minimum <= value <= 1_000_000)
    return value


def safe_path(root, path):
    root, path = root.absolute(), path.absolute()
    require(path.is_relative_to(root))
    require(not any(p.is_symlink() for p in [path, *path.parents]))
    return path


def text(root, path):
    path = safe_path(root, path)
    require(path.is_file() and path.stat().st_size <= 32 * 1024 * 1024)
    return path.read_text(encoding="utf-8-sig")


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def load_json(root, path):
    return json.loads(text(root, path), object_pairs_hook=object_pairs)


def junit_counts(raw):
    # UTF-8 text is size-bounded by the reader; reject declarations before
    # stdlib XML parsing so neither DTDs nor entity expansion reach the parser.
    require("\x00" not in raw and "<!DOCTYPE" not in raw.upper() and "<!ENTITY" not in raw.upper())
    root = ET.fromstring(raw)
    require(root.tag in {"testsuites", "testsuite"})
    cases = list(root.iter("testcase"))
    require(bool(cases))
    for case in cases:
        require(sum(len(case.findall(tag)) for tag in ("failure", "error", "skipped")) <= 1)
    for node in [root, *root.findall(".//testsuite")]:
        contained = list(node.iter("testcase"))
        # Pytest omits root totals; each concrete suite still declares its
        # count. Derive from actual children and check every present declaration.
        require(node.get("tests") is not None or (node is root and root.tag == "testsuites" and bool(root.findall("testsuite"))))
        for key, tag in [("tests", "testcase"), ("failures", "failure"), ("errors", "error"), ("skipped", "skipped")]:
            count = len(contained) if key == "tests" else sum(len(c.findall(tag)) for c in contained)
            declared = node.get(key)
            if declared is not None:
                require(re.fullmatch(r"[0-9]+", declared) is not None and int(declared) == count)
            # Error/failure children outside cases cannot be concealed by totals.
            require(len(list(node.iter(tag))) == count)
    failed = sum(bool(c.find("failure") is not None) for c in cases)
    errors = sum(bool(c.find("error") is not None) for c in cases)
    skipped = sum(bool(c.find("skipped") is not None) for c in cases)
    return {"tests": len(cases), "passed": len(cases) - failed - errors - skipped,
            "failed": failed, "errors": errors, "skipped": skipped}


def playwright_counts(
    report: dict[str, Any], *, infrastructure: bool = False, fixture_root: Path | None = None
) -> dict[str, int]:
    """Project numeric outcomes only after report consistency checks.

    Args:
        report: Parsed native Playwright report.
        infrastructure: Require the literal infrastructure inventory and controls.
        fixture_root: Independently selected launch testDir, not report data.

    Returns:
        Numeric counts, not an acceptance assertion.

    Raises:
        ValueError: Evidence is contradictory or incomplete.
    """
    require(isinstance(report, dict) and isinstance(report.get("suites"), list))
    tests = []
    def visit(suite):
        require(isinstance(suite, dict))
        for spec in suite.get("specs", []):
            require(isinstance(spec.get("tests"), list))
            tests.extend(spec["tests"])
        for child in suite.get("suites", []):
            visit(child)
    for suite in report["suites"]:
        visit(suite)
    require(bool(tests) and isinstance(report.get("errors"), list))
    expected_failed = 0
    if infrastructure:
        # Reuse the private admission contract; never copy names, errors or
        # attachments to this numeric projection. Missing/wrong controls are
        # unknown, not an invented zero or a general expected-failure allowance.
        source = Path(__file__).resolve().parents[1] / "tools/acceptance/csp.py"
        spec = importlib.util.spec_from_file_location("browser_report_contract", source)
        if spec is None or spec.loader is None:
            raise ValueError("Missing browser report contract")
        carrier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(carrier)
        fixture_root = carrier.validate_fixture_root(report, fixture_root)
        rows = carrier.report_rows(report)
        require(carrier.identities([row for row, _ in rows]) == carrier.identities(carrier.INFRA_CASES))
        for row, test in rows:
            identity = (row["file"], row["title"], row["project"])
            if identity in carrier.NEGATIVE_CONTROLS:
                carrier.validate_negative(row, test, fixture_root=fixture_root)
                expected_failed += 1
            else:
                require(test.get("expectedStatus") == "passed")
        require(expected_failed == len(carrier.NEGATIVE_CONTROLS))
    else:
        require(not any(test.get("expectedStatus") == "failed" for test in tests))
    outcomes = Counter()
    categories = Counter()
    for test in tests:
        results = test.get("results")
        require(isinstance(results, list) and len(results) == 1)
        result = results[0]
        require(type(result.get("retry")) is int and result["retry"] == 0)
        status = result.get("status")
        require(status in {"passed", "failed", "timedOut", "interrupted", "skipped"})
        if status == "passed":
            require(not result.get("error") and not result.get("errors"))
        category = test.get("status")
        require(category in {"expected", "unexpected", "flaky", "skipped"})
        categories[category] += 1
        outcomes[status] += 1
    require(isinstance(report.get("stats"), dict))
    for key in ("expected", "unexpected", "flaky", "skipped"):
        require(integer(report["stats"].get(key)) == categories[key])
    return {"tests": len(tests), "passed": outcomes["passed"],
            "failed": sum(outcomes[k] for k in ("failed", "timedOut", "interrupted")),
            "expected_failed": expected_failed,
            "errors": len(report["errors"]), "skipped": outcomes["skipped"]}


def project(state, head, *, browser_source: Path | None = None):
    # The CI launcher archives into this fixed sibling, mounted at the same
    # absolute path. This is caller-owned context, not a report/receipt claim.
    source = state.parent / "acceptance-source" if browser_source is None else browser_source
    result = {"schema": 2, "head": None, "exit_code": None, "isolation_guard_passed": None,
              "lanes": [], "reports": [], "projection_valid": False,
              "acceptance_verified": False, "issues": []}
    issues = result["issues"]
    try:
        commit = text(head.parent, head).strip()
        require(re.fullmatch(r"[0-9a-f]{40}", commit) is not None)
        result["head"] = commit
    except (ValueError, OSError):
        issues.append("head-invalid")
    run = None
    try:
        receipts = list(safe_path(state, state / "runs").glob("maintained-acceptance-*.json"))
        require(len(receipts) == 1)
        receipt = load_json(state, receipts[0])
        require(receipt["label"] == "maintained-acceptance")
        code = integer(receipt["exit_code"], -255)
        guard = receipt["isolation_guard_passed"]
        require(type(guard) is bool)
        run = safe_path(state, Path(receipt["run_directory"]))
        require(run.parent == state.absolute() and run.name.startswith("flinttrade-maintained-acceptance-") and run.is_dir())
        result.update(exit_code=code, isolation_guard_passed=guard)
        if not guard:
            issues.append("isolation-unverified")
    except (ValueError, OSError, KeyError, TypeError):
        run = None
        issues.append("receipt-invalid-or-missing")
    directories = {}
    first_missing = None
    if run is not None:
        for lane in LANES:
            try:
                directory = safe_path(state, run / "e2e-evidence" / lane)
                completed = directory.is_dir()
                if not completed and first_missing is None:
                    first_missing = lane
                elif completed and first_missing is not None:
                    issues.append("lane-order-invalid")
                directories[lane] = directory if completed else (run / "artifacts" if lane == first_missing else directory)
                result["lanes"].append({"lane": lane, "completed": completed})
            except (ValueError, OSError):
                issues.append("lane-path-invalid")
        if result["exit_code"] == 0 and first_missing is not None:
            issues.append("successful-exit-with-incomplete-lanes")
    for name, lane, relative in REPORTS:
        row = {"report": name, "status": "missing", "counts": None}
        result["reports"].append(row)
        try:
            if lane not in directories:
                raise FileNotFoundError
            path = safe_path(state, directories[lane] / relative)
            if not path.exists():
                raise FileNotFoundError
            raw = text(state, path)
            counts = junit_counts(raw) if relative.endswith(".xml") else playwright_counts(
                json.loads(raw, object_pairs_hook=object_pairs), infrastructure=name == "default-infra",
                fixture_root=source / "packages/apps/terminal/e2e",
            )
            row.update(status="present", counts=counts)
            if result["exit_code"] == 0 and (
                counts["failed"] != counts.get("expected_failed", 0) or counts["errors"] or counts["skipped"]
            ):
                issues.append("successful-exit-with-nonpassing-report")
        except FileNotFoundError:
            issues.append("report-missing")
        except (ValueError, OSError, KeyError, TypeError, AttributeError, RecursionError, ET.ParseError):
            row["status"] = "invalid"
            issues.append("report-invalid")
    result["issues"] = sorted(set(issues))
    result["projection_valid"] = not issues
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("state", "head", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--browser-source", type=Path, help="Trusted launch checkout; defaults to state's acceptance-source sibling")
    args = parser.parse_args()
    summary = project(args.state.absolute(), args.head.absolute(), browser_source=args.browser_source)
    # Output lives separately: no raw file or previous summary can be overwritten.
    require(not args.output.absolute().is_relative_to(args.state.absolute()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(summary, indent=2) + "\n")
    print("Public evidence projection " + ("valid" if summary["projection_valid"] else "incomplete or invalid"))
    return 0 if summary["projection_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
