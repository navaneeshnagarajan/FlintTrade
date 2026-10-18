"""Documentation obligations on the two newly exposed exact-read APIs."""
from __future__ import annotations

import inspect

import pytest

from flinttrade_core.model_run_config import ModelRunConfiguration, exact_control

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("function", [ModelRunConfiguration.selector, exact_control])
def test_exact_configuration_public_apis_document_their_contract(function: object) -> None:
    """The public projection and authenticated route need truthful docstrings."""
    assert inspect.getdoc(function)
