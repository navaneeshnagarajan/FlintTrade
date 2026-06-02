"""Supply-chain helper script behaviour tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_generate_sbom_help_does_not_write_default_file(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate-sbom.py"), "--help"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--output" in result.stdout
    assert not (tmp_path / "sbom.json").exists()


def test_generate_sbom_check_passes_for_current_output(tmp_path: Path) -> None:
    script = ROOT / "scripts" / "generate-sbom.py"

    subprocess.run(
        [sys.executable, str(script), "--output", "sbom.json"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
    )
    result = subprocess.run(
        [sys.executable, str(script), "--check", "--output", "sbom.json"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "up to date" in result.stdout
