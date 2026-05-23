"""Tests for ChartPreferences.

Run with:
    python -m pytest packages/core/core/tests/test_chart_prefs.py -v --import-mode=importlib
"""
from __future__ import annotations

import pytest


@pytest.fixture()
def prefs(tmp_path):
    """ChartPreferences backed by a temporary DuckDB file.

    Imports directly from the module file to avoid triggering
    flinttrade_core.__init__ which runs create_flask_app() at import time
    and may conflict with a live security.db on this machine.
    """
    import importlib.util
    import pathlib

    spec = importlib.util.spec_from_file_location(
        "chart_prefs",
        pathlib.Path(__file__).parent.parent / "src" / "chart_prefs.py",
    )
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    db_path = str(tmp_path / "chart_prefs_test.duckdb")
    p = module.ChartPreferences(db_path=db_path)
    yield p
    p.close()


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------


class TestTheme:
    """Tests for set_theme / get_theme."""

    def test_get_theme_returns_none_when_not_set(self, prefs):
        assert prefs.get_theme("u1") is None

    def test_set_and_get_theme_roundtrip(self, prefs):
        theme = {"background": "#0a0a0f", "upColor": "#22c55e"}
        prefs.set_theme("u1", theme)
        assert prefs.get_theme("u1") == theme

    def test_set_theme_overwrites_existing(self, prefs):
        prefs.set_theme("u1", {"background": "#000"})
        prefs.set_theme("u1", {"background": "#fff"})
        assert prefs.get_theme("u1") == {"background": "#fff"}

    def test_themes_are_user_isolated(self, prefs):
        prefs.set_theme("u1", {"color": "red"})
        prefs.set_theme("u2", {"color": "blue"})
        assert prefs.get_theme("u1")["color"] == "red"
        assert prefs.get_theme("u2")["color"] == "blue"

    def test_empty_theme_dict_accepted(self, prefs):
        prefs.set_theme("u1", {})
        assert prefs.get_theme("u1") == {}

    def test_complex_nested_theme_preserved(self, prefs):
        theme = {
            "grid": {"visible": True, "color": "rgba(255,255,255,0.1)"},
            "candles": {"up": "#22c55e", "down": "#ef4444"},
        }
        prefs.set_theme("u1", theme)
        assert prefs.get_theme("u1") == theme


# ---------------------------------------------------------------------------
# Indicator sets
# ---------------------------------------------------------------------------


class TestIndicatorSets:
    """Tests for save / load / list / delete indicator sets."""

    def test_load_nonexistent_returns_none(self, prefs):
        assert prefs.load_indicator_set("u1", "missing") is None

    def test_save_and_load_roundtrip(self, prefs):
        indicators = [{"name": "EMA", "params": {"period": 9}}]
        prefs.save_indicator_set("u1", "scalping", indicators)
        assert prefs.load_indicator_set("u1", "scalping") == indicators

    def test_list_empty_when_none_saved(self, prefs):
        assert prefs.list_indicator_sets("u1") == []

    def test_list_returns_all_names(self, prefs):
        prefs.save_indicator_set("u1", "scalping", [])
        prefs.save_indicator_set("u1", "swing", [])
        names = prefs.list_indicator_sets("u1")
        assert sorted(names) == ["scalping", "swing"]

    def test_save_overwrites_existing(self, prefs):
        prefs.save_indicator_set("u1", "set1", [{"name": "SMA"}])
        prefs.save_indicator_set("u1", "set1", [{"name": "EMA"}])
        loaded = prefs.load_indicator_set("u1", "set1")
        assert loaded == [{"name": "EMA"}]

    def test_sets_are_user_isolated(self, prefs):
        prefs.save_indicator_set("u1", "mySet", [{"a": 1}])
        assert prefs.load_indicator_set("u2", "mySet") is None

    def test_delete_existing_set(self, prefs):
        prefs.save_indicator_set("u1", "tmp", [])
        assert prefs.delete_indicator_set("u1", "tmp") is True
        assert prefs.load_indicator_set("u1", "tmp") is None

    def test_delete_nonexistent_returns_false(self, prefs):
        assert prefs.delete_indicator_set("u1", "ghost") is False

    def test_complex_indicator_config_preserved(self, prefs):
        indicators = [
            {"name": "Bollinger Bands", "params": {"period": 20, "stddev": 2.0}, "visible": True},
            {"name": "RSI", "params": {"period": 14}, "panel": "below"},
        ]
        prefs.save_indicator_set("u1", "complex", indicators)
        assert prefs.load_indicator_set("u1", "complex") == indicators


# ---------------------------------------------------------------------------
# Layouts
# ---------------------------------------------------------------------------


class TestLayouts:
    """Tests for save / load / list / delete layouts."""

    def test_load_nonexistent_returns_none(self, prefs):
        assert prefs.load_layout("u1", "missing") is None

    def test_save_and_load_roundtrip(self, prefs):
        layout = {"panels": [{"id": "chart1", "type": "chart"}]}
        prefs.save_layout("u1", "intraday", layout)
        assert prefs.load_layout("u1", "intraday") == layout

    def test_list_empty_when_none_saved(self, prefs):
        assert prefs.list_layouts("u1") == []

    def test_list_returns_all_names(self, prefs):
        prefs.save_layout("u1", "intraday", {})
        prefs.save_layout("u1", "swing", {})
        names = prefs.list_layouts("u1")
        assert sorted(names) == ["intraday", "swing"]

    def test_save_overwrites_existing(self, prefs):
        prefs.save_layout("u1", "l1", {"v": 1})
        prefs.save_layout("u1", "l1", {"v": 2})
        assert prefs.load_layout("u1", "l1") == {"v": 2}

    def test_layouts_are_user_isolated(self, prefs):
        prefs.save_layout("u1", "myLayout", {"x": 1})
        assert prefs.load_layout("u2", "myLayout") is None

    def test_delete_existing_layout(self, prefs):
        prefs.save_layout("u1", "tmp", {})
        assert prefs.delete_layout("u1", "tmp") is True
        assert prefs.load_layout("u1", "tmp") is None

    def test_delete_nonexistent_returns_false(self, prefs):
        assert prefs.delete_layout("u1", "ghost") is False

    def test_complex_layout_preserved(self, prefs):
        layout = {
            "panels": [
                {"id": "p1", "type": "chart", "symbol": "NIFTY", "interval": "5m"},
                {"id": "p2", "type": "orderpad"},
            ],
            "theme": "graphite",
        }
        prefs.save_layout("u1", "scalper_zone", layout)
        assert prefs.load_layout("u1", "scalper_zone") == layout
