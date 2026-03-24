"""Shared fixtures for gateway tests."""
import pytest
from pathlib import Path


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Temporary database path for tests."""
    return tmp_path / "test.db"


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to test fixtures directory."""
    return Path(__file__).parent / "fixtures"
