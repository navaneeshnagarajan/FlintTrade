"""Verify every declared version floor agrees with ``flint.toml``.

``flint.toml``'s ``[requirements]`` table is the single source of truth for the
versions FlintTrade supports. Before it existed the repo declared four different
Node floors across four files - ``>=22.22.0``, ``>=22.0.0``,
``^20.19.0 || >=22.12.0`` and ``>=22.12`` - with nothing to notice the drift, so
the value actually in force depended on which file a reader happened to open.

These tests mirror ``tests/test_site_url_single_source.py``: they fail naming the
file and the disagreeing value, so a floor cannot rot silently.
"""

from __future__ import annotations

import json
import pathlib
import tomllib

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_FLINT_TOML = _REPO_ROOT / "flint.toml"


def _requirements() -> dict[str, str]:
    """Return the ``[requirements]`` table from ``flint.toml``.

    Returns:
        The declared floors and targets.
    """
    with _FLINT_TOML.open("rb") as handle:
        return tomllib.load(handle)["requirements"]


def _package_json(relative: str) -> dict[str, object]:
    """Load a tracked ``package.json``.

    Args:
        relative: Repo-relative path to the manifest.

    Returns:
        The parsed manifest.
    """
    return json.loads((_REPO_ROOT / relative).read_text(encoding="utf-8"))


@pytest.mark.unit
def test_requirements_table_is_present_and_complete() -> None:
    declared = _requirements()
    expected = {
        "python_requires",
        "python_target",
        "node_requires",
        "node_target",
        "os_requires",
        "os_target",
    }
    missing = expected - declared.keys()
    assert not missing, f"flint.toml [requirements] is missing: {sorted(missing)}"


@pytest.mark.unit
def test_every_python_package_declares_the_flint_toml_floor() -> None:
    expected = _requirements()["python_requires"]
    disagreeing: list[str] = []
    manifests = sorted(_REPO_ROOT.glob("packages/*/*/pyproject.toml"))
    assert manifests, "no packages/*/*/pyproject.toml found - the glob is wrong"
    for manifest in manifests:
        with manifest.open("rb") as handle:
            data = tomllib.load(handle)
        declared = data.get("project", {}).get("requires-python")
        if declared is None:
            continue
        if declared != expected:
            disagreeing.append(f"{manifest.relative_to(_REPO_ROOT)}: {declared!r} != {expected!r}")
    assert not disagreeing, "requires-python disagrees with flint.toml:\n" + "\n".join(disagreeing)


@pytest.mark.unit
def test_every_node_engines_field_declares_the_flint_toml_floor() -> None:
    expected = _requirements()["node_requires"]
    disagreeing: list[str] = []
    for relative in (
        "package.json",
        "packages/apps/desktop/package.json",
        "packages/apps/terminal/package.json",
        "packages/apps/site/package.json",
        "packages/core/design-system/package.json",
    ):
        manifest = _REPO_ROOT / relative
        if not manifest.exists():
            continue
        engines = _package_json(relative).get("engines")
        if not isinstance(engines, dict) or "node" not in engines:
            continue
        if engines["node"] != expected:
            disagreeing.append(f"{relative}: {engines['node']!r} != {expected!r}")
    assert not disagreeing, "engines.node disagrees with flint.toml:\n" + "\n".join(disagreeing)


@pytest.mark.unit
def test_the_node_target_is_not_below_the_floor() -> None:
    """A target that trails its own floor would be incoherent."""
    declared = _requirements()
    floor_major = int(declared["node_requires"].lstrip(">=^~").split(".")[0])
    target_major = int(str(declared["node_target"]).split(".")[0])
    assert target_major >= floor_major, (
        f"node_target {declared['node_target']} is below node_requires {declared['node_requires']}"
    )


@pytest.mark.unit
def test_the_readme_documents_the_declared_floors() -> None:
    """The floors must be discoverable without reading flint.toml."""
    declared = _requirements()
    readme = (_REPO_ROOT / "readme.md").read_text(encoding="utf-8")
    for value in (declared["python_requires"], declared["node_requires"]):
        assert value in readme, f"readme.md does not document the declared floor {value!r}"


@pytest.mark.unit
def test_the_declared_targets_are_actually_exercised_somewhere() -> None:
    """A target no lane runs is an aspiration dressed up as a guarantee.

    Every per-push lane runs the FLOOR, which is right - that is the version
    users must be able to run. But before this guard existed, ``python_target``
    and ``node_target`` were declared as "what CI builds" while nothing anywhere
    executed either of them.
    """
    declared = _requirements()
    nightly = (_REPO_ROOT / ".github/workflows/nightly-cross-platform.yml").read_text(encoding="utf-8")
    python_target = str(declared["python_target"])
    node_target = str(declared["node_target"])
    assert f"python-version: '{python_target}'" in nightly, (
        f"flint.toml declares python_target {python_target!r}, but no nightly lane installs it. "
        "Either exercise the target or stop declaring it."
    )
    assert f"node-version: '{node_target}'" in nightly, (
        f"flint.toml declares node_target {node_target!r}, but no nightly lane installs it. "
        "Either exercise the target or stop declaring it."
    )
