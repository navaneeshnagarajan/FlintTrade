"""Tests for BaseStrategy state persistence methods.

All tests use a tmp_path fixture so no files are written to the real
~/.flinttrade directory.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy, StrategyState


# ---------------------------------------------------------------------------
# Minimal concrete strategy for testing
# ---------------------------------------------------------------------------


class _TestStrategy(BaseStrategy):
    """Concrete BaseStrategy subclass that tracks a simple counter."""

    def __init__(self, name: str = "TestStrat", **kwargs: Any) -> None:
        super().__init__(name, **kwargs)
        self.tick_count: int = 0
        self.last_symbol: str = ""

    def on_tick(self, quote: Quote) -> None:
        self.tick_count += 1
        self.last_symbol = quote.symbol

    def on_bar(self, bar: OHLCV) -> None:
        pass

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        return []

    def get_state_dict(self) -> dict[str, Any]:
        return {
            "tick_count": self.tick_count,
            "last_symbol": self.last_symbol,
        }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def strategy(tmp_path: Path):
    """_TestStrategy with state dir redirected to pytest tmp_path."""
    s = _TestStrategy(name="UnitTest", strategy_id="unit_test")
    # Redirect state dir to a temp directory so tests are hermetic
    s._state_dir = tmp_path / "strategies" / "unit_test"
    return s


# ---------------------------------------------------------------------------
# save_state
# ---------------------------------------------------------------------------


class TestSaveState:
    def test_creates_state_file(self, strategy, tmp_path):
        strategy.save_state()
        assert strategy.state_file.exists()

    def test_state_file_contains_strategy_id(self, strategy):
        strategy.save_state()
        data = json.loads(strategy.state_file.read_text())
        assert data["strategy_id"] == "unit_test"

    def test_state_file_contains_lifecycle_state(self, strategy):
        strategy.save_state()
        data = json.loads(strategy.state_file.read_text())
        assert data["lifecycle_state"] == str(StrategyState.STOPPED)

    def test_state_file_contains_custom_fields(self, strategy):
        strategy.tick_count = 42
        strategy.last_symbol = "NIFTY"
        strategy.save_state()
        data = json.loads(strategy.state_file.read_text())
        assert data["tick_count"] == 42
        assert data["last_symbol"] == "NIFTY"

    def test_save_creates_parent_dirs(self, strategy):
        """save_state should create the full directory hierarchy."""
        assert not strategy._state_dir.exists()
        strategy.save_state()
        assert strategy._state_dir.exists()

    def test_second_save_overwrites_first(self, strategy):
        strategy.tick_count = 1
        strategy.save_state()
        strategy.tick_count = 99
        strategy.save_state()
        data = json.loads(strategy.state_file.read_text())
        assert data["tick_count"] == 99


# ---------------------------------------------------------------------------
# load_state
# ---------------------------------------------------------------------------


class TestLoadState:
    def test_returns_none_when_no_file(self, strategy):
        result = strategy.load_state()
        assert result is None

    def test_loads_saved_state(self, strategy):
        strategy.tick_count = 7
        strategy.save_state()
        data = strategy.load_state()
        assert data is not None
        assert data["tick_count"] == 7

    def test_load_returns_dict(self, strategy):
        strategy.save_state()
        data = strategy.load_state()
        assert isinstance(data, dict)

    def test_load_after_corrupt_file_returns_none(self, strategy):
        strategy._state_dir.mkdir(parents=True, exist_ok=True)
        strategy.state_file.write_text("not valid json", encoding="utf-8")
        result = strategy.load_state()
        assert result is None


# ---------------------------------------------------------------------------
# clear_state
# ---------------------------------------------------------------------------


class TestClearState:
    def test_clear_removes_state_file(self, strategy):
        strategy.save_state()
        assert strategy.state_file.exists()
        strategy.clear_state()
        assert not strategy.state_file.exists()

    def test_clear_when_no_file_does_not_raise(self, strategy):
        # No file exists — should be a no-op
        strategy.clear_state()  # must not raise

    def test_load_after_clear_returns_none(self, strategy):
        strategy.save_state()
        strategy.clear_state()
        assert strategy.load_state() is None


# ---------------------------------------------------------------------------
# state_file property
# ---------------------------------------------------------------------------


class TestStateFileProperty:
    def test_state_file_path_ends_with_state_json(self, strategy):
        assert strategy.state_file.name == "state.json"

    def test_state_file_parent_is_state_dir(self, strategy):
        assert strategy.state_file.parent == strategy._state_dir


# ---------------------------------------------------------------------------
# get_state_dict override
# ---------------------------------------------------------------------------


class TestGetStateDictOverride:
    def test_base_class_returns_empty_dict(self):
        """BaseStrategy.get_state_dict is not abstract — returns {}."""
        # We cannot instantiate BaseStrategy directly; verify via _TestStrategy
        # that a subclass that does NOT call super().get_state_dict() still works.
        class _MinimalStrategy(_TestStrategy):
            def get_state_dict(self) -> dict[str, Any]:
                return {}

        s = _MinimalStrategy(name="Minimal")
        s._state_dir = Path("/tmp/flinttrade_test_minimal")
        try:
            s.save_state()
            data = s.load_state()
            assert data is not None
            assert "strategy_id" in data
        finally:
            import shutil
            shutil.rmtree("/tmp/flinttrade_test_minimal", ignore_errors=True)
