"""Strategy Hot-Reload: watch ~/.flinttrade/strategies/ and live-reload on change.

User strategy files are Python modules that expose a ``Strategy`` class.
The hot-reloader:

1. Discovers ``*.py`` files in the configured directory.
2. AST-validates uploaded code using the same rules as
   :class:`~flinttrade_engine.strategy_runner.UserStrategyRunner`.
3. Imports them with :mod:`importlib` in an isolated module namespace.
4. Watches the directory with ``watchdog`` and calls a user callback whenever
   a strategy file is created, modified, or deleted.
5. Guarantees safe transitions: the old strategy is stopped (via the optional
   ``stop_callback``) before the new module is loaded.

Usage::

    reloader = StrategyHotReloader()
    names = reloader.discover()

    cls = reloader.load("my_strategy")
    ok, msg = reloader.reload("my_strategy")

    reloader.watch(on_change=lambda name, event: print(name, event))
    # ... later ...
    reloader.stop_watching()

    valid, errors = reloader.validate(source_code)
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import logging
import sys
import threading
from pathlib import Path
from typing import Callable

logger = logging.getLogger("flinttrade.engine.strategy_hot_reload")

# ---------------------------------------------------------------------------
# Watchdog — optional; tests mock it if unavailable
# ---------------------------------------------------------------------------

try:
    from watchdog.events import FileSystemEventHandler  # type: ignore[import]
    from watchdog.observers import Observer  # type: ignore[import]

    _WATCHDOG_AVAILABLE = True
except ImportError:  # pragma: no cover
    _WATCHDOG_AVAILABLE = False
    Observer = None  # type: ignore[assignment,misc]
    FileSystemEventHandler = object  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# AST rules (mirrored from strategy_runner to remain self-contained)
# ---------------------------------------------------------------------------

_BLOCKED_MODULES: frozenset[str] = frozenset(
    {
        "os",
        "subprocess",
        "socket",
        "shutil",
        "ctypes",
        "multiprocessing",
        "threading",
        "signal",
        "resource",
        "pty",
        "fcntl",
        "select",
        "selectors",
        "asyncio",
        "concurrent",
        "mmap",
        "tempfile",
        "http",
        "urllib",
        "requests",
        "httpx",
        "ftplib",
        "smtplib",
        "webbrowser",
    }
)

_BLOCKED_BUILTINS: frozenset[str] = frozenset(
    {
        "eval",
        "exec",
        "__import__",
        "compile",
        "globals",
        "locals",
        "vars",
        "dir",
        "getattr",
        "setattr",
        "delattr",
        "open",
        "breakpoint",
    }
)

_BLOCKED_ATTR_PATTERNS: frozenset[tuple[str, str]] = frozenset(
    {
        ("os", "system"),
        ("os", "popen"),
        ("os", "execv"),
        ("os", "fork"),
        ("subprocess", "run"),
        ("subprocess", "call"),
        ("subprocess", "Popen"),
    }
)

_FORBIDDEN_ATTRS: frozenset[str] = frozenset(
    {
        "__class__",
        "__bases__",
        "__subclasses__",
        "__globals__",
        "__code__",
    }
)

_WRITE_MODES: frozenset[str] = frozenset({"w", "wb", "a", "ab", "x", "xb", "w+", "r+", "a+"})


# ---------------------------------------------------------------------------
# Internal watchdog handler
# ---------------------------------------------------------------------------


class _StrategyFileHandler(FileSystemEventHandler):  # type: ignore[misc]
    """Watchdog handler that forwards .py file events to the hot-reloader.

    Args:
        on_change: Callback invoked as ``on_change(strategy_name, event_type)``
            where ``event_type`` is one of ``"created"``, ``"modified"``,
            or ``"deleted"``.
    """

    def __init__(self, on_change: Callable[[str, str], None]) -> None:
        super().__init__()
        self._on_change = on_change

    def _handle(self, path: str, event_type: str) -> None:
        p = Path(path)
        if p.suffix == ".py":
            self._on_change(p.stem, event_type)

    def on_created(self, event: object) -> None:  # type: ignore[override]
        if not getattr(event, "is_directory", False):
            self._handle(getattr(event, "src_path", ""), "created")

    def on_modified(self, event: object) -> None:  # type: ignore[override]
        if not getattr(event, "is_directory", False):
            self._handle(getattr(event, "src_path", ""), "modified")

    def on_deleted(self, event: object) -> None:  # type: ignore[override]
        if not getattr(event, "is_directory", False):
            self._handle(getattr(event, "src_path", ""), "deleted")


# ---------------------------------------------------------------------------
# StrategyHotReloader
# ---------------------------------------------------------------------------


class StrategyHotReloader:
    """Hot-reload user strategy files from a watched directory.

    Uses :mod:`watchdog` to detect file changes and :mod:`importlib` to reload
    modules.  Each reload is atomic: the old module is removed from
    :data:`sys.modules` before the new one is imported.

    A strategy file must:
    - Pass AST validation (no dangerous imports/calls).
    - Define a class named ``Strategy``.

    Args:
        strategies_dir: Directory to watch and load strategies from.
            Created automatically if it does not exist.
        stop_callback: Optional callable invoked as
            ``stop_callback(name)`` before a strategy is reloaded, giving
            the caller a chance to stop a running instance.
    """

    def __init__(
        self,
        strategies_dir: Path = Path.home() / ".flinttrade" / "strategies",
        stop_callback: Callable[[str], None] | None = None,
    ) -> None:
        self._dir = Path(strategies_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._stop_callback = stop_callback

        # name → loaded module (kept alive to prevent GC)
        self._modules: dict[str, object] = {}
        # watchdog observer + handler references
        self._observer: object | None = None
        self._watch_thread: threading.Thread | None = None
        self._watching: bool = False

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self) -> list[str]:
        """Find all ``*.py`` files that define a ``Strategy`` class.

        Returns:
            Sorted list of strategy names (file stems that pass AST
            validation **and** contain a ``Strategy`` class definition).
        """
        names: list[str] = []
        for py_file in sorted(self._dir.glob("*.py")):
            try:
                source = py_file.read_text(encoding="utf-8")
            except OSError:
                continue
            valid, _ = self.validate(source)
            if not valid:
                continue
            if _has_strategy_class(source):
                names.append(py_file.stem)
        return names

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load(self, name: str) -> type:
        """Import a strategy file and return its ``Strategy`` class.

        The module is cached in :attr:`_modules`.  If the file has already
        been loaded, the cached module is returned directly (call
        :meth:`reload` to force a fresh import).

        Args:
            name: Strategy name (file stem, e.g. ``"ema_crossover"``).

        Returns:
            The ``Strategy`` class defined in the module.

        Raises:
            FileNotFoundError: If ``{name}.py`` does not exist.
            ValueError: If the file fails AST validation or does not define
                a ``Strategy`` class.
            ImportError: If the module raises an error on import.
        """
        if name in self._modules:
            module = self._modules[name]
            return _extract_strategy_class(module, name)

        return self._load_fresh(name)

    # ------------------------------------------------------------------
    # Reload
    # ------------------------------------------------------------------

    def reload(self, name: str) -> tuple[bool, str]:
        """Reload a strategy file, replacing the cached module.

        Stops any running instance via ``stop_callback`` before loading the
        new module.  If the new module fails to load the old module is NOT
        restored (the strategy remains stopped).

        Args:
            name: Strategy name to reload.

        Returns:
            ``(True, "reloaded successfully")`` on success, or
            ``(False, <error message>)`` on failure.
        """
        # Stop existing instance before reload
        if self._stop_callback is not None:
            try:
                self._stop_callback(name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("stop_callback raised for '%s': %s", name, exc)

        # Evict from module cache and sys.modules
        self._evict(name)

        try:
            self._load_fresh(name)
            logger.info("Strategy reloaded: %s", name)
            return True, f"Strategy '{name}' reloaded successfully"
        except Exception as exc:  # noqa: BLE001
            msg = f"Failed to reload strategy '{name}': {exc}"
            logger.error(msg)
            return False, msg

    # ------------------------------------------------------------------
    # Watch
    # ------------------------------------------------------------------

    def watch(self, on_change: Callable[[str, str], None]) -> None:
        """Start a background filesystem watcher.

        Calls ``on_change(name, event_type)`` on the watchdog observer
        thread whenever a ``.py`` file is created, modified, or deleted.

        If watchdog is not installed the method logs a warning and returns
        without starting any watcher (graceful degradation).

        Args:
            on_change: Callback invoked with ``(strategy_name, event_type)``.
                ``event_type`` is one of ``"created"``, ``"modified"``,
                ``"deleted"``.
        """
        if self._watching:
            logger.warning("StrategyHotReloader is already watching; ignoring duplicate call")
            return

        if not _WATCHDOG_AVAILABLE or Observer is None:
            logger.warning(
                "watchdog library not installed — hot-reload file watching disabled. "
                "Install with: pip install watchdog"
            )
            return

        handler = _StrategyFileHandler(on_change)
        observer = Observer()
        observer.schedule(handler, str(self._dir), recursive=False)  # type: ignore[union-attr]
        observer.start()  # type: ignore[union-attr]
        self._observer = observer
        self._watching = True
        logger.info("StrategyHotReloader watching %s", self._dir)

    def stop_watching(self) -> None:
        """Stop the filesystem watcher and join its thread.

        Safe to call even if :meth:`watch` was never called.
        """
        if not self._watching or self._observer is None:
            return
        observer = self._observer
        try:
            observer.stop()  # type: ignore[union-attr]
            observer.join(timeout=5)  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            logger.exception("Error stopping watchdog observer")
        finally:
            self._observer = None
            self._watching = False
            logger.info("StrategyHotReloader stopped watching")

    # ------------------------------------------------------------------
    # Validate
    # ------------------------------------------------------------------

    def validate(self, code: str) -> tuple[bool, list[str]]:
        """AST-validate strategy source code for dangerous patterns.

        No code is executed.  Uses Python's :mod:`ast` module.

        Args:
            code: Python source text.

        Returns:
            ``(True, [])`` when the code is safe, or
            ``(False, [error_message, ...])`` when violations are found.
        """
        errors: list[str] = []

        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return False, [f"SyntaxError: {exc}"]

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in _BLOCKED_MODULES:
                        errors.append(f"Blocked import: '{alias.name}' (module '{root}' is not allowed)")

            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                if root in _BLOCKED_MODULES:
                    errors.append(
                        f"Blocked import: 'from {node.module} import ...' (module '{root}' is not allowed)"
                    )
                for alias in node.names:
                    if alias.name in _BLOCKED_BUILTINS:
                        errors.append(f"Blocked import: 'from {node.module} import {alias.name}'")

            elif isinstance(node, ast.Attribute):
                if node.attr in _FORBIDDEN_ATTRS:
                    errors.append(f"Blocked attribute: '.{node.attr}' is not allowed in strategies")
                if isinstance(node.value, ast.Name):
                    pair = (node.value.id, node.attr)
                    if pair in _BLOCKED_ATTR_PATTERNS:
                        errors.append(
                            f"Blocked call: '{node.value.id}.{node.attr}()' is not allowed"
                        )

            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in _BLOCKED_BUILTINS:
                    if func.id == "open":
                        _check_open_mode(node, errors)
                    else:
                        errors.append(f"Blocked call: '{func.id}()' is not allowed in strategies")

        return (len(errors) == 0), errors

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_fresh(self, name: str) -> type:
        """Import a strategy module from disk, bypassing the cache.

        Args:
            name: Strategy name (file stem).

        Returns:
            The ``Strategy`` class.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If validation fails or no ``Strategy`` class is found.
            ImportError: If the module raises on import.
        """
        py_file = self._dir / f"{name}.py"
        if not py_file.exists():
            raise FileNotFoundError(f"Strategy file not found: {py_file}")

        source = py_file.read_text(encoding="utf-8")
        valid, errors = self.validate(source)
        if not valid:
            raise ValueError(
                f"Strategy '{name}' failed AST validation ({len(errors)} issue(s)):\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

        if not _has_strategy_class(source):
            raise ValueError(f"Strategy '{name}' does not define a 'Strategy' class")

        # Build a unique module name to avoid collisions with built-ins
        module_name = f"_flinttrade_strategy_{name}"
        spec = importlib.util.spec_from_file_location(module_name, str(py_file))
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create import spec for {py_file}")

        module = importlib.util.module_from_spec(spec)
        # Register before exec so relative imports inside the strategy resolve
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)  # type: ignore[union-attr]
        except Exception:
            sys.modules.pop(module_name, None)
            raise

        self._modules[name] = module
        logger.info("Strategy loaded: %s (module=%s)", name, module_name)
        return _extract_strategy_class(module, name)

    def _evict(self, name: str) -> None:
        """Remove a module from the cache and from :data:`sys.modules`.

        Args:
            name: Strategy name to evict.
        """
        self._modules.pop(name, None)
        module_name = f"_flinttrade_strategy_{name}"
        sys.modules.pop(module_name, None)

    @property
    def watching(self) -> bool:
        """Return ``True`` when the filesystem watcher is active."""
        return self._watching

    @property
    def loaded_names(self) -> list[str]:
        """Return names of all currently cached strategy modules."""
        return list(self._modules.keys())


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _has_strategy_class(source: str) -> bool:
    """Return ``True`` if *source* defines a class named ``Strategy``.

    Args:
        source: Python source text.

    Returns:
        ``True`` if a top-level or nested ``class Strategy`` definition exists.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    return any(
        isinstance(node, ast.ClassDef) and node.name == "Strategy"
        for node in ast.walk(tree)
    )


