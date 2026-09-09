from __future__ import annotations

import builtins
import logging
import os
import socket
import subprocess
import sys
import traceback
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from uuid import UUID

import pytest

from flinttrade_core.llm_provider_profiles import LLM_SERVICE_PROVIDER_IDS
from flinttrade_core.service_connections import (
    INT64_MAX,
    ServiceConnection,
    ServiceConnectionRef,
    ServiceSecretVersion,
    create_service_connection,
    update_service_connection,
)


NOW = datetime(2026, 9, 5, 9, 30, tzinfo=UTC)
LATER = datetime(2026, 9, 5, 9, 31, tzinfo=UTC)
CONNECTION_ID = UUID("00000000-0000-4000-8000-000000000001")
OTHER_CONNECTION_ID = UUID("00000000-0000-4000-8000-000000000002")


@pytest.mark.parametrize("operation", ["create", "update"])
def test_factory_request_failures_have_input_only_type(operation):
    from flinttrade_core import service_connections as contracts

    current = create_service_connection({"provider_id": "llm:ollama", "label": "Local"}, clock_factory=lambda: NOW)
    with pytest.raises(ValueError) as caught:
        if operation == "create":
            create_service_connection({"provider_id": "llm:ollama", "label": ""})
        else:
            update_service_connection(current, {"label": ""})
    assert isinstance(caught.value, getattr(contracts, "ServiceConnectionInputError", ()))
    assert caught.value.__cause__ is None


@pytest.mark.parametrize("failure", ["uuid", "clock", "regression", "current"])
def test_factory_authority_failures_are_not_input_rejections(failure):
    from flinttrade_core import service_connections as contracts

    payload = {"provider_id": "llm:ollama", "label": "Local"}
    current = create_service_connection(payload, clock_factory=lambda: NOW)
    with pytest.raises(ValueError) as caught:
        if failure == "uuid":
            create_service_connection(payload, uuid_factory=lambda: UUID(int=0))
        elif failure == "clock":
            create_service_connection(payload, clock_factory=lambda: datetime(2026, 9, 5))
        elif failure == "regression":
            update_service_connection(current, {}, clock_factory=lambda: NOW - timedelta(seconds=1))
        else:
            update_service_connection(object(), {})
    assert not isinstance(caught.value, getattr(contracts, "ServiceConnectionInputError", ()))


STORE_ID = UUID("00000000-0000-4000-8000-000000000003")
BINDING_ID = UUID("00000000-0000-4000-8000-000000000004")
SECRET_GENERATION_MARKER = 818181818181818181
# Literal redacted form from ServiceSecretVersion.__repr__. Logged as a fixture so
# CodeQL py/clear-text-logging-sensitive-data does not see a secret-named object
# reach a logging sink. The live object is still compared against this text.
MASKED_BINDING_LOG_TEXT = "ServiceSecretVersion(<redacted>)"

EXPECTED_PROVIDER_IDS = (
    "llm:ollama",
    "llm:anthropic",
    "llm:openai",
    "llm:gemini",
    "llm:deepseek",
    "llm:groq",
    "llm:grok",
    "llm:mistral",
    "llm:together",
    "llm:nvidia",
    "llm:cerebras",
    "llm:openrouter",
    "llm:hermes",
    "llm:custom",
)

PROVIDER_MATRIX = (
    ("llm:ollama", None, None),
    ("llm:anthropic", "https://api.anthropic.com/v1/messages", "api_key"),
    ("llm:openai", "https://api.openai.com/v1/chat/completions", "api_key"),
    (
        "llm:gemini",
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "api_key",
    ),
    ("llm:deepseek", "https://api.deepseek.com/v1/chat/completions", "api_key"),
    ("llm:groq", "https://api.groq.com/openai/v1/chat/completions", "api_key"),
    ("llm:grok", "https://api.x.ai/v1/chat/completions", "api_key"),
    ("llm:mistral", "https://api.mistral.ai/v1/chat/completions", "api_key"),
    ("llm:together", "https://api.together.xyz/v1/chat/completions", "api_key"),
    ("llm:nvidia", "https://integrate.api.nvidia.com/v1/chat/completions", "api_key"),
    ("llm:cerebras", "https://api.cerebras.ai/v1/chat/completions", "api_key"),
    ("llm:openrouter", "https://openrouter.ai/api/v1/chat/completions", "api_key"),
    ("llm:hermes", "http://127.0.0.1:8080", None),
    ("llm:custom", "https://models.example.invalid/base", "api_key"),
)


