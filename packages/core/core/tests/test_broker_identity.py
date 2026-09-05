"""Exact identity rejects transformations that could select another account."""

import importlib
import uuid

import pytest


def identity():
    assert importlib.util.find_spec("flinttrade_core.broker_identity") is not None
    return importlib.import_module("flinttrade_core.broker_identity")


@pytest.mark.parametrize("account", ["A:b:C", "a.b_@+-9", "A" * 128])
def test_exact_roundtrip_and_path_encoding(account):
    m = identity()
    selector = m.BrokerSelector("dhan", account)
    assert m.parse_broker_selector(m.serialise_broker_selector(selector)) == selector
    assert m.broker_selector_from_path("dhan", account) == selector
    if account == "A:b:C":
        assert m.broker_selector_path_parts(selector) == ("dhan", "A%3Ab%3AC")
    assert m.BrokerSelector("dhan", "A") != m.BrokerSelector("dhan", "a")


@pytest.mark.parametrize(
    "adapter,account",
    [
        ("Dhan", "A"),
        ("", "A"),
        ("a" * 65, "A"),
        ("-a", "A"),
        ("a", ""),
        ("a", "A" * 129),
        ("a", "."),
        ("a", ".."),
        ("a", "_:+-@"),
        ("a", "A/B"),
        ("a", "A\\B"),
        ("a", "A%3AB"),
        ("a", "A%253AB"),
        ("a", " A"),
        ("a", "A "),
        ("a", "A\n"),
        ("a", "A\x00"),
        ("a", "А"),
        ("a", "é"),
        (1, "A"),
        ("a", True),
    ],
)
def test_invalid_identity_is_never_normalised_or_echoed(adapter, account):
    m = identity()
    with pytest.raises(m.BrokerSelectorValidationError) as error:
        m.BrokerSelector(adapter, account)
    assert str(error.value) == "broker_selector_invalid"
    with pytest.raises(m.BrokerSelectorValidationError):
        m.broker_selector_from_path(adapter, account)


def test_resolution_selects_complete_explicit_before_reading_configuration():
    m = identity()
    explicit = m.BrokerSelector("dhan", "A:1")
    assert m.resolve_exact_target("%bad", explicit) == explicit
    assert m.resolve_exact_target("dhan:A:1", None) == explicit
    with pytest.raises(m.BrokerSelectorValidationError):
        m.resolve_exact_target("dhan:A", "dhan:B")
    with pytest.raises(m.BrokerSelectorValidationError):
        m.resolve_exact_target("", None)
    with pytest.raises(m.BrokerTargetRequiredError):
        m.resolve_exact_target(None, None)


@pytest.mark.parametrize("generation", [True, False, -1, 2**63, 1.0, "1"])
def test_version_rejects_coerced_or_out_of_range_generations(generation):
    m = identity()
    with pytest.raises(m.BrokerSelectorValidationError):
        m.CredentialVersion(m.BrokerSelector("dhan", "A"), uuid.uuid4(), generation)


def test_version_requires_uuid4_object_and_is_frozen():
    m = identity()
    selector, incarnation = m.BrokerSelector("dhan", "A"), uuid.uuid4()
    version = m.CredentialVersion(selector, incarnation, 0)
    assert version.vault_incarnation is incarnation
    for bad in (str(incarnation), uuid.uuid1(), uuid.UUID(int=0)):
        with pytest.raises(m.BrokerSelectorValidationError):
            m.CredentialVersion(selector, bad, 1)
    with pytest.raises(AttributeError):
        version.generation = 1
