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
