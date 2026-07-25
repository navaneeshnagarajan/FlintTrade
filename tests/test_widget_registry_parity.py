"""Guard the backend widget registry against drifting from the terminal's catalogue.

`flinttrade_core.admin_routes._WIDGET_REGISTRY` is a hand-maintained Python
copy of the terminal's `widgetCatalog` (TypeScript). Nothing kept the two in
sync, and by the time this guard was written the Python side was carrying
retired widget ids (`riskpanel`, `gex`, `depth`, `oiprofile`) and pre-merge
names long after those widgets had been merged away — while its docstring
claimed it "mirrors widgetFactory.tsx".

The `/v1/admin/widgets` endpoint it serves has no frontend caller today, so the
drift was invisible. That is exactly the condition under which a list rots.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "packages/apps/terminal/src/layout/widgetFactory.tsx"

sys.path.insert(0, str(ROOT / "packages/core/core/src"))

pytestmark = pytest.mark.unit


def _terminal_catalogue() -> list[dict[str, str]]:
    """Parse the terminal's widgetCatalog entries out of widgetFactory.tsx.

    A regex rather than a TypeScript parse: the catalogue is a flat array of
    single-line object literals with a fixed key order, so this stays simple
    and fails loudly (empty list) if that ever stops being true.
    """
    source = CATALOGUE.read_text(encoding="utf-8")
    start = source.index("export const widgetCatalog")
    end = source.index("// Fallback / Error UI")
    rows = re.findall(
        r'\{ id: "(\w+)", name: "([^"]+)", icon: "[^"]*", category: "(\w+)"',
        source[start:end],
    )
    return [
        {"id": wid, "name": name.replace("\\u0026", "&"), "category": category}
        for wid, name, category in rows
    ]


def test_catalogue_parses() -> None:
    """The regex must actually match — an empty parse would pass every test below."""
    catalogue = _terminal_catalogue()
    assert len(catalogue) > 50, "widgetCatalog parse returned too few rows to be real"


def test_backend_registry_matches_the_terminal_catalogue() -> None:
    """Same widgets, same names, same categories, in the same order."""
    from flinttrade_core.admin_routes import _WIDGET_REGISTRY

    expected = _terminal_catalogue()
    actual = [
        {"id": w["id"], "name": w["name"], "category": w["category"]}
        for w in _WIDGET_REGISTRY
    ]

    expected_ids = [w["id"] for w in expected]
    actual_ids = [w["id"] for w in actual]

    missing = [wid for wid in expected_ids if wid not in actual_ids]
    stale = [wid for wid in actual_ids if wid not in expected_ids]
    assert not missing, f"backend registry is missing catalogue widgets: {missing}"
    assert not stale, (
        f"backend registry still lists widgets the terminal has retired: {stale}"
    )

    # Names and categories, not just membership — a merged widget keeps its id
    # but changes its name, and that is precisely the drift that went unnoticed.
    by_id = {w["id"]: w for w in actual}
    for widget in expected:
        got = by_id[widget["id"]]
        assert got["name"] == widget["name"], (
            f"{widget['id']}: backend name {got['name']!r} != catalogue {widget['name']!r}"
        )
        assert got["category"] == widget["category"], (
            f"{widget['id']}: backend category {got['category']!r} != "
            f"catalogue {widget['category']!r}"
        )


def test_backend_registry_has_no_duplicate_ids() -> None:
    from flinttrade_core.admin_routes import _WIDGET_REGISTRY

    ids = [w["id"] for w in _WIDGET_REGISTRY]
    duplicates = {wid for wid in ids if ids.count(wid) > 1}
    assert not duplicates, f"duplicate ids in the backend registry: {duplicates}"
