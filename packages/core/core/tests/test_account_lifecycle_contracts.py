"""Strict neutral account lifecycle values and secret-safe canonical codecs."""

import importlib
import importlib.util
import json
import pickle
from dataclasses import FrozenInstanceError, replace
from uuid import uuid4

import pytest

from flinttrade_core.broker_identity import BrokerSelector, CredentialVersion
from flinttrade_core.workspace_migrations import BrokerWorkspaceVersion, WorkspaceVersion


def contracts():
    name = "flinttrade_core.account_lifecycle_contracts"
    assert importlib.util.find_spec(name) is not None, "account lifecycle contracts are missing"
    return importlib.import_module(name)


def request(**changes):
    c = contracts()
    identity = uuid4()
    selector = BrokerSelector("dhan", "Synthetic")
    values = dict(
        operation_id=uuid4(),
        kind=c.AccountMutationKind.CONNECT,
        selector=selector,
        actor=c.AccountActorContext("synthetic-user", "session:" + "a" * 64),
        expected_workspace=WorkspaceVersion(identity, 1),
        expected_broker_workspace=BrokerWorkspaceVersion(identity, 1),
        expected_credential=CredentialVersion(selector, uuid4(), 0),
        broker="dhan",
        label="Synthetic",
        credentials={"token": "PRIVATE-token", "nested": ["PRIVATE-value"]},
    )
    values.update(changes)
    return c.AccountMutationRequest(**values)


def test_request_copies_freezes_and_redacts_private_payload():
    source = {"token": "PRIVATE-token", "nested": ["original"]}
    value = request(credentials=source)
    source["nested"].append("mutation")
    assert value.credentials["nested"] == ("original",)
    assert "PRIVATE" not in repr(value)
    with pytest.raises(TypeError):
        value.credentials["token"] = "changed"
    with pytest.raises((TypeError, pickle.PicklingError)):
        pickle.dumps(value)
    with pytest.raises(FrozenInstanceError):
        value.label = "changed"


@pytest.mark.parametrize(
    "field,value",
    [
        ("operation_id", "private-uuid"),
        ("kind", "connect"),
        ("actor", "PRIVATE-actor"),
        ("broker", "other"),
        ("label", 1),
        ("data_roles", ["quotes"]),
        ("credentials", {"value": float("nan")}),
        ("credentials", {1: "PRIVATE"}),
        ("credentials", {"secret": "x" * 65536}),
    ],
)
def test_request_rejects_noncanonical_values_without_echo(field, value):
    with pytest.raises(ValueError) as caught:
        request(**{field: value})
    assert "PRIVATE" not in str(caught.value)


def test_request_validates_nested_versions_and_remove_shape():
    c = contracts()
    base = request()
    for value in (True, -1, 2**63):
        with pytest.raises(ValueError):
            replace(base, expected_workspace=WorkspaceVersion(base.expected_workspace.instance_id, value))
    with pytest.raises(ValueError):
        replace(base, expected_broker_workspace=BrokerWorkspaceVersion(uuid4(), 1))
    with pytest.raises(ValueError):
        replace(base, expected_credential=CredentialVersion(BrokerSelector("dhan", "other"), uuid4(), 0))
    with pytest.raises(ValueError):
        replace(base, kind=c.AccountMutationKind.REMOVE)
    assert replace(base, kind=c.AccountMutationKind.REMOVE, credentials=None).credentials is None


@pytest.mark.parametrize("role", ["ticks", "historical", "option_chains", "quote", "global_indices"])
def test_request_accepts_supported_data_roles(role):
    assert request(data_roles=(role,)).data_roles == (role,)


@pytest.mark.parametrize(
    "roles",
    [
        ("quotes",),
        ("unknown",),
        ("ticks", "ticks"),
        tuple("r" + str(index).zfill(4) + "a" * 56 for index in range(1008)),
    ],
)
def test_request_refuses_unsupported_or_oversized_data_roles(roles):
    with pytest.raises(ValueError, match="account_contract_invalid"):
        request(data_roles=roles)


