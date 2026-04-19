"""Shared fixtures for packages/core tests.

The ``AuthState`` singleton persists a DuckDB file at
``~/.flinttrade/auth_state.duckdb`` by default, which causes test
isolation failures: OTP request counts and JWT revocations from one
test leak into the next, flipping rate-limit assertions non-
deterministically.

The autouse fixture below rebinds the singleton to a throw-away
DuckDB under the pytest ``tmp_path`` so every test starts with an
empty state store and finishes without side effects. Tests that want
a custom binding can still call ``reset_singleton_for_tests()`` and
``get_auth_state(db_path=...)`` themselves.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_auth_state(tmp_path_factory):
    """Point AuthState at a per-test DuckDB so OTP/JWT state is fresh."""
    from packages.core.src import auth_state as auth_state_mod

    auth_state_mod.reset_singleton_for_tests()
    db_dir = tmp_path_factory.mktemp("auth_state")
    auth_state_mod.get_auth_state(db_path=db_dir / "auth_state.duckdb")
    yield
    auth_state_mod.reset_singleton_for_tests()