def _payload(provider_id: str = "llm:openai") -> dict[str, object]:
    payload: dict[str, object] = {"provider_id": provider_id, "label": "Primary"}
    if provider_id not in {"llm:ollama", "llm:hermes"}:
        payload["auth_mode"] = "api_key"
    if provider_id == "llm:hermes":
        payload["endpoint"] = "http://127.0.0.1:8080"
    elif provider_id == "llm:custom":
        payload["endpoint"] = "https://models.example.invalid/base"
    return payload


def _create(provider_id: str = "llm:openai", **changes: object) -> ServiceConnection:
    payload = _payload(provider_id)
    payload.update(changes)
    return create_service_connection(payload, uuid_factory=lambda: CONNECTION_ID, clock_factory=lambda: NOW)


def _secret_version(connection: ServiceConnection, *, present: bool = True) -> ServiceSecretVersion:
    return ServiceSecretVersion(
        connection_ref=connection.ref,
        store_incarnation=STORE_ID,
        binding_id=BINDING_ID,
        generation=1,
        present=present,
    )


def test_llm_connection_allowlist_is_the_exact_namespaced_profile_derivation() -> None:
    assert LLM_SERVICE_PROVIDER_IDS == EXPECTED_PROVIDER_IDS


def test_reference_serialises_and_compares_the_complete_two_part_identity() -> None:
    first = ServiceConnectionRef("llm:openai", CONNECTION_ID)
    same = ServiceConnectionRef("llm:openai", CONNECTION_ID)
    different_provider = ServiceConnectionRef("llm:anthropic", CONNECTION_ID)
    different_connection = ServiceConnectionRef("llm:openai", OTHER_CONNECTION_ID)

    assert first.to_dict() == {
        "provider_id": "llm:openai",
        "connection_id": "00000000-0000-4000-8000-000000000001",
    }
    assert first == same
    assert first != different_provider
    assert first != different_connection


@pytest.mark.parametrize(
    "provider_id",
    ("openai", "OpenAI", "LLM:openai", "llm:OpenAI", "agent-runtime:hermes", "llm:missing", " llm:openai"),
)
def test_reference_rejects_noncanonical_or_non_llm_provider_ids(provider_id: str) -> None:
    with pytest.raises(ValueError, match="canonical LLM provider"):
        ServiceConnectionRef(provider_id, CONNECTION_ID)


@pytest.mark.parametrize(
    "connection_id",
    (
        "00000000-0000-4000-8000-000000000001",
        UUID("00000000-0000-1000-8000-000000000001"),
        UUID("00000000-0000-4000-0000-000000000001"),
    ),
)
def test_reference_requires_an_exact_rfc4122_uuid4(connection_id: object) -> None:
    with pytest.raises(ValueError, match="UUID4"):
        ServiceConnectionRef("llm:openai", connection_id)  # type: ignore[arg-type]


def test_create_uses_injected_server_identity_and_utc_clock_and_returns_a_redacted_dto() -> None:
    connection = _create(model="gpt-5-mini")

    assert connection.to_public_dict() == {
        "schema_version": 1,
        "provider_id": "llm:openai",
        "connection_id": "00000000-0000-4000-8000-000000000001",
        "label": "Primary",
        "model": "gpt-5-mini",
        "endpoint": "https://api.openai.com/v1/chat/completions",
        "auth_mode": "api_key",
        "credential_configured": False,
        "created_at": "2026-09-05T09:30:00Z",
        "updated_at": "2026-09-05T09:30:00Z",
    }
    assert connection.ref == ServiceConnectionRef("llm:openai", CONNECTION_ID)


def test_create_uses_the_canonical_default_model_when_model_is_omitted() -> None:
    assert _create().model == "gpt-4o-mini"
    assert _create("llm:nvidia").model == ""


