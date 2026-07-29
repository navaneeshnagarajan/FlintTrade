"""Tests for flinttrade_engine.strategy_hot_reload.

Covers:
- validate(): clean code, syntax errors, blocked imports, blocked builtins,
  blocked attr patterns, write-mode open(), forbidden dunder attrs
- _has_strategy_class(): detection of Strategy class
- discover(): finds valid strategy files, skips invalid ones
- load(): fresh import, cached return, missing file, no Strategy class
- reload(): successful reload, stop_callback invoked, failure path
- watch() / stop_watching(): watchdog integration (mocked), no-watchdog fallback
- _evict(): module cache cleared from sys.modules
- StrategyHotReloader.loaded_names / watching properties
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import flinttrade_engine.strategy_hot_reload as mod
from flinttrade_engine.strategy_hot_reload import (
    StrategyHotReloader,
    _has_strategy_class,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_STRATEGY = """\
class Strategy:
    def __init__(self):
        self.name = "test"

    def on_tick(self, tick):
        pass
"""

_SAFE_CODE = """\
import math

class Strategy:
    def run(self):
        return math.sqrt(4)
"""


def _write_strategy(tmp_path: Path, name: str, source: str = _VALID_STRATEGY) -> Path:
    """Write a strategy file and return its path."""
    p = tmp_path / f"{name}.py"
    p.write_text(source, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# validate() — clean code
# ---------------------------------------------------------------------------


class TestValidateCleanCode:
    def test_valid_strategy_passes(self, tmp_path: Path) -> None:
        r = StrategyHotReloader(strategies_dir=tmp_path)
        valid, errors = r.validate(_VALID_STRATEGY)
        assert valid is True
        assert errors == []

    def test_safe_stdlib_import_allowed(self, tmp_path: Path) -> None:
        r = StrategyHotReloader(strategies_dir=tmp_path)
        valid, errors = r.validate(_SAFE_CODE)
        assert valid is True

    def test_empty_code_passes(self, tmp_path: Path) -> None:
        r = StrategyHotReloader(strategies_dir=tmp_path)
        valid, errors = r.validate("")
        assert valid is True


# ---------------------------------------------------------------------------
# validate() — syntax errors
# ---------------------------------------------------------------------------


class TestValidateSyntaxErrors:
    def test_syntax_error_returns_false(self, tmp_path: Path) -> None:
        r = StrategyHotReloader(strategies_dir=tmp_path)
        valid, errors = r.validate("def bad(:\n    pass\n")
        assert valid is False
        assert any("SyntaxError" in e for e in errors)


# ---------------------------------------------------------------------------
# validate() — blocked imports
# ---------------------------------------------------------------------------


class TestValidateBlockedImports:
    def test_os_import_blocked(self, tmp_path: Path) -> None:
        r = StrategyHotReloader(strategies_dir=tmp_path)
        valid, errors = r.validate("import os\n")
        assert valid is False
        assert any("os" in e for e in errors)

    def test_subprocess_import_blocked(self, tmp_path: Path) -> None:
        r = StrategyHotReloader(strategies_dir=tmp_path)
        valid, errors = r.validate("import subprocess\n")
        assert valid is False

    def test_from_os_import_blocked(self, tmp_path: Path) -> None:
        r = StrategyHotReloader(strategies_dir=tmp_path)
        valid, errors = r.validate("from os import path\n")
        assert valid is False

    def test_httpx_import_blocked(self, tmp_path: Path) -> None:
        r = StrategyHotReloader(strategies_dir=tmp_path)
        valid, errors = r.validate("import httpx\n")
        assert valid is False


# ---------------------------------------------------------------------------
# validate() — blocked builtins
# ---------------------------------------------------------------------------


class TestValidateBlockedBuiltins:
    def test_eval_blocked(self, tmp_path: Path) -> None:
        r = StrategyHotReloader(strategies_dir=tmp_path)
        valid, errors = r.validate("x = eval('1+1')\n")
        assert valid is False
        assert any("eval" in e for e in errors)

    def test_exec_blocked(self, tmp_path: Path) -> None:
        r = StrategyHotReloader(strategies_dir=tmp_path)
        valid, errors = r.validate("exec('x=1')\n")
        assert valid is False

    def test_open_write_blocked(self, tmp_path: Path) -> None:
        r = StrategyHotReloader(strategies_dir=tmp_path)
        valid, errors = r.validate("f = open('x', 'w')\n")
        assert valid is False
        assert any("open" in e for e in errors)

    def test_open_read_allowed(self, tmp_path: Path) -> None:
        r = StrategyHotReloader(strategies_dir=tmp_path)
        valid, errors = r.validate("f = open('data.csv', 'r')\n")
        assert valid is True


# ---------------------------------------------------------------------------
# validate() — forbidden dunder attrs
# ---------------------------------------------------------------------------


class TestValidateForbiddenAttrs:
    def test_subclasses_blocked(self, tmp_path: Path) -> None:
        r = StrategyHotReloader(strategies_dir=tmp_path)
        valid, errors = r.validate("x = str.__subclasses__()\n")
        assert valid is False
        assert any("__subclasses__" in e for e in errors)

    def test_globals_blocked(self, tmp_path: Path) -> None:
        r = StrategyHotReloader(strategies_dir=tmp_path)
        valid, errors = r.validate("x = obj.__globals__\n")
        assert valid is False


# ---------------------------------------------------------------------------
# _has_strategy_class()
# ---------------------------------------------------------------------------


class TestHasStrategyClass:
    def test_detects_strategy_class(self) -> None:
        assert _has_strategy_class(_VALID_STRATEGY) is True

    def test_missing_strategy_class(self) -> None:
        assert _has_strategy_class("class NotStrategy:\n    pass\n") is False

    def test_syntax_error_returns_false(self) -> None:
        assert _has_strategy_class("class :\n    pass\n") is False

    def test_nested_strategy_class_detected(self) -> None:
        code = "class Outer:\n    class Strategy:\n        pass\n"
        assert _has_strategy_class(code) is True


# ---------------------------------------------------------------------------
# discover()
# ---------------------------------------------------------------------------


class TestDiscover:
    def test_discovers_valid_strategy(self, tmp_path: Path) -> None:
        _write_strategy(tmp_path, "my_strat")
        r = StrategyHotReloader(strategies_dir=tmp_path)
        names = r.discover()
        assert "my_strat" in names

    def test_skips_invalid_code(self, tmp_path: Path) -> None:
        _write_strategy(tmp_path, "bad_strat", "import os\nclass Strategy:\n    pass\n")
        r = StrategyHotReloader(strategies_dir=tmp_path)
        names = r.discover()
        assert "bad_strat" not in names

    def test_skips_missing_strategy_class(self, tmp_path: Path) -> None:
        _write_strategy(tmp_path, "no_class", "x = 1\n")
        r = StrategyHotReloader(strategies_dir=tmp_path)
        names = r.discover()
        assert "no_class" not in names

    def test_returns_sorted_names(self, tmp_path: Path) -> None:
        _write_strategy(tmp_path, "zz_strat")
        _write_strategy(tmp_path, "aa_strat")
        r = StrategyHotReloader(strategies_dir=tmp_path)
        names = r.discover()
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# load() and reload()
# ---------------------------------------------------------------------------


class TestLoad:
    def test_load_returns_strategy_class(self, tmp_path: Path) -> None:
        _write_strategy(tmp_path, "my_strat")
        r = StrategyHotReloader(strategies_dir=tmp_path)
        cls = r.load("my_strat")
        assert isinstance(cls, type)
        assert cls.__name__ == "Strategy"

    def test_load_caches_module(self, tmp_path: Path) -> None:
        _write_strategy(tmp_path, "my_strat")
        r = StrategyHotReloader(strategies_dir=tmp_path)
        cls1 = r.load("my_strat")
        cls2 = r.load("my_strat")
        assert cls1 is cls2

    def test_load_missing_file_raises(self, tmp_path: Path) -> None:
        r = StrategyHotReloader(strategies_dir=tmp_path)
        with pytest.raises(FileNotFoundError):
            r.load("nonexistent")

    def test_load_no_strategy_class_raises(self, tmp_path: Path) -> None:
        _write_strategy(tmp_path, "no_class", "x = 42\n")
        r = StrategyHotReloader(strategies_dir=tmp_path)
        with pytest.raises(ValueError, match="does not define"):
            r.load("no_class")

    def test_loaded_names_property(self, tmp_path: Path) -> None:
        _write_strategy(tmp_path, "strat_a")
        r = StrategyHotReloader(strategies_dir=tmp_path)
        r.load("strat_a")
        assert "strat_a" in r.loaded_names


class TestReload:
    def test_reload_success(self, tmp_path: Path) -> None:
        _write_strategy(tmp_path, "hot_strat")
        r = StrategyHotReloader(strategies_dir=tmp_path)
        r.load("hot_strat")
        ok, msg = r.reload("hot_strat")
        assert ok is True
        assert "reloaded" in msg.lower()

    def test_reload_calls_stop_callback(self, tmp_path: Path) -> None:
        _write_strategy(tmp_path, "hot_strat")
        stop_cb = MagicMock()
        r = StrategyHotReloader(strategies_dir=tmp_path, stop_callback=stop_cb)
        r.load("hot_strat")
        r.reload("hot_strat")
        stop_cb.assert_called_once_with("hot_strat")

    def test_reload_failure_returns_false(self, tmp_path: Path) -> None:
        r = StrategyHotReloader(strategies_dir=tmp_path)
        ok, msg = r.reload("nonexistent")
        assert ok is False
        assert "nonexistent" in msg

    def test_reload_evicts_old_module(self, tmp_path: Path) -> None:
        _write_strategy(tmp_path, "evict_strat")
        r = StrategyHotReloader(strategies_dir=tmp_path)
        r.load("evict_strat")
        module_key = "_flinttrade_strategy_evict_strat"
        assert module_key in sys.modules
        r._evict("evict_strat")
        assert module_key not in sys.modules


# ---------------------------------------------------------------------------
# watch() / stop_watching()
# ---------------------------------------------------------------------------


class TestWatch:
    def test_watch_without_watchdog_logs_warning(self, tmp_path: Path) -> None:
        r = StrategyHotReloader(strategies_dir=tmp_path)
        with patch.object(mod, "_WATCHDOG_AVAILABLE", False):
            with patch.object(mod, "Observer", None):
                r.watch(on_change=lambda n, e: None)
        assert r.watching is False

    def test_watch_starts_observer(self, tmp_path: Path) -> None:
        mock_observer = MagicMock()
        mock_observer_cls = MagicMock(return_value=mock_observer)
        r = StrategyHotReloader(strategies_dir=tmp_path)
        with patch.object(mod, "_WATCHDOG_AVAILABLE", True):
            with patch.object(mod, "Observer", mock_observer_cls):
                r.watch(on_change=lambda n, e: None)
        mock_observer.start.assert_called_once()
        assert r.watching is True
        # Clean up
        r._observer = mock_observer
        r._watching = False

    def test_stop_watching_stops_observer(self, tmp_path: Path) -> None:
        mock_observer = MagicMock()
        mock_observer_cls = MagicMock(return_value=mock_observer)
        r = StrategyHotReloader(strategies_dir=tmp_path)
        with patch.object(mod, "_WATCHDOG_AVAILABLE", True):
            with patch.object(mod, "Observer", mock_observer_cls):
                r.watch(on_change=lambda n, e: None)
        r.stop_watching()
        mock_observer.stop.assert_called_once()
        assert r.watching is False

    def test_double_watch_is_noop(self, tmp_path: Path) -> None:
        mock_observer = MagicMock()
        mock_observer_cls = MagicMock(return_value=mock_observer)
        r = StrategyHotReloader(strategies_dir=tmp_path)
        with patch.object(mod, "_WATCHDOG_AVAILABLE", True):
            with patch.object(mod, "Observer", mock_observer_cls):
                r.watch(on_change=lambda n, e: None)
                r.watch(on_change=lambda n, e: None)  # second call ignored
        assert mock_observer_cls.call_count == 1
        r.stop_watching()

    def test_stop_watching_when_not_watching_is_noop(self, tmp_path: Path) -> None:
        r = StrategyHotReloader(strategies_dir=tmp_path)
        r.stop_watching()  # should not raise


# ---------------------------------------------------------------------------
# Default strategies directory resolution + one-shot legacy migration
# ---------------------------------------------------------------------------


def _redirect_workspace(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    """Point the resolver at tmp_path for both the workspace and the legacy root.

    Clears both workspace environment overrides so the default-workspace probe
    is live, then redirects ``workspace._default_home`` and the module's
    ``_legacy_strategies_dir`` seam so nothing can reach the real home
    directory.

    Args:
        monkeypatch: pytest monkeypatch fixture.
        tmp_path: pytest temporary directory.

    Returns:
        Tuple of ``(workspace_dir, legacy_strategies_dir)``, neither created yet.
    """
    from flinttrade_core import workspace as ws

    monkeypatch.delenv("FLINTTRADE_WORKSPACE_DIR", raising=False)
    monkeypatch.delenv("FLINTTRADE_HOME", raising=False)
    workspace = tmp_path / "workspace"
    legacy = tmp_path / "legacy" / "strategies"
    monkeypatch.setattr(ws, "_default_home", lambda: workspace)
    monkeypatch.setattr(mod, "_legacy_strategies_dir", lambda: legacy)
    return workspace, legacy


class TestDefaultStrategiesDir:
    """The watched directory defaults to the workspace strategies directory."""

    @pytest.mark.unit
    def test_fresh_install_resolves_under_workspace_without_copying(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        workspace, legacy = _redirect_workspace(monkeypatch, tmp_path)

        resolved = mod.default_strategies_dir()

        assert resolved == workspace / "strategies"
        assert not legacy.exists()

    @pytest.mark.unit
    def test_no_argument_construction_uses_the_workspace_directory(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The default must match the directory ``UserStrategyRunner`` is wired to."""
        from flinttrade_core.workspace import workspace_dir

        workspace, _legacy = _redirect_workspace(monkeypatch, tmp_path)

        r = StrategyHotReloader()

        assert r._dir == workspace / "strategies"
        assert r._dir == workspace_dir() / "strategies"
        assert r._dir.is_dir(), "the watched directory is created on construction"

    @pytest.mark.unit
    def test_legacy_only_tree_is_copied_and_legacy_retained(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        workspace, legacy = _redirect_workspace(monkeypatch, tmp_path)
        legacy.mkdir(parents=True)
        (legacy / "ema.py").write_text(_VALID_STRATEGY, encoding="utf-8")

        resolved = mod.default_strategies_dir()

        assert (resolved / "ema.py").read_text(encoding="utf-8") == _VALID_STRATEGY
        assert (legacy / "ema.py").exists(), "legacy tree must be retained"
        assert StrategyHotReloader().discover() == ["ema"]

    @pytest.mark.unit
    def test_both_populated_keeps_workspace_files_untouched(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        workspace, legacy = _redirect_workspace(monkeypatch, tmp_path)
        legacy.mkdir(parents=True)
        (legacy / "legacy_only.py").write_text(_VALID_STRATEGY, encoding="utf-8")
        target = workspace / "strategies"
        target.mkdir(parents=True)
        (target / "mine.py").write_text(_SAFE_CODE, encoding="utf-8")

        resolved = mod.default_strategies_dir()

        assert sorted(p.name for p in resolved.glob("*.py")) == ["mine.py"]
        assert (target / "mine.py").read_text(encoding="utf-8") == _SAFE_CODE
        assert (legacy / "legacy_only.py").exists()

    @pytest.mark.unit
    def test_workspace_override_makes_the_probe_inert(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _workspace, legacy = _redirect_workspace(monkeypatch, tmp_path)
        legacy.mkdir(parents=True)
        (legacy / "ema.py").write_text(_VALID_STRATEGY, encoding="utf-8")
        override = tmp_path / "override"
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(override))

        resolved = mod.default_strategies_dir()

        assert resolved == override.resolve() / "strategies"
        assert not resolved.exists(), "no migration may run while an override is set"

    @pytest.mark.unit
    def test_explicit_directory_skips_the_migration_probe(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _workspace, legacy = _redirect_workspace(monkeypatch, tmp_path)
        legacy.mkdir(parents=True)
        (legacy / "ema.py").write_text(_VALID_STRATEGY, encoding="utf-8")
        explicit = tmp_path / "explicit"

        r = StrategyHotReloader(strategies_dir=explicit)

        assert r._dir == explicit
        assert r.discover() == []


class TestRuntimeArtefactsDoNotBlockTheMigration:
    """Directories the backend itself creates must not count as operator state.

    ``UserStrategyRunner.__init__`` makes ``logs/`` and
    ``BaseStrategy.save_state()`` makes one directory per strategy id, both
    inside the workspace strategies directory. Every boot after the first
    therefore finds a non-empty target — if that counted as "the operator
    already has strategies here" the one-time copy could never fire.
    """

    @pytest.mark.unit
    def test_runner_log_directory_does_not_block_the_copy(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        workspace, legacy = _redirect_workspace(monkeypatch, tmp_path)
        legacy.mkdir(parents=True)
        (legacy / "ema.py").write_text(_VALID_STRATEGY, encoding="utf-8")
        # The runner created its log directory on an earlier boot.
        logs = workspace / "strategies" / "logs"
        logs.mkdir(parents=True)
        (logs / "ema.log").write_text("previous run\n", encoding="utf-8")

        resolved = mod.default_strategies_dir()

        assert (resolved / "ema.py").read_text(encoding="utf-8") == _VALID_STRATEGY
        assert (logs / "ema.log").read_text(encoding="utf-8") == "previous run\n"
        assert (legacy / "ema.py").exists(), "legacy tree must be retained"

    @pytest.mark.unit
    def test_strategy_state_directory_does_not_block_the_copy(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        workspace, legacy = _redirect_workspace(monkeypatch, tmp_path)
        legacy.mkdir(parents=True)
        (legacy / "ema.py").write_text(_VALID_STRATEGY, encoding="utf-8")
        # BaseStrategy.save_state() wrote state for a built-in strategy.
        state_dir = workspace / "strategies" / "orb_breakout"
        state_dir.mkdir(parents=True)
        (state_dir / "state.json").write_text('{"tick_count": 3}', encoding="utf-8")

        resolved = mod.default_strategies_dir()

        assert (resolved / "ema.py").read_text(encoding="utf-8") == _VALID_STRATEGY
        assert (state_dir / "state.json").read_text(encoding="utf-8") == '{"tick_count": 3}'

    @pytest.mark.unit
    def test_uploaded_strategy_still_blocks_the_copy(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """A single user-authored file wins silently, runtime artefacts or not."""
        workspace, legacy = _redirect_workspace(monkeypatch, tmp_path)
        legacy.mkdir(parents=True)
        (legacy / "legacy_only.py").write_text(_VALID_STRATEGY, encoding="utf-8")
        target = workspace / "strategies"
        (target / "logs").mkdir(parents=True)
        (target / "mine.py").write_text(_SAFE_CODE, encoding="utf-8")

        resolved = mod.default_strategies_dir()

        assert sorted(p.name for p in resolved.glob("*.py")) == ["mine.py"]
        assert (target / "mine.py").read_text(encoding="utf-8") == _SAFE_CODE
        assert (legacy / "legacy_only.py").exists()

    @pytest.mark.unit
    def test_migration_never_overwrites_a_same_named_workspace_file(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Even a target holding only runtime artefacts keeps its own entries."""
        workspace, legacy = _redirect_workspace(monkeypatch, tmp_path)
        legacy.mkdir(parents=True)
        (legacy / "ema.py").write_text(_VALID_STRATEGY, encoding="utf-8")
        (legacy / "logs").mkdir()
        (legacy / "logs" / "ema.log").write_text("legacy run\n", encoding="utf-8")
        logs = workspace / "strategies" / "logs"
        logs.mkdir(parents=True)
        (logs / "ema.log").write_text("workspace run\n", encoding="utf-8")

        mod.default_strategies_dir()

        assert (logs / "ema.log").read_text(encoding="utf-8") == "workspace run\n"

    @pytest.mark.unit
    def test_runner_wiring_is_unblocked_end_to_end(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The runner's own boot sequence must not lock itself out.

        First boot creates ``logs/``; the second boot is the one that would
        have been blocked, so migrate on a legacy tree planted in between.
        """
        from flinttrade_engine.strategy_runner import UserStrategyRunner

        workspace, legacy = _redirect_workspace(monkeypatch, tmp_path)

        UserStrategyRunner(mod.default_strategies_dir())
        assert (workspace / "strategies" / "logs").is_dir()

        legacy.mkdir(parents=True)
        (legacy / "ema.py").write_text(_VALID_STRATEGY, encoding="utf-8")

        runner = UserStrategyRunner(mod.default_strategies_dir())

        assert (runner._strategies_dir / "ema.py").exists()
