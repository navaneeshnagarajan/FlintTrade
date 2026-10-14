"""Publish only typed numeric outcomes, never raw acceptance evidence.

This is a lossy public summary, NOT an acceptance validator. Originals remain
untouched in runner-local custody; Actions artifacts are public to repo readers.
Missing/invalid evidence is unknown (null), not zero or a successful execution.
"""
from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

LANES = ("e2e:maintained:contracts", "e2e:infra:typecheck", "e2e:infra:lint",
         "e2e:maintained:collect", "e2e:reticle:collect", "e2e:default",
         "e2e:public-demo", "e2e:incidents", "e2e:oauth", "e2e:reticle:controls",
         "e2e:reticle", "e2e:policy", "e2e:paper")
# Only these exact files are read. No traces, logs, bodies, wire, names or URLs.
REPORTS = (("default-vite", "e2e:default", "default-vite-results.json"),
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


def playwright_counts(report):
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
    outcomes = Counter()
    categories = Counter()
    for test in tests:
        results = test.get("results")
        require(isinstance(results, list) and len(results) == 1)
        result = results[0]
        require(type(result.get("retry")) is int and result["retry"] == 0)
        status = result.get("status")
        require(status in {"passed", "failed", "timedOut", "interrupted", "skipped"})
        category = test.get("status")
        require(category in {"expected", "unexpected", "flaky", "skipped"})
        categories[category] += 1
        outcomes[status] += 1
    require(isinstance(report.get("stats"), dict))
    for key in ("expected", "unexpected", "flaky", "skipped"):
        require(integer(report["stats"].get(key)) == categories[key])
    return {"tests": len(tests), "passed": outcomes["passed"],
            "failed": sum(outcomes[k] for k in ("failed", "timedOut", "interrupted")),
            "errors": len(report["errors"]), "skipped": outcomes["skipped"]}


def project(state, head):
    result = {"schema": 1, "head": None, "exit_code": None, "isolation_guard_passed": None,
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
            counts = junit_counts(raw) if relative.endswith(".xml") else playwright_counts(json.loads(raw, object_pairs_hook=object_pairs))
            row.update(status="present", counts=counts)
            if result["exit_code"] == 0 and any(counts[k] for k in ("failed", "errors", "skipped")):
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
    args = parser.parse_args()
    summary = project(args.state.absolute(), args.head.absolute())
    # Output lives separately: no raw file or previous summary can be overwritten.
    require(not args.output.absolute().is_relative_to(args.state.absolute()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(summary, indent=2) + "\n")
    print("Public evidence projection " + ("valid" if summary["projection_valid"] else "incomplete or invalid"))
    return 0 if summary["projection_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
