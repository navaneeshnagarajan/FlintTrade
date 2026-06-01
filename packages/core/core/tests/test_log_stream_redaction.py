"""T10 (OBS-06): operational log-stream identity redaction + visibility (observability §5.4).

The operational /v1/logs/* endpoints must never emit a plaintext JWT, broker
token, or raw IP, must withhold non-human (agent / external_intent) entries, and
must be gated by the admin.logs.read.operational scope.
"""

from __future__ import annotations

from flinttrade_core.log_stream import (
    _operational_visible,
    recent_logs,
    redact_identity,
    stream_logs,
)


def test_redacts_jwt() -> None:
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJuYXZhIn0.abc-DEF_123"
    out = redact_identity(f"login ok token={jwt} done")
    assert jwt not in out
    assert "<JWT>" in out


def test_redacts_bearer_token() -> None:
    out = redact_identity("Authorization: Bearer abc123.def-456_token")
    assert "abc123.def-456_token" not in out
    assert "<BROKER_ACCESS_TOKEN>" in out


def test_redacts_access_token_kv() -> None:
    out = redact_identity('connected access_token=NOTAREALTOKEN-broker-xyz done')
    assert "NOTAREALTOKEN-broker-xyz" not in out
    assert "<BROKER_ACCESS_TOKEN>" in out


def test_redacts_base64_token_in_full() -> None:
    # Re-audit fix: base64 chars (+ / =) must not leak as an exposed suffix.
    out = redact_identity("connected access_token=AB12+cd/EF== now")
    assert "AB12+cd/EF==" not in out
    assert "+cd/EF" not in out
    assert "<BROKER_ACCESS_TOKEN>" in out


def test_redacts_wss_url_with_token() -> None:
    out = redact_identity("opening wss://feed.broker.in/ws?access_token=LIVE-TOKEN-XYZ&v=2 now")
    assert "LIVE-TOKEN-XYZ" not in out
    assert "<WSS_WITH_TOKEN_REDACTED>" in out


def test_hashes_ipv4() -> None:
    out = redact_identity("request from 203.0.113.42 accepted")
    assert "203.0.113.42" not in out
    assert "ip:" in out


def test_hashes_ipv6_compressed() -> None:
    out = redact_identity("request from 2001:db8::ff00:42:8329 accepted")
    assert "2001:db8::ff00:42:8329" not in out
    assert "ip:" in out


def test_hashes_ipv6_link_local() -> None:
    out = redact_identity("peer fe80::1ff:fe23:4567:890a connected")
    assert "fe80::1ff:fe23:4567:890a" not in out
    assert "ip:" in out


def test_hashes_ipv6_loopback() -> None:
    out = redact_identity("bound to ::1 ok")
    assert "::1 " not in out
    assert "ip:" in out


def test_ipv6_does_not_match_ordinary_colon_fragment() -> None:
    # An ordinary ``key:value`` log fragment (one colon, no ``::``) must survive.
    text = "level:info status:ok elapsed:42ms"
    assert redact_identity(text) == text


def test_redacts_bare_high_entropy_token() -> None:
    # A 40-char standalone base64-ish token that mixes letters and digits.
    token = "aB3kZ9qWmN7pXr2sT5vY8cF1dG4hJ6lQ0oP2eU7w"
    assert len(token) >= 32
    out = redact_identity(f"resumed session {token} now")
    assert token not in out
    assert "<BROKER_ACCESS_TOKEN>" in out


def test_does_not_redact_ordinary_prose() -> None:
    text = "the quick brown fox jumps over the lazy dog repeatedly today"
    assert redact_identity(text) == text


def test_does_not_redact_short_word() -> None:
    assert redact_identity("orderid abc123 placed") == "orderid abc123 placed"


def test_does_not_redact_numeric_id() -> None:
    # A typical long numeric id (digits only, no letters) is not a secret.
    text = "order 123456789012345678901234567890123456 filled"
    assert redact_identity(text) == text


def test_redact_handles_empty() -> None:
    assert redact_identity(None) is None
    assert redact_identity("") == ""
    assert redact_identity("nothing sensitive here") == "nothing sensitive here"


def test_operational_visibility() -> None:
    assert _operational_visible({"message": "x"}) is True
    assert _operational_visible({"actor_type": "human"}) is True
    assert _operational_visible({"actor_type": ""}) is True
    assert _operational_visible({"actor_type": "agent"}) is False
    assert _operational_visible({"actor_type": "external_intent"}) is False


def test_endpoints_require_operational_scope() -> None:
    assert getattr(stream_logs, "__required_scope__", None) == "admin.logs.read.operational"
    assert getattr(recent_logs, "__required_scope__", None) == "admin.logs.read.operational"
