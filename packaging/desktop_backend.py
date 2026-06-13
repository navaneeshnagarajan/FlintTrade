"""PyInstaller entry script for the native-desktop backend sidecar.

This thin wrapper is the ``__main__`` PyInstaller freezes. It exists (rather
than pointing PyInstaller straight at ``flinttrade_core/desktop.py``) so that
the entry runs as a proper package import — ``flinttrade_core.desktop`` uses
relative imports (``from .app import …``) that only resolve when the module is
imported by name, not executed as a loose script.

The real logic lives in :mod:`flinttrade_core.desktop`.
"""

from __future__ import annotations

from flinttrade_core.desktop import main

if __name__ == "__main__":
    main()
