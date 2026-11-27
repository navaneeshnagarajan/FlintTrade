"""Synthetic transport examples; neither qualification nor authority."""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from flinttrade_core import native_autonomy_contracts_v2 as contracts

from flinttrade_core.native_autonomy_contracts_v2 import PositiveMoneyV2, RiskPolicyV2


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

pytestmark = pytest.mark.unit


def risk_policy() -> "dict[str, Any]":
    """Build the synthetic transport policy with separate capital, exposure and loss caps.

    Returns:
        Unvalidated JSON policy fields for the contract tests.
    """
    return {
        "policy_ref": {"id": "synthetic-risk", "revision": "a" * 64},
        "capital_basis": "non_replenishing_fee_inclusive_commitments",
        "exposure_basis": "max_entry_cost_fresh_mark_plus_possible_fills_and_exit_fees",
        "loss_basis": "run_lifetime_net_realised_plus_unrealised_after_fees",
        "threshold_action": "latch_entry_retirement_and_broker_held_or_handback",
        "capital_cap": {"amount": "100", "currency": "INR"},
        "exposure_cap": {"amount": "120", "currency": "INR"},
        "loss_action_threshold": {"amount": "10", "currency": "INR"},
        "max_mark_age_ms": 1,
        "fee_policy_ref": {"id": "synthetic-fees", "revision": "b" * 64},
    }


def test_risk_caps_are_one_currency_without_equating_loss_and_capital() -> None:
    """Require one risk currency without conflating capital, exposure and loss caps."""
    assert RiskPolicyV2.model_validate(risk_policy()).loss_action_threshold.amount == "10"
    payload = risk_policy()
    payload["exposure_cap"]["currency"] = "USD"
    with pytest.raises(ValidationError):
        RiskPolicyV2.model_validate(payload)


def test_money_requires_canonical_positive_amount_and_explicit_currency() -> None:
    """Reject noncanonical money and require an explicit currency."""
    assert PositiveMoneyV2.model_validate({"amount": "0.01", "currency": "INR"}).amount == "0.01"
    for amount in ["0", "-1", "01", "1.0", "1e3", "NaN", "1\n", True, 1, 0.1]:
        with pytest.raises(ValidationError):
            PositiveMoneyV2.model_validate({"amount": amount, "currency": "INR"})


CORPUS = json.loads((Path(__file__).parent / "fixtures/native-autonomy-v2.json").read_text())


@pytest.mark.parametrize("case", CORPUS["cases"], ids=lambda case: case["id"])
def test_portable_contract_case(case: "dict[str, Any]") -> None:
    """Apply each labelled portable contract case to its declared validator.

    Args:
        case: Named portable contract case with its schema, input and expected disposition.
    """
    model = getattr(contracts, case["model"])
    if case["valid"]:
        value = model.model_validate(case["value"])
        assert value.model_dump(mode="json") == case["value"]
        assert model.model_validate_json(json.dumps(case["value"])).model_dump(mode="json") == case["value"]
    else:
        with pytest.raises(ValidationError):
            model.model_validate(case["value"])
        with pytest.raises(ValidationError):
            model.model_validate_json(json.dumps(case["value"]))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_json_nonfinite_values_refused(value: "float") -> None:
    """Reject non-finite Python floats rather than treating them as JSON money.

    Args:
        value: Non-finite Python float that JSON-compatible money must reject.
    """
    with pytest.raises(ValidationError):
        PositiveMoneyV2.model_validate({"amount": value, "currency": "INR"})


def test_exact_case_sensitive_identity_roundtrip() -> None:
    """Preserve case-sensitive account identity through contract round-trip."""
    payload = next(c["value"] for c in CORPUS["cases"] if c["id"] == "RunScopeV2-positive")
    assert contracts.RunScopeV2.model_validate(payload).account_id == "AcctA"
    assert contracts.RunScopeV2.model_validate({**payload, "account_id": "accta"}).account_id == "accta"