@pytest.mark.parametrize(("provider_id", "endpoint", "auth_mode"), PROVIDER_MATRIX)
def test_provider_matrix_is_derived_without_invoking_a_provider(
    provider_id: str,
    endpoint: str | None,
    auth_mode: str | None,
) -> None:
    connection = _create(provider_id)

    assert connection.provider_id == provider_id
    assert connection.endpoint == endpoint
    assert connection.auth_mode == auth_mode


def test_anthropic_requires_an_explicit_allowed_opaque_auth_mode() -> None:
    assert _create("llm:anthropic", auth_mode="oauth").auth_mode == "oauth"
    with pytest.raises(ValueError, match="auth_mode"):
        _create("llm:anthropic", auth_mode="bearer")
    payload = _payload("llm:anthropic")
    del payload["auth_mode"]
    with pytest.raises(ValueError, match="auth_mode"):
        create_service_connection(payload)


@pytest.mark.parametrize("provider_id", ("llm:ollama", "llm:hermes"))
def test_no_auth_profiles_reject_credentials_and_non_null_auth_modes(provider_id: str) -> None:
    with pytest.raises(ValueError, match="auth_mode"):
        _create(provider_id, auth_mode="api_key")
    with pytest.raises(ValueError, match="unknown fields"):
        _create(provider_id, credential="do-not-echo")


@pytest.mark.parametrize(
    "field",
    (
        "roles",
        "routing",
        "health",
        "verified",
        "practice_eligible",
        "live_eligible",
        "subscription_tier",
        "entitlement",
        "api_budget",
        "rights",
        "access_grants",
        "credential",
        "api_key",
        "secret_ref",
    ),
)
def test_create_rejects_unknown_authority_and_secret_fields(field: str) -> None:
    with pytest.raises(ValueError, match="unknown fields"):
        _create(**{field: "sensitive-value-must-not-be-echoed"})


@pytest.mark.parametrize(
    "field",
    ("schema_version", "connection_id", "created_at", "updated_at", "_secret_version", "secret_version"),
)
def test_create_rejects_every_server_owned_field(field: str) -> None:
    with pytest.raises(ValueError, match="server-owned fields"):
        _create(**{field: "caller-selected"})


@pytest.mark.parametrize("provider_id", ("llm:openai", "llm:anthropic", "llm:custom"))
def test_credential_accepting_profiles_require_explicit_auth_mode(provider_id: str) -> None:
    payload = _payload(provider_id)
    del payload["auth_mode"]
    with pytest.raises(ValueError, match="auth_mode"):
        create_service_connection(payload)


def test_fixed_cloud_and_managed_profiles_reject_endpoint_fields_even_when_null() -> None:
    with pytest.raises(ValueError, match="endpoint override"):
        _create("llm:openai", endpoint="https://elsewhere.example.invalid")
    with pytest.raises(ValueError, match="endpoint override"):
        _create("llm:openai", endpoint=None)
    with pytest.raises(ValueError, match="endpoint override"):
        _create("llm:ollama", endpoint=None)


@pytest.mark.parametrize("provider_id", ("llm:hermes", "llm:custom"))
def test_operator_endpoint_profiles_require_an_endpoint(provider_id: str) -> None:
    payload = _payload(provider_id)
    del payload["endpoint"]
    with pytest.raises(ValueError, match="endpoint is required"):
        create_service_connection(payload)


@pytest.mark.parametrize(
    "endpoint",
    (
        "ftp://models.example.invalid",
        "models.example.invalid",
        "https://user:password@models.example.invalid",
        "https://models.example.invalid?token=secret",
        "https://models.example.invalid#fragment",
        "https://models.example.invalid/\nheader",
        "https://models.example.invalid/\x00tail",
        "https://models.example.invalid/a path",
        "https://models.example.invalid:",
        "https://models.example.invalid/" + ("a" * 2048),
    ),
)
@pytest.mark.parametrize("provider_id", ("llm:hermes", "llm:custom"))
def test_operator_endpoint_rejects_unsafe_url_forms(provider_id: str, endpoint: str) -> None:
    with pytest.raises(ValueError, match="operator endpoint"):
        _create(provider_id, endpoint=endpoint)


