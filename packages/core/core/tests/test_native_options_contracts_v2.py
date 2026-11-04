"""Synthetic approved options policy transport; never qualification."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from flinttrade_core import native_autonomy_contracts_v2 as contracts

pytestmark = pytest.mark.unit


def policy_payload() -> dict[str, object]:
    """Build an explicit synthetic options policy with no implicit limits.

    Returns:
        A complete JSON-compatible synthetic policy.
    """
    return {
        "profile_version": "index_options_v1",
        "policy_ref": {"id": "options-policy", "revision": "a" * 64},
        "capital_basis": "non_replenishing_long_premium_short_standalone_margin_plus_fees",
        "exposure_basis": "gross_underlying_notional_no_cross_contract_netting_plus_liabilities",
        "loss_basis": "run_lifetime_net_realised_plus_unrealised_after_fees",
        "threshold_action": "latch_entry_retirement_and_broker_held_or_handback",
        "capital_cap": {"amount": "1000000", "currency": "INR"},
        "exposure_cap": {"amount": "10000000", "currency": "INR"},
        "loss_action_threshold": {"amount": "1000", "currency": "INR"},
        "max_mark_age_ms": 100,
        "fee_policy_ref": {"id": "options-fees", "revision": "b" * 64},
    }


def test_approved_derivative_policy_is_distinct_from_cash() -> None:
    """Verify approved derivative policy is distinct from cash."""
    # RED exercises the incumbent decoder rather than failing at module import.
    model = getattr(contracts, "OptionsRiskPolicyV2", contracts.RiskPolicyV2)
    value = policy_payload()
    assert model.model_validate(value).model_dump(mode="json") == value
    assert model.model_validate_json(json.dumps(value)).model_dump(mode="json") == value
    with pytest.raises(ValidationError):
        contracts.RiskPolicyV2.model_validate(value)


@pytest.mark.parametrize(
    "field", ["capital_cap", "exposure_cap", "loss_action_threshold", "max_mark_age_ms", "profile_version"]
)
def test_options_policy_has_no_implicit_defaults(field: str) -> None:
    """Verify options policy has no implicit defaults.

    Args:
        field: Policy field or contract key under test.
    """
    value = policy_payload()
    del value[field]
    with pytest.raises(ValidationError):
        contracts.OptionsRiskPolicyV2.model_validate(value)


def test_options_currency_must_agree() -> None:
    """Verify options currency must agree."""
    value = policy_payload()
    value["exposure_cap"]["currency"] = "USD"
    with pytest.raises(ValidationError):
        contracts.OptionsRiskPolicyV2.model_validate(value)


def test_options_configuration_uses_a_separate_versioned_decoder() -> None:
    """Verify options configuration uses a separate versioned decoder."""
    corpus = json.loads((Path(__file__).parent / "fixtures/native-autonomy-v2.json").read_text())
    old = next(c["value"] for c in corpus["cases"] if c["id"] == "ConfigureRequestV2-positive")
    value = {**old, "schema_version": "2-options-1", "config": {**old["config"], "risk": policy_payload()}}
    model = getattr(contracts, "OptionsConfigureRequestV2", contracts.ConfigureRequestV2)
    assert model.model_validate(value).model_dump(mode="json") == value
    with pytest.raises(ValidationError):
        contracts.ConfigureRequestV2.model_validate(value)


def test_options_generator_emits_audited_policy() -> None:
    """Verify options generator emits audited policy."""
    import importlib.util

    path = Path(__file__).resolve().parents[4] / "scripts/generate-native-autonomy-v2-contracts.py"
    spec = importlib.util.spec_from_file_location("options_generator", path)
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    document = generator.schema_document()
    assert document["$defs"]["OptionsRiskPolicyV2"]["x-v2-refinement"] == "options_risk_currency"
    assert "export const OptionsRiskPolicyV2Schema" in generator.render_zod(document)


CORPUS = json.loads((Path(__file__).parent / "fixtures/native-options-v2.json").read_text())


@pytest.mark.parametrize("case", CORPUS["cases"], ids=lambda case: case["id"])
def test_options_portable_contract_case(case: dict[str, object]) -> None:
    """Verify options portable contract case.

    Args:
        case: Portable positive or negative contract case.
    """
    # Initial RED uses incumbent decoders; final runs use the separate options types.
    model = getattr(contracts, case["model"], getattr(contracts, case["model"].removeprefix("Options")))
    for parse in (model.model_validate, lambda v: model.model_validate_json(json.dumps(v))):
        if case["valid"]:
            assert parse(case["value"]).model_dump(mode="json") == case["value"]
        else:
            with pytest.raises(ValidationError):
                parse(case["value"])


@pytest.mark.parametrize("name", ["NativeRunConfigV2", "EntryGrantV2", "RunViewV2"])
def test_cash_decoder_cannot_accept_options_model_instances(name: str) -> None:
    """Verify cash decoder cannot accept options model instances.

    Args:
        name: Synthetic reference or nominal model name.
    """
    value = next(c["value"] for c in CORPUS["cases"] if c["id"] == "options-" + name + "-positive")
    option = getattr(contracts, "Options" + name).model_validate(value)
    with pytest.raises(ValidationError):
        getattr(contracts, name).model_validate(option)


@pytest.mark.parametrize("check", [False, True], ids=["write", "check"])
def test_options_fixture_divergence_refuses_without_partial_writes(tmp_path: Path, check: bool) -> None:
    """Verify options fixture divergence refuses without partial writes.

    Args:
        tmp_path: Disposable generator workspace.
        check: Use read-only check mode when true.
    """
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[4]
    script = tmp_path / "scripts/generate-native-autonomy-v2-contracts.py"
    script.parent.mkdir()
    script.write_bytes((root / "scripts/generate-native-autonomy-v2-contracts.py").read_bytes())
    for name in ("native-autonomy-v2.json", "native-options-v2.json"):
        for folder in ("packages/core/core/tests/fixtures", "packages/apps/terminal/src/generated/__tests__/fixtures"):
            target = tmp_path / folder / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((root / folder / name).read_bytes())
    command = [sys.executable, "-B", str(script)]
    assert subprocess.run(command, capture_output=True).returncode == 0

    def snapshot():
        return {
            p.relative_to(tmp_path).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in tmp_path.rglob("*")
            if p.is_file()
        }

    clean = snapshot()
    assert subprocess.run([*command, "--check"], capture_output=True).returncode == 0
    assert snapshot() == clean
    target = tmp_path / "packages/apps/terminal/src/generated/__tests__/fixtures/native-options-v2.json"
    target.write_bytes(target.read_bytes() + b"\n")
    divergent = snapshot()
    result = subprocess.run(command + (["--check"] if check else []), capture_output=True, text=True)
    assert result.returncode == 1 and "Fixture projection differs" in result.stdout + result.stderr
    assert snapshot() == divergent
