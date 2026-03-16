"""Tests for automation."""
import os

def test_package_exists():
    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert os.path.exists(os.path.join(pkg_dir, "src", "__init__.py"))
    assert os.path.exists(os.path.join(pkg_dir, "CLAUDE.md"))
    assert os.path.exists(os.path.join(pkg_dir, "AGENTS.md"))
