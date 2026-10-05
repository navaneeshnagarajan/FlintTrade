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
import json
import pathlib
import re
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
def test_the_ollama_pin_is_read_as_it_is_on_the_checkout(module: ModuleType) -> None:
    """The pin is parsed from ollama_runtime.py, never hard-coded in the gate."""
    report = module.Report()
    pin = module._ollama_pin(report)
    assert not report.failed, [finding.message for finding in report.findings]
    assert pin is not None
    assert re.fullmatch(r"v\d+\.\d+\.\d+", pin)
    assert f'_OLLAMA_VERSION = "{pin}"' in module._OLLAMA_RUNTIME.read_text(encoding="utf-8")


@pytest.mark.unit
def test_an_unreadable_ollama_pin_fails_loudly(module: ModuleType, tmp_path: pathlib.Path) -> None:
    """A refactor that hides the constant must not silently blind the gate and Renovate."""
    runtime = tmp_path / "ollama_runtime.py"
    runtime.write_text("_OLLAMA_VERSION = compute_version()\n", encoding="utf-8")
    module._OLLAMA_RUNTIME = runtime
    report = module.Report()
    assert module._ollama_pin(report) is None
    assert report.failed


@pytest.mark.unit
@pytest.mark.parametrize(
    ("pinned", "latest", "warns"),
    [
        ("v0.35.0", "v0.35.0", False),
        ("v0.33.0", "v0.35.1", False),  # exactly two minor versions back is still fine
        ("v0.32.0", "v0.35.0", True),
        ("v0.32.0", "v0.40.2", True),
        ("v0.35.0", "v0.32.0", False),  # a pin ahead of "latest" is not stale
        ("v0.32.0", "v1.0.0", True),  # a major move is always out of range
    ],
)
def test_an_ollama_pin_warns_only_beyond_two_minor_versions(
    module: ModuleType, pinned: str, latest: str, warns: bool
) -> None:
    """The managed Ollama pin is advisory: it warns when stale and never fails."""
    _stub_fetch(module, {module._OLLAMA_LATEST_RELEASE_URL: {"tag_name": latest, "prerelease": False}})
    report = module.Report()
    module._check_ollama(report, pinned)
    assert not report.failed
    assert [f.level for f in report.findings] == (["warn"] if warns else [])
    if warns:
        assert pinned in report.findings[0].message
        assert latest in report.findings[0].message


@pytest.mark.unit
def test_an_ollama_prerelease_is_never_the_comparison_target(module: ModuleType) -> None:
    """Only a stable release can make the pin look stale."""
    _stub_fetch(module, {module._OLLAMA_LATEST_RELEASE_URL: {"tag_name": "v0.40.0-rc1", "prerelease": True}})
    report = module.Report()
    module._check_ollama(report, "v0.32.0")
    assert not report.findings


@pytest.mark.unit
def test_renovate_tracks_the_ollama_pin_for_hand_regeneration() -> None:
    """Renovate must see the real constant, only on stable releases, and never automerge it."""
    config = json.loads((_REPO / "renovate.json").read_text(encoding="utf-8"))
    managers = [m for m in config["customManagers"] if m.get("depNameTemplate") == "ollama/ollama"]
    assert len(managers) == 1
    manager = managers[0]
    assert manager["datasourceTemplate"] == "github-releases"
    assert manager["versioningTemplate"] == "semver"

    target = _REPO / "packages/core/core/src/flinttrade_core/ollama_runtime.py"
    patterns = [re.compile(p.strip("/")) for p in manager["managerFilePatterns"]]
    assert any(p.search(target.relative_to(_REPO).as_posix()) for p in patterns)
    (match_string,) = manager["matchStrings"]
    # Renovate spells named groups `(?<name>...)`; Python wants `(?P<name>...)`.
    match = re.search(match_string.replace("(?<", "(?P<"), target.read_text(encoding="utf-8"))
    assert match is not None
    assert re.fullmatch(r"v\d+\.\d+\.\d+", match.group("currentValue"))

    rules = [r for r in config["packageRules"] if "ollama/ollama" in r.get("matchDepNames", [])]
    assert len(rules) == 1
    assert rules[0]["automerge"] is False
    assert rules[0]["ignoreUnstable"] is True
    assert "needs-hash-regeneration" in rules[0]["labels"]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("assignment", "expected_pin"),
    [
        ('_OLLAMA_VERSION = "v0.35.0"', "v0.35.0"),
        ('_OLLAMA_VERSION: str = "v0.35.0"', "v0.35.0"),
        ('_OLLAMA_VERSION: Final[str] = "v0.35.0"', "v0.35.0"),
        ("_OLLAMA_VERSION = compute_version()", None),
        ("_OLLAMA_VERSION: str = compute_version()", None),
        ('_OLLAMA_VERSION = "v0.35.0" + suffix', None),
    ],
    ids=["plain", "typed", "typed-final", "computed", "typed-computed", "concatenated"],
)
def test_ollama_freshness_and_renovate_accept_the_same_pin_syntax(
    module: ModuleType, tmp_path: pathlib.Path, assignment: str, expected_pin: str | None
) -> None:
    """A supported literal must remain discoverable; computed values must fail loudly."""
    runtime = tmp_path / "ollama_runtime.py"
    text = f"# Managed runtime version\n{assignment}\n"
    runtime.write_text(text, encoding="utf-8")
    module._OLLAMA_RUNTIME = runtime
    report = module.Report()
    assert module._ollama_pin(report) == expected_pin
    assert report.failed is (expected_pin is None)

    config = json.loads((_REPO / "renovate.json").read_text(encoding="utf-8"))
    manager = next(m for m in config["customManagers"] if m.get("depNameTemplate") == "ollama/ollama")
    (match_string,) = manager["matchStrings"]
    match = re.search(match_string.replace("(?<", "(?P<"), text)
    assert (match.group("currentValue") if match else None) == expected_pin


@pytest.mark.unit
def test_an_unreachable_source_is_skipped_not_failed(module: ModuleType) -> None:
    """A network blip must never redden an unrelated pull request."""
    _stub_fetch(module, {})
    report = module.Report()
    module._check_node(report, {"node_requires": ">=22.22.0", "node_target": "24"}, "22.23.2")
    module._check_pnpm(report, "9.15.0", "pnpm@9.15.0+sha512.x")
    module._check_uv(report, "0.11.16")
    module._check_ollama(report, "v0.32.0")
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
