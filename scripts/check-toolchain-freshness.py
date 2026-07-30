#!/usr/bin/env python3
"""Fail while a declared or pinned toolchain version is EOL, or has fallen out of the N-1 band.

``pnpm audit`` and ``pip-audit`` see published *packages*. They are blind to the
toolchain binaries FlintTrade pins itself - the Node runtime and pnpm release the
desktop bootstrap downloads, the uv build that provisions Python, and the floors
and targets ``flint.toml`` declares. Those go stale silently: nothing in CI
noticed that the pinned Node release key had expired, and nothing today notices
when a pinned runtime line reaches end of life.

This check reads ``flint.toml`` as the source of truth and compares every version
it finds against upstream release data:

* ``https://nodejs.org/dist/index.json``               - every published Node release
* ``.../nodejs/Release/main/schedule.json``            - the Node LTS/EOL calendar
* ``https://registry.npmjs.org/-/package/pnpm/dist-tags`` - the pnpm release tags
* ``https://api.github.com/repos/astral-sh/uv/releases/latest`` - the current uv
* ``https://endoflife.date/api/python.json``           - the CPython EOL calendar

Two severities, and the distinction mirrors the one ``flint.toml`` itself draws:

**Floors** (``python_requires``, ``node_requires``) are set by what the dependency
tree genuinely needs, so they are judged on end of life alone. A floor that trails
the newest release is correct behaviour, not drift.

**Targets and pins** (``python_target``, ``node_target``, the bootstrap
``tool-manifest.json`` entries, ``packageManager``) are meant to track current
stable, so they fail when the line is EOL *or* has slipped further back than one
release line (the N-1 band). Being behind on the patch inside an in-band line is a
warning, because a pin like Node's travels with a mirrored signing key and cannot
move on its own.

Network failures never fail the run: each source is fetched independently and a
source that cannot be reached is reported as skipped. A blip upstream must not
redden an unrelated pull request::

    python scripts/check-toolchain-freshness.py
    python scripts/check-toolchain-freshness.py --offline   # parse the pins, fetch nothing
    python scripts/check-toolchain-freshness.py --json      # machine-readable findings
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import pathlib
import re
import sys
import tomllib
import urllib.error
import urllib.request
from typing import Any

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_FLINT_TOML = _REPO_ROOT / "flint.toml"
_TOOL_MANIFEST = _REPO_ROOT / "packages/apps/desktop/resources/bootstrap/tool-manifest.json"
_ROOT_PACKAGE_JSON = _REPO_ROOT / "package.json"

_NODE_DIST_URL = "https://nodejs.org/dist/index.json"
_NODE_SCHEDULE_URL = "https://raw.githubusercontent.com/nodejs/Release/main/schedule.json"
_PNPM_DIST_TAGS_URL = "https://registry.npmjs.org/-/package/pnpm/dist-tags"
_UV_LATEST_RELEASE_URL = "https://api.github.com/repos/astral-sh/uv/releases/latest"
_PYTHON_CYCLES_URL = "https://endoflife.date/api/python.json"

_FETCH_TIMEOUT_SECONDS = 20
# The npm registry and the GitHub API both want a User-Agent; the default
# urllib one is rejected by some CDN edges.
_USER_AGENT = "flinttrade-toolchain-freshness/1 (+https://github.com/navaneeshnagarajan/FlintTrade)"

# How many release lines back from current still counts as supported here. 1 means
# "the newest line and the one before it" - the N-1 band.
_LINES_BACK_ALLOWED = 1


@dataclasses.dataclass(frozen=True)
class Waiver:
    """A knowingly-out-of-band pin, with a date the waiver stops working.

    Attributes:
        subject: The subject string the finding is raised against.
        reason: Why the pin cannot move yet, in one sentence.
        review_by: ISO date after which the waiver expires and the finding fails.
    """

    subject: str
    reason: str
    review_by: str


# Waivers are deliberately dated. An undated suppression is indistinguishable
# from a bug, so every entry expires and the finding turns fatal again on its own.
_WAIVERS: tuple[Waiver, ...] = (
    Waiver(
        subject="pnpm (release line)",
        reason=(
            "pnpm 9 -> 11 is a lockfile-format and lifecycle-script migration, not a version bump: "
            "pnpm 10 stopped running dependency build scripts unless allowlisted and pnpm 11 turns an "
            "un-allowlisted build into a hard failure. pnpm-workspace.yaml already carries the allowBuilds "
            "block for it, but the block is inert below pnpm 10.26.0, so the move has to be made and "
            "verified deliberately rather than as a drive-by"
        ),
        review_by="2026-10-31",
    ),
)


@dataclasses.dataclass(frozen=True)
class Finding:
    """One thing this check has to say about a version.

    Attributes:
        level: ``fail``, ``warn`` or ``note``.
        subject: What the finding is about, e.g. ``node_target (flint.toml)``.
        message: The operator-facing explanation.
    """

    level: str
    subject: str
    message: str


class Report:
    """Collected findings plus the sources that could not be reached."""

    def __init__(self) -> None:
        self.findings: list[Finding] = []
        self.skipped: list[str] = []

    def add(self, level: str, subject: str, message: str) -> None:
        """Record a finding, applying any live waiver.

        Args:
            level: ``fail``, ``warn`` or ``note``.
            subject: What the finding is about.
            message: The operator-facing explanation.
        """
        if level == "fail":
            waiver = _live_waiver(subject)
            if waiver is not None:
                self.findings.append(
                    Finding(
                        "warn",
                        subject,
                        f"{message} WAIVED until {waiver.review_by}: {waiver.reason}.",
                    )
                )
                return
        self.findings.append(Finding(level, subject, message))

    def skip(self, source: str, error: str) -> None:
        """Record an unreachable data source.

        Args:
            source: The URL that could not be read.
            error: The failure text.
        """
        self.skipped.append(f"{source} ({error})")

    @property
    def failed(self) -> bool:
        """Whether any finding is fatal."""
        return any(finding.level == "fail" for finding in self.findings)


def _live_waiver(subject: str) -> Waiver | None:
    """Return the unexpired waiver covering *subject*, if any.

    Args:
        subject: The finding subject.

    Returns:
        The waiver, or ``None`` when there is none or it has expired.
    """
    today = dt.date.today()
    for waiver in _WAIVERS:
        if waiver.subject != subject:
            continue
        if dt.date.fromisoformat(waiver.review_by) >= today:
            return waiver
    return None


def _fetch_json(url: str, report: Report) -> Any | None:
    """Fetch and parse JSON, recording a skip rather than raising.

    Args:
        url: The source to read.
        report: The report that records unreachable sources.

    Returns:
        The parsed document, or ``None`` when the source could not be read.
    """
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=_FETCH_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
        report.skip(url, str(error))
        return None


def _requirements() -> dict[str, str]:
    """Return ``flint.toml``'s ``[requirements]`` table.

    Returns:
        The declared floors and targets.
    """
    with _FLINT_TOML.open("rb") as handle:
        return {key: str(value) for key, value in tomllib.load(handle)["requirements"].items()}


def _major(version: str) -> int:
    """Return the leading integer of a version or range string.

    Args:
        version: A value such as ``">=22.22.0"``, ``"24"`` or ``"v22.23.2"``.

    Returns:
        The major component.

    Raises:
        ValueError: When no leading integer can be found.
    """
    match = re.search(r"(\d+)", version)
    if match is None:
        raise ValueError(f"no version number in {version!r}")
    return int(match.group(1))


def _version_tuple(version: str) -> tuple[int, ...]:
    """Return a comparable tuple for a dotted version.

    Args:
        version: A dotted version, optionally ``v``-prefixed.

    Returns:
        The numeric components.
    """
    return tuple(int(part) for part in re.findall(r"\d+", version.lstrip("v")))


def _parse_schedule_date(value: str | None) -> dt.date | None:
    """Parse a Node schedule date, tolerating the ``YYYY-MM`` form.

    Args:
        value: The raw date field, if present.

    Returns:
        The date, or ``None`` when absent or unparseable.
    """
    if not value:
        return None
    for pattern in ("%Y-%m-%d", "%Y-%m"):
        try:
            return dt.datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    return None


def _band_message(subject: str, line: object, allowed: list[str]) -> str:
    """Render the standard out-of-band explanation.

    Args:
        subject: What is out of band.
        line: The release line the subject sits on.
        allowed: The lines inside the N-1 band, newest first.

    Returns:
        The message text.
    """
    rendered = ", ".join(allowed)
    return (
        f"{subject} sits on line {line}, which is further back than N-1. "
        f"Supported lines today are {rendered}. Move the target/pin forward, or widen the band deliberately."
    )


def _check_node(report: Report, requirements: dict[str, str], pinned_node: str | None) -> None:
    """Check the Node floor, target and bootstrap pin against upstream release data.

    Args:
        report: The report to record findings on.
        requirements: ``flint.toml``'s ``[requirements]`` table.
        pinned_node: The bootstrap ``tool-manifest.json`` Node version, if readable.
    """
    schedule = _fetch_json(_NODE_SCHEDULE_URL, report)
    releases = _fetch_json(_NODE_DIST_URL, report)
    if not isinstance(schedule, dict):
        return

    today = dt.date.today()
    lifecycles: dict[int, dict[str, dt.date | None]] = {}
    for raw_line, entry in schedule.items():
        if not isinstance(entry, dict):
            continue
        try:
            major = _major(raw_line)
        except ValueError:
            continue
        lifecycles[major] = {
            "lts": _parse_schedule_date(entry.get("lts")),
            "maintenance": _parse_schedule_date(entry.get("maintenance")),
            "end": _parse_schedule_date(entry.get("end")),
        }

    # A "supported LTS line" is one that has actually entered LTS and has not
    # reached end of life. Node's current line (v26 today) is deliberately not
    # counted: it has an `lts` date in the future, so it is not LTS yet.
    lts_lines = sorted(
        major
        for major, dates in lifecycles.items()
        if dates["lts"] is not None
        and dates["lts"] <= today
        and (dates["end"] is None or dates["end"] > today)
    )
    band = lts_lines[-(_LINES_BACK_ALLOWED + 1) :] if lts_lines else []

    def end_of_life(major: int) -> dt.date | None:
        return lifecycles.get(major, {}).get("end")

    def report_eol(subject: str, major: int) -> bool:
        end = end_of_life(major)
        if end is not None and end <= today:
            report.add("fail", subject, f"Node {major} reached end of life on {end:%Y-%m-%d}.")
            return True
        if major not in lifecycles:
            report.add("warn", subject, f"Node {major} is not in the upstream release schedule.")
            return True
        return False

    floor_major = _major(requirements["node_requires"])
    if not report_eol("node_requires (flint.toml)", floor_major):
        dates = lifecycles[floor_major]
        maintenance = dates["maintenance"]
        end = dates["end"]
        phase = "maintenance" if maintenance is not None and maintenance <= today else "active"
        report.add(
            "note",
            "node_requires (flint.toml)",
            f"Node {floor_major} floor is in {phase} support"
            + (f" until {end:%Y-%m-%d}" if end is not None else "")
            + ". A floor is judged on end of life only - it tracks what the dependency tree needs.",
        )

    target_major = _major(requirements["node_target"])
    if not report_eol("node_target (flint.toml)", target_major) and band and target_major not in band:
        report.add(
            "fail",
            "node_target (flint.toml)",
            _band_message(f"Node target {target_major}", target_major, [str(item) for item in band[::-1]]),
        )

    if pinned_node is None:
        return

    pinned_major = _major(pinned_node)
    subject = "node (bootstrap tool-manifest.json)"
    if report_eol(subject, pinned_major):
        return
    if band and pinned_major not in band:
        report.add(
            "fail",
            subject,
            _band_message(f"The pinned Node {pinned_node}", pinned_major, [str(item) for item in band[::-1]]),
        )
        return
    if not isinstance(releases, list):
        return
    line_releases = [
        entry["version"]
        for entry in releases
        if isinstance(entry, dict) and isinstance(entry.get("version"), str) and _major(entry["version"]) == pinned_major
    ]
    if not line_releases:
        return
    newest = max(line_releases, key=_version_tuple)
    if _version_tuple(newest) > _version_tuple(pinned_node):
        report.add(
            "warn",
            subject,
            f"The bootstrap pins Node {pinned_node} but {newest.lstrip('v')} is the newest {pinned_major}.x release. "
            "Regenerate the manifest (the mirrored signing key travels with the version, so this is never a "
            "hand edit).",
        )


def _check_pnpm(report: Report, pinned_pnpm: str | None, package_manager: str | None) -> None:
    """Check the pnpm pin against the registry's release tags.

    Args:
        report: The report to record findings on.
        pinned_pnpm: The bootstrap ``tool-manifest.json`` pnpm version, if readable.
        package_manager: The root ``packageManager`` field, if readable.
    """
    if pinned_pnpm is None:
        return
    if package_manager is not None and not package_manager.startswith(f"pnpm@{pinned_pnpm}+"):
        report.add(
            "fail",
            "pnpm (bootstrap pin vs packageManager)",
            f"packageManager is {package_manager!r} but the bootstrap manifest pins pnpm {pinned_pnpm}. "
            "The desktop bootstrap enables the same pnpm the repo does, so the two must agree.",
        )

    subject = "pnpm (release line)"
    tags = _fetch_json(_PNPM_DIST_TAGS_URL, report)
    if not isinstance(tags, dict):
        return
    latest = tags.get("latest")
    if not isinstance(latest, str):
        return
    latest_major = _major(latest)
    pinned_major = _major(pinned_pnpm)
    band = list(range(latest_major - _LINES_BACK_ALLOWED, latest_major + 1))
    if pinned_major not in band:
        report.add(
            "fail",
            subject,
            _band_message(f"pnpm {pinned_pnpm}", pinned_major, [str(item) for item in band[::-1]]),
        )
        return
    newest_in_line = tags.get(f"latest-{pinned_major}")
    if isinstance(newest_in_line, str) and _version_tuple(newest_in_line) > _version_tuple(pinned_pnpm):
        report.add(
            "warn",
            subject,
            f"pnpm {pinned_pnpm} is pinned but {newest_in_line} is the newest {pinned_major}.x release.",
        )


def _check_uv(report: Report, pinned_uv: str | None) -> None:
    """Check the uv pin against the newest published release.

    Args:
        report: The report to record findings on.
        pinned_uv: The bootstrap ``tool-manifest.json`` uv version, if readable.
    """
    if pinned_uv is None:
        return
    subject = "uv (bootstrap tool-manifest.json)"
    release = _fetch_json(_UV_LATEST_RELEASE_URL, report)
    if not isinstance(release, dict):
        return
    tag = release.get("tag_name")
    if not isinstance(tag, str):
        return
    latest = _version_tuple(tag)
    pinned = _version_tuple(pinned_uv)
    if not latest or not pinned:
        return
    # uv is pre-1.0, so its release *line* is the minor, not the major.
    line_index = 1 if latest[0] == 0 else 0
    if pinned[:line_index] != latest[:line_index]:
        report.add("fail", subject, _band_message(f"uv {pinned_uv}", pinned_uv, [tag.lstrip("v")]))
        return
    lines_back = latest[line_index] - pinned[line_index]
    if lines_back > _LINES_BACK_ALLOWED:
        report.add("fail", subject, _band_message(f"uv {pinned_uv}", pinned_uv, [tag.lstrip("v")]))
        return
    if pinned < latest:
        report.add("warn", subject, f"uv {pinned_uv} is pinned but {tag.lstrip('v')} is the newest release.")


def _check_python(report: Report, requirements: dict[str, str]) -> None:
    """Check the Python floor and target against the CPython EOL calendar.

    Args:
        report: The report to record findings on.
        requirements: ``flint.toml``'s ``[requirements]`` table.
    """
    cycles = _fetch_json(_PYTHON_CYCLES_URL, report)
    if not isinstance(cycles, list):
        return
    lifecycles: dict[tuple[int, ...], dt.date | None] = {}
    for entry in cycles:
        if not isinstance(entry, dict) or not isinstance(entry.get("cycle"), str):
            continue
        lifecycles[_version_tuple(entry["cycle"])] = _parse_schedule_date(
            entry["eol"] if isinstance(entry.get("eol"), str) else None
        )
    if not lifecycles:
        return

    today = dt.date.today()
    live = sorted(cycle for cycle, eol in lifecycles.items() if eol is None or eol > today)
    band = live[-(_LINES_BACK_ALLOWED + 1) :]

    def report_eol(subject: str, cycle: tuple[int, ...]) -> bool:
        eol = lifecycles.get(cycle)
        if eol is not None and eol <= today:
            rendered = ".".join(str(part) for part in cycle)
            report.add("fail", subject, f"Python {rendered} reached end of life on {eol:%Y-%m-%d}.")
            return True
        return False

    floor = _version_tuple(requirements["python_requires"])[:2]
    if not report_eol("python_requires (flint.toml)", floor) and floor in lifecycles:
        eol = lifecycles[floor]
        report.add(
            "note",
            "python_requires (flint.toml)",
            f"Python {'.'.join(str(part) for part in floor)} floor is supported"
            + (f" until {eol:%Y-%m-%d}" if eol is not None else "")
            + ". A floor is judged on end of life only.",
        )

    target = _version_tuple(requirements["python_target"])[:2]
    if not report_eol("python_target (flint.toml)", target) and band and target not in band:
        rendered = [".".join(str(part) for part in cycle) for cycle in band[::-1]]
        report.add(
            "fail",
            "python_target (flint.toml)",
            _band_message(f"Python target {'.'.join(str(part) for part in target)}", target, rendered),
        )


def _local_pins(report: Report) -> tuple[str | None, str | None, str | None, str | None]:
    """Read the pins this repo controls.

    Args:
        report: The report to record parse failures on.

    Returns:
        The bootstrap Node, pnpm and uv versions plus the root ``packageManager``.
    """
    node = pnpm = uv = package_manager = None
    try:
        manifest = json.loads(_TOOL_MANIFEST.read_text(encoding="utf-8"))
        node = str(manifest["node"]["version"])
        pnpm = str(manifest["pnpm"]["version"])
        uv = str(manifest["uv"]["version"])
    except (OSError, KeyError, ValueError) as error:
        report.add("fail", "bootstrap tool-manifest.json", f"could not read the pinned versions: {error}")
    try:
        package_manager = str(json.loads(_ROOT_PACKAGE_JSON.read_text(encoding="utf-8"))["packageManager"])
    except (OSError, KeyError, ValueError) as error:
        report.add("fail", "package.json", f"could not read packageManager: {error}")
    return node, pnpm, uv, package_manager


def _render(report: Report, pins: dict[str, str | None]) -> None:
    """Print the human-readable report.

    Args:
        report: The findings to print.
        pins: The local pins, for the header.
    """
    print("Declared and pinned toolchain")
    for label, value in pins.items():
        print(f"  {label:<28} {value or '(unreadable)'}")
    print()

    order = {"fail": 0, "warn": 1, "note": 2}
    icons = {"fail": "FAIL", "warn": "WARN", "note": "note"}
    for finding in sorted(report.findings, key=lambda item: order[item.level]):
        print(f"{icons[finding.level]}: {finding.subject}: {finding.message}")

    if report.skipped:
        print()
        print("Sources not reached (checked skipped, not failed):")
        for source in report.skipped:
            print(f"  - {source}")

    print()
    if report.failed:
        print("RESULT: fail - a declared or pinned toolchain version is EOL or out of band.")
    else:
        print("RESULT: ok - every reachable check passed.")


def main() -> int:
    """Run the freshness checks.

    Returns:
        ``1`` when any finding is fatal, otherwise ``0``.
    """
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="Parse the local pins and fetch nothing.")
    parser.add_argument("--json", action="store_true", help="Emit findings as JSON instead of text.")
    parser.add_argument(
        "--report",
        type=pathlib.Path,
        help="Also write the JSON findings here, so one run can produce both the log and the artefact.",
    )
    args = parser.parse_args()

    report = Report()
    node, pnpm, uv, package_manager = _local_pins(report)
    requirements = _requirements()
    pins = {
        "python_requires (floor)": requirements.get("python_requires"),
        "python_target": requirements.get("python_target"),
        "node_requires (floor)": requirements.get("node_requires"),
        "node_target": requirements.get("node_target"),
        "node (bootstrap pin)": node,
        "pnpm (bootstrap pin)": pnpm,
        "uv (bootstrap pin)": uv,
        "packageManager": package_manager,
    }

    if args.offline:
        report.add(
            "note",
            "network",
            "--offline: the local pins parsed, but no upstream release data was consulted.",
        )
    else:
        _check_node(report, requirements, node)
        _check_pnpm(report, pnpm, package_manager)
        _check_uv(report, uv)
        _check_python(report, requirements)

    document = json.dumps(
        {
            "generated": dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds"),
            "pins": pins,
            "findings": [dataclasses.asdict(finding) for finding in report.findings],
            "skipped": report.skipped,
            "failed": report.failed,
        },
        indent=2,
    )
    if args.report is not None:
        args.report.write_text(document + "\n", encoding="utf-8")
    if args.json:
        print(document)
    else:
        _render(report, pins)

    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
