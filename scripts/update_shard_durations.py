"""Rebuild the per-file timing record used to balance Python CI shards.

Usage::

    uv run python scripts/update_shard_durations.py python-0.xml python-1.xml ...

Pass every JUnit file from one or more complete CI runs (the
``python-shard-*`` artefacts), with ``--runs`` set to the number of runs so
noisy files are averaged. Times are summed per test file. Files that took at least
``--min-seconds`` are written, keyed by a hash of their path and rounded to
tenths of a second, to
``scripts/pytest_shard_durations.json``; the quicker files are summarised as
one average per-test charge (``default_test_seconds``). A new file missing from
the record still runs and is charged that average until the record is
refreshed.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.pytest_shard import file_key  # noqa: E402

DEFAULT_OUTPUT = REPO_ROOT / "scripts" / "pytest_shard_durations.json"


def file_for_classname(classname: str, root: Path = REPO_ROOT) -> str | None:
    """Map a JUnit ``classname`` such as ``pkg.tests.test_x.TestY`` to its file."""
    parts = classname.split(".")
    for end in range(len(parts), 0, -1):
        candidate = Path(*parts[:end]).with_suffix(".py")
        if (root / candidate).is_file():
            return candidate.as_posix()
    return None


def collect(paths: list[Path], root: Path = REPO_ROOT) -> tuple[dict[str, float], dict[str, int], int]:
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    unresolved = 0
    for path in paths:
        for case in ET.parse(path).getroot().iter("testcase"):
            name = file_for_classname(case.get("classname", ""), root)
            if name is None:
                unresolved += 1
                continue
            totals[name] = totals.get(name, 0.0) + float(case.get("time") or 0.0)
            counts[name] = counts.get(name, 0) + 1
    return totals, counts, unresolved


def build_record(totals: dict[str, float], counts: dict[str, int], min_seconds: float) -> dict:
    slow = {name for name, seconds in totals.items() if seconds >= min_seconds}
    kept = dict(sorted((file_key(name), round(totals[name], 1)) for name in slow))
    quick = [name for name in totals if name not in slow]
    quick_tests = sum(counts[name] for name in quick)
    default = sum(totals[name] for name in quick) / quick_tests if quick_tests else 0.0
    return {"default_test_seconds": round(default, 4), "files": kept}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("junit", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--min-seconds", type=float, default=2.0)
    parser.add_argument("--runs", type=int, default=1,
                        help="How many complete CI runs the JUnit files cover; times are averaged over them.")
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    totals, counts, unresolved = collect(args.junit)
    totals = {name: seconds / args.runs for name, seconds in totals.items()}
    counts = {name: max(1, round(tests / args.runs)) for name, tests in counts.items()}
    if not totals:
        print("No test cases could be mapped to files.", file=sys.stderr)
        return 1
    record = build_record(totals, counts, args.min_seconds)
    args.output.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    print(
        f"Recorded {len(record['files'])} of {len(totals)} files ({sum(totals.values()):.0f}s in total); "
        f"{record['default_test_seconds']}s per test for the rest; {unresolved} cases unresolved."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
