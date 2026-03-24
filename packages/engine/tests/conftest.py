"""Engine test configuration.

Pre-initializes the packages.engine.src package before any test fixture runs.
This breaks the circular import chain:
  packages.engine.src.__init__
    → router.py
      → packages.core.src.models
        → packages.core.src.__init__
          → app.py
            → packages.engine.src.router.OrderRouter   (fails: partial init)

By importing packages.engine.src.router directly first (before __init__ runs),
we prime sys.modules so that when app.py tries to import OrderRouter the module
is already fully loaded.
"""

from __future__ import annotations

import sys


def pytest_configure(config) -> None:  # noqa: ANN001
    """Bootstrap engine imports before any test is collected or run.

    Called once at the very start of the pytest session, before any test
    modules are imported or fixtures are set up.
    """
    # Only bootstrap if we haven't already successfully imported the package.
    if "packages.engine.src.router" not in sys.modules:
        try:
            # Import router directly — this triggers the circular chain.
            # However, because pytest_configure runs before any test module
            # is imported, sys.modules is clean and the import succeeds on
            # the first attempt through the standard Python import machinery.
            import packages.engine.src.router  # noqa: F401
        except ImportError:
            # If this fails (e.g. on a fresh session), we still want tests
            # to proceed so pytest can report individual import errors clearly.
            pass