def test_witness_codec_is_exact_canonical_and_duplicate_safe():
    c = contracts()
    instance = uuid4()
    value = c.BrokerAccountWitness(
        schema=1,
        workspace_instance=instance,
        vault_incarnation=uuid4(),
        operation_id=uuid4(),
        epoch=0,
        before_digest="a" * 64,
        after_digest="a" * 64,
        commit_workspace=WorkspaceVersion(instance, 2),
        commit_broker_workspace=BrokerWorkspaceVersion(instance, 1),
    )
    assert c.BrokerAccountWitness.from_json(value.to_json()) == value
    assert c.BrokerAccountWitness.from_dict(value.to_dict()) == value
    for bad in (
        dict(value.to_dict(), extra=1),
        dict(value.to_dict(), epoch=True),
        dict(value.to_dict(), schema=2),
        dict(value.to_dict(), operation_id=str(uuid4()).upper()),
    ):
        with pytest.raises(ValueError):
            c.BrokerAccountWitness.from_dict(bad)
    duplicate = value.to_json()[:-1] + ',"schema":1}'
    with pytest.raises(ValueError):
        c.BrokerAccountWitness.from_json(duplicate)
    with pytest.raises(ValueError):
        c.BrokerAccountWitness.from_json(json.dumps(value.to_dict(), indent=2))


def test_domain_digest_ignores_marker_unrelated_and_telegram():
    c = contracts()
    source = {"brokers": {"accounts": []}, "dhan": {"host": "http://localhost", "telegram_username": "one"}}
    digest = c.broker_account_digest(source)
    assert c.broker_account_digest(dict(source, _broker_account_store={"epoch": 99}, theme="other")) == digest
    assert (
        c.broker_account_digest(dict(source, dhan={"host": "http://localhost", "telegram_username": "two"})) == digest
    )
    assert c.broker_account_digest(dict(source, brokers={"accounts": ["different"]})) != digest


@pytest.mark.parametrize("attempted,conflicted", [(1, False), (False, 0), (False, True)])
def test_operation_workspace_phase_flags_require_exact_monotonic_booleans(attempted, conflicted):
    c = contracts()
    assert "workspace_attempted" in c.AccountOperationSnapshot.__dataclass_fields__, (
        "workspace phase evidence is missing"
    )
    req = request()
    with pytest.raises(c.AccountContractError):
        c.AccountOperationSnapshot(
            req.operation_id,
            req.selector,
            req.kind,
            req.actor,
            c.AccountOperationStage.PLAN_READY,
            req.expected_workspace,
            req.expected_broker_workspace,
            req.expected_credential,
            before_digest="a" * 64,
            after_digest="b" * 64,
            workspace_attempted=attempted,
            workspace_conflicted=conflicted,
        )


@pytest.mark.parametrize("state", ["admitted", "authentication_started"])
def test_attempted_operation_cannot_have_pre_plan_stage(state):
    c = contracts()
    assert "workspace_attempted" in c.AccountOperationSnapshot.__dataclass_fields__, (
        "workspace phase evidence is missing"
    )
    req = request()
    with pytest.raises(c.AccountContractError):
        c.AccountOperationSnapshot(
            req.operation_id,
            req.selector,
            req.kind,
            req.actor,
            c.AccountOperationStage(state),
            req.expected_workspace,
            req.expected_broker_workspace,
            req.expected_credential,
            workspace_attempted=True,
        )


def test_workspace_attempt_phase_requires_recorded_plan_digests():
    c = contracts()
    req = request()
    with pytest.raises(c.AccountContractError):
        c.AccountOperationSnapshot(
            req.operation_id,
            req.selector,
            req.kind,
            req.actor,
            c.AccountOperationStage.PLAN_READY,
            req.expected_workspace,
            req.expected_broker_workspace,
            req.expected_credential,
            workspace_attempted=True,
        )
