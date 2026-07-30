"""Tests for the toolchain EOL / N-1 freshness gate.

``scripts/check-toolchain-freshness.py`` is the only thing in CI that notices a
pinned runtime line reaching end of life, so its two load-bearing behaviours are
pinned here: an EOL or out-of-band version must fail, and an unreachable upstream
source must be reported as skipped rather than turned into a red pull request.

Every test drives the module with synthetic release data - no network.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib
import sys
from types import ModuleType
from typing import Any

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "check-toolchain-freshness.py"


def _load() -> ModuleType:
    """Import the check script as a module.

    Returns:
        The freshly imported module.
    """
    spec = importlib.util.spec_from_file_location("check_toolchain_freshness", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def module() -> ModuleType:
    return _load()


def _schedule(end: str) -> dict[str, dict[str, str]]:
    """Return a two-line Node schedule where line 22 ends on *end*.

    Args:
        end: The ISO end-of-life date for Node 22.

    Returns:
        A schedule document shaped like the upstream one.
    """
    return {
        "v22": {"lts": "2024-10-29", "maintenance": "2025-10-21", "end": end},
        "v24": {"lts": "2025-10-28", "maintenance": "2026-10-20", "end": "2028-04-30"},
        "v26": {"lts": "2026-10-28", "maintenance": "2027-10-20", "end": "2029-04-30"},
    }


def _stub_fetch(module: ModuleType, responses: dict[str, Any]) -> None:
    """Replace the module's fetcher with a table lookup.

    Args:
        module: The imported check module.
        responses: URL to document; a missing URL is treated as unreachable.
    """

    def fetch(url: str, report: Any) -> Any:
        if url not in responses:
            report.skip(url, "stubbed as unreachable")
            return None
        return responses[url]

    module._fetch_json = fetch  # type: ignore[attr-defined]


@pytest.mark.unit
def test_the_repo_pins_parse(module: ModuleType) -> None:
    """The real flint.toml and tool-manifest must be readable, or the gate is blind."""
    report = module.Report()
    node, pnpm, uv, package_manager = module._local_pins(report)
    assert not report.failed, [finding.message for finding in report.findings]
    assert node and pnpm and uv and package_manager
    requirements = module._requirements()
    assert requirements["node_requires"].startswith(">=")
    assert requirements["python_requires"].startswith(">=")


@pytest.mark.unit
def test_an_eol_node_line_fails(module: ModuleType) -> None:
    """A pinned Node line past its end-of-life date is fatal."""
    _stub_fetch(module, {module._NODE_SCHEDULE_URL: _schedule("2020-04-30")})
    report = module.Report()
    module._check_node(report, {"node_requires": ">=22.22.0", "node_target": "24"}, "22.23.2")
    messages = [f.message for f in report.findings if f.level == "fail"]
    assert report.failed
    assert any("end of life" in message for message in messages), messages


@pytest.mark.unit
def test_a_node_pin_two_lines_back_fails(module: ModuleType) -> None:
    """A live but N-2 Node line is out of band and fatal."""
    schedule = _schedule("2027-04-30")
    schedule["v20"] = {"lts": "2023-10-24", "maintenance": "2024-10-22", "end": "2030-04-30"}
    _stub_fetch(module, {module._NODE_SCHEDULE_URL: schedule})
    report = module.Report()
    module._check_node(report, {"node_requires": ">=20.0.0", "node_target": "20"}, "20.20.2")
    fails = [f for f in report.findings if f.level == "fail"]
    # The floor is judged on end of life only, so it is not fatal; the target and
    # the bootstrap pin both are.
    assert sorted(f.subject for f in fails) == [
        "node (bootstrap tool-manifest.json)",
        "node_target (flint.toml)",
    ]
    assert all("further back than N-1" in f.message for f in fails)


@pytest.mark.unit
def test_a_stale_patch_inside_the_band_only_warns(module: ModuleType) -> None:
    """Being behind on the patch is a warning: the Node pin travels with a signing key."""
    _stub_fetch(
        module,
        {
            module._NODE_SCHEDULE_URL: _schedule("2027-04-30"),
            module._NODE_DIST_URL: [{"version": "v22.99.0"}, {"version": "v22.23.2"}],
        },
    )
    report = module.Report()
    module._check_node(report, {"node_requires": ">=22.22.0", "node_target": "24"}, "22.23.2")
    assert not report.failed
    warnings = [f.message for f in report.findings if f.level == "warn"]
    assert any("22.99.0" in message for message in warnings), warnings


@pytest.mark.unit
def test_a_packagemanager_mismatch_fails(module: ModuleType) -> None:
    """The bootstrap pnpm pin and the repo's packageManager must be the same release."""
    _stub_fetch(module, {})
    report = module.Report()
    module._check_pnpm(report, "9.15.0", "pnpm@9.14.0+sha512.deadbeef")
    fails = [f.message for f in report.findings if f.level == "fail"]
    assert any("must agree" in message for message in fails), fails


@pytest.mark.unit
def test_an_unreachable_source_is_skipped_not_failed(module: ModuleType) -> None:
    """A network blip must never redden an unrelated pull request."""
    _stub_fetch(module, {})
    report = module.Report()
    module._check_node(report, {"node_requires": ">=22.22.0", "node_target": "24"}, "22.23.2")
    module._check_pnpm(report, "9.15.0", "pnpm@9.15.0+sha512.x")
    module._check_uv(report, "0.11.16")
    module._check_python(report, {"python_requires": ">=3.12", "python_target": "3.14"})
    assert not report.failed
    assert report.skipped


@pytest.mark.unit
def test_an_expired_waiver_stops_suppressing(module: ModuleType) -> None:
    """A waiver past its review date must let the finding turn fatal again."""
    subject = "test subject"
    module._WAIVERS = (module.Waiver(subject=subject, reason="reason", review_by="2000-01-01"),)
    report = module.Report()
    report.add("fail", subject, "boom")
    assert report.failed


@pytest.mark.unit
def test_every_waiver_carries_a_future_review_date(module: ModuleType) -> None:
    """A waiver that has silently expired is a red gate waiting to happen at head."""
    for waiver in module._WAIVERS:
        review_by = dt.date.fromisoformat(waiver.review_by)
        assert review_by >= dt.date.today(), (
            f"the waiver for {waiver.subject!r} expired on {waiver.review_by}. "
            "Either move the pin or re-date the waiver with a fresh justification."
        )
        assert waiver.reason.strip(), f"the waiver for {waiver.subject!r} has no reason"