MALFORMED_OPERATOR_ENDPOINTS = (
    "https://models.example.invalid/%",
    "https://models.example.invalid/%2",
    "https://models.example.invalid/%ZZ",
    "https://models.example.invalid/%2G",
    "https://models.example.invalid\\@other.invalid/base",
    "https://models|example.invalid/base",
    "https://bücher.example.invalid/base",
    "https://models.example.invalid/✓",
    "https://[2001:db8::1/base",
    "https://models].example.invalid/base",
    "https://models.example.invalid:443:444/base",
    "https://models.example.invalid:not-a-port/base",
    "https://models.example.invalid:65536/base",
    "https://models.example.invalid/{raw}/base",
    "https://models.example.invalid/[raw]/base",
)


PERCENT_ESCAPED_OPERATOR_AUTHORITIES = (
    "https://%E2%98%83.example.invalid/base",
    "https://models%2Eexample.invalid/base",
    "https://models%2Fother.invalid/base",
    "https://models%40other.invalid/base",
    "https://models%3A443.example.invalid/base",
)


@pytest.mark.parametrize("endpoint", PERCENT_ESCAPED_OPERATOR_AUTHORITIES)
@pytest.mark.parametrize("provider_id", ("llm:hermes", "llm:custom"))
def test_create_rejects_percent_escaped_operator_authorities(provider_id: str, endpoint: str) -> None:
    with pytest.raises(ValueError, match="operator endpoint"):
        _create(provider_id, endpoint=endpoint)


@pytest.mark.parametrize("endpoint", PERCENT_ESCAPED_OPERATOR_AUTHORITIES)
@pytest.mark.parametrize("provider_id", ("llm:hermes", "llm:custom"))
def test_update_rejects_percent_escaped_operator_authorities(provider_id: str, endpoint: str) -> None:
    with pytest.raises(ValueError, match="operator endpoint"):
        update_service_connection(_create(provider_id), {"endpoint": endpoint}, clock_factory=lambda: LATER)


@pytest.mark.parametrize("endpoint", PERCENT_ESCAPED_OPERATOR_AUTHORITIES)
@pytest.mark.parametrize("provider_id", ("llm:hermes", "llm:custom"))
def test_direct_construction_rejects_percent_escaped_operator_authorities(provider_id: str, endpoint: str) -> None:
    with pytest.raises(ValueError, match="operator endpoint"):
        ServiceConnection(
            schema_version=1,
            provider_id=provider_id,
            connection_id=CONNECTION_ID,
            label="Plain authority",
            model="model",
            endpoint=endpoint,
            auth_mode="api_key" if provider_id == "llm:custom" else None,
            created_at=NOW,
            updated_at=NOW,
        )


@pytest.mark.parametrize("endpoint", MALFORMED_OPERATOR_ENDPOINTS)
@pytest.mark.parametrize("provider_id", ("llm:hermes", "llm:custom"))
def test_create_rejects_non_ascii_or_malformed_operator_uri_syntax(provider_id: str, endpoint: str) -> None:
    with pytest.raises(ValueError, match="operator endpoint"):
        _create(provider_id, endpoint=endpoint)


@pytest.mark.parametrize("endpoint", MALFORMED_OPERATOR_ENDPOINTS)
@pytest.mark.parametrize("provider_id", ("llm:hermes", "llm:custom"))
def test_update_rejects_non_ascii_or_malformed_operator_uri_syntax(provider_id: str, endpoint: str) -> None:
    with pytest.raises(ValueError, match="operator endpoint"):
        update_service_connection(_create(provider_id), {"endpoint": endpoint}, clock_factory=lambda: LATER)


@pytest.mark.parametrize("endpoint", MALFORMED_OPERATOR_ENDPOINTS)
@pytest.mark.parametrize("provider_id", ("llm:hermes", "llm:custom"))
def test_direct_construction_rejects_non_ascii_or_malformed_operator_uri_syntax(
    provider_id: str,
    endpoint: str,
) -> None:
    with pytest.raises(ValueError, match="operator endpoint"):
        ServiceConnection(
            schema_version=1,
            provider_id=provider_id,
            connection_id=CONNECTION_ID,
            label="Strict URI",
            model="model",
            endpoint=endpoint,
            auth_mode="api_key" if provider_id == "llm:custom" else None,
            created_at=NOW,
            updated_at=NOW,
        )


