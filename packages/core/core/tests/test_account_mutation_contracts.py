"""Canonical registry versions reject ambiguous or foreign authority shapes."""

from uuid import UUID, uuid4

import pytest

from flinttrade_core import account_mutation_contracts as contracts
from flinttrade_core.broker_identity import INT64_MAX, BrokerSelector, CredentialVersion
from flinttrade_core.workspace_migrations import BrokerWorkspaceVersion, WorkspaceVersion


@pytest.mark.parametrize("generation,present", [(True, False), (-1, False), (0, True), (INT64_MAX + 1, True), (1, 1)])
def test_registry_version_rejects_invalid_generation_presence(generation, present):
    with pytest.raises(contracts.RegistryVersionValidationError):
        contracts.RegistrySelectorVersion(BrokerSelector("dhan", "Case"), uuid4(), generation, present)


def test_session_version_binds_canonical_selector_and_both_workspace_identities():
    selector = BrokerSelector("dhan", "Case")
    registry = contracts.RegistrySelectorVersion(selector, uuid4(), 1, True)
    credential = CredentialVersion(selector, uuid4(), 1)
    instance = UUID("00000000-0000-0000-0000-000000000001")
    full = WorkspaceVersion(instance, 9)
    broker = BrokerWorkspaceVersion(instance, 2)
    value = contracts.SessionVersion(selector, registry, credential, full, broker)
    assert value.workspace_version.generation == 9
    with pytest.raises(contracts.RegistryVersionValidationError):
        contracts.SessionVersion(selector, registry, credential, full, BrokerWorkspaceVersion(uuid4(), 2))
    with pytest.raises(contracts.RegistryVersionValidationError):
        contracts.SessionVersion(selector, registry, CredentialVersion(selector, uuid4(), 0), full, broker)


def test_conflict_receipt_never_renders_payload():
    receipt = {"sensitive": "secret"}
    error = contracts.RegistryVersionConflict(retirement_receipt=receipt)
    assert error.retirement_receipt is receipt
    assert error.args == ("registry_version_conflict",)
    assert "secret" not in repr(error)
