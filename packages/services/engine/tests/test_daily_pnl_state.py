"""Durability and account-scope tests for Layer 4 daily-loss state."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from flinttrade_engine.daily_pnl_state import DailyPnLStateError, DailyPnLStateStore


def test_opening_capital_is_frozen_and_survives_restart(tmp_path):
    path = tmp_path / "daily-pnl.sqlite"
    first = DailyPnLStateStore(path)
    state = first.resolve(
        selector="dhan:primary",
        session_key="2026-07-13",
        observed_opening_capital=100_000,
    )
    assert state.opening_risk_capital == 100_000

    restarted = DailyPnLStateStore(path)
    restored = restarted.resolve(
        selector="dhan:primary",
        session_key="2026-07-13",
        observed_opening_capital=250_000,
    )
    assert restored.opening_risk_capital == 100_000


def test_operator_configuration_cannot_dilute_a_frozen_session(tmp_path):
    store = DailyPnLStateStore(tmp_path / "daily-pnl.sqlite")
    store.configure(
        selector="openalgo:default",
        session_key="2026-07-13",
        opening_risk_capital=80_000,
    )

    with pytest.raises(DailyPnLStateError, match="already frozen"):
        store.configure(
            selector="openalgo:default",
            session_key="2026-07-13",
            opening_risk_capital=160_000,
        )


def test_latches_are_selector_scoped_and_reset_keeps_capital(tmp_path):
    store = DailyPnLStateStore(tmp_path / "daily-pnl.sqlite")
    for selector in ("dhan:primary", "upstox:primary"):
        store.resolve(
            selector=selector,
            session_key="2026-07-13",
            observed_opening_capital=100_000,
        )

    latched = store.latch(
        selector="dhan:primary",
        session_key="2026-07-13",
        killed=True,
    )
    other = store.get(selector="upstox:primary", session_key="2026-07-13")
    assert latched.killed is True
    assert other is not None and other.killed is False

    reset = store.reset(selector="dhan:primary", session_key="2026-07-13")
    assert reset.killed is False
    assert reset.paused is False
    assert reset.opening_risk_capital == 100_000


def test_new_session_accepts_a_new_opening_capital(tmp_path):
    store = DailyPnLStateStore(tmp_path / "daily-pnl.sqlite")
    store.resolve(
        selector="dhan:primary",
        session_key="2026-07-13",
        observed_opening_capital=100_000,
    )
    next_day = store.resolve(
        selector="dhan:primary",
        session_key="2026-07-14",
        observed_opening_capital=120_000,
    )
    assert next_day.opening_risk_capital == 120_000


def test_concurrent_first_read_freezes_exactly_one_capital(tmp_path):
    store = DailyPnLStateStore(tmp_path / "daily-pnl.sqlite")

    def resolve(capital: float) -> float:
        return store.resolve(
            selector="upstox:primary",
            session_key="2026-07-13",
            observed_opening_capital=capital,
        ).opening_risk_capital

    with ThreadPoolExecutor(max_workers=2) as executor:
        resolved = set(executor.map(resolve, (100_000.0, 200_000.0)))

    assert len(resolved) == 1
    assert resolved <= {100_000.0, 200_000.0}


def test_healthcheck_initialises_a_valid_database(tmp_path):
    store = DailyPnLStateStore(tmp_path / "daily-pnl.sqlite")
    store.healthcheck()
    assert store.list_session(session_key="2026-07-13") == ()