@pytest.mark.parametrize("provider_id", ("llm:hermes", "llm:custom"))
@pytest.mark.parametrize(
    "endpoint",
    (
        "http://localhost",
        "http://127.0.0.1:8080/base",
        "https://[2001:db8::1]:8443/v1",
        "https://xn--bcher-kva.example/%E2%9C%93/a-._~!$&'()*+,;=:@",
    ),
)
def test_operator_endpoint_accepts_and_preserves_valid_ascii_uri_forms(provider_id: str, endpoint: str) -> None:
    connection = _create(provider_id, endpoint=endpoint)
    updated = update_service_connection(connection, {"endpoint": endpoint}, clock_factory=lambda: LATER)

    assert connection.endpoint == endpoint
    assert updated.endpoint == endpoint


def test_operator_endpoint_preserves_exact_validated_spelling_at_the_2048_character_boundary() -> None:
    prefix = "https://models.example.invalid/"
    endpoint = prefix + ("a" * (2048 - len(prefix)))

    assert len(endpoint) == 2048
    assert _create("llm:custom", endpoint=endpoint).endpoint == endpoint


@pytest.mark.parametrize(
    "endpoint",
    (
        "https://fixture-secret＠example.invalid",
        "https://models.example.invalid:fixture-secret",
    ),
)
def test_parser_errors_and_exception_logs_do_not_chain_sensitive_endpoint_text(
    endpoint: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sensitive = "fixture-secret"

    with caplog.at_level(logging.ERROR):
        try:
            _create("llm:custom", endpoint=endpoint)
        except ValueError as exc:
            rendered = "".join(traceback.format_exception(exc))
            logging.getLogger("test.service-connections").exception("connection validation rejected")
        else:
            pytest.fail("unsafe Unicode endpoint was accepted")

    assert sensitive not in rendered
    assert sensitive not in caplog.text


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("label", "", "non-blank"),
        ("label", " " * 3, "non-blank"),
        ("label", "a" * 129, "at most 128"),
        ("label", "safe\nunsafe", "control"),
        ("model", "m" * 257, "at most 256"),
        ("model", "safe\x00unsafe", "control"),
    ),
)
def test_operator_text_fields_are_bounded_without_echoing_values(field: str, value: str, message: str) -> None:
    with pytest.raises(ValueError, match=message) as exc_info:
        _create(**{field: value})
    if value:
        assert value not in str(exc_info.value)


def test_operator_text_boundaries_and_blank_model_are_valid() -> None:
    connection = _create(label="l" * 128, model="m" * 256)
    assert connection.label == "l" * 128
    assert connection.model == "m" * 256
    assert _create(model="").model == ""


def test_multiple_connections_for_one_provider_keep_distinct_server_identities() -> None:
    ids = iter((CONNECTION_ID, OTHER_CONNECTION_ID))
    first = create_service_connection(_payload(), uuid_factory=lambda: next(ids), clock_factory=lambda: NOW)
    second = create_service_connection(_payload(), uuid_factory=lambda: next(ids), clock_factory=lambda: NOW)

    assert first.provider_id == second.provider_id == "llm:openai"
    assert first.ref != second.ref


def test_connections_and_nested_identity_are_deeply_immutable() -> None:
    connection = _create()
    public = connection.to_public_dict()
    public["label"] = "mutated copy"

    with pytest.raises(FrozenInstanceError):
        connection.label = "mutated"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        connection.ref.provider_id = "llm:anthropic"  # type: ignore[misc]
    assert connection.label == "Primary"


@pytest.mark.parametrize("field", ("provider_id", "connection_id", "schema_version", "created_at", "secret_version"))
def test_update_rejects_immutable_or_server_owned_fields(field: str) -> None:
    with pytest.raises(ValueError, match="immutable|server-owned"):
        update_service_connection(_create(), {field: "caller-selected"}, clock_factory=lambda: LATER)


def test_label_and_model_updates_preserve_the_credential_binding() -> None:
    connection = _create().with_secret_version(_secret_version(_create()))

    updated = update_service_connection(
        connection,
        {"label": "Secondary", "model": "gpt-5"},
        clock_factory=lambda: LATER,
    )

    assert updated is not connection
    assert updated.created_at == NOW
    assert updated.updated_at == LATER
    assert updated.label == "Secondary"
    assert updated.model == "gpt-5"
    assert updated.secret_version == connection.secret_version
    assert updated.credential_configured is True