def _extract_strategy_class(module: object, name: str) -> type:
    """Extract the ``Strategy`` class from an imported module.

    Args:
        module: The loaded Python module object.
        name: Strategy name (used in error messages).

    Returns:
        The ``Strategy`` class.

    Raises:
        ValueError: If the module has no ``Strategy`` attribute or it is not
            a class.
    """
    cls = getattr(module, "Strategy", None)
    if cls is None:
        raise ValueError(f"Strategy module '{name}' does not export a 'Strategy' class")
    if not isinstance(cls, type):
        raise ValueError(f"'Strategy' in module '{name}' is not a class (got {type(cls).__name__})")
    return cls


def _check_open_mode(node: ast.Call, errors: list[str]) -> None:
    """Flag ``open()`` calls with write-mode arguments.

    Args:
        node: The :class:`ast.Call` node.
        errors: List to append error messages to.
    """
    if len(node.args) >= 2:
        mode_arg = node.args[1]
        if isinstance(mode_arg, ast.Constant) and str(mode_arg.value) in _WRITE_MODES:
            errors.append(
                f"Blocked call: 'open()' with write mode '{mode_arg.value}' is not allowed"
            )
            return
    for kw in node.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            if str(kw.value.value) in _WRITE_MODES:
                errors.append(
                    f"Blocked call: 'open()' with write mode '{kw.value.value}' is not allowed"
                )
                return
