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

Also rebinds the ``AuthState`` singleton at session-scope to a tmp DuckDB so
that engine tests that mint or decode FlintTrade JWTs (e.g. test_mode_guard)
never touch the developer's real ``~/.flinttrade/auth_state.duckdb`` and
never collide with a backend instance that may already hold the file lock.
Mirrors the autouse fixture in ``packages/core/tests/conftest.py``.
"""

from __future__ import annotations

import sys

import pytest


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


@pytest.fixture(autouse=True)
def _isolated_auth_state(tmp_path_factory):
    """Point AuthState at a per-test DuckDB so JWT revocation state is fresh.

    Engine tests that decode JWTs go through
    :func:`packages.core.src.auth_routes.decode_token`, which consults
    :func:`packages.core.src.auth_state.get_auth_state` to check the JTI
    revocation blocklist. Without isolation, that touches
    ``~/.flinttrade/auth_state.duckdb`` — mutating real state and
    potentially racing the backend's DuckDB lock. Rebinding the
    singleton to a tmp DuckDB makes engine JWT tests hermetic.
    """
    from packages.core.src import auth_state as auth_state_mod

    auth_state_mod.reset_singleton_for_tests()
    db_dir = tmp_path_factory.mktemp("engine_auth_state")
    auth_state_mod.get_auth_state(db_path=db_dir / "auth_state.duckdb")
    yield
    auth_state_mod.reset_singleton_for_tests()
