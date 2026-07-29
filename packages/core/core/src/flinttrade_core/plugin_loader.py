"""Dynamic plugin discovery and hot-reload for FlintTrade.

Users drop ``*.py`` files into the ``plugins/`` directory of their platform
workspace — ``~/.flinttrade/plugins/`` on Linux, ``~/Library/Application
Support/flinttrade/plugins/`` on macOS, ``%APPDATA%/flinttrade/plugins/`` on
Windows, resolved by :func:`flinttrade_core.workspace.workspace_dir` so the
``FLINTTRADE_WORKSPACE_DIR``/``FLINTTRADE_HOME`` overrides are honoured.  A
plugin directory left behind at the old cross-platform default
(``~/.flinttrade/plugins``) is copied into the platform workspace once, so an
upgrade never makes an operator's installed plugins vanish.  Each
file must contain a class named ``Plugin`` that inherits from
:class:`PluginInterface`.  The :class:`PluginLoader` discovers, loads,
activates, deactivates, and hot-reloads those classes without modifying any
core package.

Example plugin file (``<workspace>/plugins/my_plugin.py``)::

    from flinttrade_core.plugin_loader import PluginInterface, PluginContext

    class Plugin(PluginInterface):
        name = "my_plugin"
        version = "1.0.0"
        description = "Example user plugin."

        def activate(self, context: PluginContext) -> None:
            context.event_bus.subscribe("order.placed", self._on_order)

        def deactivate(self) -> None:
            pass

        def _on_order(self, payload: dict) -> None:
            print(f"Order placed: {payload}")

Singleton loader available as :data:`loader` (uses the default plugin dir).
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .event_bus import EventBus
from .workspace import WorkspaceStateMigrationError, plugins_dir, workspace_dir

logger = logging.getLogger("flinttrade.core.plugin_loader")


# ---------------------------------------------------------------------------
# Public interface types
# ---------------------------------------------------------------------------


class PluginInterface(ABC):
    """Base class all plugins must subclass.

    Class-level attributes ``name``, ``version``, and ``description`` are
    required; the loader validates their presence on discovery.
    """

    name: str
    version: str
    description: str

    @abstractmethod
    def activate(self, context: "PluginContext") -> None:
        """Called once when the plugin is activated.

        Args:
            context: Dependency-injection bag providing access to the event
                bus, order router, and raw configuration.
        """

    @abstractmethod
    def deactivate(self) -> None:
        """Called once when the plugin is deactivated or unloaded.

        Must clean up any subscriptions or resources acquired in
        :meth:`activate`.
        """


@dataclass
class PluginContext:
    """Dependency-injection container passed to :meth:`PluginInterface.activate`.

    Args:
        event_bus: Shared :class:`~flinttrade_core.event_bus.EventBus`
            instance.
        order_router: Order routing facade (typed ``Any`` to avoid a circular
            import; the engine package supplies the real object).
        config: Arbitrary key/value config dict (from workspace.json slice or
            caller-supplied overrides).
    """

    event_bus: EventBus
    order_router: Any  # OrderRouter — engine package; avoid circular import
    config: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal state record
# ---------------------------------------------------------------------------


@dataclass
class _PluginRecord:
    name: str
    path: Path
    module_name: str
    instance: PluginInterface
    active: bool = False


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class PluginError(Exception):
    """Raised when a plugin cannot be discovered, loaded, or activated."""


# ---------------------------------------------------------------------------
# PluginLoader
# ---------------------------------------------------------------------------


class PluginLoader:
    """Discovers and manages user plugins from a directory.

    Plugins are ``*.py`` files that contain a class named ``Plugin``
    inheriting from :class:`PluginInterface`.  Each file maps to one plugin;
    the plugin's ``name`` attribute is the canonical identifier used in all
    public methods.

    Thread safety: all mutable state is protected by a reentrant lock so that
    :meth:`reload` can safely call :meth:`deactivate` → :meth:`load` →
    :meth:`activate` in a single lock scope.

    Args:
        plugin_dir: Directory to scan.  Defaults to ``plugins/`` inside the
            platform workspace (:func:`flinttrade_core.workspace.plugins_dir`)
            when omitted, which also migrates a legacy ``~/.flinttrade/plugins``
            directory once on macOS and Windows.
        context: :class:`PluginContext` passed to each plugin on activation.

    Example::

        loader = PluginLoader(Path("/tmp/my_plugins"), context)
        names = loader.discover()
        for n in names:
            loader.load(n)
            loader.activate(n)
        print(loader.list_loaded())
    """

    def __init__(
        self,
        plugin_dir: Path | None = None,
        context: PluginContext | None = None,
    ) -> None:
        if plugin_dir is None:
            # plugins_dir() copies a legacy ~/.flinttrade/plugins tree into the
            # platform workspace once. A migration that cannot complete must not
            # take the whole loader — and therefore the backend — down with it:
            # the operator's plugins are still safe in the legacy directory, and
            # a loud log plus an empty scan is recoverable, while an exception
            # raised from a constructor at import time is not.
            try:
                plugin_dir = plugins_dir()
            except WorkspaceStateMigrationError:
                logger.exception("PluginLoader: could not migrate the legacy plugin directory")
                plugin_dir = workspace_dir() / "plugins"
        self._plugin_dir = plugin_dir
        self._context = context or PluginContext(
            event_bus=EventBus(),
            order_router=None,
        )
        self._records: dict[str, _PluginRecord] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self) -> list[str]:
        """Scan ``plugin_dir`` for valid plugin files.

        A file is valid when it is a ``*.py`` file (not ``__init__.py``) that
        contains a class named ``Plugin`` with the required ``name``,
        ``version``, and ``description`` class attributes.

        Returns:
            Sorted list of plugin *name* strings found (as declared in the
            ``Plugin.name`` attribute, not the file stem).

        Raises:
            Nothing — malformed files are logged and skipped.
        """
        found: list[str] = []

        if not self._plugin_dir.exists():
            logger.debug("PluginLoader: plugin_dir %s does not exist", self._plugin_dir)
            return found

        for py_file in sorted(self._plugin_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                plugin_class = self._load_class_from_file(py_file)
                self._validate_class(plugin_class, py_file)
                found.append(plugin_class.name)
                logger.debug("PluginLoader: discovered '%s' in %s", plugin_class.name, py_file)
            except PluginError as exc:
                logger.warning("PluginLoader: skipping %s — %s", py_file.name, exc)
            except Exception:
                logger.exception("PluginLoader: unexpected error reading %s", py_file.name)

        return found

    # ------------------------------------------------------------------
    # Load / Unload
    # ------------------------------------------------------------------

    def load(self, name: str) -> PluginInterface:
        """Import and instantiate the plugin identified by *name*.

        Searches ``plugin_dir`` for a ``*.py`` file whose ``Plugin.name``
        attribute matches *name*.

        Args:
            name: Plugin name as declared in ``Plugin.name``.

        Returns:
            The instantiated (but not yet activated) :class:`PluginInterface`.

        Raises:
            PluginError: When the plugin file cannot be found or the class
                fails to instantiate.
        """
        with self._lock:
            py_file = self._find_file_for_name(name)
            module_name = f"_flinttrade_plugin_{py_file.stem}"

            try:
                plugin_class = self._load_class_from_file(py_file)
                self._validate_class(plugin_class, py_file)
                instance = plugin_class()
            except PluginError:
                raise
            except Exception as exc:
                raise PluginError(f"Failed to instantiate plugin '{name}': {exc}") from exc

            record = _PluginRecord(
                name=name,
                path=py_file,
                module_name=module_name,
                instance=instance,
                active=False,
            )
            self._records[name] = record
            logger.info("PluginLoader: loaded '%s'", name)
            return instance

    # ------------------------------------------------------------------
    # Activate / Deactivate
    # ------------------------------------------------------------------

    def activate(self, name: str) -> None:
        """Call ``plugin.activate(context)`` for a loaded plugin.

        Args:
            name: Plugin name.

        Raises:
            PluginError: When the plugin is not loaded or activation raises.
        """
        with self._lock:
            record = self._get_record(name)
            if record.active:
                logger.debug("PluginLoader: '%s' already active", name)
                return
            try:
                record.instance.activate(self._context)
                record.active = True
                logger.info("PluginLoader: activated '%s'", name)
            except Exception as exc:
                raise PluginError(f"Plugin '{name}' raised during activate(): {exc}") from exc

    def deactivate(self, name: str) -> None:
        """Call ``plugin.deactivate()`` and mark the plugin inactive.

        Args:
            name: Plugin name.

        Raises:
            PluginError: When the plugin is not loaded or deactivation raises.
        """
        with self._lock:
            record = self._get_record(name)
            if not record.active:
                logger.debug("PluginLoader: '%s' already inactive", name)
                return
            try:
                record.instance.deactivate()
                record.active = False
                logger.info("PluginLoader: deactivated '%s'", name)
            except Exception as exc:
                raise PluginError(f"Plugin '{name}' raised during deactivate(): {exc}") from exc

    # ------------------------------------------------------------------
    # Hot reload
    # ------------------------------------------------------------------

    def reload(self, name: str) -> None:
        """Hot-reload a plugin: deactivate → re-import module → activate.

        Useful during development or when a user has edited a plugin file
        without restarting FlintTrade.

        Args:
            name: Plugin name.

        Raises:
            PluginError: When deactivation, re-import, or re-activation fails.
        """
        with self._lock:
            record = self._get_record(name)

            # Deactivate if active
            if record.active:
                self.deactivate(name)

            # Evict old module from sys.modules so importlib.reload picks up
            # the file changes.
            old_module = sys.modules.pop(record.module_name, None)

            # Invalidate importlib's path cache so it picks up file changes on
            # fast file systems where the mtime may not have advanced.
            importlib.invalidate_caches()

            # Re-load from file
            try:
                plugin_class = self._load_class_from_file(record.path)
                self._validate_class(plugin_class, record.path)
                instance = plugin_class()
                record.instance = instance
                logger.info("PluginLoader: reloaded module for '%s'", name)
            except Exception as exc:
                # Restore old module if available so the system stays consistent.
                if old_module is not None:
                    sys.modules[record.module_name] = old_module
                raise PluginError(f"Plugin '{name}' failed to reload: {exc}") from exc

            # Re-activate
            self.activate(name)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_loaded(self) -> list[dict[str, Any]]:
        """Return metadata for all currently loaded plugins.

        Returns:
            List of dicts with keys: ``name``, ``version``, ``description``,
            ``active``, ``path``.
        """
        with self._lock:
            return [
                {
                    "name": r.name,
                    "version": r.instance.version,
                    "description": r.instance.description,
                    "active": r.active,
                    "path": str(r.path),
                }
                for r in self._records.values()
            ]

    @property
    def plugin_dir(self) -> Path:
        """The directory this loader scans for plugins."""
        return self._plugin_dir

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_class_from_file(self, py_file: Path) -> type[PluginInterface]:
        """Import *py_file* and return the ``Plugin`` class it defines.

        Source is compiled directly from the file's raw bytes, bypassing
        Python's ``.pyc`` bytecode cache.  This guarantees that hot-reload
        always picks up the current contents of the file even when the mtime
        has not advanced (e.g. two writes within the same second on Windows).
        """
        module_name = f"_flinttrade_plugin_{py_file.stem}"
        # Always evict stale module first.
        sys.modules.pop(module_name, None)

        try:
            source = py_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise PluginError(f"Cannot read {py_file}: {exc}") from exc

        try:
            code = compile(source, str(py_file), "exec")
        except SyntaxError as exc:
            raise PluginError(f"Syntax error in {py_file.name}: {exc}") from exc

        module = importlib.util.module_from_spec(
            importlib.util.spec_from_loader(module_name, loader=None)  # type: ignore[arg-type]
        )
        module.__file__ = str(py_file)
        module.__loader__ = None  # type: ignore[assignment]
        sys.modules[module_name] = module

        try:
            exec(code, module.__dict__)  # noqa: S102
        except Exception as exc:
            sys.modules.pop(module_name, None)
            raise PluginError(f"Error executing {py_file.name}: {exc}") from exc

        plugin_class = getattr(module, "Plugin", None)
        if plugin_class is None:
            raise PluginError(f"{py_file.name} has no 'Plugin' class")
        return plugin_class  # type: ignore[return-value]

    @staticmethod
    def _validate_class(cls: type, py_file: Path) -> None:
        """Validate that *cls* is a proper PluginInterface subclass."""
        if not (isinstance(cls, type) and issubclass(cls, PluginInterface)):
            raise PluginError(
                f"{py_file.name}: Plugin does not inherit from PluginInterface"
            )
        for attr in ("name", "version", "description"):
            if not isinstance(getattr(cls, attr, None), str):
                raise PluginError(
                    f"{py_file.name}: Plugin.{attr} must be a str class attribute"
                )

    def _find_file_for_name(self, name: str) -> Path:
        """Locate the ``*.py`` file whose ``Plugin.name == name``."""
        if not self._plugin_dir.exists():
            raise PluginError(
                f"Plugin directory {self._plugin_dir} does not exist"
            )
        for py_file in self._plugin_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            try:
                plugin_class = self._load_class_from_file(py_file)
                if getattr(plugin_class, "name", None) == name:
                    return py_file
            except PluginError:
                continue
        raise PluginError(f"No plugin named '{name}' found in {self._plugin_dir}")

    def _get_record(self, name: str) -> _PluginRecord:
        record = self._records.get(name)
        if record is None:
            raise PluginError(f"Plugin '{name}' is not loaded")
        return record
