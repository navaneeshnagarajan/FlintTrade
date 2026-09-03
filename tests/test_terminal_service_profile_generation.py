"""Regression coverage for the generated terminal service-profile projection."""

from __future__ import annotations

import importlib.util
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from flinttrade_core.llm_provider_profiles import LLM_PROVIDER_PROFILES


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts" / "generate-terminal-service-profiles.py"
OUTPUT = ROOT / "packages" / "apps" / "terminal" / "src" / "generated" / "serviceProviders.ts"


def _generator_module():
    spec = importlib.util.spec_from_file_location("terminal_service_profile_generator", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_terminal_profile_projection_is_current_and_reproducible(tmp_path: Path) -> None:
    """The checked-in terminal data is an exact deterministic core projection."""
    assert GENERATOR.is_file(), "terminal service-profile generator is missing"
    assert OUTPUT.is_file(), "generated terminal service profiles are missing"

    tracked_before = OUTPUT.stat()
    tracked_bytes = OUTPUT.read_bytes()
    subprocess.run([sys.executable, str(GENERATOR), "--check"], cwd=ROOT, check=True)
    tracked_after = OUTPUT.stat()
    assert OUTPUT.read_bytes() == tracked_bytes
    assert tracked_after.st_ino == tracked_before.st_ino
    assert tracked_after.st_mtime_ns == tracked_before.st_mtime_ns
    assert stat.S_IMODE(tracked_after.st_mode) == stat.S_IMODE(tracked_before.st_mode)

    temporary_output = tmp_path / "serviceProviders.ts"
    subprocess.run(
        [sys.executable, str(GENERATOR), "--output", str(temporary_output)],
        cwd=ROOT,
        check=True,
    )
    before = temporary_output.read_bytes()
    subprocess.run(
        [sys.executable, str(GENERATOR), "--output", str(temporary_output)],
        cwd=ROOT,
        check=True,
    )
    assert temporary_output.read_bytes() == before
    assert stat.S_IMODE(temporary_output.stat().st_mode) == 0o644

    generated = OUTPUT.read_text(encoding="utf-8")
    profile_ids = tuple(profile.provider_id for profile in LLM_PROVIDER_PROFILES)
    assert len(profile_ids) == 14
    assert "nvidia" in profile_ids
    for provider_id in profile_ids:
        assert generated.count(f'"{provider_id}"') == 1
    assert "claude-code-oauth" not in generated

    for source_name in ("LLMSection.tsx", "useSettingsState.ts"):
        source = (ROOT / "packages" / "apps" / "terminal" / "src" / (
            "tools/Settings" if source_name == "LLMSection.tsx" else "hooks"
        ) / source_name).read_text(encoding="utf-8")
        assert "type LlmProvider = LlmProviderId;" in source
        assert "type LlmProvider =\n" not in source


def test_atomic_generation_failure_preserves_existing_output_and_cleans_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An interrupted replacement cannot corrupt the previous generated projection."""
    module = _generator_module()
    output = tmp_path / "serviceProviders.ts"
    output.write_text("previous projection\n", encoding="utf-8")
    output.chmod(0o640)

    def interrupted_replace(_source: Path, _destination: Path) -> None:
        raise OSError("simulated atomic replacement interruption")

    monkeypatch.setattr(module.os, "replace", interrupted_replace)

    with pytest.raises(OSError, match="simulated atomic replacement interruption"):
        module._atomic_write("replacement projection\n", output)

    assert output.read_text(encoding="utf-8") == "previous projection\n"
    assert stat.S_IMODE(output.stat().st_mode) == 0o640
    assert list(tmp_path.glob(f".{output.name}.*")) == []