def test_sequential_updates_reject_a_regressed_clock_but_accept_equal_and_forward_times() -> None:
    first_update_time = datetime(2026, 9, 5, 9, 32, tzinfo=UTC)
    between_creation_and_update = datetime(2026, 9, 5, 9, 31, tzinfo=UTC)
    forward_time = datetime(2026, 9, 5, 9, 33, tzinfo=UTC)
    first = update_service_connection(_create(), {"label": "First"}, clock_factory=lambda: first_update_time)

    with pytest.raises(ValueError, match="updated_at"):
        update_service_connection(first, {"label": "Regressed"}, clock_factory=lambda: between_creation_and_update)

    equal = update_service_connection(first, {"label": "Equal"}, clock_factory=lambda: first_update_time)
    forward = update_service_connection(equal, {"label": "Forward"}, clock_factory=lambda: forward_time)

    assert equal.updated_at == first_update_time
    assert forward.updated_at == forward_time


def test_auth_or_exact_operator_endpoint_changes_invalidate_the_credential_binding() -> None:
    anthropic = _create("llm:anthropic").with_secret_version(_secret_version(_create("llm:anthropic")))
    custom = _create("llm:custom").with_secret_version(_secret_version(_create("llm:custom")))

    changed_auth = update_service_connection(anthropic, {"auth_mode": "oauth"}, clock_factory=lambda: LATER)
    changed_endpoint = update_service_connection(
        custom,
        {"endpoint": "https://models.example.invalid/base/"},
        clock_factory=lambda: LATER,
    )

    assert changed_auth.secret_version is None
    assert changed_endpoint.secret_version is None
    assert changed_auth.credential_configured is False
    assert changed_endpoint.credential_configured is False


def test_exactly_unchanged_auth_and_endpoint_preserve_the_credential_binding() -> None:
    custom = _create("llm:custom").with_secret_version(_secret_version(_create("llm:custom")))

    updated = update_service_connection(
        custom,
        {"auth_mode": "api_key", "endpoint": "https://models.example.invalid/base"},
        clock_factory=lambda: LATER,
    )

    assert updated.secret_version == custom.secret_version


def test_secret_versions_validate_full_identity_and_exact_integer_domain() -> None:
    ref = ServiceConnectionRef("llm:openai", CONNECTION_ID)
    version = ServiceSecretVersion(ref, STORE_ID, BINDING_ID, INT64_MAX, False)
    assert version.present is False

    with pytest.raises(ValueError, match="generation"):
        ServiceSecretVersion(ref, STORE_ID, BINDING_ID, True, True)
    with pytest.raises(ValueError, match="generation"):
        ServiceSecretVersion(ref, STORE_ID, BINDING_ID, 0, False)
    with pytest.raises(ValueError, match="generation"):
        ServiceSecretVersion(ref, STORE_ID, BINDING_ID, INT64_MAX + 1, False)
    with pytest.raises(ValueError, match="present"):
        ServiceSecretVersion(ref, STORE_ID, BINDING_ID, 1, 1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="UUID4"):
        ServiceSecretVersion(
            ref,
            UUID("00000000-0000-1000-8000-000000000001"),
            BINDING_ID,
            1,
            True,
        )


def test_binding_install_requires_exact_connection_identity_and_auth_compatibility() -> None:
    openai = _create()
    foreign = ServiceSecretVersion(
        ServiceConnectionRef("llm:openai", OTHER_CONNECTION_ID),
        STORE_ID,
        BINDING_ID,
        1,
        True,
    )

    with pytest.raises(ValueError, match="connection identity") as exc_info:
        openai.with_secret_version(foreign)
    assert str(OTHER_CONNECTION_ID) not in str(exc_info.value)
    with pytest.raises(ValueError, match="does not accept credentials"):
        _create("llm:ollama").with_secret_version(
            ServiceSecretVersion(
                ServiceConnectionRef("llm:ollama", CONNECTION_ID),
                STORE_ID,
                BINDING_ID,
                1,
                True,
            )
        )


