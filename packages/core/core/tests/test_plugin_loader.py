"""Tests for packages/core/core/src/plugin_loader.py.

Covers: discover, load, activate, deactivate, reload, list_loaded,
        validation errors, missing plugin dir, hot-reload, thread safety.
"""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from flinttrade_core.event_bus import EventBus
from flinttrade_core.plugin_loader import (
    PluginContext,
    PluginError,
    PluginInterface,
    PluginLoader,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def plugin_dir(tmp_path: Path) -> Path:
    """Return a temporary plugin directory."""
    d = tmp_path / "plugins"
    d.mkdir()
    return d


@pytest.fixture
def context() -> PluginContext:
    return PluginContext(event_bus=EventBus(), order_router=MagicMock(), config={})


@pytest.fixture
def loader(plugin_dir: Path, context: PluginContext) -> PluginLoader:
    return PluginLoader(plugin_dir=plugin_dir, context=context)


def _write_plugin(
    plugin_dir: Path,
    filename: str,
    name: str = "test_plugin",
    version: str = "1.0.0",
    description: str = "A test plugin.",
    extra: str = "",
) -> Path:
    """Write a minimal valid plugin file to *plugin_dir*."""
    path = plugin_dir / filename
    path.write_text(
        f"""from flinttrade_core.plugin_loader import PluginInterface, PluginContext

class Plugin(PluginInterface):
    name = "{name}"
    version = "{version}"
    description = "{description}"

    def __init__(self):
        self.activated = False
        self.deactivated = False

    def activate(self, context: PluginContext) -> None:
        self.activated = True

    def deactivate(self) -> None:
        self.deactivated = True

{extra}
""",
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# discover()
# ---------------------------------------------------------------------------


def test_discover_empty_dir(loader: PluginLoader) -> None:
    """discover() on an empty dir returns an empty list."""
    assert loader.discover() == []


def test_discover_finds_valid_plugin(loader: PluginLoader, plugin_dir: Path) -> None:
    """discover() returns the plugin name declared in Plugin.name."""
    _write_plugin(plugin_dir, "alpha.py", name="alpha")
    names = loader.discover()
    assert "alpha" in names


def test_discover_skips_dunder_files(loader: PluginLoader, plugin_dir: Path) -> None:
    """discover() ignores __init__.py and other dunder files."""
    (plugin_dir / "__init__.py").write_text("", encoding="utf-8")
    assert loader.discover() == []


def test_discover_skips_no_plugin_class(loader: PluginLoader, plugin_dir: Path) -> None:
    """discover() skips .py files with no Plugin class."""
    (plugin_dir / "broken.py").write_text("x = 1", encoding="utf-8")
    assert loader.discover() == []


def test_discover_skips_invalid_base(loader: PluginLoader, plugin_dir: Path) -> None:
    """discover() skips plugins that do not inherit PluginInterface."""
    (plugin_dir / "bad_base.py").write_text(
        "class Plugin:\n    name='x'\n    version='1'\n    description='y'\n    def activate(self, c): pass\n    def deactivate(self): pass\n",
        encoding="utf-8",
    )
    assert loader.discover() == []


def test_discover_missing_dir(tmp_path: Path, context: PluginContext) -> None:
    """discover() on a non-existent directory returns empty list."""
    loader = PluginLoader(plugin_dir=tmp_path / "nonexistent", context=context)
    assert loader.discover() == []


def test_discover_multiple_plugins(loader: PluginLoader, plugin_dir: Path) -> None:
    """discover() returns names from all valid plugin files."""
    _write_plugin(plugin_dir, "p1.py", name="plugin_one")
    _write_plugin(plugin_dir, "p2.py", name="plugin_two")
    names = loader.discover()
    assert "plugin_one" in names
    assert "plugin_two" in names


# ---------------------------------------------------------------------------
# load()
# ---------------------------------------------------------------------------


def test_load_returns_plugin_interface(loader: PluginLoader, plugin_dir: Path) -> None:
    """load() returns an instance of PluginInterface."""
    _write_plugin(plugin_dir, "my_plugin.py", name="my_plugin")
    instance = loader.load("my_plugin")
    assert isinstance(instance, PluginInterface)


def test_load_unknown_name_raises(loader: PluginLoader) -> None:
    """load() raises PluginError when the name does not exist."""
    with pytest.raises(PluginError, match="nonexistent"):
        loader.load("nonexistent")


def test_load_syntax_error_raises(loader: PluginLoader, plugin_dir: Path) -> None:
    """load() raises PluginError when the plugin file has a syntax error."""
    (plugin_dir / "syntax_err.py").write_text(
        "class Plugin:\n    name = 'syntax_err'\n    this is invalid python !!!\n",
        encoding="utf-8",
    )
    with pytest.raises(PluginError):
        loader.load("syntax_err")


# ---------------------------------------------------------------------------
# activate() / deactivate()
# ---------------------------------------------------------------------------


def test_activate_calls_plugin(loader: PluginLoader, plugin_dir: Path) -> None:
    """activate() calls plugin.activate(context)."""
    _write_plugin(plugin_dir, "activatable.py", name="activatable")
    loader.load("activatable")
    loader.activate("activatable")
    instance = loader._records["activatable"].instance  # noqa: SLF001
    assert instance.activated is True


def test_deactivate_calls_plugin(loader: PluginLoader, plugin_dir: Path) -> None:
    """deactivate() calls plugin.deactivate()."""
    _write_plugin(plugin_dir, "deact.py", name="deact")
    loader.load("deact")
    loader.activate("deact")
    loader.deactivate("deact")
    instance = loader._records["deact"].instance  # noqa: SLF001
    assert instance.deactivated is True


def test_activate_not_loaded_raises(loader: PluginLoader) -> None:
    """activate() on an unloaded plugin raises PluginError."""
    with pytest.raises(PluginError, match="not loaded"):
        loader.activate("ghost")


def test_deactivate_already_inactive_is_noop(loader: PluginLoader, plugin_dir: Path) -> None:
    """deactivate() on an inactive plugin is a no-op (does not raise)."""
    _write_plugin(plugin_dir, "inactive.py", name="inactive")
    loader.load("inactive")
    loader.deactivate("inactive")  # should not raise


def test_activate_already_active_is_noop(loader: PluginLoader, plugin_dir: Path) -> None:
    """activate() on an already active plugin is a no-op."""
    _write_plugin(plugin_dir, "double_act.py", name="double_act")
    loader.load("double_act")
    loader.activate("double_act")
    loader.activate("double_act")  # second call should not raise
    assert loader._records["double_act"].active is True  # noqa: SLF001


# ---------------------------------------------------------------------------
# reload()
# ---------------------------------------------------------------------------


def test_reload_hot_swaps_plugin(loader: PluginLoader, plugin_dir: Path) -> None:
    """reload() deactivates, re-imports, and re-activates the plugin."""
    _write_plugin(plugin_dir, "reloadable.py", name="reloadable", version="1.0.0")
    loader.load("reloadable")
    loader.activate("reloadable")

    # Update the file with a new version
    _write_plugin(plugin_dir, "reloadable.py", name="reloadable", version="2.0.0")
    loader.reload("reloadable")

    record = loader._records["reloadable"]  # noqa: SLF001
    assert record.instance.version == "2.0.0"
    assert record.active is True


def test_reload_unloaded_raises(loader: PluginLoader) -> None:
    """reload() on an unloaded plugin raises PluginError."""
    with pytest.raises(PluginError, match="not loaded"):
        loader.reload("ghost")


# ---------------------------------------------------------------------------
# list_loaded()
# ---------------------------------------------------------------------------


def test_list_loaded_returns_metadata(loader: PluginLoader, plugin_dir: Path) -> None:
    """list_loaded() returns dicts with expected keys."""
    _write_plugin(plugin_dir, "meta.py", name="meta", version="3.1.4", description="Pi plugin")
    loader.load("meta")
    result = loader.list_loaded()
    assert len(result) == 1
    entry = result[0]
    assert entry["name"] == "meta"
    assert entry["version"] == "3.1.4"
    assert entry["description"] == "Pi plugin"
    assert entry["active"] is False
    assert "path" in entry


def test_list_loaded_empty_when_nothing_loaded(loader: PluginLoader) -> None:
    """list_loaded() returns empty list when no plugins are loaded."""
    assert loader.list_loaded() == []


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


def test_concurrent_load_activate(loader: PluginLoader, plugin_dir: Path) -> None:
    """Concurrent load+activate calls from multiple threads do not corrupt state."""
    for i in range(5):
        _write_plugin(plugin_dir, f"p{i}.py", name=f"thread_plugin_{i}")

    errors: list[Exception] = []

    def _work(name: str) -> None:
        try:
            loader.load(name)
            loader.activate(name)
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=_work, args=(f"thread_plugin_{i}",))
        for i in range(5)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Thread errors: {errors}"
    assert len(loader.list_loaded()) == 5
