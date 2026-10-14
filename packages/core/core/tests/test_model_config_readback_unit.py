"""Pure exact-selector contract; no normalisation or authority lookup."""
import pytest

from flinttrade_core.model_run_config import ModelRunConfiguration

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("action,value,expected", [
    ("learning-rights", {"subject": "source"}, {"action": "learning-rights", "subject": "source"}),
    ("learning-rights", {"subject": "output"}, {"action": "learning-rights", "subject": "output"}),
    ("candidate", {"candidate": "trial:one"}, {"action": "candidate", "trial": "trial:one"}),
    ("evaluation", {"trial": "trial:one", "suite": "suite:one"}, {"action": "evaluation", "trial": "trial:one", "suite": "suite:one"}),
    ("training-backend", {"connection_id": "00000000-0000-4000-8000-000000000041"}, {"action": "training-backend", "connection_id": "00000000-0000-4000-8000-000000000041"}),
])
def test_exact_selector_preserves_identifiers(action, value, expected):
    selected = ModelRunConfiguration.selector(action, value)
    assert selected == expected
    ModelRunConfiguration._validate_selector("run:one", selected)


@pytest.mark.parametrize("selected", [
    {}, {"action": "candidate", "trial": " trial"}, {"action": "evaluation", "trial": "trial", "suite": "suite\n"},
    {"action": "learning-rights", "subject": "SOURCE"}, {"action": "learning-rights", "subject": "source", "actor": "foreign"},
    {"action": "training-backend", "connection_id": "00000000000040008000000000000041"},
    {"action": "training-backend", "connection_id": "AAAAAAAA-0000-4000-8000-000000000041"},
])
def test_exact_selector_rejects_malformed_without_repair(selected):
    with pytest.raises((ValueError, TypeError)):
        ModelRunConfiguration._validate_selector("run:one", selected)