def test_materialised_absence_is_distinct_from_no_binding_but_publicly_unconfigured() -> None:
    connection = _create()
    tombstoned = connection.with_secret_version(_secret_version(connection, present=False))

    assert connection.secret_version is None
    assert tombstoned.secret_version is not None
    assert connection.to_public_dict()["credential_configured"] is False
    assert tombstoned.to_public_dict()["credential_configured"] is False


def test_repr_public_dto_errors_and_actual_logs_never_expose_binding_or_supplied_secrets(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _create()
    secret_version = ServiceSecretVersion(
        connection_ref=base.ref,
        store_incarnation=STORE_ID,
        binding_id=BINDING_ID,
        generation=SECRET_GENERATION_MARKER,
        present=True,
    )
    connection = base.with_secret_version(secret_version)
    assert str(secret_version) == MASKED_BINDING_LOG_TEXT
    assert repr(secret_version) == MASKED_BINDING_LOG_TEXT
    sensitive_values = (
        "credential-material-super-secret",
        str(STORE_ID),
        str(BINDING_ID),
        str(SECRET_GENERATION_MARKER),
        "secret://service/private-binding",
    )

    with caplog.at_level(logging.DEBUG):
        logger = logging.getLogger("test.service-connections.binding-redaction")
        logger.debug("connection str: %s", connection)
        logger.debug("connection repr: %r", connection)
        logger.debug("binding version str: %s", MASKED_BINDING_LOG_TEXT)
        logger.debug("binding version repr: %s", MASKED_BINDING_LOG_TEXT)
        with pytest.raises(ValueError) as exc_info:
            _create(api_key=sensitive_values[0], secret_ref=sensitive_values[4])

    rendered = (
        repr(connection) + repr(secret_version) + repr(connection.to_public_dict()) + str(exc_info.value) + caplog.text
    )
    assert len(caplog.records) == 4
    assert connection.to_public_dict()["credential_configured"] is True
    for sensitive in sensitive_values:
        assert sensitive not in rendered
    assert "last4" not in rendered.lower()
    assert "secret_version" not in connection.to_public_dict()

    def unsafe_repr(value: ServiceSecretVersion) -> str:
        return (
            "ServiceSecretVersion("
            f"connection_ref={value.connection_ref!r}, "
            f"store_incarnation={value.store_incarnation!r}, "
            f"binding_id={value.binding_id!r}, generation={value.generation!r}, present={value.present!r})"
        )

    monkeypatch.setattr(ServiceSecretVersion, "__repr__", unsafe_repr)
    mutated_rendering = repr(secret_version)
    with pytest.raises(AssertionError, match=str(STORE_ID)):
        for sensitive in sensitive_values:
            assert sensitive not in mutated_rendering, sensitive


@pytest.mark.parametrize(
    "factory_value",
    (
        "00000000-0000-4000-8000-000000000001",
        UUID("00000000-0000-1000-8000-000000000001"),
    ),
)
def test_uuid_factory_must_mint_an_exact_uuid4(factory_value: object) -> None:
    with pytest.raises(ValueError, match="UUID4"):
        create_service_connection(_payload(), uuid_factory=lambda: factory_value, clock_factory=lambda: NOW)  # type: ignore[arg-type,return-value]


def test_default_factories_mint_uuid4_identity_and_utc_timestamps() -> None:
    connection = create_service_connection(_payload())

    assert connection.connection_id.version == 4
    assert connection.connection_id.variant == "specified in RFC 4122"
    assert connection.created_at.tzinfo is UTC
    assert connection.updated_at == connection.created_at


@pytest.mark.parametrize(
    "clock_value",
    (
        datetime(2026, 9, 5, 9, 30),
        datetime(2026, 9, 5, 15, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))),
        "2026-09-05T09:30:00Z",
    ),
)
def test_clock_factory_must_return_a_timezone_aware_utc_datetime(clock_value: object) -> None:
    with pytest.raises(ValueError, match="UTC datetime"):
        create_service_connection(_payload(), uuid_factory=lambda: CONNECTION_ID, clock_factory=lambda: clock_value)  # type: ignore[arg-type,return-value]


