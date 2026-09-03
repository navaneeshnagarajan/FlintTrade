"""Regression coverage for the generated terminal service-profile projection."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from flinttrade_core.llm_provider_profiles import LLM_PROVIDER_PROFILES


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts" / "generate-terminal-service-profiles.py"
OUTPUT = ROOT / "packages" / "apps" / "terminal" / "src" / "generated" / "serviceProviders.ts"


def test_terminal_profile_projection_is_current_and_reproducible() -> None:
    """The checked-in terminal data is an exact deterministic core projection."""
    assert GENERATOR.is_file(), "terminal service-profile generator is missing"
    assert OUTPUT.is_file(), "generated terminal service profiles are missing"

    subprocess.run([sys.executable, str(GENERATOR), "--check"], cwd=ROOT, check=True)
    before = OUTPUT.read_bytes()
    subprocess.run([sys.executable, str(GENERATOR)], cwd=ROOT, check=True)
    assert OUTPUT.read_bytes() == before

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