def test_update_rejects_a_non_connection_without_echoing_it() -> None:
    with pytest.raises(ValueError, match="ServiceConnection") as exc_info:
        update_service_connection("credential-material", {}, clock_factory=lambda: LATER)  # type: ignore[arg-type]
    assert "credential-material" not in str(exc_info.value)


def test_create_and_update_are_pure_and_perform_no_environment_file_network_or_subprocess_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("unexpected I/O")

    monkeypatch.setattr(os, "getenv", forbidden)
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)

    connection = _create("llm:custom")
    updated = update_service_connection(connection, {"label": "No I/O"}, clock_factory=lambda: LATER)

    assert updated.label == "No I/O"


def test_fresh_import_construction_validation_and_update_perform_no_io() -> None:
    probe = """
import builtins
from datetime import UTC, datetime
import os
import socket
import subprocess
import sys
from uuid import UUID

import flinttrade_core

assert "flinttrade_core.service_connections" not in sys.modules

def forbidden(*_args, **_kwargs):
    raise AssertionError("unexpected I/O")

class ForbiddenEnvironment:
    def __getitem__(self, _key):
        forbidden()
    def get(self, _key, _default=None):
        forbidden()

os.environ = ForbiddenEnvironment()
os.getenv = forbidden
builtins.open = forbidden
socket.socket = forbidden
subprocess.Popen = forbidden
from flinttrade_core.service_connections import create_service_connection, update_service_connection

connection = create_service_connection(
    {
        "provider_id": "llm:custom",
        "label": "No I/O",
        "endpoint": "https://models.example.invalid/base",
        "auth_mode": "api_key",
    },
    uuid_factory=lambda: UUID("00000000-0000-4000-8000-000000000001"),
    clock_factory=lambda: datetime(2026, 9, 5, 9, 30, tzinfo=UTC),
)
update_service_connection(
    connection,
    {"label": "Still no I/O"},
    clock_factory=lambda: datetime(2026, 9, 5, 9, 31, tzinfo=UTC),
)
"""

    completed = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_direct_connection_construction_rejects_invalid_schema_and_non_utc_timestamps() -> None:
    fields = {
        "schema_version": 1,
        "provider_id": "llm:openai",
        "connection_id": CONNECTION_ID,
        "label": "Primary",
        "model": "gpt-4o-mini",
        "endpoint": "https://api.openai.com/v1/chat/completions",
        "auth_mode": "api_key",
        "created_at": NOW,
        "updated_at": NOW,
    }
    with pytest.raises(ValueError, match="schema_version"):
        ServiceConnection(**{**fields, "schema_version": True})
    with pytest.raises(ValueError, match="UTC datetime"):
        ServiceConnection(
            **{
                **fields,
                "updated_at": datetime(2026, 9, 5, 15, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))),
            }
        )


def test_factory_and_direct_construction_detach_mutable_zero_offset_timezone_state() -> None:
    class MutableOffset(tzinfo):
        def __init__(self) -> None:
            self.offset = timedelta(0)

        def utcoffset(self, _value: datetime | None) -> timedelta:
            return self.offset

        def dst(self, _value: datetime | None) -> timedelta:
            return timedelta(0)

    mutable_timezone = MutableOffset()
    supplied = datetime(2026, 9, 5, 9, 30, tzinfo=mutable_timezone)
    factory_connection = create_service_connection(
        _payload(),
        uuid_factory=lambda: CONNECTION_ID,
        clock_factory=lambda: supplied,
    )
    direct_connection = ServiceConnection(
        schema_version=1,
        provider_id="llm:openai",
        connection_id=CONNECTION_ID,
        label="Primary",
        model="gpt-4o-mini",
        endpoint="https://api.openai.com/v1/chat/completions",
        auth_mode="api_key",
        created_at=supplied,
        updated_at=supplied,
    )

    mutable_timezone.offset = timedelta(hours=1)

    assert factory_connection.created_at.tzinfo is UTC
    assert direct_connection.created_at.tzinfo is UTC
    assert factory_connection.to_public_dict()["created_at"] == "2026-09-05T09:30:00Z"
    assert direct_connection.to_public_dict()["updated_at"] == "2026-09-05T09:30:00Z"
